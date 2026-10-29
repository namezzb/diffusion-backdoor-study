#!/usr/bin/env python3
"""Offline temporary-Git regressions for inventory and closeout enforcement."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location("maintain_index", Path(__file__).with_name("maintain_index.py"))
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="research-index-test-")
        self.root = Path(self.temp.name).resolve()
        self.git("init", "-q")
        self.git("config", "user.name", "Offline Test")
        self.git("config", "user.email", "offline@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.policy = {
            "schema_version": 1,
            "inventory": "storage/repository_index.jsonl",
            "receipt": "storage/maintenance/latest.json",
            "routes": [
                {"prefix": "research/", "index": "research/README.md", "related_records": ["research/project_state.json"]},
                {"prefix": "storage/", "index": "storage/README.md"},
                {"prefix": "archive/", "index": "archive/README.md"},
                {"prefix": "papers/", "index": "papers/README.md"},
                {"prefix": "", "index": "README.md"}],
            "required_entries": ["README.md", "research/project_state.json"],
            "active_indexes": ["README.md", "research/README.md", "storage/README.md", "papers/README.md"],
        }
        self.write("README.md", "# Research\n\n[Research](research/README.md)\n[Storage](storage/README.md)\n")
        self.write("research/README.md", "# Research\n\n[State](project_state.json)\n")
        self.write("research/project_state.json", '{"status":"paused"}\n')
        self.write("storage/README.md", "# Storage\n")
        self.write("papers/README.md", "# Papers\n")
        self.write("archive/README.md", "# Frozen evidence\n")
        self.write("archive/frozen.dat", b"original\r\nevidence\x00\n")
        self.write_policy()
        self.git("add", ".")
        self.git("commit", "-qm", "baseline research")
        self.closeout()
        self.assertEqual("passed", self.check(staged=True)["status"])
        self.git("commit", "-qm", "initial inventory")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.PIPE).decode().strip()

    def write(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data.encode() if isinstance(data, str) else data)

    def write_policy(self):
        self.write(module.POLICY, json.dumps(self.policy, indent=2) + "\n")

    def view(self, staged=False):
        return module.git_view(self.root) if staged else module.work_view(self.root)

    def closeout(self, stage=True):
        view = self.view()
        policy = module.load_policy(view)
        before = module.git_view(self.root, "HEAD")
        changes = module.changed_entries(before, view, (policy["inventory"], policy["receipt"]))
        changed_paths = {row["path"] for row in changes}
        receipt = {"base_commit": self.git("rev-parse", "HEAD"), "summary": "Reviewed this bounded fixture change.",
                   "reviewed_changes": changes,
                   "index_decisions": [{"path": path, "action": "updated" if path in changed_paths else "unchanged",
                                        "reason": "Entry reviewed; exact fixture state is intentional."}
                                       for path in sorted(module.review_targets(changes, policy))]}
        self.write(policy["receipt"], json.dumps(receipt, indent=2) + "\n")
        module.refresh(self.root, self.view(), policy)
        if stage:
            self.git("add", "-A")
        return receipt

    def check(self, staged=False, scan_local=True):
        view = self.view(staged)
        return module.check(self.root, view, module.load_policy(view), scan_local, staged=staged)

    def assert_failed(self, text, staged=False, scan_local=True):
        result = self.check(staged, scan_local)
        self.assertEqual("failed", result["status"])
        self.assertIn(text, "\n".join(result["errors"]))
        return result

    def mutate_receipt(self, change):
        path = self.policy["receipt"]
        receipt = json.loads((self.root / path).read_text())
        change(receipt)
        self.write(path, json.dumps(receipt) + "\n")
        module.refresh(self.root, self.view(), self.policy)
        self.git("add", "-A")

    def test_clean_committed_snapshot_validates_without_new_receipt(self):
        for staged in (False, True):
            result = self.check(staged)
            self.assertEqual("passed", result["status"])
            self.assertEqual("committed_snapshot", result["receipt_mode"])

    def test_addition_is_detected_then_exact_receipt_passes(self):
        self.write("research/new.md", "new finding\n")
        self.assert_failed("inventory stale")
        receipt = self.closeout()
        self.assertEqual(["research/new.md"], [row["path"] for row in receipt["reviewed_changes"]])
        self.assertEqual("passed", self.check(True)["status"])

    def test_content_change_invalidates_inventory_and_receipt(self):
        self.write("research/project_state.json", '{"status":"paused","next":"review"}\n')
        self.assert_failed("inventory stale")
        self.closeout()
        self.assertEqual("passed", self.check(True)["status"])

    def test_deletion_and_rename_record_exact_removed_and_added_paths(self):
        self.write("research/one.md", "same bytes\n")
        self.closeout()
        self.git("commit", "-qm", "one")
        (self.root / "research/one.md").rename(self.root / "research/two.md")
        self.assert_failed("inventory stale")
        receipt = self.closeout()
        self.assertEqual([
            {"path": "research/one.md", "kind": "deleted", "sha256": None},
            {"path": "research/two.md", "kind": "file", "sha256": module.digest(b"same bytes\n")},
        ], receipt["reviewed_changes"])
        self.assertEqual("passed", self.check(True)["status"])
        (self.root / "research/two.md").unlink()
        self.assert_failed("inventory stale")

    def test_missing_receipt_fails_even_with_fresh_inventory(self):
        (self.root / self.policy["receipt"]).unlink()
        module.refresh(self.root, self.view(), self.policy)
        self.assert_failed("missing regular JSON file")

    def test_omitted_changed_file_in_receipt_is_rejected(self):
        self.write("research/new.md", "new\n")
        self.closeout()
        self.mutate_receipt(lambda receipt: receipt.update(reviewed_changes=[]))
        self.assert_failed("receipt changes do not match", True)

    def test_stale_receipt_sha_fails_after_inventory_refresh(self):
        self.write("research/new.md", "version one\n")
        self.closeout()
        self.write("research/new.md", "version two\n")
        module.refresh(self.root, self.view(), self.policy)
        self.git("add", "-A")
        self.assert_failed("stale_sha_or_kind", True)

    def test_stale_base_commit_rejected(self):
        self.write("research/new.md", "new\n")
        self.closeout()
        old_base = self.git("rev-parse", "HEAD^")
        self.mutate_receipt(lambda receipt: receipt.update(base_commit=old_base))
        self.assert_failed("base_commit is stale", True)

    def test_updated_index_claim_requires_actual_change(self):
        self.write("research/new.md", "new\n")
        self.closeout()
        self.mutate_receipt(lambda receipt: receipt["index_decisions"][0].update(action="updated"))
        self.assert_failed("disagrees with actual change", True)

    def test_related_state_record_must_have_review_decision(self):
        self.write("research/new.md", "new\n")
        self.closeout()
        self.mutate_receipt(lambda receipt: receipt.update(index_decisions=[d for d in receipt["index_decisions"]
                                                                          if d["path"] != "research/project_state.json"]))
        self.assert_failed("missing index decisions: research/project_state.json", True)

    def test_unchanged_index_requires_explicit_nonempty_reason(self):
        self.write("research/new.md", "new\n")
        self.closeout()
        self.mutate_receipt(lambda receipt: receipt["index_decisions"][0].update(reason="  "))
        self.assert_failed("needs a reason", True)

    def test_unstaged_doc_cannot_satisfy_staged_receipt(self):
        self.write("research/new.md", "new\n")
        self.write("research/README.md", "# Research\n\n[State](project_state.json)\n[New](new.md)\n")
        self.closeout(stage=False)
        self.git("add", "research/new.md", self.policy["receipt"], self.policy["inventory"])
        self.assertEqual("passed", self.check()["status"])
        result = self.assert_failed("receipt changes do not match", True)
        self.assertIn("research/README.md", "\n".join(result["errors"]))

    def test_unstaged_policy_exception_cannot_fix_staged_link(self):
        self.write("research/README.md", "# Research\n\n[Missing](missing.txt)\n")
        self.closeout()
        self.policy["link_exceptions"] = [{"source": "research/README.md", "target": "missing.txt", "reason": "Specific archived absent fixture."}]
        self.write_policy()
        self.assert_failed("missing local link", True)

    def test_policy_has_no_catchall_for_unknown_directory(self):
        self.write("unplanned/file.json", "{}\n")
        with self.assertRaisesRegex(module.IndexError_, "unrouted file"):
            module.inventory_rows(self.view(), self.policy)

    def test_safe_symlink_indexes_link_text_without_reading_target_as_alias(self):
        (self.root / "research/alias").symlink_to("../archive/frozen.dat")
        self.closeout()
        row = next(row for row in module.inventory_rows(self.view(), self.policy) if row["path"] == "research/alias")
        self.assertEqual("symlink", row["kind"])
        self.assertEqual("archive/frozen.dat", row["relative_target"])
        self.assertEqual(module.digest(b"../archive/frozen.dat"), row["sha256"])
        self.assertEqual("passed", self.check(True)["status"])

    def test_outside_absolute_and_traversing_symlinks_rejected(self):
        link = self.root / "research/alias"
        for target in ("/etc/passwd", "../../company-file"):
            with self.subTest(target=target):
                link.symlink_to(target)
                with self.assertRaises(module.IndexError_):
                    module.inventory_rows(self.view(), self.policy)
                link.unlink()

    def test_symlink_parent_is_not_followed(self):
        self.write("research/folder/inside.md", "fixture\n")
        self.closeout()
        self.git("commit", "-qm", "nested")
        outside = self.root / "other"
        outside.mkdir()
        (outside / "inside.md").write_text("do not read\n")
        (self.root / "research/folder/inside.md").unlink()
        (self.root / "research/folder").rmdir()
        (self.root / "research/folder").symlink_to(outside)
        with self.assertRaisesRegex(module.IndexError_, "parent is not a real directory"):
            self.view()

    def test_symlink_cycle_and_missing_target_rejected(self):
        first = self.root / "research/first"
        second = self.root / "research/second"
        first.symlink_to("second")
        second.symlink_to("first")
        with self.assertRaisesRegex(module.IndexError_, "symlink cycle"):
            module.inventory_rows(self.view(), self.policy)
        second.unlink()
        with self.assertRaisesRegex(module.IndexError_, "dangling tracked symlink"):
            module.inventory_rows(self.view(), self.policy)

    def test_missing_active_link_requires_exact_documented_exception(self):
        self.write("research/README.md", "# Research\n\n[Old](missing.txt)\n")
        self.closeout()
        self.assert_failed("missing local link", True)
        self.policy["link_exceptions"] = [{"source": "research/README.md", "target": "missing.txt", "reason": "Exact historical missing attachment; no substitute claimed."}]
        self.write_policy()
        self.closeout()
        result = self.check(True)
        self.assertEqual("passed", result["status"])
        self.assertEqual(1, result["link_exceptions_used"])

    def test_known_retrievable_attachment_is_valid_link_without_local_file(self):
        self.write("papers/README.md", "# Papers\n\n[Original](pdf/one.pdf)\n")
        row = {"path": "papers/pdf/one.pdf", "bytes": 123, "sha256": "3" * 64,
               "status": "indexed_source", "sources": [{"kind": "public_fixed_version",
                                                        "url": "https://example.invalid/paper/v1.pdf", "version": "v1"}]}
        self.write("storage/retrieval_catalog.jsonl", json.dumps(row) + "\n")
        self.write("storage/asset_registry.jsonl", json.dumps(row) + "\n")
        self.closeout()
        self.assertEqual("passed", self.check(True)["status"])

    def add_git_catalog_fixture(self):
        self.write("research/source.txt", "recorded source\n")
        row = {"path": "research/source.txt", "bytes": len(b"recorded source\n"), "sha256": module.digest(b"recorded source\n"),
               "status": "indexed_source", "sources": [{"kind": "git", "path": "research/source.txt"}]}
        self.write("storage/retrieval_catalog.jsonl", json.dumps(row) + "\n")
        self.closeout()
        self.git("commit", "-qm", "record source")
        return row

    def test_changed_git_source_cannot_retain_historical_hash_in_catalog(self):
        self.add_git_catalog_fixture()
        self.write("research/source.txt", "new bytes with old catalog\n")
        self.closeout()
        self.assert_failed("retrieval Git source is stale", True)

    def test_catalog_git_source_uses_staged_blob_instead_of_unstaged_fix(self):
        self.add_git_catalog_fixture()
        self.write("research/source.txt", "staged incorrect version\n")
        self.closeout()
        self.write("research/source.txt", "recorded source\n")
        self.assert_failed("retrieval Git source is stale", True)
        view = self.view()
        errors, _ = module.catalog_consistency(view, self.policy)
        self.assertEqual([], errors)

    def test_new_registry_identity_requires_regenerated_catalog(self):
        old = self.add_git_catalog_fixture()
        new = {"path": "research/future.png", "bytes": 123, "sha256": "1" * 64, "sources": []}
        self.write("storage/asset_registry.jsonl", json.dumps(new) + "\n")
        self.closeout()
        self.assert_failed("registered artifact missing from retrieval catalog", True)
        self.write("storage/retrieval_catalog.jsonl", json.dumps(old) + "\n" + json.dumps({**new, "status": "local_only_unresolved"}) + "\n")
        self.closeout()
        self.assert_failed("unresolved retrieval artifact", True)

    def test_new_paper_identity_requires_regenerated_catalog(self):
        self.add_git_catalog_fixture()
        self.write("papers/catalog.json", json.dumps({"papers": [{"file": "pdf/new.pdf", "bytes": 456, "sha256": "2" * 64}]}) + "\n")
        self.closeout()
        self.assert_failed("registered artifact missing from retrieval catalog: papers/pdf/new.pdf", True)

    def test_indexed_source_must_not_have_empty_sources(self):
        self.write("storage/retrieval_catalog.jsonl", json.dumps({"path": "papers/pdf/empty.pdf", "bytes": 0,
                                                               "sha256": module.digest(b""), "status": "indexed_source", "sources": []}) + "\n")
        self.closeout()
        self.assert_failed("indexed_source has no sources", True)

    def public_fixture(self):
        row = {"path": "papers/pdf/one.pdf", "bytes": 123, "sha256": "3" * 64,
               "status": "indexed_source", "sources": [{"kind": "public_fixed_version",
                                                        "url": "https://example.invalid/paper/v1.pdf", "version": "v1"}]}
        self.write("storage/retrieval_catalog.jsonl", json.dumps(row) + "\n")
        return row

    def test_registry_source_url_change_requires_catalog_regeneration(self):
        row = self.public_fixture()
        self.write("storage/asset_registry.jsonl", json.dumps(row) + "\n")
        self.closeout()
        self.assertEqual("passed", self.check(True)["status"])
        self.git("commit", "-qm", "public registry")
        row["sources"][0]["url"] = "https://changed.example.invalid/paper/v1.pdf"
        self.write("storage/asset_registry.jsonl", json.dumps(row) + "\n")
        self.closeout()
        self.assert_failed("registered source missing or changed", True)

    def test_paper_retrieval_version_change_requires_catalog_regeneration(self):
        row = self.public_fixture()
        paper = {"file": "pdf/one.pdf", "sha256": row["sha256"], "bytes": row["bytes"], "retrieval": row["sources"][0]}
        self.write("papers/catalog.json", json.dumps({"papers": [paper]}) + "\n")
        self.closeout()
        self.assertEqual("passed", self.check(True)["status"])
        self.git("commit", "-qm", "paper registry")
        paper["retrieval"].update(version="v2", url="https://example.invalid/paper/v2.pdf")
        self.write("papers/catalog.json", json.dumps({"papers": [paper]}) + "\n")
        self.closeout()
        self.assert_failed("registered source missing or changed", True)

    def test_registry_removing_all_public_sources_rejects_stale_catalog(self):
        row = self.public_fixture()
        self.write("storage/asset_registry.jsonl", json.dumps(row) + "\n")
        self.closeout()
        self.assertEqual("passed", self.check(True)["status"])
        self.git("commit", "-qm", "declared public source")
        self.write("storage/asset_registry.jsonl", json.dumps({**row, "sources": []}) + "\n")
        self.closeout()
        self.assert_failed("public sources removed from current declarations", True)

    def test_registry_removing_one_of_two_public_sources_rejects_only_stale_source(self):
        row = self.public_fixture()
        row["sources"].append({**row["sources"][0], "url": "https://other.example.invalid/paper/v1.pdf"})
        self.write("storage/retrieval_catalog.jsonl", json.dumps(row) + "\n")
        self.write("storage/asset_registry.jsonl", json.dumps(row) + "\n")
        self.closeout()
        self.assertEqual("passed", self.check(True)["status"])
        self.git("commit", "-qm", "two public sources")
        self.write("storage/asset_registry.jsonl", json.dumps({**row, "sources": row["sources"][1:]}) + "\n")
        self.closeout()
        result = self.assert_failed("public sources removed from current declarations", True)
        self.assertIn("(1 sources)", "\n".join(result["errors"]))

    def test_paper_removing_retrieval_rejects_stale_public_source(self):
        row = self.public_fixture()
        paper = {"file": "pdf/one.pdf", "sha256": row["sha256"], "bytes": row["bytes"], "retrieval": row["sources"][0]}
        self.write("papers/catalog.json", json.dumps({"papers": [paper]}) + "\n")
        self.closeout()
        self.assertEqual("passed", self.check(True)["status"])
        self.git("commit", "-qm", "paper retrieval")
        del paper["retrieval"]
        self.write("papers/catalog.json", json.dumps({"papers": [paper]}) + "\n")
        self.closeout()
        self.assert_failed("public sources removed from current declarations", True)

    def test_school_source_checks_all_signature_fields_and_staged_evidence(self):
        source = {"kind": "school_ssh", "server": "104", "relative_path": "results/run/image.png",
                  "remote_path": module.SERVER_ROOTS["104"] + "/results/run/image.png",
                  "index": "storage/server-index/104.jsonl", "observed_at": "2026-10-29T01:00:00Z"}
        row = {"path": "research/image.png", "sha256": "4" * 64, "bytes": 123, "status": "indexed_source", "sources": [source]}
        evidence = {"server": "104", "relative_path": source["relative_path"], "remote_path": source["remote_path"],
                    "sha256": row["sha256"], "bytes": row["bytes"], "inventory_observed_at": source["observed_at"]}
        self.write(source["index"], json.dumps(evidence) + "\n")
        self.write("storage/retrieval_catalog.jsonl", json.dumps(row) + "\n")
        self.closeout()
        self.assertEqual("passed", self.check(True)["status"])
        self.git("commit", "-qm", "school source")
        for field, changed in (("server", "103"), ("relative_path", "results/other.png"), ("remote_path", "/data2/zhangzibo/arxiv-tssa/results/other.png"),
                               ("sha256", "5" * 64), ("bytes", 124), ("inventory_observed_at", "2026-10-30T01:00:00Z")):
            with self.subTest(field=field):
                self.write(source["index"], json.dumps({**evidence, field: changed}) + "\n")
                self.closeout()
                self.write(source["index"], json.dumps(evidence) + "\n")
                self.assert_failed("school source has no matching saved index evidence", True)
                self.assertEqual([], module.catalog_consistency(self.view(), self.policy)[0])
        (self.root / source["index"]).unlink()
        self.closeout()
        self.assert_failed("school source has no matching saved index evidence", True)

    def test_unknown_or_invalid_public_sources_never_count_as_downloadable(self):
        row = self.public_fixture()
        valid = row["sources"][0]
        for invalid in ({"kind": "unknown"}, {**valid, "url": "http://example.invalid/paper/v1.pdf"},
                        {**valid, "version": "latest"}, {**valid, "expected_sha256": "0" * 64}):
            with self.subTest(source=invalid):
                self.write("storage/retrieval_catalog.jsonl", json.dumps({**row, "sources": [invalid]}) + "\n")
                self.closeout()
                self.assert_failed("invalid retrieval source", True)

    def test_ignored_new_attachment_is_detected_without_reading_contents(self):
        self.write(".gitignore", "*.png\n")
        self.closeout()
        self.git("commit", "-qm", "ignore originals")
        self.write("research/new.png", b"private ignored payload")
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("must not read ignored file")):
            self.assert_failed("ignored file has no index", True)
        self.assertEqual("passed", self.check(True, scan_local=False)["status"])

    def test_new_untracked_nonignored_file_cannot_be_silently_left_out_of_commit(self):
        self.write("research/forgotten.md", "must register this finding\n")
        result = self.assert_failed("new nonignored file is absent from staged tree", True)
        self.assertEqual(1, result["untracked_not_staged"])
        self.assertEqual("passed", self.check(True, scan_local=False)["status"])

    def test_ignored_attachment_registered_by_exact_saved_index_passes(self):
        self.write(".gitignore", "*.png\n")
        self.write("research/new.png", b"fixture payload")
        self.write("storage/server-index/104.jsonl", json.dumps({"local": {"path": "research/new.png"}}) + "\n")
        self.closeout()
        result = self.check(True)
        self.assertEqual("passed", result["status"])
        self.assertEqual(1, result["ignored_indexed"])

    def test_ignored_dependency_explicit_pattern_excludes_only_named_scope(self):
        self.write(".gitignore", "cache/\n*.png\n")
        self.write("cache/module.bin", b"fixture cache")
        self.policy["local_exclusions"] = [{"pattern": "cache/*", "reason": "Regenerable local cache only."}]
        self.write_policy()
        self.closeout()
        result = self.check(True)
        self.assertEqual("passed", result["status"])
        self.assertEqual(1, result["ignored_excluded"])
        self.write("research/missing.png", b"uncatalogued research")
        self.assert_failed("ignored file has no index", True)

    def test_refresh_is_deterministic_only_inventory_changes_and_frozen_evidence_intact(self):
        before = {p: blob["data"] for p, blob in self.view().items()}
        receipt = (self.root / self.policy["receipt"]).read_bytes()
        first = module.refresh(self.root, self.view(), self.policy)
        saved = (self.root / self.policy["inventory"]).read_bytes()
        second = module.refresh(self.root, self.view(), self.policy)
        self.assertEqual(first, second)
        self.assertEqual(saved, (self.root / self.policy["inventory"]).read_bytes())
        self.assertEqual(receipt, (self.root / self.policy["receipt"]).read_bytes())
        self.assertEqual(before, {p: blob["data"] for p, blob in self.view().items()})
        self.assertEqual(b"original\r\nevidence\x00\n", (self.root / "archive/frozen.dat").read_bytes())
        selfrow = next(row for row in module.jsonl(self.view(), self.policy["inventory"]) if row["path"] == self.policy["inventory"])
        self.assertTrue(selfrow["self_generated"])
        self.assertIsNone(selfrow["sha256"])

    def test_impact_routes_without_writes_and_lists_associated_state(self):
        self.write("research/new.md", "new\n")
        before = self.git("status", "--porcelain=v1")
        result = module.impact(self.root, self.view(), self.policy)
        self.assertEqual(["research/README.md", "research/project_state.json"], result["review_indexes"])
        self.assertEqual("research/README.md", result["changes"][0]["owner_index"])
        self.assertEqual(before, self.git("status", "--porcelain=v1"))
        self.assertFalse(result["network_accessed"])

    def test_cli_check_exit_status_and_staged_refresh_rejected(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, module.main(["check", "--staged"], repo=self.root))
        self.assertEqual("staged", json.loads(output.getvalue())["view"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(1, module.main(["refresh", "--staged"], repo=self.root))


if __name__ == "__main__":
    unittest.main()
