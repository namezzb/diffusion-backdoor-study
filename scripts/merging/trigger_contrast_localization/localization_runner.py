"""Sequential, resumable localization for an already reviewed frozen run.

This is a library entry, not a standalone authorized CLI. The caller must
load the frozen plan via preflight and create an explicitly allocated runtime.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core import coordinates_for_blocks, mask_hash, partition, response
from generation import _atomic_write
from intervene import intervene_resumable
from preflight import FrozenPlan
from selection import ScientificStop, build_selection, propose_groups
from selection_audit import _audit_combination, _evidence, _scored, block_id
from text_backend import TextBackend


def _write_once(path, content):
    path = Path(path)
    if path.exists():
        if not path.is_file() or path.read_bytes() != content:
            raise ValueError("existing frozen localization artifact differs: " + str(path))
        return
    _atomic_write(path, content)


def _status(ledger, unit):
    row = ledger.db.execute("SELECT status FROM units WHERE name=?", (unit,)).fetchone()
    return None if row is None else row[0]


def run_localization(plan, runtime, ledger, selection_dir):
    """Run 2 baselines, all blocks, and six frozen group combinations."""
    if not isinstance(plan, FrozenPlan):
        raise ValueError("an authenticated frozen plan is required")
    identity = json.loads(ledger.db.execute("SELECT value FROM metadata WHERE id=1").fetchone()[0])
    if identity.get("run_id") != plan.run_id or identity.get("manifest_sha") != plan.manifest_sha:
        raise ValueError("localization ledger belongs to another run")
    observed = {name: data["sha256"] for name, data in runtime.assets.file_hashes.items()}
    if observed != plan.asset_hashes:
        raise ValueError("loaded model files do not match the frozen manifest")
    text = TextBackend(runtime, plan.rows)
    if set(text.ids) != set(ledger.contexts):
        raise ValueError("localization inputs differ from the frozen ledger")
    assets = runtime.assets
    names = assets.parameter_names
    clean = {name: assets.text_states["clean"][name] for name in names}
    backdoor = {name: assets.text_states["backdoor"][name] for name in names}
    blocks, delta = partition(clean, backdoor)
    if set(identity.get("block_ids", ())) != {block_id(block) for block in blocks}:
        raise ValueError("ledger blocks differ from actual frozen TE parameters")
    baseline = {}
    for source in ("clean", "backdoor"):
        unit = "baseline:" + source
        baseline[source] = text.load_baseline(ledger, source) if _status(ledger, unit) == "complete" else text.baseline(ledger, source)
    before = response(baseline["backdoor"]["trigger"], baseline["backdoor"]["dog"],
                      baseline["clean"]["trigger"], baseline["clean"]["dog"])
    runtime.activate_source("original_backdoor")
    scores = {}
    for block in blocks:
        unit = "block:" + block_id(block)
        coordinates = coordinates_for_blocks([block])
        if _status(ledger, unit) is None:
            ledger.begin(unit)
        if _status(ledger, unit) == "started":
            ledger.resume(unit)
            intervene_resumable(runtime.text_encoder, clean, coordinates, text.ids, text.texts,
                                baseline["clean"], baseline["backdoor"], ledger, unit, text.forward)
        record = _evidence(ledger, unit)
        scores[block] = _scored(record, before, block.size, mask_hash(coordinates))
    proposal = propose_groups(blocks, scores, delta, plan.random_seeds)
    masks = {"clean": {}, "backdoor": {}}
    masks.update({name: {key: value.tolist() for key, value in coords.items()} for name, coords in proposal["groups"].items()})
    selection_dir = Path(selection_dir)
    mask_files, mask_hashes = {}, {}
    for version, coords in masks.items():
        data = json.dumps(coords, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        path = selection_dir / (version + ".mask.json")
        _write_once(path, data)
        mask_files[version], mask_hashes[version] = path.name, hashlib.sha256(data).hexdigest()
    preselection = {"run_id": plan.run_id, "manifest_sha256": plan.manifest_sha,
                    "mask_sha256": mask_hashes, "K": proposal["K"], "status": "preselected"}
    _write_once(selection_dir / "preselection.json", json.dumps(preselection, sort_keys=True, separators=(",", ":")).encode())
    after = None
    for version, coordinates in proposal["groups"].items():
        unit = "control:" + version
        if _status(ledger, unit) is None:
            ledger.begin(unit)
        if _status(ledger, unit) == "started":
            ledger.resume(unit)
            intervene_resumable(runtime.text_encoder, clean, coordinates, text.ids, text.texts,
                                baseline["clean"], baseline["backdoor"], ledger, unit, text.forward)
        record = _evidence(ledger, unit)
        actual = _audit_combination(ledger, unit, text.ids, baseline, record, before, proposal["K"], mask_hashes[version])
        if version == "new":
            after = actual
            if after >= before:
                raise ScientificStop("combined new group did not improve the frozen trigger response",
                                     "combined_response_not_improved",
                                     {"response_before": before, "response_after": after, "K": proposal["K"],
                                      "new_mask_sha256": mask_hashes[version]})
    validated = build_selection(blocks, scores, delta, before, after, plan.random_seeds)
    final = {"status": "frozen", "run_id": plan.run_id, "manifest_sha256": plan.manifest_sha,
             "mask_sha256": mask_hashes, "mask_files": mask_files, "K": validated["K"],
             "total_parameters": validated["total_parameters"], "summaries": validated["summaries"],
             "response_before": before, "response_after": after}
    content = json.dumps(final, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    _write_once(selection_dir / "selection.json", content)
    return final
