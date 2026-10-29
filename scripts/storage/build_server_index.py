#!/usr/bin/env python3
"""Build portable server indices from saved local evidence; never connects remotely."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
ORG = "results/organization-2026-10-29"
EXP = "results/tssa-opt-exploration-2026-10-28"
DIAG = "results/tssa-target-semantic-diagnostic-2026-10-28"
MVP_ID = "mvp-2026-10-28-single-v1"
EXP_ID = "tssa-opt-exploration-2026-10-28-v1"
DIAG_ID = "tssa-target-semantic-diagnostic-2026-10-28-v1"


def read(path):
    return json.loads((ROOT / path).read_text())


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def relative(value):
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("unsafe evidence path")
    return path.as_posix()


def local_status(path, expected_hash, expected_bytes):
    """Only read a mapped repository file, including a checked internal alias."""
    if path is None:
        return {"status": "not_mapped_locally", "path": None}
    p = ROOT / relative(path)
    resolved = p.resolve()
    if not resolved.is_relative_to(ROOT):
        raise ValueError("local mapping escapes repository")
    if not p.is_file():
        return {"status": "mapped_file_missing", "path": path}
    actual = digest(p)
    matched = actual == expected_hash and p.stat().st_size == expected_bytes
    return {"status": "verified_local_against_saved_remote_hash" if matched else "local_mismatch",
            "path": path, "sha256": actual, "bytes": p.stat().st_size,
            "internal_symlink": p.is_symlink()}


def file_row(server, root, item, observed_at, hash_evidence=None, local=None):
    path = relative(item["path"])
    sha = item.get("sha256")
    return {"server": server, "ssh_alias": "school" + server,
            "remote_root": root, "relative_path": path, "remote_path": root + "/" + path,
            "bytes": item["bytes"], "mtime_ns": item.get("mtime_ns"),
            "sha256": sha, "sha256_evidence": hash_evidence if sha else None,
            "inventory_observed_at": observed_at, "live_state_verified": False,
            "run_id": next((r for r in (MVP_ID, EXP_ID, DIAG_ID) if path.startswith("results/" + r + "/")), None),
            "local": local_status(local, sha, item["bytes"]) if local else {"status": "not_mapped_locally", "path": None}}


def write_rows(path, rows):
    (ROOT / path).parent.mkdir(parents=True, exist_ok=True)
    (ROOT / path).write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in sorted(rows, key=lambda x: x["relative_path"])))


def main():
    now = datetime.now(timezone.utc).isoformat()
    m104_path = ORG + "/server104_hash_manifest.json"
    m104 = read(m104_path)
    retrieval = read(ORG + "/server104_retrieval.json")
    rows104 = []
    for item in m104["files"]:
        path = item["path"]
        local = "results/server-archive-2026-10-29/server104/" + path if path in retrieval["files"] else None
        row = file_row("104", m104["root"], item, m104["at"], m104_path, local)
        row["same_content_remote_path"] = retrieval["remote_aliases"].get(path)
        row["category"] = "research_or_model_config"
        rows104.append(row)
    for item in m104["public_model_payloads_not_copied"]:
        row = file_row("104", m104["root"], item, m104["at"])
        row.update(category="public_model_payload", source_manifest="research/tssa_mvp_assets_2026-10-26.json")
        rows104.append(row)

    m103_path = ORG + "/server103_inventory.json"
    m103 = read(m103_path)["inventory"]
    diag_report = DIAG + "/observation_20261029T015422409669Z/report.json"
    exp_report = EXP + "/observation_103_20261028T111524087743Z-7268ad87/report.json"
    png_report = EXP + "/final_PNG_hash_acceptance_816_20261028T1115Z.json"
    mappings = {}
    for path, info in read(diag_report)["returned_files"].items():
        mappings["results/" + DIAG_ID + "/" + path] = (info["sha256"], DIAG + "/observation_20261029T015422409669Z/artifacts/" + path, diag_report)
    for path, info in read(exp_report)["result"]["files"].items():
        if path.startswith("run/"):
            mappings["results/" + EXP_ID + "/" + path[4:]] = (info["sha256"], EXP + "/observation_103_20261028T111524087743Z-7268ad87/artifacts/" + path, exp_report)
    for info in read(png_report)["remote"]["rows"]:
        operation = EXP + "/observation_103_20261028T111524087743Z-7268ad87/artifacts/run/operations/" + info["task_id"] + ".json"
        image_path = relative(read(operation)["record"]["image_path"])
        mappings["results/" + EXP_ID + "/" + image_path] = (info["image_sha256"], EXP + "/final_images_816_20261028/" + image_path, png_report)
    rows103 = []
    for item in m103["files"]:
        item = dict(item)
        sha, local, evidence = mappings.get(item["path"], (None, None, None))
        if sha:
            item["sha256"] = sha
        row = file_row("103", m103["root"], item, m103["at"], evidence, local)
        row["category"] = "research"
        rows103.append(row)

    write_rows("storage/server-index/104.jsonl", rows104)
    write_rows("storage/server-index/103.jsonl", rows103)
    # Model hashes are historical transfer evidence, not a new inventory.
    models_path = EXP + "/node103_models_completed_20261028T0849Z.json"
    models = read(models_path)
    model_rows = [file_row("103", m103["root"], {"path": p, "bytes": v["size"], "sha256": v["sha256"]}, v["at"], models_path) for p, v in models["files"].items()]
    write_rows("storage/server-index/103-models-historical.jsonl", model_rows)

    nodes = []
    for server, rows, source in [("104", rows104, m104_path), ("103", rows103, m103_path)]:
        nodes.append({"server": server, "ssh_alias": "school" + server,
                      "root": rows[0]["remote_root"], "index": "storage/server-index/" + server + ".jsonl",
                      "inventory_source": source, "inventory_sha256": digest(ROOT / source),
                      "inventory_observed_at": rows[0]["inventory_observed_at"],
                      "rows": len(rows), "bytes": sum(x["bytes"] for x in rows),
                      "local_status_counts": dict(Counter(x["local"]["status"] for x in rows)),
                      "live_state_verified": False})
    catalog = {"schema_version": 1, "generated_at": now, "mode": "local_organization_only",
               "network_accessed_by_builder": False, "remote_files_modified": False,
               "note": "Saved observations only. Local hashes are checked now; remote existence and contents are not refreshed.",
               "servers": nodes,
               "runs": [
                   {"run_id": MVP_ID, "server": "104", "remote_path": m104["root"] + "/results/" + MVP_ID,
                    "local_entry": "results/tssa-mvp-2026-10-26/README.md", "images": 1520, "updates": 144,
                    "local_coverage": "terminal summaries, metrics, coefficient trace, panels and some cache; original images and selected model payloads remain remote"},
                   {"run_id": EXP_ID, "server": "103", "remote_path": m103["root"] + "/results/" + EXP_ID,
                    "local_entry": EXP + "/README.md", "images": 816, "updates": 0,
                    "local_coverage": "all 816 PNG and 833 terminal artifacts (including launch/recovery outside run root); whole project extras incomplete"},
                   {"run_id": DIAG_ID, "server": "103", "remote_path": m103["root"] + "/results/" + DIAG_ID,
                    "local_entry": DIAG + "/README.md", "images": 0, "updates": 0,
                    "local_coverage": "all 1141 run artifacts; peripheral preparation/runtime directories not fully mirrored"}],
               "server104_not_mirrored": {"logical_files": len(retrieval["missing_files"]), "unique_files": retrieval["new_unique_files"],
                                           "unique_bytes": retrieval["new_unique_bytes"], "transfer_status": "paused_by_user",
                                           "last_attempt_finished_at": retrieval["finished_at"], "last_transport_exit": retrieval["transport_returncode"]},
               "server103_models": {"index": "storage/server-index/103-models-historical.jsonl", "rows": len(model_rows), "source": models_path, "live_state_verified": False},
               "amax": {"status": "historical_paths_only_current_session_unverified", "last_access_evidence": ORG + "/amax_access_check.json",
                        "paths": ["/opt/data/private/BackdoorDM/", "/opt/data/private/EvilEdit/results/eviledit_reproduce/backdoored_unet.pt",
                                  "/opt/data/private/models/stable-diffusion-v1-5/", "/opt/data/private/models/vit-base-patch16-224/", "/opt/data/private/models/clip-vit-base-patch32/"],
                        "bytes": None, "sha256": None},
               "limitations": ["Missing local copies are intentionally left on servers under the latest user instruction.",
                               "A file index is not a second data copy; an inaccessible or deleted server file cannot be recovered from its index.",
                               "Unknown hashes stay null; older successful transfer evidence does not assert current server availability."]}
    (ROOT / "storage/server_catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"servers": nodes, "mismatches": sum(x["local"]["status"] == "local_mismatch" for x in rows104 + rows103)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
