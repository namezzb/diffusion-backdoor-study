"""Authenticate a frozen run's prompt, mask, code and review identities."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType

from evidence import CLASSES, STATES, VERSIONS
from inputs import validate_structure


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def input_digest(row, category):
    text = row["texts"][category]
    score_prompt = row["texts"]["dog"] if category == "trigger" else text
    content = {"id": row["id"], "partition": row["partition"], "category": category,
               "prompt": text, "score_prompt": score_prompt, "tokenization": row["tokenization"][category],
               "class_ids": row["class_ids"][category]}
    return _digest(json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode())


@dataclass(frozen=True)
class FrozenBindings:
    run_id: str
    manifest_sha: str
    review_sha: str
    selection_sha: str
    seeds: tuple
    bootstrap_seed: int
    random_seeds: tuple
    input_hashes: object
    mask_hashes: object
    coordinate_masks: object
    labels: object
    prompt_rows: object
    asset_hashes: object


def load_frozen_bindings(manifest_file, prompt_file, review_file, selection_file, repository_root):
    """Require M06 plus the subsequently frozen localization selection."""
    manifest_bytes = Path(manifest_file).read_bytes()
    manifest_sha = _digest(manifest_bytes)
    manifest = json.loads(manifest_bytes)
    review_bytes = Path(review_file).read_bytes()
    review = json.loads(review_bytes)
    if (manifest.get("status") != "frozen" or manifest.get("task_id") != "TCL-20261029-01"
            or not isinstance(manifest.get("run_id"), str) or not manifest["run_id"]):
        raise ValueError("a frozen independent TCL run identity is required")
    if review.get("status") != "passed" or review.get("manifest_sha256") != manifest_sha or not review.get("reviewer"):
        raise ValueError("M06 review must approve this exact frozen manifest")
    prompt_bytes = Path(prompt_file).read_bytes()
    if _digest(prompt_bytes) != manifest.get("prompts_sha256"):
        raise ValueError("frozen prompts file hash mismatch")
    seeds = manifest.get("generation_seeds")
    if not isinstance(seeds, list) or len(seeds) != 2 or len(set(seeds)) != 2 or any(type(s) is not int for s in seeds):
        raise ValueError("two fixed generation seeds required")
    bootstrap_seed = manifest.get("bootstrap_seed")
    if type(bootstrap_seed) is not int or bootstrap_seed < 0:
        raise ValueError("fixed bootstrap seed is required")
    random_seeds = manifest.get("random_control_seeds")
    if not isinstance(random_seeds, list) or len(random_seeds) != 3 or len(set(random_seeds)) != 3 or any(type(s) is not int for s in random_seeds):
        raise ValueError("three fixed random control seeds are required")
    selection_bytes = Path(selection_file).read_bytes()
    selection = json.loads(selection_bytes)
    if selection.get("status") != "frozen" or selection.get("manifest_sha256") != manifest_sha or selection.get("run_id") != manifest["run_id"]:
        raise ValueError("parameter selection must be frozen to this run after localization")
    masks = selection.get("mask_sha256")
    if not isinstance(masks, dict) or set(masks) != set(VERSIONS) or not all(_sha(x) for x in masks.values()):
        raise ValueError("eight frozen mask identities required")
    mask_files = selection.get("mask_files")
    if not isinstance(mask_files, dict) or set(mask_files) != set(VERSIONS):
        raise ValueError("eight parameter mask files required")
    selection_root = Path(selection_file).resolve().parent
    coordinate_masks = {}
    for version in VERSIONS:
        relative = mask_files[version]
        if not isinstance(relative, str):
            raise ValueError("mask file must be a relative path")
        path = selection_root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(selection_root) or not path.is_file():
            raise ValueError("missing or escaped mask file")
        content = path.read_bytes()
        if _digest(content) != masks[version]:
            raise ValueError("parameter mask content hash mismatch")
        coordinates = json.loads(content)
        if not isinstance(coordinates, dict) or any(not isinstance(k, str) or not k for k in coordinates):
            raise ValueError("invalid named parameter mask")
        canonical = json.dumps(coordinates, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        if content != canonical:
            raise ValueError("mask file must use canonical JSON")
        for values in coordinates.values():
            if not isinstance(values, list) or any(type(x) is not int or x < 0 for x in values) or values != sorted(set(values)):
                raise ValueError("mask coordinates must be sorted unique integers")
        coordinate_masks[version] = coordinates
    if any(coordinate_masks[v] for v in ("clean", "backdoor")):
        raise ValueError("baseline masks must be empty")
    sizes = [sum(map(len, coordinate_masks[v].values())) for v in VERSIONS[2:]]
    if not sizes or sizes[0] == 0 or len(set(sizes)) != 1:
        raise ValueError("restoration groups must share a positive coordinate count")
    randoms = [json.dumps(coordinate_masks[v], sort_keys=True, separators=(",", ":")) for v in ("new", "random_1", "random_2", "random_3")]
    if len(set(randoms)) != 4:
        raise ValueError("random masks must be distinct and differ from new")
    assets, sources = manifest.get("asset_sha256"), manifest.get("code_sha256")
    if not isinstance(assets, dict) or not assets or not all(_sha(x) for x in assets.values()):
        raise ValueError("current verified component hashes required")
    if not isinstance(sources, dict) or not sources or not all(_sha(x) for x in sources.values()):
        raise ValueError("frozen implementation hashes required")
    root = Path(repository_root).resolve()
    for relative, expected in sources.items():
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file() or _digest(path.read_bytes()) != expected:
            raise ValueError("frozen implementation file differs: " + str(relative))
    rows = [json.loads(line) for line in prompt_bytes.splitlines() if line.strip()]
    validate_structure(rows)
    hashes, labels, prompts = {}, {}, {}
    for row in rows:
        if set(row.get("tokenization", {})) != set(CLASSES):
            raise ValueError("all fixed tokenizations are required")
        for category in CLASSES:
            token = row["tokenization"][category]
            if (set(token) != {"input_ids", "attention_mask"} or len(token["input_ids"]) != 77
                    or len(token["attention_mask"]) != 77 or any(type(v) is not int for v in token["input_ids"])
                    or any(type(v) is not int or v not in (0, 1) for v in token["attention_mask"])):
                raise ValueError("invalid fixed tokenization")
            if row["partition"] in STATES:
                key = (row["partition"], row["id"], category)
                hashes[key] = input_digest(row, category)
                labels[key] = tuple(row["class_ids"][category])
                prompts[key] = json.dumps({"prompt": row["texts"][category],
                    "score_prompt": row["texts"]["dog"] if category == "trigger" else row["texts"][category],
                    "tokenization": token}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    encoded_masks = {v: json.dumps(coordinate_masks[v], sort_keys=True, separators=(",", ":")) for v in VERSIONS}
    return FrozenBindings(manifest["run_id"], manifest_sha, _digest(review_bytes), _digest(selection_bytes), tuple(seeds), bootstrap_seed, tuple(random_seeds),
                          MappingProxyType(hashes), MappingProxyType(dict(masks)), MappingProxyType(encoded_masks), MappingProxyType(labels),
                          MappingProxyType(prompts), MappingProxyType(dict(assets)))
