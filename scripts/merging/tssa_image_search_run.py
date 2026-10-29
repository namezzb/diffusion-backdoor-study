"""Bounded, image-scored search over the original frozen TSSA two-scalar basis.

This is a separate experiment identity, never a resume/amendment of the MVP.
`check` imports no ML libraries. `run` requires an externally authorized GPU
UUID, locally verified assets, and a new plan with independent data partitions.
Unfinished image operations are deliberately not replayable by this runner.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
import traceback
import unicodedata
from typing import Any, Mapping

STAGES = ("search", "dev", "confirm")
SOURCE_FILES = ("tssa_image_search_run.py", "tssa_sd_runtime.py", "tssa_gradient_core.py", "tssa_mvp_score.py")
TARGET_IDS = frozenset(range(281, 288))


class IntegrityError(RuntimeError):
    pass


class InflightOperation(IntegrityError):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, canonical(value))


def identifier(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", value) is not None


def normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split()).casefold()


def validate_plan(plan: Mapping[str, Any], old_protocol: Mapping[str, Any]) -> dict[str, int]:
    """Validate all scientific gates without importing torch or loading models."""
    if plan.get("schema_version") != 1 or not identifier(plan.get("id")):
        raise IntegrityError("Expected schema_version=1 and a safe independent experiment id.")
    thresholds = plan.get("thresholds", {})
    if thresholds != {"accuracy_drop_max": 0.05, "clip_drop_max": 1.0}:
        raise IntegrityError("Normal ACC/CLIP thresholds must be frozen to 0.05 and 1.0.")
    candidates = plan.get("candidates", {})
    if (not isinstance(candidates, dict) or candidates.get("naive") != [1, 1]
            or "clean" in candidates or len(candidates) < 2):
        raise IntegrityError("Declare naive=[1,1] and at least one new candidate; clean=[0,0] is implicit.")
    coefficients = set()
    for name, values in candidates.items():
        if (not identifier(name) or not isinstance(values, list) or len(values) != 2
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                       or not 0 <= v <= 32 for v in values)):
            raise IntegrityError("Candidate coefficients must be unique finite pairs in [0,32].")
        key = tuple(values)
        if key == (0, 0) or key in coefficients:
            raise IntegrityError("Duplicate coefficient pairs or implicit clean control are forbidden.")
        coefficients.add(key)
    top_k = plan.get("search_top_k")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 3:
        raise IntegrityError("search_top_k must be an integer in [1,3].")
    if set(plan.get("stages", {})) != set(STAGES):
        raise IntegrityError("Exactly search, dev, and confirm partitions are required.")
    prior_texts, prior_seeds, prior_ids, allowed_normal_labels = set(), set(), set(), set()
    for block in old_protocol.get("prompts", {}).values():
        if not isinstance(block, dict):
            continue
        for group in ("pairs", "extra_normal"):
            for row in block.get(group, []):
                prior_ids.add(row["id"])
                allowed_normal_labels.add(tuple(sorted(row.get("normal_class_ids", row.get("class_ids", [])))))
                for key in ("normal", "triggered", "prompt"):
                    if isinstance(row.get(key), str):
                        prior_texts.add(normalized(row[key]))
                if isinstance(row.get("trajectory_seed"), int):
                    prior_seeds.add(row["trajectory_seed"])
    for key, values in old_protocol.get("sampling", {}).items():
        if "seed" in key:
            prior_seeds.update(values if isinstance(values, list) else [values])
    development = old_protocol["merging"]["development_normal_states"]
    all_conditions = development + old_protocol["merging"]["heldout_states"]
    seen_ids, seen_texts, seen_seeds = set(prior_ids), set(prior_texts), set(prior_seeds)
    counts = {}
    for stage in STAGES:
        block = plan["stages"][stage]
        conditions, rows = block.get("conditions", []), block.get("rows", [])
        allowed = all_conditions if stage == "confirm" else development
        condition_ids = [c.get("id") for c in conditions]
        if (not conditions or len(set(condition_ids)) != len(conditions) or "upload" not in condition_ids
                or any(dict(c) not in allowed or not identifier(c.get("id")) for c in conditions)):
            raise IntegrityError(f"{stage}: conditions must be original declared states, including upload.")
        attack_ids = block.get("attack_condition_ids")
        expected_attack = {c["id"] for c in conditions if c["expert"] is not None}
        if not expected_attack or not isinstance(attack_ids, list) or set(attack_ids) != expected_attack or len(attack_ids) != len(expected_attack):
            raise IntegrityError(f"{stage}: attack_condition_ids must include all merge states and exclude upload.")
        if not isinstance(rows, list) or not rows:
            raise IntegrityError(f"{stage}: nonempty image rows are required.")
        ids, texts, seeds, signatures = set(), set(), set(), set()
        paired_normal = set()
        for row in rows:
            if not identifier(row.get("id")) or row["id"] in ids or row["id"] in seen_ids:
                raise IntegrityError(f"{stage}: duplicate, unsafe, or previously exposed row id.")
            ids.add(row["id"])
            if any(not isinstance(row.get(k), str) or not row[k].strip() for k in ("prompt", "normal_prompt")):
                raise IntegrityError(f"{stage}: nonempty generation and paired normal text required.")
            if type(row.get("triggered")) is not bool or type(row.get("seed")) is not int or not 0 <= row["seed"] < 2**63:
                raise IntegrityError(f"{stage}: exact boolean trigger and nonnegative integer seed required.")
            labels = row.get("expected_class_ids")
            if (not isinstance(labels, list) or not labels or len(set(labels)) != len(labels)
                    or any(type(v) is not int or not 0 <= v < 1000 for v in labels)):
                raise IntegrityError(f"{stage}: predeclared normal ImageNet labels required for every row.")
            if tuple(sorted(labels)) not in allowed_normal_labels:
                raise IntegrityError(f"{stage}: normal labels must use a previously registered class mapping.")
            if row["triggered"]:
                if set(row.get("target_class_ids", [])) != TARGET_IDS:
                    raise IntegrityError(f"{stage}: trigger targets must be the frozen ImageNet cat IDs 281..287.")
                trigger = old_protocol["trigger"]
                if row["prompt"] != row["normal_prompt"].replace(trigger["source"], trigger["replacement"]):
                    raise IntegrityError(f"{stage}: trigger text must use the exact original case-sensitive replace_all without normalization.")
            prompt, normal = normalized(row["prompt"]), normalized(row["normal_prompt"])
            if prompt in seen_texts or normal in seen_texts or row["seed"] in seen_seeds:
                raise IntegrityError(f"{stage}: fresh prompt and seed partitions must not overlap previous MVP or stages.")
            if (row["triggered"] and prompt == normal) or (not row["triggered"] and prompt != normal):
                raise IntegrityError(f"{stage}: trigger flags disagree with generation/normal prompt pair.")
            signature = (prompt, row["seed"])
            if signature in signatures:
                raise IntegrityError(f"{stage}: duplicate generation prompt/seed would repeat a scientific sample.")
            signatures.add(signature)
            if not row["triggered"]:
                paired_normal.add((normal, row["seed"], tuple(sorted(labels))))
            texts.update((prompt, normal))
            seeds.add(row["seed"])
        if not any(r["triggered"] for r in rows) or not paired_normal:
            raise IntegrityError(f"{stage}: both attack and normal rows are mandatory.")
        for row in rows:
            if row["triggered"] and (normalized(row["normal_prompt"]), row["seed"], tuple(sorted(row["expected_class_ids"]))) not in paired_normal:
                raise IntegrityError(f"{stage}: each trigger needs its paired normal image with the same seed and labels.")
        seen_ids.update(ids)
        seen_texts.update(texts)
        seen_seeds.update(seeds)
        candidate_count = len(candidates) + 1 if stage == "search" else min(top_k, len(candidates) - 1) + 2 if stage == "dev" else 3
        counts[stage] = candidate_count * len(conditions) * len(rows)
    max_images = plan.get("max_images")
    if type(max_images) is not int or max_images <= 0 or sum(counts.values()) > max_images:
        raise IntegrityError("The frozen image budget cannot cover the maximum declared stage work.")
    return counts


def load_plan(path: Path, old_path: Path, assets_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = json.loads(path.read_text())
    for key, target in (("old_protocol_sha256", old_path), ("asset_manifest_sha256", assets_path)):
        if plan.get(key) != file_hash(target):
            raise IntegrityError(f"Frozen input hash mismatch: {key}")
    hashes = plan.get("source_hashes", {})
    if not set(SOURCE_FILES).issubset(hashes):
        raise IntegrityError("Freeze hashes for the runner and all three imported research source files.")
    for name, expected in hashes.items():
        if Path(name).name != name or file_hash(Path(__file__).parent / name) != expected:
            raise IntegrityError(f"Frozen implementation hash mismatch: {name}")
    counts = validate_plan(plan, json.loads(old_path.read_text()))
    return plan, {"id": plan["id"], "plan_sha256": file_hash(path), "plan_payload_sha256": digest(plan),
                  "old_protocol_sha256": plan["old_protocol_sha256"], "asset_manifest_sha256": plan["asset_manifest_sha256"],
                  "source_hashes": hashes, "max_images": plan["max_images"], "maximum_stage_images": counts}


class Store:
    """One owner, atomic receipts, immutable identity, and fail-closed recovery."""
    def __init__(self, root: Path, identity: Mapping[str, Any], *, resume: bool = False):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = (self.root / ".run.lock").open("a+")
        try:
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            identity_path = self.root / "identity.json"
            if identity_path.exists():
                if not resume or json.loads(identity_path.read_text()) != identity:
                    raise IntegrityError("Existing run needs explicit resume and exactly matching immutable identity.")
            else:
                if resume or any(p.name != ".run.lock" for p in self.root.iterdir()):
                    raise IntegrityError("Use a new empty run directory; do not adopt unrelated or incomplete directories.")
                atomic_json(identity_path, identity)
            self.identity = dict(identity)
            self.receipts = {}
            self.inflight = None
            for path in sorted((self.root / "operations").glob("*.json")):
                receipt = json.loads(path.read_text())
                if receipt.get("status") != "completed":
                    raise InflightOperation(f"Unfinished operation {path.name}; preserve evidence and audit manually, never replay automatically.")
                self._verify_receipt(receipt, path)
                self.receipts[receipt["task_id"]] = receipt
            if len(self.receipts) > self.identity["max_images"]:
                raise IntegrityError("Stored operation count exceeds frozen budget.")
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if not self.lock.closed:
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_UN)
            self.lock.close()

    def _verify_receipt(self, receipt: dict[str, Any], path: Path) -> None:
        task = receipt["task"]
        if digest(task) != receipt["task_id"] or path.stem != receipt["task_id"] or receipt["identity_sha256"] != digest(self.identity):
            raise IntegrityError("Receipt/task/run binding is corrupt.")
        record = receipt["record"]
        if digest(record) != receipt["record_sha256"]:
            raise IntegrityError("Scored record hash mismatch.")
        image = (self.root / record["image_path"]).resolve()
        if not image.is_relative_to(self.root) or not image.is_file() or file_hash(image) != record["image_sha256"]:
            raise IntegrityError("Completed PNG is missing, changed, or outside this run.")
        validate_score(record["score"])

    def artifact(self, name: str) -> Any | None:
        path = self.root / name
        if not path.exists():
            return None
        envelope = json.loads(path.read_text())
        if envelope.get("sha256") != digest(envelope.get("payload")):
            raise IntegrityError(f"Artifact checksum mismatch: {name}")
        if envelope.get("identity_sha256") != digest(self.identity):
            raise IntegrityError(f"Artifact belongs to another run: {name}")
        return envelope["payload"]

    def commit(self, name: str, payload: Any) -> None:
        existing = self.artifact(name)
        if existing is not None:
            if existing != payload:
                raise IntegrityError(f"Attempt to overwrite an immutable committed artifact: {name}")
            return
        atomic_json(self.root / name, {"payload": payload, "sha256": digest(payload), "identity_sha256": digest(self.identity)})

    def perform(self, task: dict[str, Any], backend: Any) -> dict[str, Any]:
        task_id = digest(task)
        if self.inflight is not None:
            raise InflightOperation("An earlier operation in this process did not commit; stop without further work.")
        if task_id in self.receipts:
            return self.receipts[task_id]["record"]
        if len(self.receipts) >= self.identity["max_images"]:
            raise IntegrityError("Hard image budget exhausted before starting another generation.")
        path = self.root / "operations" / (task_id + ".json")
        if path.exists():
            raise InflightOperation("An uncommitted operation already exists; no implicit replay.")
        receipt = {"task_id": task_id, "identity_sha256": digest(self.identity), "task": task,
                   "status": "started", "started_at": now()}
        atomic_json(path, receipt)
        self.inflight = task_id
        # Receipt precedes model sampling: a crash consumes an auditable attempt.
        started = time.monotonic()
        image = backend.sample(task)
        image_path = Path("images") / task["stage"] / task["condition"]["id"] / task["candidate"] / (task["row"]["id"] + ".png")
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        atomic_bytes(self.root / image_path, stream.getvalue())
        from PIL import Image
        with Image.open(self.root / image_path) as saved:
            score = backend.score(saved.convert("RGB"), task["row"]["normal_prompt"])
        validate_score(score)
        record = {"task_id": task_id, "stage": task["stage"], "candidate": task["candidate"],
                  "condition_id": task["condition"]["id"], "row": task["row"], "coefficients": task["coefficients"],
                  "image_path": str(image_path), "image_sha256": file_hash(self.root / image_path), "score": score,
                  "seconds": time.monotonic() - started, "execution_id": getattr(backend, "execution_id", "cpu_fixture"),
                  "resources_current_process": backend.resources()}
        receipt.update(status="completed", completed_at=now(), record=record, record_sha256=digest(record))
        atomic_json(path, receipt)
        self.receipts[task_id] = receipt
        self.inflight = None
        atomic_json(self.root / "progress.json", {"updated_at": now(), "stage": task["stage"], "candidate": task["candidate"],
                    "condition_id": task["condition"]["id"], "completed_images": len(self.receipts),
                    "max_images": self.identity["max_images"], "resources_current_process": backend.resources()})
        return record


def validate_score(score: Mapping[str, Any]) -> None:
    if (set(score) != {"vit_class", "clip_score"} or type(score["vit_class"]) is not int or not 0 <= score["vit_class"] < 1000
            or isinstance(score["clip_score"], bool) or not isinstance(score["clip_score"], (int, float))
            or not math.isfinite(score["clip_score"]) or not 0 <= score["clip_score"] <= 100):
        raise IntegrityError("Independent scorer returned an invalid class or CLIP score.")


def wilson(success: int, total: int) -> list[float]:
    z = 1.959963984540054
    p, z2 = success / total, z * z
    center = (p + z2 / (2 * total)) / (1 + z2 / total)
    half = z * math.sqrt(p * (1 - p) / total + z2 / (4 * total * total)) / (1 + z2 / total)
    return [max(0, center - half), min(1, center + half)]


def image_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    attacked = [r for r in records if r["row"]["triggered"]]
    normal = [r for r in records if not r["row"]["triggered"]]
    paired_keys = {(r["row"]["normal_prompt"], r["row"]["seed"]) for r in attacked}
    def normal_metrics(rows):
        correct = sum(r["score"]["vit_class"] in r["row"]["expected_class_ids"] for r in rows)
        return {"normal_n": len(rows), "normal_correct": correct,
                "normal_accuracy": correct / len(rows) if rows else None,
                "normal_clip": sum(r["score"]["clip_score"] for r in rows) / len(rows) if rows else None}
    success = sum(r["score"]["vit_class"] in TARGET_IDS for r in attacked)
    return {"attack_success": success, "attack_n": len(attacked), "asr": success / len(attacked) if attacked else None,
            "asr_wilson95": wilson(success, len(attacked)) if attacked else None, **normal_metrics(normal),
            "normal_groups": {"paired_normal": normal_metrics([r for r in normal if (r["row"]["normal_prompt"], r["row"]["seed"]) in paired_keys]),
                              "extra_normal": normal_metrics([r for r in normal if (r["row"]["normal_prompt"], r["row"]["seed"]) not in paired_keys])}}


def summarize(plan: Mapping[str, Any], stage: str, names: list[str], records: list[dict[str, Any]]) -> dict[str, Any]:
    block = plan["stages"][stage]
    expected = {(name, c["id"], r["id"]) for name in names for c in block["conditions"] for r in block["rows"]}
    indexed = {(r["candidate"], r["condition_id"], r["row"]["id"]): r for r in records}
    if set(indexed) != expected or len(indexed) != len(records):
        raise IntegrityError("Stage contains missing, duplicate, or unexpected attack/normal samples.")
    for name, condition, row_id in expected:
        actual = indexed[name, condition, row_id]
        declared = next(r for r in block["rows"] if r["id"] == row_id)
        values = [0, 0] if name == "clean" else plan["candidates"][name]
        if actual["row"] != declared or actual["coefficients"] != values or actual["stage"] != stage:
            raise IntegrityError("Stage record disagrees with its frozen prompt, coefficient, or split.")
    result = {}
    for name in names:
        cells = {}
        for condition in block["conditions"]:
            cell_records = [indexed[name, condition["id"], row["id"]] for row in block["rows"]]
            cells[condition["id"]] = image_metrics(cell_records)
            cells[condition["id"]]["per_seed"] = {str(seed): image_metrics([r for r in cell_records if r["row"]["seed"] == seed])
                                                     for seed in sorted({r["row"]["seed"] for r in cell_records})}
        attacks = [cells[c]["asr"] for c in block["attack_condition_ids"]]
        values = [0, 0] if name == "clean" else plan["candidates"][name]
        result[name] = {"coefficients": values, "coefficient_norm": math.hypot(*values), "states": cells,
                        "macro_asr": sum(attacks) / len(attacks), "worst_asr": min(attacks)}
    clean = result["clean"]["states"]
    for name, metrics in result.items():
        for condition, cell in metrics["states"].items():
            cell["accuracy_drop_vs_clean"] = clean[condition]["normal_accuracy"] - cell["normal_accuracy"]
            cell["clip_drop_vs_clean"] = clean[condition]["normal_clip"] - cell["normal_clip"]
            cell["normal_pass"] = (cell["accuracy_drop_vs_clean"] <= 0.05 + 1e-12 and cell["clip_drop_vs_clean"] <= 1.0 + 1e-12)
            improved = harmed = 0
            for row in block["rows"]:
                if row["triggered"]:
                    candidate_hit = indexed[name, condition, row["id"]]["score"]["vit_class"] in TARGET_IDS
                    baseline_hit = indexed["naive", condition, row["id"]]["score"]["vit_class"] in TARGET_IDS
                    improved += candidate_hit and not baseline_hit
                    harmed += baseline_hit and not candidate_hit
            discordant = improved + harmed
            p = min(1.0, 2 * sum(math.comb(discordant, k) for k in range(min(improved, harmed) + 1)) / 2**discordant) if discordant else 1.0
            cell["paired_vs_naive"] = {"improved": improved, "harmed": harmed, "unchanged": cell["attack_n"] - discordant,
                                       "asr_difference": cell["asr"] - result["naive"]["states"][condition]["asr"],
                                       "exact_mcnemar_p_two_sided": p}
        metrics["normal_pass"] = all(cell["normal_pass"] for cell in metrics["states"].values())
        metrics["macro_difference_vs_naive"] = metrics["macro_asr"] - result["naive"]["macro_asr"]
        metrics["worst_difference_vs_naive"] = metrics["worst_asr"] - result["naive"]["worst_asr"]
    eligible = [name for name in names if name not in ("clean", "naive") and result[name]["normal_pass"]]
    ranked = sorted(eligible, key=lambda n: (-result[n]["macro_asr"], -result[n]["worst_asr"], result[n]["coefficient_norm"], n))
    return {"stage": stage, "image_count": len(records), "generation_and_scoring_seconds": sum(r["seconds"] for r in records),
            "candidates": result, "ranked_eligible": ranked,
            "attack_condition_ids": block["attack_condition_ids"], "normal_condition_ids": [c["id"] for c in block["conditions"]],
            "record_sha256": [digest(r) for r in records],
            "inference_limits": "Wilson and exact McNemar describe each cell only; no multiplicity adjustment or prompt-cluster independence claim. Independent confirm is required; no SOTA/statistical-significance claim is automatic."}


def select(plan: Mapping[str, Any], stage: str, summary: Mapping[str, Any]) -> dict[str, Any]:
    ranked = summary["ranked_eligible"]
    selected = ranked[:plan["search_top_k"]] if stage == "search" else []
    reason = "eligible_candidates" if selected else "no_qualified_candidate"
    promotion_eligible = []
    if stage in ("dev", "confirm") and ranked:
        promotion_eligible = [name for name in ranked if summary["candidates"][name]["macro_difference_vs_naive"] > 0
                              and summary["candidates"][name]["worst_difference_vs_naive"] >= -1e-12]
        if promotion_eligible:
            selected, reason = promotion_eligible[:1], "observed_merge_asr_improvement_with_normal_constraints"
        else:
            reason = "no_candidate_exceeds_naive_macro_with_noninferior_worst"
    return {"stage": stage, "selected": selected, "reason": reason, "summary_sha256": digest(summary), "promotion_eligible": promotion_eligible,
            "coefficients": {name: plan["candidates"][name] for name in selected}}


class Runner:
    def __init__(self, plan: dict[str, Any], store: Store, backend_factory):
        self.plan, self.store, self.backend_factory = plan, store, backend_factory
        self.backend = None

    def execute(self, until: str = "confirm") -> dict[str, Any]:
        if until not in STAGES:
            raise ValueError("Unknown final stage.")
        self.store.commit("plan.json", self.plan)
        # A complete run can be inspected/resumed without allocating any GPU.
        completed = self.store.artifact("final_report.json")
        if completed is not None:
            return completed
        names = ["clean"] + list(self.plan["candidates"])
        for stage in STAGES:
            if stage != "search":
                previous = STAGES[STAGES.index(stage) - 1]
                selection = self.store.artifact(f"{previous}_selection.json")
                if not selection or not selection["selected"]:
                    raise IntegrityError("The next split cannot be opened without a committed nonempty selection.")
                names = ["clean", "naive"] + selection["selected"]
            if stage == "confirm" and self.store.artifact("confirm_binding.json") is None:
                selection = self.store.artifact("dev_selection.json")
                if len(selection["selected"]) != 1:
                    raise IntegrityError("Confirmation requires exactly one previously frozen development winner.")
                self.store.commit("confirm_binding.json", {"dev_selection_sha256": digest(selection),
                                  "candidate_coefficients": {n: [0, 0] if n == "clean" else self.plan["candidates"][n] for n in names}})
            records = []
            block = self.plan["stages"][stage]
            for condition in block["conditions"]:
                for name in names:
                    for row in block["rows"]:
                        task = {"stage": stage, "candidate": name, "condition": condition, "row": row,
                                "coefficients": [0, 0] if name == "clean" else self.plan["candidates"][name]}
                        task_id = digest(task)
                        if task_id in self.store.receipts:
                            records.append(self.store.receipts[task_id]["record"])
                            continue
                        if self.backend is None:
                            self.backend = self.backend_factory()
                            metadata_path = f"executions/{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
                            self.backend.execution_id = Path(metadata_path).stem
                            self.store.commit(metadata_path, self.backend.metadata())
                        if stage == "confirm" and not getattr(self, "_unlocked", False):
                            binding = self.store.artifact("confirm_binding.json")
                            if binding["dev_selection_sha256"] != digest(self.store.artifact("dev_selection.json")):
                                raise IntegrityError("Confirmation selection binding changed.")
                            self.backend.unlock_heldout(binding["candidate_coefficients"])
                            self._unlocked = True
                        records.append(self.store.perform(task, self.backend))
            summary = summarize(self.plan, stage, names, records)
            self.store.commit(f"{stage}_summary.json", summary)
            selection = select(self.plan, stage, summary)
            self.store.commit(f"{stage}_selection.json", selection)
            print(json.dumps({"at": now(), "stage": stage, "images": len(records), "selected": selection["selected"], "reason": selection["reason"]}), flush=True)
            if not selection["selected"] or stage == "confirm":
                report = {"id": self.plan["id"], "status": "completed", "stopped_after": stage,
                          "reason": selection["reason"], "confirmed_observed_improvement": stage == "confirm" and bool(selection["selected"]),
                          "selected": selection["selected"], "completed_images": len(self.store.receipts),
                          "max_images": self.plan["max_images"], "last_summary_sha256": digest(summary),
                          "generation_and_scoring_seconds": sum(r["record"]["seconds"] for r in self.store.receipts.values()),
                          "per_execution_last_resources": {r["record"]["execution_id"]: r["record"]["resources_current_process"]
                              for r in sorted(self.store.receipts.values(), key=lambda r: r["completed_at"])},
                          "new_scientific_budget": True, "old_mvp_rewritten_or_replayed": False,
                          "claim_limit": "Observed independent-sample outcome, not automatic robust/statistically significant improvement; all per-state utility and ASR comparisons must be reported."}
                self.store.commit("final_report.json", report)
                return report
            if stage == until:
                return {"status": "stage_complete", "stage": stage, "selected": selection["selected"], "completed_images": len(self.store.receipts)}
        raise AssertionError("Unreachable stage transition")


class RealBackend:
    def __init__(self, old_path: Path, assets_path: Path, models_root: Path, plan: dict[str, Any], scorer_device: str):
        from tssa_sd_runtime import load_cpu_assets, SDGradientRuntime
        from tssa_mvp_score import IndependentScorer
        assets = load_cpu_assets(old_path, assets_path, models_root)
        # The old runtime truncates long text; this independent plan rejects it first.
        for stage in STAGES:
            for row in plan["stages"][stage]["rows"]:
                for key in ("prompt", "normal_prompt"):
                    ids = assets.tokenizer(row[key], truncation=False, add_special_tokens=True)["input_ids"]
                    if len(ids) > 77:
                        raise IntegrityError(f"Prompt exceeds CLIP token limit: {stage}/{row['id']}/{key}")
        self.runtime = SDGradientRuntime(assets)
        self.scorer = IndependentScorer(models_root, device=scorer_device)

    def metadata(self) -> dict[str, Any]:
        return {"created_at": now(), "kind": "real_offline_diffusion_image_search", "runtime": self.runtime.environment_record(),
                "scorer": self.scorer.describe(), "models_and_sampling_from_old_protocol_only": True,
                "original_mvp_loss_or_training_not_run": True}

    def sample(self, task):
        from tssa_mvp_score import to_rgb_pil
        output = self.runtime.sample(task["row"]["prompt"], task["row"]["seed"],
                                     condition=task["condition"], coefficients=task["coefficients"])
        return to_rgb_pil(output["image"])

    def score(self, image, normal_prompt):
        return self.scorer.score(image, normal_prompt)

    def unlock_heldout(self, coefficients):
        self.runtime.unlock_heldout(coefficients)

    def resources(self):
        return self.runtime.resource_record()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "run"))
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--old-protocol", required=True, type=Path)
    parser.add_argument("--asset-manifest", required=True, type=Path)
    parser.add_argument("--models-root", type=Path)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--scorer-device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--until", choices=STAGES, default="confirm")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    plan, identity = load_plan(args.plan, args.old_protocol, args.asset_manifest)
    if args.scorer_device != plan.get("scorer_device", "cpu"):
        raise IntegrityError("The scorer device must match the frozen plan (CPU by default).")
    identity["scorer_device"] = args.scorer_device
    if args.command == "check":
        print(json.dumps({"passed": True, "models_loaded": False, "CUDA_initialized": False, **identity}, ensure_ascii=False, indent=2))
        return
    if args.models_root is None or args.run_root is None:
        parser.error("run requires --models-root and --run-root")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    store = Store(args.run_root, identity, resume=args.resume)
    try:
        runner = Runner(plan, store, lambda: RealBackend(args.old_protocol, args.asset_manifest, args.models_root, plan, args.scorer_device))
        report = runner.execute(args.until)
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    except BaseException:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        atomic_json(store.root / "failures" / f"{stamp}.json", {"at": now(), "traceback": traceback.format_exc(),
                    "automatic_replay_permitted": False, "completed_images": len(store.receipts)})
        raise
    finally:
        store.close()


if __name__ == "__main__":
    main()
