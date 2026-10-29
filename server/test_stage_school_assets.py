"""Offline transfer audit; no school connections or actual downloads are made.

Recovery and integrity regressions for the next helper revision, isolated from
the currently running production transfer and its lock.
"""
from __future__ import annotations

from contextlib import ExitStack, redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import quote


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
spec = importlib.util.spec_from_file_location("stage_school_assets_audit", HERE / "stage_school_assets.py")
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)


class FakeSession:
    def __init__(self, existing=None, fail_commit=False):
        self.existing = existing or {"exists": False}
        self.fail_commit = fail_commit
        self.upload_calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def upload(self, local, remote):
        self.upload_calls.append((Path(local), remote))

    def remote(self, source, *args):
        if source == stage.REMOTE_CHECK:
            return json.dumps(self.existing)
        if source == stage.REMOTE_COMMIT:
            if self.fail_commit:
                raise RuntimeError("simulated lost commit response")
            return json.dumps({"exists": True, "sha256": args[1], "size": int(args[2])})
        raise AssertionError("Unexpected remote operation")


class TransferRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="school-stage-audit-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.staging = self.root / "staging"
        self.staging.mkdir(mode=0o700)
        self.ledger = self.root / "ledger.jsonl"

    def entry(self, payload=b"official", with_sha=True):
        return {
            "repo_id": "public/fixture",
            "revision": "a" * 40,
            "path": "config.json",
            "local_dir": "fixture",
            "local_path": "fixture/config.json",
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest() if with_sha else None,
            "git_blob_oid": hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest(),
        }

    def part_path(self, entry):
        url = "https://huggingface.co/" + entry["repo_id"] + "/resolve/" + entry["revision"] + "/" + quote(entry["path"], safe="/")
        return self.staging / (hashlib.sha256(url.encode()).hexdigest() + ".part")

    def invoke(self, entries, session, payload=b"official", extra=()):
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps({"files": entries}))
        argv = ["stage_school_assets.py", "--manifest", str(manifest), "--staging", str(self.staging), "--ledger", str(self.ledger), *extra]

        def fake_run(command, **_):
            if command[0] != "curl":
                raise AssertionError("Only a simulated local curl is permitted")
            Path(command[command.index("-o") + 1]).write_bytes(payload)
            return subprocess.CompletedProcess(command, 0)

        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(sys, "argv", argv))
            session_factory = stack.enter_context(mock.patch.object(stage, "SchoolSession", return_value=session))
            stack.enter_context(mock.patch.object(stage, "LOCK_PATH", self.staging / ".test-transfer.lock"))
            stack.enter_context(mock.patch.object(stage, "run", side_effect=fake_run))
            stack.enter_context(mock.patch.object(stage.subprocess, "run", side_effect=AssertionError("Real subprocess forbidden")))
            stack.enter_context(mock.patch.object(stage.socket, "create_connection", side_effect=AssertionError("Network forbidden")))
            stack.enter_context(mock.patch.object(stage.shutil, "disk_usage", return_value=mock.Mock(free=100 * 1024**3)))
            stack.enter_context(redirect_stdout(io.StringIO()))
            stage.main()
            return session_factory.call_args

    def test_failed_commit_retains_local_file_without_verified_ledger_entry(self):
        entry = self.entry()
        session = FakeSession(fail_commit=True)
        with self.assertRaisesRegex(RuntimeError, "lost commit response"):
            self.invoke([entry], session)
        self.assertTrue(self.part_path(entry).exists())
        self.assertFalse(self.ledger.exists())
        self.assertEqual(len(session.upload_calls), 1)

    def test_successful_commit_removes_only_staging_payload(self):
        entry = self.entry()
        sentinel = self.staging / "unrelated-user-file"
        sentinel.write_text("retain")
        self.invoke([entry], FakeSession())
        self.assertFalse(self.part_path(entry).exists())
        self.assertEqual(sentinel.read_text(), "retain")
        record = json.loads(self.ledger.read_text())
        self.assertEqual(record["status"], "transferred_verified")
        self.assertEqual(record["sha256"], entry["sha256"])

    def test_remote_commit_recovery_cleans_matching_task_local_part(self):
        entry = self.entry()
        self.part_path(entry).write_bytes(b"official")
        session = FakeSession(existing={"exists": True, "sha256": entry["sha256"], "size": entry["size"]})
        self.invoke([entry], session)
        self.assertEqual(session.upload_calls, [])
        self.assertFalse(self.part_path(entry).exists(), "Verified remote success must not strand a full local staging file")

    def test_non_lfs_same_size_wrong_git_blob_is_rejected(self):
        entry = self.entry(with_sha=False)
        with self.assertRaises((RuntimeError, ValueError)):
            self.invoke([entry], FakeSession(), payload=b"tampered")

    def test_empty_role_selection_does_not_return_success(self):
        with self.assertRaises((RuntimeError, ValueError, SystemExit)):
            self.invoke([self.entry()], FakeSession(), extra=("--role", "missing-role"))

    def test_temporary_session_is_cleaned_when_master_shutdown_times_out(self):
        session = stage.SchoolSession()
        session.config = self.root / "fake-config"
        session.temporary = mock.Mock()
        with mock.patch.object(stage.subprocess, "run", side_effect=subprocess.TimeoutExpired("ssh", 15)):
            try:
                session.__exit__(None, None, None)
            except subprocess.TimeoutExpired:
                pass
        session.temporary.cleanup.assert_called_once()

    def test_upload_resumes_only_a_verified_prefix_and_skips_complete_copy(self):
        local = self.root / "fixture with spaces"
        local.write_bytes(b"official")
        session = stage.SchoolSession()
        session.config = self.root / "fake-config"
        for size in (0, 3, len(b"official")):
            with self.subTest(size=size):
                prefix = hashlib.sha256(b"official"[:size]).hexdigest()
                with mock.patch.object(session, "remote", return_value=json.dumps({"size": size, "sha256": prefix})), \
                        mock.patch.object(stage, "run") as execute:
                    session.upload(local, stage.REMOTE_ROOT + "/fixture.uploading")
                    if size == len(b"official"):
                        execute.assert_not_called()
                    else:
                        self.assertEqual(execute.call_args.args[0][0], "sftp")
                        self.assertTrue(execute.call_args.kwargs["input"].startswith("reput " if size else "put "))
                        self.assertIn('"' + str(local) + '"', execute.call_args.kwargs["input"])

    def test_upload_mismatch_keeps_both_copies_untouched(self):
        local = self.root / "fixture"
        local.write_bytes(b"official")
        session = stage.SchoolSession()
        with mock.patch.object(session, "remote", return_value=json.dumps({"size": 3, "sha256": "0" * 64})), \
                mock.patch.object(stage, "run") as execute:
            with self.assertRaisesRegex(RuntimeError, "prefix differs"):
                session.upload(local, stage.REMOTE_ROOT + "/fixture.uploading")
            execute.assert_not_called()
        self.assertEqual(local.read_bytes(), b"official")

    def test_independent_sftp_option_reaches_transport_without_changing_verified_resume(self):
        options = self.invoke([self.entry()], FakeSession(), extra=("--independent-sftp", "--verbose-sftp"))
        self.assertEqual(options.kwargs, {"independent_sftp": True, "verbose_sftp": True, "ssh_chunk_bytes": 0})
        local = self.root / "payload"
        local.write_bytes(b"official")
        session = stage.SchoolSession(**options.kwargs)
        session.config = self.root / "same-strict-config"
        prefix = hashlib.sha256(b"off").hexdigest()
        with mock.patch.object(session, "remote", return_value=json.dumps({"size": 3, "sha256": prefix})), \
                mock.patch.object(stage, "run") as execute:
            session.upload(local, stage.REMOTE_ROOT + "/fixture.uploading")
        self.assertEqual(execute.call_args.args[0], ["sftp", "-vv", "-b", "-", "-F", str(session.config),
                                                   "-o", "ControlMaster=no", "-o", "ControlPath=none", "school104"])
        self.assertTrue(execute.call_args.kwargs["input"].startswith("reput "))
        status = json.loads(next(self.root.glob("ledger.*.status.json")).read_text())
        self.assertTrue(status["independent_sftp"] and status["verbose_sftp"])

    def test_default_sftp_keeps_existing_connection_behavior(self):
        options = self.invoke([self.entry()], FakeSession())
        self.assertEqual(options.kwargs, {"independent_sftp": False, "verbose_sftp": False, "ssh_chunk_bytes": 0})

    def test_chunk_size_cli_is_bounded_and_reaches_session(self):
        options = self.invoke([self.entry()], FakeSession(), extra=("--ssh-chunk-bytes", "16777216"))
        self.assertEqual(options.kwargs["ssh_chunk_bytes"], 16777216)
        status = json.loads(next(self.root.glob("ledger.*.status.json")).read_text())
        self.assertEqual(status["ssh_chunk_bytes"], 16777216)
        for bad in ("-1", "67108865"):
            with self.subTest(size=bad), self.assertRaises(SystemExit):
                self.invoke([self.entry()], FakeSession(), extra=("--ssh-chunk-bytes", bad))

    def test_manifest_status_distinguishes_failure_and_complete(self):
        entry = self.entry()
        with self.assertRaises(RuntimeError):
            self.invoke([entry], FakeSession(fail_commit=True))
        paths = list(self.root.glob("ledger.*.status.json"))
        self.assertEqual(len(paths), 1)
        status = json.loads(paths[0].read_text())
        self.assertEqual((status["status"], status["verified_files"]), ("failed", 0))
        self.invoke([entry], FakeSession())
        status = json.loads(paths[0].read_text())
        self.assertEqual((status["status"], status["verified_files"], status["selected_files"]), ("complete", 1, 1))

    def test_unsafe_relative_paths_are_rejected(self):
        for value in ("/etc/passwd", "../escape", "ok/../../escape", "bad name", "$(cmd)"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                stage.validate_relative(value)


class ManifestOfflineInstallTests(unittest.TestCase):
    def test_environment_wheels_match_the_version_hash_lock_and_remote_layout(self):
        data = json.loads((ROOT / "research/tssa_mvp_environment_2026-10-26.json").read_text())
        lock = ROOT / data["lock_file"]
        self.assertEqual(hashlib.sha256(lock.read_bytes()).hexdigest(), data["lock_file_sha256"])
        blocks = {}
        current = None
        for line in lock.read_text().splitlines():
            match = re.match(r"^([A-Za-z0-9_.-]+)==([^\s\\;]+)", line)
            if match:
                current = match.groups()
                blocks[current] = set()
            if current:
                blocks[current].update(re.findall(r"--hash=sha256:([a-f0-9]{64})", line))
        self.assertEqual(len(data["files"]), len(blocks))
        for entry in data["files"]:
            with self.subTest(package=entry["name"]):
                self.assertIn(entry["sha256"], blocks[(entry["name"], entry["version"])])
                self.assertEqual(entry["local_path"], "wheelhouse/" + entry["filename"])
                self.assertEqual(entry["kind"], "wheel")
                self.assertFalse(any(x in entry["filename"] for x in ("macosx", "win_amd64", "win32", "aarch64", "arm64")))
        self.assertEqual(sum(e["size"] for e in data["files"]), data["total_wheel_bytes"])

    def test_model_manifest_has_pinned_source_integrity_identifiers(self):
        data = json.loads((ROOT / "research/tssa_mvp_assets_2026-10-26.json").read_text())
        destinations = set()
        for entry in data["files"]:
            with self.subTest(path=entry["local_path"]):
                self.assertEqual(len(entry["revision"]), 40)
                self.assertNotIn(entry["local_path"], destinations)
                destinations.add(entry["local_path"])
                stage.validate_relative(entry["local_path"])
                self.assertEqual(len(entry["sha256"] or entry["git_blob_oid"]), 64 if entry["sha256"] else 40)
        self.assertEqual(sum(e["size"] for e in data["files"]), data["total_model_bytes"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
