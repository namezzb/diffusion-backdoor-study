#!/usr/bin/env python3
"""Offline safety checks: no SSH connection or research task is started."""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location("fetch_server_file", Path(__file__).with_name("fetch_server_file.py"))
fetch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch)


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="research-fetch-test-")
        self.root = Path(self.temporary.name).resolve()
        self.target = self.root / "target"
        self.receipt = self.root / "receipts" / "one.json"
        self.data = b"research evidence\n"
        self.row = {"server": "104", "ssh_alias": "school104", "remote_root": fetch.ROOTS["104"],
                    "relative_path": "results/run/file.bin", "remote_path": fetch.ROOTS["104"] + "/results/run/file.bin",
                    "bytes": len(self.data), "sha256": hashlib.sha256(self.data).hexdigest(),
                    "inventory_observed_at": "2026-10-29T02:11:14+00:00"}
        (self.root / "storage/server-index").mkdir(parents=True)
        (self.root / "server").mkdir()
        self.config = self.root / "server/school_ssh_config"
        self.config.write_text("Host school104\n    HostName 192.168.1.104\n")
        self.write_index()

    def tearDown(self):
        self.temporary.cleanup()

    def write_index(self, rows=None):
        (self.root / "storage/server-index/104.jsonl").write_text(
            "\n".join(json.dumps(row) for row in (rows or [self.row])) + "\n")

    def run_download(self, chunks=None, **kwargs):
        transport = mock.Mock(return_value=iter([self.data] if chunks is None else chunks))
        result = fetch.download(self.row, self.target, self.receipt, transport, reserve_bytes=0, **kwargs)
        self.assertEqual(result, json.loads(self.receipt.read_text()))
        return result, transport

    def destination(self):
        return self.target / self.row["relative_path"]

    def assert_no_payload(self):
        self.assertFalse(self.destination().exists())
        self.assertEqual([], list(self.root.rglob("*.part")))

    def test_plan_only_does_not_connect_or_write(self):
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))
        with mock.patch.object(fetch.subprocess, "Popen", side_effect=AssertionError("network")), contextlib.redirect_stdout(io.StringIO()) as output:
            code = fetch.main(["--server", "104", self.row["relative_path"], "--target", str(self.target)], repo=self.root)
        self.assertEqual(0, code)
        self.assertFalse(json.loads(output.getvalue())["network_started"])
        self.assertEqual(before, sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*")))

    def test_metadata_only_plan_and_download_refusal(self):
        self.row["sha256"] = None
        self.write_index()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, fetch.main(["--server", "104", self.row["relative_path"], "--target", str(self.target)], repo=self.root))
        self.assertFalse(json.loads(output.getvalue())["download_eligible"])
        transport = mock.Mock()
        with self.assertRaisesRegex(fetch.FetchError, "metadata-only"):
            fetch.download(self.row, self.target, self.receipt, transport)
        transport.assert_not_called()
        self.assertFalse(self.target.exists())

    def test_exact_file_download_and_idempotent_reuse(self):
        result, transport = self.run_download([self.data[:4], self.data[4:]])
        self.assertEqual("downloaded_and_verified", result["status"])
        self.assertEqual(self.data, self.destination().read_bytes())
        self.assertEqual([], list(self.root.rglob("*.part")))
        self.receipt = self.root / "receipts/two.json"
        result, transport = self.run_download()
        self.assertEqual("reused_existing_verified_file", result["status"])
        transport.assert_not_called()

    def test_different_existing_file_refuses_without_network(self):
        self.destination().parent.mkdir(parents=True)
        self.destination().write_bytes(b"other content")
        result, transport = self.run_download()
        self.assertEqual("failed", result["status"])
        self.assertIn("conflicts", result["error"])
        self.assertEqual(b"other content", self.destination().read_bytes())
        transport.assert_not_called()

    def test_truncation_hash_mismatch_and_overrun_never_publish(self):
        for index, data in enumerate((self.data[:-1], b"x" * len(self.data), self.data + b"x")):
            with self.subTest(index=index):
                self.receipt = self.root / "receipts" / (str(index) + ".json")
                result, _ = self.run_download([data])
                self.assertEqual("failed", result["status"])
                self.assert_no_payload()

    def test_transport_failure_closes_stream_and_removes_only_own_part(self):
        closed = []
        def broken():
            try:
                yield self.data[:3]
                raise fetch.FetchError("transport failed")
            finally:
                closed.append(True)
        self.destination().parent.mkdir(parents=True)
        unrelated = self.destination().parent / "another.part"
        unrelated.write_bytes(b"keep")
        result = fetch.download(self.row, self.target, self.receipt, broken, reserve_bytes=0)
        self.assertEqual("failed", result["status"])
        self.assertEqual([True], closed)
        self.assertFalse(self.destination().exists())
        self.assertEqual(b"keep", unrelated.read_bytes())

    def test_rejects_traversal_absolute_control_and_ambiguous_paths(self):
        for path in ("../outside", "/tmp/file", "a/../b", "a//b", "a/./b", "a\\b", "a\nb", "a\x00b", "a/", ""):
            with self.subTest(path=path), self.assertRaises(fetch.FetchError):
                fetch.relative_path(path)

    def test_rejects_wrong_server_root_alias_path_size_and_hash(self):
        mutations = [("server", "103"), ("remote_root", "/data2/other"), ("ssh_alias", "other"),
                     ("remote_path", "/etc/passwd"), ("bytes", -1), ("bytes", True),
                     ("bytes", fetch.DEFAULT_MAX_BYTES + 1), ("sha256", "X" * 64)]
        for key, value in mutations:
            row = dict(self.row, **{key: value})
            with self.subTest(key=key, value=value), self.assertRaises(fetch.FetchError):
                fetch.validate_entry(row, "104", self.row["relative_path"])

    def test_unknown_or_duplicate_index_entry_refused(self):
        with self.assertRaisesRegex(fetch.FetchError, "found 0"):
            fetch.load_entry(self.root, "104", "missing")
        self.write_index([self.row, self.row])
        with self.assertRaisesRegex(fetch.FetchError, "found 2"):
            fetch.load_entry(self.root, "104", self.row["relative_path"])

    def test_symlink_target_parent_and_target_file_refused(self):
        outside = self.root / "outside"
        outside.mkdir()
        self.target.symlink_to(outside, target_is_directory=True)
        result, transport = self.run_download()
        self.assertEqual("failed", result["status"])
        self.assertEqual([], list(outside.iterdir()))
        transport.assert_not_called()
        self.target.unlink()
        self.destination().parent.mkdir(parents=True)
        victim = outside / "victim"
        victim.write_bytes(self.data)
        self.destination().symlink_to(victim)
        self.receipt = self.root / "receipts/two.json"
        result, transport = self.run_download()
        self.assertEqual("failed", result["status"])
        self.assertEqual(self.data, victim.read_bytes())
        transport.assert_not_called()

    def test_index_and_config_symlinks_refused(self):
        index = self.root / "storage/server-index/104.jsonl"
        actual = self.root / "actual.jsonl"
        index.rename(actual)
        index.symlink_to(actual)
        with self.assertRaises(OSError):
            fetch.load_entry(self.root, "104", self.row["relative_path"])
        self.config.unlink()
        self.config.symlink_to(actual)
        with self.assertRaises(OSError):
            fetch.ssh_command(self.config, self.row)

    def test_existing_receipt_never_overwritten_or_connects(self):
        self.receipt.parent.mkdir()
        self.receipt.write_bytes(b"prior receipt")
        transport = mock.Mock()
        with self.assertRaises(FileExistsError):
            fetch.download(self.row, self.target, self.receipt, transport)
        self.assertEqual(b"prior receipt", self.receipt.read_bytes())
        transport.assert_not_called()

    def test_receipt_inside_target_refused(self):
        with self.assertRaisesRegex(fetch.FetchError, "outside"):
            fetch.download(self.row, self.target, self.target / "receipt.json", mock.Mock())

    def test_disk_reserve_refuses_before_connection(self):
        disk = type("Disk", (), {"f_bavail": 0, "f_frsize": 4096})()
        with mock.patch.object(fetch.os, "fstatvfs", return_value=disk):
            result, transport = self.run_download()
        self.assertEqual("failed", result["status"])
        transport.assert_not_called()
        self.assert_no_payload()

    def test_publish_race_never_overwrites_a_different_file(self):
        def changed():
            yield self.data
            self.destination().write_bytes(b"concurrent user file")
        result = fetch.download(self.row, self.target, self.receipt, changed, reserve_bytes=0)
        self.assertEqual("failed", result["status"])
        self.assertEqual(b"concurrent user file", self.destination().read_bytes())
        self.assertEqual([], list(self.root.rglob("*.part")))

    def test_host_keys_strict_for_both_hops_and_remote_arguments_quoted(self):
        self.row["relative_path"] = "results/space ' dollar$ name.bin"
        self.row["remote_path"] = self.row["remote_root"] + "/" + self.row["relative_path"]
        command = fetch.ssh_command(self.config, self.row)
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn("UpdateHostKeys=no", command)
        proxy = next(value.split("=", 1)[1] for value in command if value.startswith("ProxyCommand="))
        self.assertIn("StrictHostKeyChecking=yes", shlex.split(proxy))
        self.assertIn("UpdateHostKeys=no", shlex.split(proxy))
        self.assertEqual(["python3", "-I", "-c", fetch.REMOTE_READER, self.row["remote_root"],
                          self.row["relative_path"], str(self.row["bytes"])], shlex.split(command[-1]))

    def test_transport_creation_failure_closes_file_and_keeps_receipt(self):
        with mock.patch.object(fetch.os, "fdopen", wraps=fetch.os.fdopen) as wrapped:
            result = fetch.download(self.row, self.target, self.receipt,
                                    mock.Mock(side_effect=OSError("cannot launch transport")), reserve_bytes=0)
        self.assertEqual("failed", result["status"])
        self.assert_no_payload()
        for call in wrapped.call_args_list:
            with self.assertRaises(OSError):
                os.fstat(call.args[0])

    def test_remote_reader_rejects_unapproved_root_without_opening_files(self):
        with mock.patch.object(sys, "argv", ["-c", "/etc", "passwd", "100"]), \
                mock.patch.object(os, "open", side_effect=AssertionError("file opened")), \
                self.assertRaisesRegex(RuntimeError, "unapproved root"):
            exec(compile(fetch.REMOTE_READER, "<remote-reader>", "exec"), {})

    def test_remote_reader_rejects_wrong_account_without_opening_files(self):
        import pwd
        account = type("Account", (), {"pw_name": "someone_else"})()
        with mock.patch.object(sys, "argv", ["-c", fetch.ROOTS["104"], "results/file", "100"]), \
                mock.patch.object(pwd, "getpwuid", return_value=account), \
                mock.patch.object(os, "open", side_effect=AssertionError("file opened")), \
                self.assertRaisesRegex(RuntimeError, "unexpected remote account"):
            exec(compile(fetch.REMOTE_READER, "<remote-reader>", "exec"), {})

    def test_transport_deadline_stops_only_its_local_test_process(self):
        # Substitute a local Python child; never start ssh or access the network.
        command = [sys.executable, "-c", "import time; time.sleep(10)"]
        with mock.patch.object(fetch, "ssh_command", return_value=command), \
                self.assertRaisesRegex(fetch.FetchError, "timed out"):
            list(fetch.ssh_chunks(self.config, self.row, timeout=0.05))

    def test_transport_failure_after_correct_bytes_still_prevents_publication(self):
        command = [sys.executable, "-c", "import os, sys; os.write(1, " + repr(self.data) + "); sys.exit(3)"]
        with mock.patch.object(fetch, "ssh_command", return_value=command):
            result = fetch.download(self.row, self.target, self.receipt,
                                    lambda: fetch.ssh_chunks(self.config, self.row, timeout=5), reserve_bytes=0)
        self.assertEqual("failed", result["status"])
        self.assertIn("exited with code 3", result["error"])
        self.assert_no_payload()


if __name__ == "__main__":
    unittest.main()
