"""CPU-only safety checks; never connect or install on any server."""
from __future__ import annotations
import ast
import hashlib
import os
import types
import io
import json
import sys
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import prepare_node103_offline as prep


def member(name, *, kind=tarfile.REGTYPE, target="", size=1):
    m = tarfile.TarInfo(name)
    m.type, m.linkname, m.size = kind, target, size
    return m


class FakeProcess:
    def __init__(self, *, timeout=False):
        self.stdout = io.BytesIO()
        self.returncode = None
        self.timed_out = timeout
        self.terminated = self.killed = False
    def communicate(self, timeout):
        if self.timed_out:
            raise subprocess.TimeoutExpired("fake SSH", timeout)
        self.returncode = 0
        return b"{}", b""
    def poll(self):
        return self.returncode
    def terminate(self):
        self.terminated = True
        self.returncode = -15
    def kill(self):
        self.killed = True
        self.returncode = -9
    def wait(self, timeout):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class PreparationTests(unittest.TestCase):
    def test_frozen_manifests_cover_exact_assets(self):
        wheels, models = prep.checked_entries("wheels"), prep.checked_entries("models")
        self.assertEqual(len(wheels), 51)
        self.assertEqual(len(models), 47)
        self.assertEqual(len({r["relative"] for r in wheels + models}), 98)
        self.assertTrue(all(len(e["sha256"]) == 64 for e in wheels + models))

    def test_paths_cannot_escape_or_use_alias_spelling(self):
        for path in ("", ".", "../secret", "/home/other/file", "models/../../file", "models//file", "models/./file", "models/f\nile", "models\\file"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                prep.safe_relative(path)
        self.assertEqual(prep.safe_relative("models/sd15/config.json"), "models/sd15/config.json")

    def test_bad_partial_hash_is_never_appended(self):
        full = "a" * 64
        entry = {"size": 100, "sha256": full}
        source = {"size": 100, "sha256": full, "prefix_sha256": "b" * 64}
        target = {"prefix_size": 10, "prefix_sha256": "c" * 64}
        with self.assertRaisesRegex(RuntimeError, "not the source prefix"):
            prep.ensure_prefix(source, target, entry)
        target["prefix_sha256"] = source["prefix_sha256"]
        self.assertEqual(prep.ensure_prefix(source, target, entry), 10)
        source["sha256"] = "f" * 64
        with self.assertRaisesRegex(RuntimeError, "Frozen source"):
            prep.ensure_prefix(source, target, entry)

    def test_existing_verified_target_never_opens_source_or_stream(self):
        entry = {"relative": "models/a.bin", "size": 10, "sha256": "a" * 64}
        with patch.object(prep, "remote_json", return_value={"complete": True, "size": 10, "sha256": "a" * 64}) as remote, patch.object(prep.subprocess, "Popen") as process:
            result = prep.relay(Path("/tmp/test-config"), entry)
        self.assertEqual(result["status"], "verified_existing_target")
        self.assertEqual(remote.call_count, 1)
        process.assert_not_called()

    def test_timeout_terminates_both_local_transport_processes_without_retry(self):
        entry = {"relative": "models/a.bin", "size": 10, "sha256": "a" * 64}
        empty = hashlib.sha256(b"").hexdigest()
        target = {"complete": False, "prefix_size": 0, "prefix_sha256": empty}
        source = {"size": 10, "sha256": "a" * 64, "prefix_sha256": empty}
        read, write = FakeProcess(), FakeProcess(timeout=True)
        with patch.object(prep, "remote_json", side_effect=[target, source]) as remote, patch.object(prep.subprocess, "Popen", side_effect=[read, write]) as process:
            with self.assertRaises(subprocess.TimeoutExpired):
                prep.relay(Path("/tmp/test-config"), entry)
        self.assertEqual(process.call_count, 2)
        self.assertEqual(remote.call_count, 2)
        self.assertTrue(read.terminated and write.terminated)

    def test_ssh_uses_registered_aliases_and_strict_host_validation(self):
        argv = prep.ssh_argv(Path("/tmp/config"), "school103", "print('ok')")
        self.assertIn("StrictHostKeyChecking=yes", argv)
        self.assertIn("BatchMode=yes", argv)
        self.assertIn("ConnectionAttempts=1", argv)
        self.assertIn("ControlPath=none", argv)
        self.assertEqual(argv[-2], "school103")
        with self.assertRaises(ValueError):
            prep.ssh_argv(Path("/tmp/config"), "192.168.1.206", "print('no')")

    def test_tar_symlink_within_private_tree_allowed(self):
        items = [member("python/bin/python3.11"), member("python/bin/python3", kind=tarfile.SYMTYPE, target="python3.11")]
        self.assertEqual(prep.archive_members_safe(items), 2)

    def test_tar_paths_links_and_special_files_are_rejected_before_extract(self):
        cases = [
            [member("../../outside")],
            [member("/tmp/outside")],
            [member("python/bin/link", kind=tarfile.SYMTYPE, target="../../../outside")],
            [member("python/bin/link", kind=tarfile.SYMTYPE, target="/tmp/outside")],
            [member("python/hard", kind=tarfile.LNKTYPE, target="python/lib")],
            [member("python/device", kind=tarfile.CHRTYPE)],
            [member("python/dir", kind=tarfile.SYMTYPE, target="lib"), member("python/dir/sub")],
            [member("python/repeated"), member("python/repeated")],
        ]
        for items in cases:
            with self.subTest(names=[m.name for m in items]), self.assertRaises(ValueError):
                prep.archive_members_safe(items)

    def test_actual_archive_hash_and_safe_listing_without_install(self):
        entries = prep.checked_entries("python")
        self.assertEqual(entries[0]["sha256"], prep.ARCHIVE_SHA)
        with tarfile.open(prep.ARCHIVE, "r:gz") as tar:
            members = tar.getmembers()
            expanded = prep.archive_members_safe(members)
        self.assertEqual(len(members), 2364)
        self.assertEqual(expanded, 91072956)

    def test_remote_templates_compile_without_execution(self):
        for name in ("REMOTE_PREFLIGHT", "REMOTE_DEST_INFO", "REMOTE_SOURCE_INFO", "REMOTE_READ", "REMOTE_RECEIVE", "ENV_WRAPPER"):
            compile(getattr(prep, name), name, "exec")
        compile(prep.python_install_source(), "PYTHON_INSTALL", "exec")

    def test_receiver_rejects_hardlinked_partial_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original, partial, target = root / "unrelated.bin", root / "asset.partial", root / "asset"
            original.write_bytes(b"existing-user-data")
            os.link(original, partial)
            remote_body = prep.REMOTE_RECEIVE[len(prep.REMOTE_COMMON):]
            namespace = {"sys": types.SimpleNamespace(argv=["relay", "asset", "18", "20", "a" * 64, "b" * 64]),
                         "DEST": str(root), "checked": lambda base, relative, create: partial if relative.endswith(".partial") else target,
                         "remote_lock": lambda: None}
            with self.assertRaisesRegex(AssertionError, "hardlinked"):
                exec(compile(remote_body, "remote-receiver-test", "exec"), namespace)
            self.assertEqual(original.read_bytes(), b"existing-user-data")
            self.assertEqual(partial.read_bytes(), b"existing-user-data")

    def test_system_python38_can_parse_remote_bootstrap_code(self):
        for source in (prep.REMOTE_PREFLIGHT, prep.REMOTE_DEST_INFO, prep.REMOTE_SOURCE_INFO,
                       prep.REMOTE_READ, prep.REMOTE_RECEIVE, prep.python_install_source()):
            ast.parse(source, feature_version=(3, 8))

    def test_install_wrapper_refuses_unrelated_venv_before_loading_installer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "setup").mkdir()
            base = root / "python-standalone-3.11.7-20240107"
            (base / "bin").mkdir(parents=True)
            (base / "bin/python3.11").write_bytes(b"synthetic executable identity only")
            state = {"status": "completed", "archive_sha256": prep.ARCHIVE_SHA,
                     "python_sha256": prep.sha256(base / "bin/python3.11")}
            (root / "setup/python_install_state.json").write_text(json.dumps(state))
            prefix = prep.ENV_WRAPPER.split("source=root/'setup/install_school_offline_env.py'", 1)[0]
            prefix = prefix.replace("pathlib.Path('/data1/zhangzibo/arxiv-tssa')", "pathlib.Path(" + repr(str(root)) + ")")
            with patch.object(sys, "version_info", (3, 11, 7)), patch.object(sys, "prefix", str(root / "unrelated-venv")), patch.object(sys, "base_prefix", str(base)):
                with self.assertRaisesRegex(AssertionError, "unrelated pre-existing"):
                    exec(compile(prefix, "isolated-wrapper-prerequisite", "exec"), {})
            self.assertFalse((root / "setup/environment_install_state.json").exists())

    def test_local_prefix_hash_rejects_length_beyond_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "small.bin"
            path.write_bytes(b"abcdef")
            self.assertEqual(prep.sha256(path, 3), hashlib.sha256(b"abc").hexdigest())
            with self.assertRaises(RuntimeError):
                prep.sha256(path, 7)


if __name__ == "__main__":
    unittest.main()
