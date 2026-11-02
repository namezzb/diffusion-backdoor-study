import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

from PIL import Image
from pilot24_worker_compute import generate_one, score_existing, run_worker, run_session, _inputs
from pilot24_worker_ledger import WorkerLedger
from test_pilot24_worker_ledger import assignment


class WorkerComputeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.plan = assignment()
        self.plan["assignment_id"] = "S0-worker-a-000"
        self.key = self.plan["units"][0]["key"]
        self.ledger = WorkerLedger(Path(self.temp.name), self.plan)
        self.bindings = SimpleNamespace(mask_hashes={"clean": "d" * 64})
        self.runtime = SimpleNamespace(active=("tcl", "source", "clean", "d" * 64))
        self.scorer = SimpleNamespace(score=lambda image, prompt: {"vit_class": 151, "clip_score": 30.0})
        self.prompt = {"prompt": "A dog", "score_prompt": "A dog", "tokenization": {}}
        self.provenance = {name: "a" * 64 for name in ("assignment_sha256", "t0_sha256", "model_bundle_sha256", "scorer_sha256")}
        self.receipt = self.ledger.root / "progress.json"

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def sample(self, runtime, prompt, seed, callback):
        callback("text_encoder_forwards", 2)
        callback("unet_branch_nfe", 50)
        callback("vae_decodes", 1)
        return Image.new("RGB", (512, 512))

    @patch("pilot24_worker_compute._inputs")
    @patch("pilot24_worker_compute._utc_now", return_value="2026-11-02T01:00:00+00:00")
    @patch("generation.sample_prepared")
    def test_generated_and_scored_once(self, sample, now, inputs):
        inputs.return_value = self.prompt
        sample.side_effect = self.sample
        out = generate_one(self.runtime, self.scorer, self.bindings, self.ledger, self.key, "2026-11-02T00:00:00Z")
        self.assertTrue(out["new_generation"])
        self.assertEqual(self.ledger.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 1)
        with self.assertRaises(ValueError):
            generate_one(self.runtime, self.scorer, self.bindings, self.ledger, self.key, "2026-11-02T00:00:00Z")

    @patch("pilot24_worker_compute._inputs")
    @patch("pilot24_worker_compute._utc_now", return_value="2026-11-02T01:00:00+00:00")
    @patch("generation.sample_prepared")
    def test_scoring_failure_resumes_without_generation(self, sample, now, inputs):
        inputs.return_value = self.prompt
        sample.side_effect = self.sample
        self.scorer.score = lambda image, prompt: (_ for _ in ()).throw(RuntimeError("scorer failed"))
        with self.assertRaises(RuntimeError):
            generate_one(self.runtime, self.scorer, self.bindings, self.ledger, self.key, "2026-11-02T00:00:00Z")
        self.scorer.score = lambda image, prompt: {"vit_class": 151, "clip_score": 30.0}
        result = score_existing(self.runtime, self.scorer, self.bindings, self.ledger, self.key, "2026-11-02T00:00:00Z")
        self.assertFalse(result["new_generation"])
        self.assertEqual(sample.call_count, 1)
        self.assertEqual(self.ledger.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 1)

    @patch("pilot24_worker_compute._inputs")
    @patch("pilot24_worker_compute._utc_now", return_value="2026-11-02T22:00:00+00:00")
    def test_no_reservation_after_stop(self, now, inputs):
        inputs.return_value = self.prompt
        with self.assertRaises(ValueError):
            generate_one(self.runtime, self.scorer, self.bindings, self.ledger, self.key, "2026-11-02T00:00:00Z")
        self.assertEqual(self.ledger.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0)

    @patch("pilot24_worker_compute._inputs")
    @patch("pilot24_worker_compute._utc_now", return_value="2026-11-02T01:00:00+00:00")
    @patch("generation.sample_prepared")
    def test_worker_exports_complete_attempt_accounting_and_resumes(self, sample, now, inputs):
        inputs.return_value = self.prompt
        sample.side_effect = self.sample
        # Use one real key so the mocked runtime needs no second model install.
        self.ledger.close()
        self.plan["units"] = self.plan["units"][:1]
        self.ledger = WorkerLedger(self.ledger.root / "single", self.plan)
        result = run_worker(self.runtime, self.scorer, self.bindings, self.ledger,
                            "2026-11-02T00:00:00Z", self.receipt, self.provenance)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["new_generation_attempts"], 1)
        self.assertEqual(result["attempts"][0]["resource"]["unet_branch_nfe"], 50)
        self.assertEqual(json.loads(self.receipt.read_text())["records"], result["records"])
        again = run_worker(self.runtime, self.scorer, self.bindings, self.ledger,
                           "2026-11-02T00:00:00Z", self.receipt, self.provenance)
        self.assertEqual(again["new_generation_attempts"], 1)
        self.assertEqual(sample.call_count, 1)

    @patch("pilot24_worker_compute._inputs")
    @patch("pilot24_worker_compute._utc_now", return_value="2026-11-02T01:00:00+00:00")
    @patch("generation.sample_prepared")
    def test_worker_scoring_failure_never_spends_second_generation(self, sample, now, inputs):
        inputs.return_value = self.prompt
        sample.side_effect = self.sample
        self.scorer.score = lambda image, prompt: (_ for _ in ()).throw(RuntimeError("scorer unavailable"))
        result = run_worker(self.runtime, self.scorer, self.bindings, self.ledger,
                            "2026-11-02T00:00:00Z", self.receipt, self.provenance)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["new_generation_attempts"], 1)
        self.assertEqual(result["attempts"][0]["resource"]["scoring_calls"], 2)
        self.assertEqual(self.ledger.status(self.key), "scoring")
        self.assertEqual(sample.call_count, 1)

    @patch("pilot24_worker_compute._utc_now", return_value="2026-11-02T22:00:00+00:00")
    def test_worker_deadline_receipt_does_not_charge_unstarted_keys(self, now):
        result = run_worker(self.runtime, self.scorer, self.bindings, self.ledger,
                            "2026-11-02T00:00:00Z", self.receipt, self.provenance)
        self.assertEqual(result["status"], "deadline")
        self.assertEqual(result["new_generation_attempts"], 0)

    @patch("pilot24_worker_compute._inputs")
    @patch("pilot24_worker_compute._utc_now", return_value="2026-11-02T22:05:00+00:00")
    def test_scoring_after_generation_cutoff_precedes_unstarted_keys(self, now, inputs):
        inputs.return_value = self.prompt
        key = self.plan["units"][1]["key"]
        self.ledger.start(key)
        image = self.ledger.image_path(key)
        image.parent.mkdir()
        Image.new("RGB", (512, 512)).save(image)
        self.ledger.register_image(key, image)
        result = run_worker(self.runtime, self.scorer, self.bindings, self.ledger,
                            "2026-11-02T00:00:00Z", self.receipt, self.provenance)
        self.assertEqual(result["status"], "deadline")
        self.assertEqual(result["new_generation_attempts"], 1)
        self.assertEqual(result["records"][0]["key"], key)
        self.assertEqual(self.ledger.status(self.key), "unstarted")

    @patch("pilot24_worker_compute._utc_now", return_value="2026-11-02T01:00:00+00:00")
    @patch("pilot24_worker_compute.generate_one")
    def test_worker_bounded_generation_retries_remain_charged(self, generate, now):
        def fail(*args):
            args[3].start(args[4])
            raise RuntimeError("CUDA operation failed")
        generate.side_effect = fail
        result = run_worker(self.runtime, self.scorer, self.bindings, self.ledger,
                            "2026-11-02T00:00:00Z", self.receipt, self.provenance)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["new_generation_attempts"], 2)
        self.assertEqual(result["retry_attempts"], 1)
        self.assertEqual([a["status"] for a in result["attempts"]], ["interrupted", "interrupted"])
        self.assertEqual(generate.call_count, 2)

    @patch("generation._validate_tokens")
    def test_unit_binding_checks_model_scorer_mask_and_run(self, tokens):
        import sys
        parent = Path(__file__).resolve().parents[1]
        if str(parent) not in sys.path:
            sys.path.insert(0, str(parent))
        from tssa_mvp_score import IndependentScorer
        root = self.ledger.root
        scorer = IndependentScorer.__new__(IndependentScorer)
        scorer.root = root
        assets = SimpleNamespace(models_root=root, file_hashes={"model": {"sha256": "f" * 64}}, tokenizer=object())
        runtime = SimpleNamespace(assets=assets, _tcl_verified_selection_sha="b" * 64)
        bindings = SimpleNamespace(run_id=self.plan["run_id"], manifest_sha=self.plan["manifest_sha256"],
            selection_sha="b" * 64, asset_hashes={"model": "f" * 64},
            input_hashes={("source", "home-04", "dog"): "c" * 64}, mask_hashes={"clean": "d" * 64},
            prompt_rows={("source", "home-04", "dog"): json.dumps(self.prompt)})
        self.assertEqual(_inputs(runtime, scorer, bindings, self.ledger, self.key), self.prompt)
        bindings.manifest_sha = "e" * 64
        with self.assertRaises(ValueError):
            _inputs(runtime, scorer, bindings, self.ledger, self.key)
        bindings.manifest_sha = self.plan["manifest_sha256"]
        assets.file_hashes["model"]["sha256"] = "e" * 64
        with self.assertRaises(ValueError):
            _inputs(runtime, scorer, bindings, self.ledger, self.key)


class WorkerSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.mailbox = self.root / "mailbox"
        self.mailbox.mkdir()
        self.receipts = self.root / "receipts"
        self.stop = self.root / "stop.json"
        self.permission_ref = self.root / "permission-ref.json"
        self.permission_ref.write_text(json.dumps({"path": str(self.root / "permission.json"), "sha256": "a" * 64}))
        reviewed_config = self.root / 'config.json'
        reviewed_config.write_text('{}')
        review = self.root / 'review.json'
        review.write_text(json.dumps({'coordinator_config_file': str(reviewed_config),
                                      'coordinator_config_sha256': __import__('hashlib').sha256(reviewed_config.read_bytes()).hexdigest(),
                                      'manifest_sha256': 'a' * 64}))
        self.prepared = []
        for index in range(2):
            plan = assignment()
            plan.update(assignment_id="S0-worker-a-00" + str(index), server="104", gpu_uuid="GPU-" + "a" * 36,
                        output_root=str(self.root / ("worker-" + str(index))))
            job = self.mailbox / (plan["assignment_id"] + ".json")
            job.write_text(json.dumps({"assignment": str(self.root / ("assignment-" + str(index))), "gate": str(self.root / "gate")}))
            self.prepared.append(SimpleNamespace(assignment=plan, manifest_sha256="a" * 64,
                assignment_sha256="b" * 64, model_bundle_sha256="c" * 64, scorer_sha256="d" * 64,
                bindings=SimpleNamespace(selection_sha="e" * 64), gate={"config_sha256": "f" * 64}, assets=None,
                bundle={'review_file': str(review)}))

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, permission=None, alter_second=False):
        assets = object()
        runtime = SimpleNamespace(assets=assets)
        def prepare_assets(prepared):
            prepared.assets = assets
        def run(*args):
            if args[3].assignment["assignment_id"].endswith("001"):
                self.stop.write_text("{}")
            return {"status": "complete"}
        if alter_second:
            self.prepared[1].assignment["gpu_uuid"] = "GPU-" + "b" * 36
        permission = permission or Mock()
        with patch.dict("sys.modules", {"pilot24_provenance": SimpleNamespace(validate_worker_permission=permission)}), \
                patch.dict("os.environ", {"PILOT24_SUPERVISED": "a" * 64}), \
                patch("pilot24_runtime.prepare_worker", side_effect=self.prepared) as prepare, \
                patch("pilot24_runtime.prepare_assets", side_effect=prepare_assets) as cpu, \
                patch("pilot24_runtime.create_runtime", return_value=(runtime, object())) as create, \
                patch("pilot24_watchdog.load_t0", return_value={"t0_utc": "2026-11-02T00:00:00Z"}), \
                patch("pilot24_worker_compute._utc_now", return_value="2026-11-02T01:00:00+00:00"), \
                patch("pilot24_worker_compute._process_identity", return_value={"pid": 12, "uid": 1000, "start_ticks": 123}), \
                patch("pilot24_worker_compute.run_worker", side_effect=run) as execute:
            result = run_session(self.mailbox, self.receipts, self.root / "bundle", "worker-a", self.root / "t0",
                                 "a" * 64, self.permission_ref, self.stop)
        return result, prepare, cpu, create, execute, permission

    def test_two_assignments_reuse_one_runtime_and_one_permission(self):
        result, prepare, cpu, create, execute, permission = self.invoke()
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(len(result["completed_assignments"]), 2)
        self.assertEqual(prepare.call_count, 2)
        self.assertEqual(cpu.call_count, 1)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(permission.call_count, 1)
        self.assertEqual(execute.call_count, 2)
        ready = json.loads((self.receipts / "sessions" / "worker-a" / "ready.json").read_text())
        self.assertEqual(ready["launcher"]["start_ticks"], 123)
        self.assertFalse((self.receipts / "ready.json").exists())

    def test_rejected_live_permission_writes_actionable_blocked_status(self):
        with self.assertRaisesRegex(ValueError, "permission stale"):
            self.invoke(permission=Mock(side_effect=ValueError("permission stale")))
        state = json.loads((self.receipts / "sessions" / "worker-a" / "session.json").read_text())
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["error"], "permission stale")

    def test_changed_gpu_cannot_reuse_authorized_session(self):
        with self.assertRaisesRegex(ValueError, "cannot change"):
            self.invoke(alter_second=True)
        state = json.loads((self.receipts / "sessions" / "worker-a" / "session.json").read_text())
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(len(state["completed_assignments"]), 1)

    def test_worker_session_files_do_not_overwrite_other_worker(self):
        other = self.receipts / "sessions" / "worker-b"
        other.mkdir(parents=True)
        (other / "ready.json").write_text('{"launcher":{"pid":99}}')
        self.invoke()
        self.assertEqual(json.loads((other / "ready.json").read_text())["launcher"]["pid"], 99)


if __name__ == "__main__":
    unittest.main()
