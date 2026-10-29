#!/usr/bin/env python3
"""Offline end-to-end and boundary tests for catalog-based research restoration."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


SCRIPT = Path(__file__).with_name("restore_from_catalog.py")
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("restore_from_catalog", SCRIPT)
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class CatalogRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="research-catalog-test-")
        self.root = Path(self.temporary.name).resolve()
        self.repo = self.root / "repo"
        self.downloads = self.root / "downloads"
        self.target = self.root / "target"
        self.receipts = self.root / "receipts"
        self.repo.mkdir()
        self.downloads.mkdir()
        (self.repo / "storage/manifests").mkdir(parents=True)
        self.catalog_path = self.repo / "storage/catalog.json"
        self.catalog = {"schema_version": 1, "packages": []}

    def tearDown(self):
        self.temporary.cleanup()

    def add(self, name="images-001", group="images", files=None, status="roundtrip_verified"):
        files = files or {"results/run/a.png": b"image evidence"}
        package = self.downloads / (name + ".zip")
        with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for path, content in files.items():
                output.writestr(path, content)
        manifest = {"schema_version": 1,
                    "package": {"size": package.stat().st_size, "sha256": sha(package.read_bytes())},
                    "files": [{"path": path, "size": len(content), "sha256": sha(content)}
                              for path, content in files.items()]}
        manifest_relative = "storage/manifests/" + name + ".json"
        (self.repo / manifest_relative).write_text(json.dumps(manifest))
        entry = {"name": name, "group": group, "manifest": manifest_relative,
                 "drive": {"id": "test-" + name,
                           "url": "https://drive.google.com/file/d/test-" + name + "/view"},
                 "verification_status": status}
        self.catalog["packages"].append(entry)
        self.save_catalog()
        return entry, manifest, package

    def save_catalog(self):
        self.catalog_path.write_text(json.dumps(self.catalog))

    def load(self):
        return tool.load_catalog("storage/catalog.json", self.repo)

    def restore(self, groups=None, receipts=None):
        return tool.restore_groups(self.load(), self.downloads, self.target,
                                   groups or ["all"], receipts or self.receipts)

    def assert_no_target(self):
        self.assertFalse(self.target.exists())

    def test_list_reports_exact_group_sizes_links_and_verification(self):
        one, m1, _ = self.add()
        two, m2, _ = self.add("images-002", files={"results/run/b.png": b"second"}, status="uploaded")
        self.add("notes-001", "notes", {"research/progress.md": b"paused"})
        result = tool.list_groups(self.load())
        images = next(entry for entry in result["groups"] if entry["group"] == "images")
        self.assertEqual(2, images["package_count"])
        self.assertEqual(m1["package"]["size"] + m2["package"]["size"], images["download_bytes"])
        self.assertFalse(images["all_roundtrip_verified"])
        self.assertEqual(one["drive"]["url"], images["packages"][0]["drive"]["url"])
        self.assertEqual("uploaded", images["packages"][1]["verification_status"])
        self.assert_no_target()
        self.assertFalse(self.receipts.exists())

    def test_selective_restore_then_other_group(self):
        self.add()
        self.add("notes-001", "notes", {"research/progress.md": b"paused"})
        result = self.restore(["images"])
        self.assertEqual("restored", result["status"])
        self.assertEqual(b"image evidence", (self.target / "results/run/a.png").read_bytes())
        self.assertFalse((self.target / "research").exists())
        result2 = self.restore(["notes"], self.root / "receipts-notes")
        self.assertEqual("restored", result2["status"])
        self.assertEqual(b"paused", (self.target / "research/progress.md").read_bytes())

    def test_multiple_groups_and_repeated_selection_do_not_duplicate_work(self):
        self.add()
        self.add("notes-001", "notes", {"research/progress.md": b"paused"})
        result = self.restore(["images", "notes", "images"])
        self.assertEqual("restored", result["status"])
        self.assertEqual(2, result["counts"]["selected_packages"])
        self.assertEqual(2, result["counts"]["written_files"])
        self.assertTrue(result["all_packages_verified_before_restore"])
        self.assertTrue(result["all_destinations_preflighted"])
        self.assertEqual(result, json.loads((self.receipts / "summary.json").read_text()))

    def test_all_restores_every_group_and_subsequent_run_reuses(self):
        self.add()
        self.add("notes-001", "notes", {"research/progress.md": b"paused"})
        first = self.restore()
        self.assertEqual(2, first["counts"]["restored_packages"])
        second = self.restore(receipts=self.root / "receipts-second")
        self.assertEqual(0, second["counts"]["written_files"])
        self.assertEqual(2, second["counts"]["reused_files"])

    def test_all_missing_packages_reported_before_any_restore(self):
        self.add()
        _, _, second = self.add("images-002", files={"results/run/b.png": b"b"})
        _, _, third = self.add("notes-001", "notes", {"research/progress.md": b"paused"})
        second.unlink()
        third.unlink()
        result = self.restore()
        self.assertEqual("blocked", result["status"])
        self.assertEqual(["images-002", "notes-001"], [e["name"] for e in result["missing_packages"]])
        self.assertFalse(result["target_modified"])
        self.assertFalse(self.receipts.exists())
        self.assert_no_target()

    def test_missing_unselected_package_does_not_block_selected_group(self):
        self.add()
        _, _, other = self.add("notes-001", "notes", {"research/progress.md": b"paused"})
        other.unlink()
        self.assertEqual("restored", self.restore(["images"])["status"])

    def test_unverified_package_cannot_be_restored(self):
        self.add()
        self.add("notes-001", "notes", {"research/progress.md": b"paused"}, "uploaded")
        result = self.restore()
        self.assertEqual("blocked", result["status"])
        self.assertEqual("uploaded", result["unverified_packages"][0]["verification_status"])
        self.assert_no_target()

    def test_missing_verification_status_is_unknown_and_blocks(self):
        self.add()
        del self.catalog["packages"][0]["verification_status"]
        self.save_catalog()
        result = self.restore()
        self.assertEqual("unknown", result["unverified_packages"][0]["verification_status"])
        self.assert_no_target()

    def test_corrupt_second_package_prevents_first_package_restoration(self):
        self.add()
        _, _, second = self.add("notes-001", "notes", {"research/progress.md": b"paused"})
        second.write_bytes(b"corrupt")
        result = self.restore()
        self.assertEqual("failed", result["status"])
        self.assertEqual(1, result["counts"]["verified_packages"])
        self.assertEqual(0, result["counts"]["restored_packages"])
        self.assertTrue((self.receipts / "summary.json").is_file())
        self.assert_no_target()

    def test_conflict_in_later_package_prevents_earlier_writes(self):
        self.add()
        self.add("notes-001", "notes", {"research/progress.md": b"old progress"})
        conflict = self.target / "research/progress.md"
        conflict.parent.mkdir(parents=True)
        conflict.write_bytes(b"new progress must stay")
        result = self.restore()
        self.assertEqual("failed", result["status"])
        self.assertEqual(2, result["counts"]["verified_packages"])
        self.assertEqual(0, result["counts"]["written_files"])
        self.assertEqual(b"new progress must stay", conflict.read_bytes())
        self.assertFalse((self.target / "results").exists())

    def test_cross_package_version_conflict_is_rejected(self):
        self.add("old-001", "old", {"research/progress.md": b"old"})
        self.add("new-001", "new", {"research/progress.md": b"new"})
        with self.assertRaisesRegex(tool.core.ArchiveError, "conflicting versions"):
            self.restore()
        self.assert_no_target()

    def test_identical_cross_package_member_is_safely_reused(self):
        self.add("old-001", "old", {"research/progress.md": b"same"})
        self.add("new-001", "new", {"research/progress.md": b"same"})
        result = self.restore()
        self.assertEqual("restored", result["status"])
        self.assertEqual(1, result["unique_member_count"])
        self.assertEqual(1, result["counts"]["written_files"])
        self.assertEqual(1, result["counts"]["reused_files"])

    def test_catalog_escape_relative_and_absolute_are_rejected(self):
        self.add()
        outside = self.root / "external-catalog.json"
        outside.write_text(json.dumps(self.catalog))
        for path in ("../external-catalog.json", str(outside)):
            with self.subTest(path=path), self.assertRaises(tool.core.ArchiveError):
                tool.load_catalog(path, self.repo)

    def test_manifest_escape_is_rejected(self):
        entry, manifest, _ = self.add()
        outside = self.root / "outside-manifest.json"
        outside.write_text(json.dumps(manifest))
        for path in ("../outside-manifest.json", str(outside)):
            with self.subTest(path=path):
                entry["manifest"] = path
                self.save_catalog()
                with self.assertRaises(tool.core.ArchiveError):
                    self.load()

    def test_catalog_symlink_is_rejected(self):
        self.add()
        original = self.repo / "storage/original.json"
        self.catalog_path.rename(original)
        self.catalog_path.symlink_to(original)
        with self.assertRaises(tool.core.ArchiveError):
            self.load()

    def test_manifest_symlink_is_rejected(self):
        entry, _, _ = self.add()
        manifest = self.repo / entry["manifest"]
        original = manifest.with_suffix(".original")
        manifest.rename(original)
        manifest.symlink_to(original)
        with self.assertRaises(tool.core.ArchiveError):
            self.load()

    def test_manifest_symlink_parent_is_rejected(self):
        self.add()
        original = self.repo / "original-manifests"
        (self.repo / "storage/manifests").rename(original)
        (self.repo / "storage/manifests").symlink_to(original, target_is_directory=True)
        with self.assertRaises(OSError):
            self.load()

    def test_download_symlink_is_rejected_even_if_correct_hash(self):
        _, _, package = self.add()
        original = self.root / "actual.zip"
        package.rename(original)
        package.symlink_to(original)
        result = self.restore()
        self.assertEqual("blocked", result["status"])
        self.assertEqual(1, len(result["unsafe_downloads"]))
        self.assert_no_target()

    def test_package_name_cannot_escape_downloads(self):
        self.add()
        self.catalog["packages"][0]["name"] = "../outside"
        self.save_catalog()
        with self.assertRaises(tool.core.ArchiveError):
            self.load()

    def test_unknown_groups_and_all_combination_fail(self):
        self.add()
        for groups in (["unknown"], ["all", "images"], []):
            with self.subTest(groups=groups), self.assertRaises(tool.core.ArchiveError):
                tool.select_packages(self.load(), groups)
        self.assert_no_target()

    def test_existing_receipt_directory_is_not_reused(self):
        self.add()
        self.receipts.mkdir()
        (self.receipts / "prior.json").write_text("preserved")
        with self.assertRaises(FileExistsError):
            self.restore()
        self.assertEqual("preserved", (self.receipts / "prior.json").read_text())
        self.assert_no_target()

    def test_cli_listing_needs_no_download_or_target_arguments(self):
        self.add()
        completed = subprocess.run([sys.executable, str(SCRIPT), "--repo-root", str(self.repo),
                                    "--catalog", "storage/catalog.json", "--list"],
                                   capture_output=True, text=True)
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        self.assertEqual("listed", json.loads(completed.stdout)["status"])
        self.assert_no_target()

    def test_cli_full_restore(self):
        self.add()
        completed = subprocess.run([sys.executable, str(SCRIPT), "--repo-root", str(self.repo),
                                    "--catalog", "storage/catalog.json", "--downloads", str(self.downloads),
                                    "--target", str(self.target), "--group", "all", "--receipts", str(self.receipts)],
                                   capture_output=True, text=True)
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        self.assertEqual("restored", json.loads(completed.stdout)["status"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
