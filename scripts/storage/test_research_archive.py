#!/usr/bin/env python3
"""Adversarial offline archive tests; all artifacts stay in a temporary folder."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile


SCRIPT = Path(__file__).with_name("research_archive.py")
SPEC = importlib.util.spec_from_file_location("research_archive", SCRIPT)
archive_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(archive_tool)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="research-archive-test-")
        # macOS /var and /tmp may themselves be links; test a genuine directory.
        self.root = Path(self.temporary.name).resolve()
        self.package = self.root / "research.zip"
        self.manifest = self.root / "manifest.json"
        self.receipt = self.root / "receipt.json"
        self.target = self.root / "restored"

    def tearDown(self):
        self.temporary.cleanup()

    def bundle(self, entries=None, manifest_entries=None):
        entries = entries or [("research/progress.md", b"paused\n"),
                              ("results/run/metrics.json", b'{"asr":0}\n')]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.package, "w", compression=zipfile.ZIP_DEFLATED) as output:
                for path, content in entries:
                    output.writestr(path, content)
        if manifest_entries is None:
            manifest_entries = [{"path": name.filename if isinstance(name, zipfile.ZipInfo) else name,
                                 "size": len(content), "sha256": sha(content)}
                                for name, content in entries]
        data = {"schema_version": 1,
                "package": {"size": self.package.stat().st_size,
                            "sha256": sha(self.package.read_bytes())},
                "files": manifest_entries}
        self.manifest.write_text(json.dumps(data), encoding="utf-8")
        return data

    def invoke(self, command="restore", target=None, receipt=None):
        result = archive_tool.run(command, self.package, self.manifest,
                                  receipt or self.receipt,
                                  (target or self.target) if command == "restore" else None)
        self.assertEqual(result, json.loads((receipt or self.receipt).read_text()))
        return result

    def assert_failed_untouched(self, result):
        self.assertEqual("failed", result["status"])
        self.assertTrue(result["errors"])
        self.assertFalse(self.target.exists())

    def test_correct_verification_then_restore_then_idempotent_reuse(self):
        data = self.bundle()
        verified = self.invoke("verify-package")
        self.assertEqual("verified", verified["status"])
        self.assertFalse(self.target.exists())
        restored = self.invoke(receipt=self.root / "restored-receipt.json")
        self.assertEqual("restored", restored["status"])
        self.assertEqual(2, restored["counts"]["written_files"])
        for entry in data["files"]:
            self.assertEqual(entry["sha256"], sha((self.target / entry["path"]).read_bytes()))
        existing_stat = (self.target / "research/progress.md").stat()
        reused = self.invoke(receipt=self.root / "reused-receipt.json")
        self.assertEqual(2, reused["counts"]["reused_files"])
        self.assertEqual(0, reused["counts"]["written_files"])
        self.assertEqual(existing_stat.st_ino, (self.target / "research/progress.md").stat().st_ino)
        self.assertEqual([], list(self.target.rglob("*.part")))

    def test_corrupted_package_refused_before_target_creation(self):
        self.bundle()
        with self.package.open("ab") as stream:
            stream.write(b"altered")
        self.assert_failed_untouched(self.invoke())

    def test_wrong_member_hash_after_good_member_still_writes_nothing(self):
        data = self.bundle()
        data["files"][1]["sha256"] = "0" * 64
        self.manifest.write_text(json.dumps(data))
        result = self.invoke()
        self.assert_failed_untouched(result)
        self.assertEqual(1, result["counts"]["verified_files"])
        self.assertFalse(result["all_members_verified"])

    def test_unlisted_member_is_rejected(self):
        self.bundle([("allowed.txt", b"a"), ("unlisted.txt", b"b")],
                    [{"path": "allowed.txt", "size": 1, "sha256": sha(b"a")}])
        self.assert_failed_untouched(self.invoke())

    def test_missing_member_is_rejected(self):
        self.bundle([("allowed.txt", b"a")],
                    [{"path": "missing.txt", "size": 1, "sha256": sha(b"a")}])
        self.assert_failed_untouched(self.invoke())

    def test_duplicate_zip_member_is_rejected(self):
        self.bundle([("same.txt", b"first"), ("same.txt", b"other")],
                    [{"path": "same.txt", "size": 5, "sha256": sha(b"other")}])
        self.assert_failed_untouched(self.invoke())

    def test_duplicate_manifest_entry_is_rejected(self):
        entry = {"path": "a.txt", "size": 1, "sha256": sha(b"a")}
        self.bundle([("a.txt", b"a")], [entry, entry])
        self.assert_failed_untouched(self.invoke())

    def test_case_colliding_paths_are_rejected_for_portability(self):
        self.bundle([("Results/a.txt", b"a"), ("results/A.txt", b"b")])
        self.assert_failed_untouched(self.invoke())

    def test_unicode_colliding_paths_are_rejected_for_portability(self):
        self.bundle([("caf\u00e9.txt", b"a"), ("cafe\u0301.txt", b"b")])
        self.assert_failed_untouched(self.invoke())

    def test_file_cannot_be_another_members_parent(self):
        self.bundle([("a", b"a"), ("a/b", b"b")])
        self.assert_failed_untouched(self.invoke())

    def test_zip_symlink_is_rejected(self):
        entry = zipfile.ZipInfo("link")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.bundle([(entry, b"../../elsewhere")])
        self.assert_failed_untouched(self.invoke())

    def test_zip_special_file_is_rejected(self):
        entry = zipfile.ZipInfo("pipe")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFIFO | 0o600) << 16
        self.bundle([(entry, b"")])
        self.assert_failed_untouched(self.invoke())

    def test_path_escape_and_ambiguous_paths_are_rejected(self):
        for i, unsafe in enumerate(("../outside.txt", "/absolute.txt", "a/../../outside.txt",
                                   "a/../b", "a//b", "./a", "a/", "C:/a", "a\\b")):
            with self.subTest(path=unsafe):
                self.bundle([(unsafe, b"escape")])
                result = self.invoke(receipt=self.root / ("escape-%s.json" % i))
                self.assert_failed_untouched(result)
                self.assertFalse((self.root / "outside.txt").exists())

    def test_extra_escaping_zip_member_is_rejected_even_with_safe_manifest(self):
        self.bundle([("../outside.txt", b"a")], [])
        self.assert_failed_untouched(self.invoke())

    def test_existing_conflict_stops_all_writes(self):
        self.bundle()
        conflict = self.target / "results/run/metrics.json"
        conflict.parent.mkdir(parents=True)
        conflict.write_bytes(b"must be preserved")
        result = self.invoke()
        self.assertEqual("failed", result["status"])
        self.assertEqual(b"must be preserved", conflict.read_bytes())
        self.assertFalse((self.target / "research").exists())
        self.assertEqual(0, result["counts"]["written_files"])

    def test_existing_same_size_different_hash_conflicts(self):
        self.bundle([("same.txt", b"AAAA")])
        self.target.mkdir()
        (self.target / "same.txt").write_bytes(b"BBBB")
        self.assertEqual("failed", self.invoke()["status"])
        self.assertEqual(b"BBBB", (self.target / "same.txt").read_bytes())

    def test_symlink_parent_cannot_escape_target(self):
        self.bundle([("results/a.txt", b"secret")])
        outside = self.root / "outside"
        outside.mkdir()
        self.target.mkdir()
        (self.target / "results").symlink_to(outside, target_is_directory=True)
        self.assertEqual("failed", self.invoke()["status"])
        self.assertEqual([], list(outside.iterdir()))

    def test_target_root_symlink_is_rejected(self):
        self.bundle()
        outside = self.root / "outside"
        outside.mkdir()
        self.target.symlink_to(outside, target_is_directory=True)
        self.assertEqual("failed", self.invoke()["status"])
        self.assertEqual([], list(outside.iterdir()))

    def test_target_ancestor_symlink_is_rejected(self):
        self.bundle()
        outside = self.root / "outside"
        outside.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(outside, target_is_directory=True)
        self.assertEqual("failed", self.invoke(target=alias / "new-target")["status"])
        self.assertEqual([], list(outside.iterdir()))

    def test_existing_member_symlink_is_never_reused(self):
        self.bundle([("a.txt", b"exact content")])
        outside = self.root / "outside.txt"
        outside.write_bytes(b"exact content")
        self.target.mkdir()
        (self.target / "a.txt").symlink_to(outside)
        self.assertEqual("failed", self.invoke()["status"])
        self.assertTrue((self.target / "a.txt").is_symlink())
        self.assertEqual(b"exact content", outside.read_bytes())

    def test_concurrently_created_destination_is_not_overwritten(self):
        self.bundle([("a.txt", b"archive content")])
        real_link = os.link

        def competing_writer(src, dst, **kwargs):
            if str(src).startswith(".research-restore-"):
                fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
                             dir_fd=kwargs["dst_dir_fd"])
                with os.fdopen(fd, "wb") as stream:
                    stream.write(b"concurrent writer")
            return real_link(src, dst, **kwargs)

        with mock.patch.object(archive_tool, "_require_safe_io"), \
                mock.patch.object(archive_tool.os, "link", side_effect=competing_writer):
            result = self.invoke()
        self.assertEqual("failed", result["status"])
        self.assertEqual(b"concurrent writer", (self.target / "a.txt").read_bytes())
        self.assertEqual([], list(self.target.rglob("*.part")))

    def test_receipt_collision_does_not_overwrite_evidence(self):
        self.bundle()
        self.receipt.write_text("existing evidence")
        with self.assertRaises(archive_tool.ArchiveError):
            self.invoke()
        self.assertEqual("existing evidence", self.receipt.read_text())
        self.assertFalse(self.target.exists())

    def test_receipt_inside_target_is_rejected(self):
        self.bundle()
        self.target.mkdir()
        result = self.invoke(receipt=self.target / "audit.json")
        self.assertEqual("failed", result["status"])
        self.assertEqual(["audit.json"], sorted(p.name for p in self.target.iterdir()))

    def test_duplicate_json_key_is_rejected(self):
        self.bundle()
        self.manifest.write_text('{"schema_version":1,"schema_version":1}')
        self.assert_failed_untouched(self.invoke())

    def test_invalid_boolean_size_is_rejected(self):
        data = self.bundle()
        data["files"][0]["size"] = True
        self.manifest.write_text(json.dumps(data))
        self.assert_failed_untouched(self.invoke())

    def test_cli_success_and_corrupt_input_return_codes(self):
        self.bundle()
        base = [sys.executable, str(SCRIPT), "verify-package", "--package", str(self.package),
                "--manifest", str(self.manifest), "--receipt"]
        success = subprocess.run(base + [str(self.receipt)], capture_output=True, text=True)
        self.assertEqual(0, success.returncode, success.stderr + success.stdout)
        self.assertEqual("verified", json.loads(success.stdout)["status"])
        self.package.write_bytes(b"broken zip")
        failed_receipt = self.root / "failed.json"
        failure = subprocess.run(base + [str(failed_receipt)], capture_output=True, text=True)
        self.assertEqual(1, failure.returncode)
        self.assertEqual("failed", json.loads(failed_receipt.read_text())["status"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
