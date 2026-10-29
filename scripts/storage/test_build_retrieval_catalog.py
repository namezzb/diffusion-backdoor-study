"""Offline catalog regression tests using disposable research-only repositories."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import build_retrieval_catalog as catalog


def sha(data):
    return hashlib.sha256(data).hexdigest()


class RetrievalCatalogTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "storage/server-index").mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value), encoding="utf-8")

    def lines(self, path, rows):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def asset(self, path="results/new.png", data=b"new", sources=()):
        return {"path": path, "bytes": len(data), "sha256": sha(data),
                "sources": list(sources), "status": "indexed_source", "note": "fixture"}

    def public(self, data=b"new", version="2601.12345v2"):
        return {"kind": "public_fixed_version", "url": "https://arxiv.org/pdf/" + version,
                "version": version, "expected_sha256": sha(data), "expected_bytes": len(data)}

    def server(self, local_path=None, data=b"new", digest=True):
        row = {"server": "104", "remote_root": catalog.SERVER_ROOTS["104"],
               "relative_path": "results/run/new.png",
               "remote_path": catalog.SERVER_ROOTS["104"] + "/results/run/new.png",
               "sha256": sha(data) if digest else None, "bytes": len(data),
               "inventory_observed_at": "2026-10-29T00:00:00Z", "local": {"path": None}}
        if local_path:
            row["local"] = {"path": local_path, "sha256": sha(data), "bytes": len(data)}
        self.lines("storage/server-index/104.jsonl", [row])
        return {"kind": "school_ssh", "server": "104", "relative_path": row["relative_path"],
                "remote_path": row["remote_path"], "index": "storage/server-index/104.jsonl",
                "observed_at": row["inventory_observed_at"], "live_download_tested": False}

    def tracked(self, path, data=b"new"):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        subprocess.run(["git", "add", "--", path], cwd=self.root, check=True)

    def frozen(self, path="results/new.png", data=b"old"):
        self.write("storage/payload_packages.json", {"packages": [{"name": "images-001",
                   "manifest": "storage/manifests/frozen.json"}]})
        self.write("storage/manifests/frozen.json", {"files": [{"path": path, "size": len(data), "sha256": sha(data)}]})

    def collect(self):
        return catalog.collect(self.root)

    def test_new_manual_attachment_is_discovered_without_historical_package(self):
        self.lines("storage/asset_registry.jsonl", [self.asset(sources=[self.public()])])
        records, audit = self.collect()
        self.assertEqual(records[0]["path"], "results/new.png")
        self.assertEqual(records[0]["status"], "indexed_source")
        self.assertEqual(audit["input_counts"]["manual_registry_entries"], 1)

    def test_new_paper_is_discovered_without_historical_package(self):
        self.write("papers/catalog.json", {"papers": [{"file": "pdf/new.pdf", "bytes": 3,
                   "sha256": sha(b"new"), "retrieval": self.public()}]})
        records, _ = self.collect()
        self.assertEqual(records[0]["path"], "papers/pdf/new.pdf")
        self.assertEqual(records[0]["status"], "indexed_source")

    def test_saved_local_mapping_needs_no_file_on_new_computer(self):
        self.server("results/not-present/new.png")
        records, audit = self.collect()
        self.assertFalse((self.root / records[0]["path"]).exists())
        self.assertEqual(records[0]["status"], "indexed_source")
        self.assertFalse(audit["network_accessed"])

    def test_missing_sources_writes_unresolved_report_and_fails(self):
        self.lines("storage/asset_registry.jsonl", [self.asset()])
        with self.assertRaises(SystemExit) as error, contextlib.redirect_stdout(io.StringIO()):
            catalog.main(self.root)
        self.assertEqual(error.exception.code, 1)
        audit = json.loads((self.root / "storage/audits/retrieval_coverage.json").read_text())
        self.assertEqual(audit["unresolved"], ["results/new.png"])

    def test_git_only_regular_tracked_matching_file_is_valid(self):
        self.tracked("results/new.png")
        self.lines("storage/asset_registry.jsonl", [self.asset()])
        records, _ = self.collect()
        self.assertEqual(records[0]["sources"], [{"kind": "git", "path": "results/new.png"}])

    def test_untracked_existing_file_is_not_git_source(self):
        (self.root / "new.bin").write_bytes(b"new")
        self.lines("storage/asset_registry.jsonl", [self.asset(path="new.bin")])
        self.assertEqual(self.collect()[0][0]["status"], "local_only_unresolved")

    def test_wrong_git_hash_is_not_source(self):
        self.tracked("results/new.png", b"different")
        self.lines("storage/asset_registry.jsonl", [self.asset()])
        self.assertEqual(self.collect()[0][0]["status"], "local_only_unresolved")

    def test_outside_git_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as outside:
            external = Path(outside) / "external"
            external.write_bytes(b"new")
            (self.root / "link").symlink_to(external)
            subprocess.run(["git", "add", "link"], cwd=self.root, check=True)
            self.lines("storage/asset_registry.jsonl", [self.asset(path="link")])
            with patch.object(Path, "read_bytes", side_effect=AssertionError("should not follow outside symlink")):
                self.assertEqual(self.collect()[0][0]["status"], "local_only_unresolved")

    def test_historical_different_hash_is_preserved_and_manifest_unchanged(self):
        self.frozen(data=b"old")
        manifest = self.root / "storage/manifests/frozen.json"
        before = manifest.read_bytes()
        self.lines("storage/asset_registry.jsonl", [self.asset(sources=[self.public()])])
        records, _ = self.collect()
        self.assertEqual({r["sha256"] for r in records}, {sha(b"old"), sha(b"new")})
        self.assertEqual(next(r for r in records if r["sha256"] == sha(b"old"))["status"], "local_only_unresolved")
        self.assertEqual(manifest.read_bytes(), before)

    def test_same_path_hash_combines_sources_and_origins(self):
        self.frozen(data=b"new")
        remote = self.server("results/new.png")
        self.lines("storage/asset_registry.jsonl", [self.asset(sources=[remote, self.public()])])
        records, _ = self.collect()
        self.assertEqual(len(records), 1)
        self.assertEqual(len(records[0]["record_origins"]), 3)
        self.assertEqual({s["kind"] for s in records[0]["sources"]}, {"school_ssh", "public_fixed_version"})

    def test_missing_or_invalid_hash_rejected(self):
        for digest in [None, "", "a" * 63, "G" * 64]:
            with self.subTest(digest=digest):
                row = self.asset(); row["sha256"] = digest
                self.lines("storage/asset_registry.jsonl", [row])
                with self.assertRaises(catalog.CatalogError):
                    self.collect()

    def test_invalid_sizes_rejected(self):
        for size in [None, -1, 1.5, True, "3"]:
            with self.subTest(size=size):
                row = self.asset(); row["bytes"] = size
                self.lines("storage/asset_registry.jsonl", [row])
                with self.assertRaises(catalog.CatalogError):
                    self.collect()

    def test_unsafe_local_paths_rejected(self):
        for path in ["/private/file", "../file", "results/../../file", "a//b", "a/./b", "a\\b", "a\nb"]:
            with self.subTest(path=path):
                self.lines("storage/asset_registry.jsonl", [self.asset(path=path)])
                with self.assertRaises(catalog.CatalogError):
                    self.collect()

    def test_evidence_symlink_is_not_followed(self):
        (self.root / "storage/asset_registry.jsonl").symlink_to("/not/research")
        with self.assertRaises(catalog.CatalogError):
            catalog.read_rows(self.root, "storage/asset_registry.jsonl")

    def test_school_source_requires_matching_saved_evidence(self):
        source = self.server()
        source["observed_at"] = "2027-01-01T00:00:00Z"
        self.lines("storage/asset_registry.jsonl", [self.asset(sources=[source])])
        with self.assertRaises(catalog.CatalogError):
            self.collect()

    def test_school_source_mismatched_size_or_digest_rejected(self):
        source = self.server(data=b"different")
        self.lines("storage/asset_registry.jsonl", [self.asset(sources=[source])])
        with self.assertRaises(catalog.CatalogError):
            self.collect()

    def test_school_source_outside_personal_root_rejected(self):
        source = self.server(); source["remote_path"] = "/data2/another-user/results/new.png"
        self.lines("storage/asset_registry.jsonl", [self.asset(sources=[source])])
        with self.assertRaises(catalog.CatalogError):
            self.collect()

    def test_unauthorized_server_rejected(self):
        source = self.server(); source["server"] = "206"
        self.lines("storage/asset_registry.jsonl", [self.asset(sources=[source])])
        with self.assertRaises(catalog.CatalogError):
            self.collect()

    def test_null_server_hash_not_promoted_to_source(self):
        self.server("results/new.png", digest=False)
        self.lines("storage/asset_registry.jsonl", [self.asset()])
        records, audit = self.collect()
        self.assertEqual(records[0]["status"], "local_only_unresolved")
        self.assertEqual(audit["server_records_without_hash_not_used_as_sources"], 1)

    def test_conflicting_saved_local_mapping_rejected(self):
        self.server("results/new.png")
        path = self.root / "storage/server-index/104.jsonl"
        row = json.loads(path.read_text()); row["local"]["sha256"] = sha(b"wrong")
        self.lines("storage/server-index/104.jsonl", [row])
        with self.assertRaises(catalog.CatalogError):
            self.collect()

    def test_public_url_rejects_http_credentials_and_signed_query(self):
        for url in ["http://arxiv.org/pdf/2601.12345v2", "https://user:secret@arxiv.org/pdf/2601.12345v2",
                    "https://arxiv.org/pdf/2601.12345v2?token=secret", "https://arxiv.org/pdf/2601.12345v2#secret"]:
            with self.subTest(url=url):
                source = self.public(); source["url"] = url
                self.lines("storage/asset_registry.jsonl", [self.asset(sources=[source])])
                with self.assertRaises(catalog.CatalogError):
                    self.collect()

    def test_public_version_must_be_pinned_in_path(self):
        for version, url in [("latest", "https://example.org/latest/a"), ("v1", "https://example.org/v11/a"),
                             ("v1", "https://example.org/v1/../latest/a"), ("v1", "https://example.org/main/a")]:
            with self.subTest(version=version, url=url):
                source = self.public(); source.update(version=version, url=url)
                self.lines("storage/asset_registry.jsonl", [self.asset(sources=[source])])
                with self.assertRaises(catalog.CatalogError):
                    self.collect()

    def test_public_hash_mismatch_rejected(self):
        source = self.public(); source["expected_sha256"] = sha(b"wrong")
        self.lines("storage/asset_registry.jsonl", [self.asset(sources=[source])])
        with self.assertRaises(catalog.CatalogError):
            self.collect()

    def test_forged_git_source_not_trusted(self):
        self.lines("storage/asset_registry.jsonl", [self.asset(sources=[{"kind": "git", "path": "results/new.png"}])])
        with self.assertRaises(catalog.CatalogError):
            self.collect()

    def test_deterministic_output_and_all_inputs_are_unchanged(self):
        self.lines("storage/asset_registry.jsonl", [self.asset(sources=[self.public()])])
        registry = (self.root / "storage/asset_registry.jsonl").read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            catalog.main(self.root)
            first = (self.root / "storage/retrieval_catalog.jsonl").read_bytes()
            first_audit = (self.root / "storage/audits/retrieval_coverage.json").read_bytes()
            catalog.main(self.root)
        self.assertEqual(first, (self.root / "storage/retrieval_catalog.jsonl").read_bytes())
        self.assertEqual(first_audit, (self.root / "storage/audits/retrieval_coverage.json").read_bytes())
        self.assertEqual(registry, (self.root / "storage/asset_registry.jsonl").read_bytes())
        self.assertFalse(json.loads(first_audit)["network_accessed"])

    def test_input_cannot_claim_fresh_live_verification(self):
        source = self.public(); source["live_download_tested"] = True
        self.lines("storage/asset_registry.jsonl", [self.asset(sources=[source])])
        records, _ = self.collect()
        self.assertFalse(records[0]["sources"][0]["live_download_tested"])

    def test_duplicate_json_key_rejected(self):
        target = self.root / "storage/asset_registry.jsonl"
        target.write_text('{"path":"safe","path":"../unsafe"}\n')
        with self.assertRaises(catalog.CatalogError):
            self.collect()


if __name__ == "__main__":
    unittest.main()
