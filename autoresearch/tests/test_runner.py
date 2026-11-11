import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ar", ROOT / "ar.py")
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        # Scratch stays inside the task, never in the scientific run namespace.
        scratch = ROOT / "_scratch"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.base = Path(self.temp.name)
        self.template = self.base / "template"
        shutil.copytree(ROOT / "examples" / "polynomial", self.template)
        self.run = self.base / "run"

    def tearDown(self):
        self.temp.cleanup()

    def configure(self, **changes):
        path = self.template / "config.json"
        config = json.loads(path.read_text())
        config.update(changes)
        path.write_text(json.dumps(config))

    def init(self):
        ar.create_run(self.run, self.template)

    def test_real_fit_keep_discard_and_resume(self):
        self.init()
        baseline = ar.run_attempt(self.run, "linear baseline")
        self.assertEqual(baseline["decision"], "baseline")
        candidate = self.run / "work" / "candidate.py"
        candidate.write_text(candidate.read_text().replace("DEGREE = 1", "DEGREE = 3"))
        improved = ar.run_attempt(self.run, "cubic nonlinear model")
        self.assertEqual(improved["decision"], "keep")
        self.assertLess(improved["metrics"]["mse"], baseline["metrics"]["mse"])
        candidate.write_text(candidate.read_text().replace("DEGREE = 3", "DEGREE = 0"))
        worse = ar.run_attempt(self.run, "constant model")
        self.assertEqual(worse["decision"], "discard")
        self.assertIn("DEGREE = 3", candidate.read_text())
        self.assertEqual(ar.status(self.run)["attempts"], 3)
        self.assertEqual(ar.status(self.run)["best"]["commit"], improved["commit"])
        self.assertEqual(ar.git(self.run / "work", "show", worse["commit"] + ":candidate.py").splitlines()[1], "DEGREE = 0")
        resumed = ar.run_attempt(self.run, "rerun current best after fresh state read")
        self.assertEqual(resumed["decision"], "discard")
        self.assertEqual(ar.status(self.run)["attempts"], 4)

    def test_crash_after_metric_is_not_success(self):
        self.configure(command=["{python}", "-c", 'print(\'AUTORESEARCH_METRICS {"mse":0,"n_parameters":1}\');raise SystemExit(7)'])
        self.init()
        result = ar.run_attempt(self.run, "failing evaluator")
        self.assertEqual(result["decision"], "crash")
        self.assertIsNone(ar.status(self.run)["best"])
        self.assertGreater(ar.status(self.run)["compute_seconds"], 0)

    def test_nonfinite_missing_and_duplicate_metrics_rejected(self):
        for output in ('{"mse":NaN}', '{"other":1}', '{"mse":true}', '{"mse":1}\nAUTORESEARCH_METRICS {"mse":0}'):
            log = self.base / "output.log"
            log.write_text("AUTORESEARCH_METRICS " + output + "\n")
            if output == '{"other":1}':
                self.configure(command=["{python}", "-c", "print('AUTORESEARCH_METRICS " + output + "')"])
                self.init()
                self.assertEqual(ar.run_attempt(self.run, "missing primary")["decision"], "crash")
            else:
                with self.assertRaises(ValueError):
                    ar.metrics_from(log)

    def test_quality_constraint_blocks_better_score(self):
        self.configure(constraints=[{"name": "n_parameters", "op": "<=", "value": 2}])
        self.init()
        baseline = ar.run_attempt(self.run, "baseline")
        candidate = self.run / "work" / "candidate.py"
        candidate.write_text(candidate.read_text().replace("DEGREE = 1", "DEGREE = 3"))
        trial = ar.run_attempt(self.run, "exceed parameter guard")
        self.assertEqual(trial["decision"], "constraint_failed")
        self.assertLess(trial["metrics"]["mse"], baseline["metrics"]["mse"])
        self.assertIn("DEGREE = 1", candidate.read_text())

    def test_timeout_is_charged_and_budget_survives(self):
        self.configure(max_attempts=1, attempt_timeout=0.15,
                       command=["{python}", "-c", "import time;time.sleep(10)"])
        self.init()
        trial = ar.run_attempt(self.run, "timeout")
        self.assertEqual(trial["decision"], "crash")
        self.assertGreaterEqual(trial["seconds"], 0.15)
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            ar.run_attempt(self.run, "must not reset budget")

    def test_stop_interrupts_active_command(self):
        self.configure(command=["{python}", "-c", "import time;time.sleep(10)"])
        self.init()
        timer = threading.Timer(0.15, lambda: (self.run / "STOP").write_text("stop"))
        timer.start()
        try:
            trial = ar.run_attempt(self.run, "stop during training")
        finally:
            timer.join()
        self.assertEqual(trial["decision"], "stopped")
        self.assertLess(trial["seconds"], 3)
        self.assertFalse(ar.status(self.run)["pending"])

    def test_cumulative_budget_prevents_new_work(self):
        self.configure(max_seconds=0.04, attempt_timeout=1,
                       command=["{python}", "-c", "import time;time.sleep(1)"])
        self.init()
        ar.run_attempt(self.run, "use total budget")
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            ar.run_attempt(self.run, "must not continue")

    def test_pending_attempt_needs_recovery_and_keeps_consumption(self):
        self.init()
        baseline = ar.run_attempt(self.run, "baseline")
        ar.append(self.run, {"event": "started", "attempt": 2, "commit": baseline["commit"],
                             "hypothesis": "lost process", "time": time.time() - 4})
        with self.assertRaisesRegex(ValueError, "unfinished"):
            ar.run_attempt(self.run, "duplicate")
        state = ar.recover(self.run, "verified original processes exited")
        self.assertEqual(state["attempts"], 2)
        self.assertGreaterEqual(state["compute_seconds"], 4)
        self.assertEqual(state["best"]["commit"], baseline["commit"])
        self.assertEqual(ar.history(self.run)[-1]["decision"], "interrupted")

    def test_gpu_requires_guard_and_cleanup(self):
        self.configure(compute="managed_gpu")
        with self.assertRaisesRegex(ValueError, "guard"):
            self.init()

    def test_resource_guard_stops_execution(self):
        self.configure(guard=["{python}", "-c", "raise SystemExit(3)"])
        self.init()
        result = ar.run_attempt(self.run, "permission unavailable")
        self.assertEqual(result["decision"], "resource_blocked")
        self.assertFalse((self.run / "attempts/0001/output.log").exists())

    def test_failed_cleanup_preserves_stop_and_rejects_result(self):
        self.configure(cleanup=["{python}", "-c", "raise SystemExit(2)"])
        self.init()
        result = ar.run_attempt(self.run, "cleanup failure")
        self.assertEqual(result["decision"], "cleanup_failed")
        self.assertTrue(ar.status(self.run)["stopped"])
        self.assertIsNone(ar.status(self.run)["best"])

    def test_parent_repository_and_stop_are_protected(self):
        self.init()
        (self.run / "STOP").write_text("stop")
        with self.assertRaisesRegex(ValueError, "STOP"):
            ar.run_attempt(self.run, "must stop")
        self.assertEqual(ar.status(self.run)["attempts"], 0)
        (self.run / "STOP").unlink()
        shutil.rmtree(self.run / "work/.git")
        with self.assertRaisesRegex(ValueError, "isolated"):
            ar.run_attempt(self.run, "must not commit parent")

    def test_truncated_ledger_is_not_silently_ignored(self):
        self.init()
        with (self.run / "RESULTS.md").open("a") as f:
            f.write('\n```json\n{"event":')
        with self.assertRaisesRegex(ValueError, "incomplete"):
            ar.status(self.run)


if __name__ == "__main__":
    unittest.main()
