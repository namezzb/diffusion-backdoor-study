"""CPU-only admission fault tests; none of these fixtures is resource evidence."""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pilot24_provenance as provenance
from pilot24_inputs import RUN, PARENT, VERSIONS, SEED

REPOSITORY = Path(__file__).resolve().parents[3]
TASK = REPOSITORY / "research/tasks/2026-10-29-trigger-contrast-localization"
OLD_GPU = "GPU-1e9f28a2-986d-7765-2476-3e6388b01170"
GPU = "GPU-11111111-2222-3333-4444-555555555555"
NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)


def write(path, value):
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True).encode()
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def gpu_xml(gpu=GPU, process="", mode="Default"):
    return (f"<nvidia_smi_log><gpu><uuid>{gpu}</uuid><compute_mode>{mode}</compute_mode>"
            f"<processes>{process}</processes></gpu></nvidia_smi_log>").encode()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.snapshot = self.root / "snapshot"
        self.snapshot.mkdir()
        self.output = self.root / RUN
        self.output.mkdir()
        self.copies = []
        parent = TASK / "manifest_candidate.json"
        parent_ref = {"path": str(parent), "sha256": hashlib.sha256(parent.read_bytes()).hexdigest()}
        self.assertEqual(parent_ref["sha256"], provenance.PARENT_MANIFEST_SHA256)
        self.old_root = json.loads(parent.read_text())["output_root"]
        masks = {version: self.copy("mask:" + version, version + ".json", {"version": version})
                 for version in VERSIONS}
        self.selection = self.copy("selection", "selection.json", {
            "status": "frozen", "run_id": PARENT, "manifest_sha256": parent_ref["sha256"],
            "mask_files": {version: version + ".json" for version in VERSIONS},
            "mask_sha256": {version: ref["sha256"] for version, ref in masks.items()}})
        self.copy("localization_terminal", "terminal.json", {
            "run_id": PARENT, "manifest_sha256": parent_ref["sha256"], "status": "complete", "phase": "localize"})
        ledger = self.root / "localization.sqlite"
        with sqlite3.connect(ledger) as db:
            db.execute("CREATE TABLE metadata(id INTEGER PRIMARY KEY,value TEXT)")
            db.execute("INSERT INTO metadata VALUES(1,?)", (json.dumps({"run_id": PARENT,
                "manifest_sha": parent_ref["sha256"]}),))
        self.copy("localization_ledger", ledger.name, ledger.read_bytes())
        history = self.copy("historical_reconciliation", "history.json",
            (TASK / "recovery_provisional_keys_20261102.json").read_bytes())
        launch = write(self.root / "launch.json", {"run_id": PARENT, "gpu_uuid": OLD_GPU,
            "manifest_sha256": parent_ref["sha256"]})
        self.legacy = write(self.root / "legacy_bound.json", {"run_id": PARENT, "server": "school103",
            "gpu_uuids": [OLD_GPU], "upper_bound": 1, "launch_records": [launch]})
        ids_path = TASK / "pilot24_context_ids.json"
        ids_ref = {"path": str(ids_path), "sha256": hashlib.sha256(ids_path.read_bytes()).hexdigest()}
        self.proof = {"schema_version": 1, "run_id": RUN, "parent_run_id": PARENT,
            "mode": "immutable_snapshot_namespace_isolation", "parent_manifest": parent_ref,
            "parent_code_root": str(REPOSITORY), "context_ids": ids_ref,
            "old_output_roots": [{"server": "school103", "path": self.old_root}],
            "snapshot_root": str(self.snapshot), "output_root": str(self.output),
            "source_writer_state": "unknown", "legacy_occupancy_bound": self.legacy,
            "freeze": {"source_imports": 0, "merge_imports": 0,
                "late_parent_results": "not_admitted", "no_reuse_reason": "CPU fixture uses no image imports"},
            "copies": self.copies, "imports": [], "historical_reconciliation": history}
        self.snapshot.chmod(0o555)
        self.refresh_proof()

    def tearDown(self):
        self.snapshot.chmod(0o755)
        for path in self.snapshot.rglob("*"):
            if path.is_dir():
                path.chmod(0o755)
        self.temp.cleanup()

    def copy(self, role, name, data):
        ref = write(self.snapshot / name, data)
        Path(ref["path"]).chmod(0o444)
        self.copies.append({"role": role, **ref, "origin": {
            "server": "school103", "path": self.old_root + "/" + name, "sha256": ref["sha256"]}})
        return ref

    def refresh_proof(self):
        self.proof_ref = write(self.root / "isolation.json", self.proof)

    def validate(self):
        self.refresh_proof()
        return provenance.validate_source_isolation(**{"path": self.proof_ref["path"],
            "expected_sha256": self.proof_ref["sha256"], "output_root": self.output / "workers" / "worker-S0"})

    def add_import(self):
        from PIL import Image
        self.snapshot.chmod(0o755)
        image_path = self.root / "image.png"
        Image.new("RGB", (512, 512), "white").save(image_path)
        image = self.copy("image:0", "image.png", image_path.read_bytes())
        context = json.loads(Path(self.proof["context_ids"]["path"]).read_text())["source_context_ids"][0]
        origin = (PARENT, "source", "clean", "trigger", context, SEED)
        mask = json.loads(Path(self.selection["path"]).read_text())["mask_sha256"]["clean"]
        scores = {"vit_class": 281, "clip_score": 0.3}
        ledger_path = self.root / "generation.sqlite"
        with sqlite3.connect(ledger_path) as db:
            db.executescript("CREATE TABLE metadata(id INTEGER PRIMARY KEY,value TEXT);"
                "CREATE TABLE attempts(run_id TEXT,state TEXT,version TEXT,class TEXT,context_id TEXT,seed INT,"
                "status TEXT,input_sha TEXT,mask_sha TEXT,image_sha TEXT,scores TEXT);"
                "CREATE TABLE attempt_history(run_id TEXT,state TEXT,version TEXT,class TEXT,context_id TEXT,seed INT);")
            db.execute("INSERT INTO metadata VALUES(1,?)", (json.dumps({"run_id": PARENT,
                "manifest_sha": provenance.PARENT_MANIFEST_SHA256, "selection_sha": self.selection["sha256"]}),))
            db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?,?,?)", (*origin, "complete", "a" * 64,
                mask, image["sha256"], json.dumps(scores)))
        ledger = self.copy("generation_ledger:0", ledger_path.name, ledger_path.read_bytes())
        parent = json.loads(Path(self.proof["parent_manifest"]["path"]).read_text())
        assets, code = parent["asset_sha256"], parent["code_sha256"]
        model_sha = provenance._digest(assets)
        scorer_sha = provenance._digest({"assets": {name: value for name, value in assets.items()
            if name.split('/')[0] in ("vit", "clip")}, "code": {name: code[name] for name in
            ("scripts/merging/tssa_mvp_score.py", "scripts/merging/tssa_sd_runtime.py")},
            "dtype": "float32", "device": "cpu", "image_source": "saved_rgb_png",
            "score_prompt": "untriggered_paired_prompt"})
        row = {"key": [RUN, *origin[1:]], "origin_key": list(origin), "origin_attempt": 1,
            "ledger": ledger, "image": image, "input_sha256": "a" * 64, "mask_sha256": mask,
            "model_bundle_sha256": model_sha, "scorer_sha256": scorer_sha, "scores": scores}
        self.proof["imports"] = [row]
        self.proof["freeze"].update(source_imports=1, model_bundle_sha256=model_sha, scorer_sha256=scorer_sha)
        self.snapshot.chmod(0o555)
        return row


class SourceIsolationTests(Fixture):
    def test_historical_evidence_is_mandatory_and_pinned(self):
        self.validate()
        self.proof['historical_reconciliation']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'historical reconciliation'):
            self.validate()

    def test_r0_keeps_copied_localization_and_unknown_writer_occupancy(self):
        result = self.validate()
        self.assertEqual(result["freeze"]["source_imports"], 0)
        self.assertEqual(result["source_writer_state"], "unknown")

    def test_worker_subdirectory_allowed_but_other_root_rejected(self):
        self.validate()
        with self.assertRaises(ValueError):
            provenance.validate_source_isolation(self.proof_ref["path"], self.proof_ref["sha256"],
                                                  output_root=self.root / "escape")

    def test_evidence_digest_cannot_be_changed(self):
        with self.assertRaises(ValueError):
            provenance.validate_source_isolation(self.proof_ref["path"], "0" * 64)

    def test_r0_does_not_skip_localization_or_reason(self):
        self.proof["freeze"].pop("no_reuse_reason")
        with self.assertRaises(ValueError):
            self.validate()
        self.proof["freeze"]["no_reuse_reason"] = "no imports"
        self.proof["copies"] = []
        with self.assertRaises(ValueError):
            self.validate()

    def test_roots_must_be_disjoint(self):
        self.proof["old_output_roots"].append({"server": "school104", "path": str(self.root)})
        with self.assertRaises(ValueError):
            self.validate()

    def test_symlink_ancestor_and_hardlink_are_rejected(self):
        alias = self.root / "alias"
        alias.symlink_to(self.snapshot, target_is_directory=True)
        self.proof["snapshot_root"] = str(alias)
        with self.assertRaises(ValueError):
            self.validate()
        self.proof["snapshot_root"] = str(self.snapshot)
        os.link(self.selection["path"], self.root / "hardlink")
        with self.assertRaises(ValueError):
            self.validate()

    def test_writable_snapshot_file_rejected(self):
        self.validate()
        Path(self.selection["path"]).chmod(0o644)
        with self.assertRaises(ValueError):
            self.validate()

    def test_sidecar_is_not_a_standalone_copy(self):
        self.validate()
        self.snapshot.chmod(0o755)
        (self.snapshot / "localization.sqlite-wal").write_bytes(b"uncaptured transaction")
        self.snapshot.chmod(0o555)
        with self.assertRaises(ValueError):
            self.validate()

    def test_late_parent_results_cannot_be_admitted(self):
        self.proof["freeze"]["late_parent_results"] = "admit"
        with self.assertRaises(ValueError):
            self.validate()

    def test_legacy_bound_requires_actual_launch_record(self):
        bound = json.loads(Path(self.legacy["path"]).read_text())
        bound["launch_records"] = []
        self.proof["legacy_occupancy_bound"] = write(Path(self.legacy["path"]), bound)
        with self.assertRaises(ValueError):
            self.validate()

    def test_completed_historical_import_authenticates_exact_attempt(self):
        row = self.add_import()
        self.assertEqual(self.validate()["imports"][0], row)

    def test_duplicate_import_or_false_attempt_is_rejected(self):
        row = self.add_import()
        self.proof["imports"].append(dict(row))
        self.proof["freeze"]["source_imports"] = 2
        with self.assertRaises(ValueError):
            self.validate()
        self.proof["imports"] = [row]
        self.proof["freeze"]["source_imports"] = 1
        row["origin_attempt"] = 2
        with self.assertRaises(ValueError):
            self.validate()

    def test_import_scores_and_frozen_R_must_match(self):
        row = self.add_import()
        row["scores"]["clip_score"] = 0.9
        with self.assertRaises(ValueError):
            self.validate()
        row["scores"]["clip_score"] = 0.3
        self.proof["freeze"]["source_imports"] = 0
        with self.assertRaises(ValueError):
            self.validate()

    def test_streaming_copy_authentication_does_not_return_database_bytes(self):
        ledger = next(c for c in self.copies if c["role"] == "localization_ledger")
        self.assertIsNone(provenance._ref({k: ledger[k] for k in ("path", "sha256")},
                                        readonly=True, contents=False))

    def test_readonly_hash_cache_skips_reread_and_rejects_changed_file(self):
        ledger = next(c for c in self.copies if c["role"] == "localization_ledger")
        ref = {k: ledger[k] for k in ("path", "sha256")}
        provenance._ref(ref, readonly=True, contents=False)
        with patch.object(provenance.os, "fdopen", wraps=os.fdopen) as opened:
            provenance._ref(ref, readonly=True, contents=False)
            opened.assert_not_called()
        path = Path(ref["path"])
        before, raw = path.stat(), path.read_bytes()
        path.chmod(0o644)
        path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        path.chmod(0o444)
        with self.assertRaises(ValueError):
            provenance._ref(ref, readonly=True, contents=False)

    def test_cached_hash_does_not_accept_new_hardlink(self):
        ledger = next(c for c in self.copies if c["role"] == "localization_ledger")
        ref = {k: ledger[k] for k in ("path", "sha256")}
        provenance._ref(ref, readonly=True, contents=False)
        os.link(ref["path"], self.root / "ledger-hardlink")
        with self.assertRaises(ValueError):
            provenance._ref(ref, readonly=True, contents=False)

    def test_unchanged_hashed_database_reuses_integrity_check(self):
        traces, connect = [], sqlite3.connect
        provenance._SQLITE_CHECK_CACHE.clear()
        def tracked(*args, **kwargs):
            db = connect(*args, **kwargs)
            db.set_trace_callback(traces.append)
            return db
        with patch.object(provenance.sqlite3, "connect", side_effect=tracked):
            self.validate()
            self.validate()
        self.assertEqual(traces.count("PRAGMA quick_check"), 1)

    def test_self_declared_scorer_identity_cannot_relabel_cpu_history(self):
        row = self.add_import()
        row["scorer_sha256"] = "d" * 64
        self.proof["freeze"]["scorer_sha256"] = "d" * 64
        with self.assertRaises(ValueError):
            self.validate()


class SystemGnomeShellTests(unittest.TestCase):
    def setUp(self):
        self.pid, self.uid = 8374, 125
        self.account = SimpleNamespace(pw_name="gdm", pw_uid=self.uid,
                                       pw_dir="/var/lib/gdm3", pw_shell="/bin/false")
        self.file = SimpleNamespace(st_dev=1, st_ino=2, st_size=8, st_mtime_ns=3, st_ctime_ns=4,
                                    st_mode=provenance.stat.S_IFREG | 0o755, st_nlink=1, st_uid=0, st_gid=0)
        self.identity = {"pid": self.pid, "uid": self.uid, "start_ticks": 123,
                         "parent_pid": 1, "state": "S"}
        self.status = f"Uid:\t{self.uid}\t{self.uid}\t{self.uid}\t{self.uid}\n"
        self.comm, self.cmdline, self.binary = "gnome-shell\n", b"/usr/bin/gnome-shell\0", b"\x7fELFtest"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(provenance, "_process_identity", side_effect=lambda pid: dict(self.identity)))
        self.stack.enter_context(patch.object(provenance.pwd, "getpwuid", side_effect=lambda uid: self.account))
        self.stack.enter_context(patch.object(Path, "lstat", side_effect=lambda: self.file))
        self.stack.enter_context(patch.object(Path, "read_text", autospec=True,
            side_effect=lambda path: self.status if path.name == "status" else self.comm))
        self.stack.enter_context(patch.object(Path, "read_bytes", autospec=True,
            side_effect=lambda path: self.cmdline if path.name == "cmdline" else self.binary))
        self.stack.enter_context(patch.object(Path, "resolve", side_effect=PermissionError(errno.EACCES, "cross uid")))

    def check(self, kind="G", name="/usr/bin/gnome-shell"):
        return provenance._system_gnome_shell(self.pid, name, kind)

    def test_verified_gdm_graphics_and_gpu_inventory(self):
        self.assertTrue(self.check())
        process = (f"<process_info><pid>{self.pid}</pid><type>G</type>"
                   "<process_name>/usr/bin/gnome-shell</process_name></process_info>")
        provenance._gpu(gpu_xml(process=process), GPU, set())

    def test_other_users_names_types_and_commands_rejected(self):
        self.assertFalse(self.check("C"))
        self.assertFalse(self.check(name="/tmp/gnome-shell"))
        for field, value in [("pw_name", "researcher"), ("pw_uid", 1001),
                             ("pw_dir", "/home/gdm"), ("pw_shell", "/bin/bash")]:
            with self.subTest(field=field):
                original = getattr(self.account, field)
                setattr(self.account, field, value)
                self.assertFalse(self.check())
                setattr(self.account, field, original)
        for field, value in [("status", "Uid:\t125\t125\t1001\t125\n"),
                             ("comm", "python\n"), ("cmdline", b"/usr/bin/gnome-shell\0--research\0")]:
            with self.subTest(field=field):
                original = getattr(self, field)
                setattr(self, field, value)
                self.assertFalse(self.check())
                setattr(self, field, original)

    def test_unsafe_or_changed_process_and_binary_rejected(self):
        for field, value in [("st_uid", 125), ("st_mode", provenance.stat.S_IFREG | 0o775),
                             ("st_mode", provenance.stat.S_IFLNK | 0o755)]:
            with self.subTest(field=field):
                original = getattr(self.file, field)
                setattr(self.file, field, value)
                self.assertFalse(self.check())
                setattr(self.file, field, original)
        self.binary = b"#!/bin/sh"
        self.assertFalse(self.check())
        self.binary = b"\x7fELFtest"
        changed = dict(self.identity, start_ticks=124)
        with patch.object(provenance, "_process_identity", side_effect=[self.identity, changed]):
            self.assertFalse(self.check())


class PermissionTests(Fixture):
    def setUp(self):
        super().setUp()
        self.host = {"hostname": "cpu-fixture", "machine_id_sha256": "f" * 64, "account_uid": os.geteuid()}
        raw = write(self.root / "platform.html", b"CPU TEST ONLY; not a platform observation")
        xml = write(self.root / "probe.xml", gpu_xml())
        self.platform = {"source": "https://gpu.orz2333.fun/", "observed_at_utc": NOW.isoformat(),
            "effective_gpu_cap": 4, "other_or_unknown_occupied_gpus": 1, "approved_gpu_uuids": [GPU],
            "raw_capture": raw, "other_occupancy": [{"count": 1, "reason": "unknown legacy writer",
                "evidence": self.legacy}], "gpus": [{"gpu_uuid": GPU, "server": "school104",
                "disabled": False, "sampling_valid": True, "allocation_conflict": False}]}
        self.probe = {**self.host, "server": "school104", "gpu_uuid": GPU,
            "observed_at_utc": NOW.isoformat(), "raw_nvidia_smi_xml": xml}
        self.prepared = SimpleNamespace(bundle={"inputs": {"source_isolation": self.proof_ref}},
            assignment={"worker_id": "worker", "server": "school104", "gpu_uuid": GPU,
                "output_root": str(self.output / "workers" / "worker-S0")},
            assignment_sha256="a" * 64, manifest_sha256="b" * 64)
        self.permit = {"run_id": RUN, "manifest_sha256": "b" * 64, "assignment_sha256": "a" * 64,
            "worker_id": "worker", "server": "school104", "gpu_uuid": GPU, "allowed": True,
            "observed_at_utc": NOW.isoformat(), "expires_at_utc": (NOW + timedelta(seconds=120)).isoformat(),
            "launcher": {"pid": os.getpid(), "uid": os.geteuid(), "start_ticks": 123},
            "effective_gpu_cap": 4, "other_or_unknown_occupied_gpus": 1, "approved_gpu_uuids": [GPU]}
        self.mocks = ExitStack()
        self.mocks.enter_context(patch.object(provenance, "_now", return_value=NOW))
        self.mocks.enter_context(patch.object(provenance, "_host_identity", return_value=self.host))
        self.mocks.enter_context(patch.object(provenance, "_process_identity", side_effect=lambda pid: {
            "pid": pid, "uid": os.geteuid(), "start_ticks": 123, "parent_pid": 0, "state": "S"}))
        self.mocks.enter_context(patch.object(provenance, "_live_gpu_xml", return_value=gpu_xml()))

    def tearDown(self):
        self.mocks.close()
        super().tearDown()

    def check_permit(self):
        self.permit["platform_evidence"] = write(self.root / "platform.json", self.platform)
        self.permit["probe_evidence"] = write(self.root / "probe.json", self.probe)
        ref = write(self.root / "permit.json", self.permit)
        return provenance.validate_worker_permission(self.prepared, ref["path"], ref["sha256"])

    def test_current_launcher_avoids_future_worker_pid_dependency(self):
        self.assertTrue(self.check_permit()["allowed"])

    def test_assignment_or_launcher_identity_mismatch_fails(self):
        self.permit["assignment_sha256"] = "c" * 64
        with self.assertRaises(ValueError):
            self.check_permit()
        self.permit["assignment_sha256"] = "a" * 64
        self.permit["launcher"]["start_ticks"] = 124
        with self.assertRaises(ValueError):
            self.check_permit()

    def test_unrelated_launcher_or_dead_launcher_fails(self):
        self.permit["launcher"]["pid"] = os.getpid() + 100
        with self.assertRaises(ValueError):
            self.check_permit()
        self.permit["launcher"]["pid"] = os.getpid()
        with patch.object(provenance, "_process_identity", return_value={"pid": os.getpid(),
                "uid": os.geteuid(), "start_ticks": 123, "parent_pid": 0, "state": "Z"}):
            with self.assertRaises(ValueError):
                self.check_permit()

    def test_gpu_upper_bound_includes_unknown_legacy_device(self):
        self.permit["effective_gpu_cap"] = 1
        with self.assertRaises(ValueError):
            self.check_permit()
        self.permit["effective_gpu_cap"] = 4
        self.permit["other_or_unknown_occupied_gpus"] = 0
        with self.assertRaises(ValueError):
            self.check_permit()

    def test_three_new_gpus_plus_one_unknown_fit_but_four_do_not(self):
        extra = ["GPU-21111111-2222-3333-4444-555555555555", "GPU-31111111-2222-3333-4444-555555555555"]
        self.permit["approved_gpu_uuids"].extend(extra)
        self.platform["approved_gpu_uuids"] = list(self.permit["approved_gpu_uuids"])
        self.platform["gpus"].extend({"gpu_uuid": uuid, "server": "school104",
            "disabled": False, "sampling_valid": True, "allocation_conflict": False} for uuid in extra)
        self.assertTrue(self.check_permit()["allowed"])
        self.permit["approved_gpu_uuids"].append("GPU-41111111-2222-3333-4444-555555555555")
        with self.assertRaises(ValueError):
            self.check_permit()

    def test_reserved_legacy_gpu_cannot_be_selected_as_free(self):
        self.permit["approved_gpu_uuids"].append(OLD_GPU)
        with self.assertRaises(ValueError):
            self.check_permit()

    def test_stale_future_or_oversized_permission_rejected(self):
        self.permit["expires_at_utc"] = NOW.isoformat()
        with self.assertRaises(ValueError):
            self.check_permit()
        self.permit["expires_at_utc"] = (NOW + timedelta(seconds=121)).isoformat()
        with self.assertRaises(ValueError):
            self.check_permit()

    def test_stale_platform_and_wrong_host_rejected(self):
        self.platform["observed_at_utc"] = (NOW - timedelta(seconds=121)).isoformat()
        with self.assertRaises(ValueError):
            self.check_permit()
        self.platform["observed_at_utc"] = NOW.isoformat()
        self.probe["hostname"] = "other-machine"
        with self.assertRaises(ValueError):
            self.check_permit()

    def test_raw_gpu_uuid_and_process_inventory_are_checked(self):
        self.probe["raw_nvidia_smi_xml"] = write(self.root / "wrong.xml", gpu_xml(OLD_GPU))
        with self.assertRaises(ValueError):
            self.check_permit()
        self.probe["raw_nvidia_smi_xml"] = write(self.root / "probe.xml", gpu_xml())
        other = "<process_info><pid>8888</pid><type>C</type><process_name>python</process_name></process_info>"
        with patch.object(provenance, "_live_gpu_xml", return_value=gpu_xml(process=other)):
            with self.assertRaises(ValueError):
                self.check_permit()

    def test_disabled_or_conflicting_platform_gpu_rejected(self):
        for field in ("disabled", "allocation_conflict"):
            self.platform["gpus"][0][field] = True
            with self.assertRaises(ValueError):
                self.check_permit()
            self.platform["gpus"][0][field] = False

    def test_unknown_occupancy_requires_hashed_source_evidence(self):
        self.platform["other_occupancy"] = []
        with self.assertRaises(ValueError):
            self.check_permit()

    def test_expiry_is_rechecked_after_live_gpu_probe(self):
        with patch.object(provenance, "_now", side_effect=[NOW, NOW + timedelta(seconds=121)]):
            with self.assertRaises(ValueError):
                self.check_permit()


if __name__ == "__main__":
    unittest.main()
