"""Strict, CPU-only aggregation and gates for the frozen TSSA gradient MVP.

This module does not generate images or load scoring models. Each JSONL row is
an already scored real image with candidate, state, split, prompt_id, kind,
seed, vit_class, clip_score and protocol_sha256. Kinds are ``triggered``,
``paired_normal`` and ``extra_normal``; pair IDs are shared by their two kinds.

Response summaries contain protocol_sha256, B_star_rms, unit_ids and candidates.
Each candidate has normal_mse (four states), backdoor_mse (three merge states),
delta_l2 and per_state_unit_count=24. These must be complete-cache means, not
training minibatches. Selection accepts validation images only; held-out images
are consumed by a separate reporting function after the selection is frozen.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class EvidenceError(ValueError):
    """Incomplete, mixed, malformed or protocol-incompatible evidence."""


KEY_FIELDS = ("candidate", "state", "split", "prompt_id", "kind", "seed")
KINDS = ("triggered", "paired_normal", "extra_normal")


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _number(value: Any, name: str, *, minimum: float = 0.0,
            maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvidenceError(f"{name} must be a finite number.")
    result = float(value)
    if not math.isfinite(result) or result < minimum or (maximum is not None and result > maximum):
        raise EvidenceError(f"{name} is nonfinite or outside its allowed range.")
    return result


def _count(value: Any, name: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvidenceError(f"{name} must be an integer.")
    if value < minimum or (maximum is not None and value > maximum):
        raise EvidenceError(f"{name} is outside its allowed range.")
    return value


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                raise EvidenceError(f"Blank JSONL row at line {line_number}.")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise EvidenceError(f"Invalid JSON at line {line_number}.") from error
            if not isinstance(value, dict):
                raise EvidenceError(f"JSONL line {line_number} is not an object.")
            rows.append(value)
    return rows


class MVPEvaluator:
    def __init__(self, protocol: Mapping[str, Any], protocol_sha256: str):
        self.p = protocol
        if len(protocol_sha256) != 64 or any(c not in "0123456789abcdef" for c in protocol_sha256):
            raise EvidenceError("protocol_sha256 must be the frozen file SHA256.")
        self.sha = protocol_sha256
        self.dev_states = [x["id"] for x in protocol["merging"]["development_backdoor_states"]]
        self.normal_states = [x["id"] for x in protocol["merging"]["development_normal_states"]]
        self.hold_states = [x["id"] for x in protocol["merging"]["heldout_states"]]
        self.static = [x["id"] for x in protocol["static_candidates"]]
        self.candidate_ids = {x["id"]: x["candidate_id"] for x in protocol["static_candidates"]}
        self.candidate_ids.update(protocol["learned_candidate_ids"])
        self.all_candidates = sorted(self.candidate_ids, key=self.candidate_ids.get)
        self.prompts: dict[tuple[str, str], dict[str, Any]] = {}
        for split, block in protocol["prompts"].items():
            for kind in ("pairs", "extra_normal"):
                for prompt in block[kind]:
                    key = (split, prompt["id"])
                    if key in self.prompts:
                        raise EvidenceError(f"Duplicate protocol prompt: {key}")
                    self.prompts[key] = {**prompt, "_group": kind}
        self.unit_ids = [unit["id"] for unit in protocol["cache"]["training_units"]]
        if len(self.unit_ids) != 24 or len(set(self.unit_ids)) != 24:
            raise EvidenceError("This frozen MVP requires 24 distinct response units.")

    @classmethod
    def from_file(cls, path: str | Path) -> "MVPEvaluator":
        contents = Path(path).read_bytes()
        return cls(json.loads(contents), hashlib.sha256(contents).hexdigest())

    def expected_keys(self, stage: str, selection: Mapping[str, Any] | None = None) -> set[tuple[Any, ...]]:
        """Enumerate every expected image identity, without inventing any scores."""
        if stage == "source":
            candidates, states, split = ["clean", "original_backdoor"], ["upload"], "fit"
            seeds = [self.p["sampling"]["source_gate_seed"]]
            pair_ids = [x["id"] for x in self.p["prompts"][split]["pairs"]]
            extra_ids = [x["id"] for x in self.p["prompts"][split]["extra_normal"]]
            trigger_states = set(states)
        elif stage == "screen":
            candidates, states, split = self.static + ["matched_clean"], self.normal_states, "fit"
            seeds = [self.p["sampling"]["static_screen_seed"]]
            pair_ids = self.p["static_proxy_screen"]["fit_pair_ids"]
            extra_ids = self.p["static_proxy_screen"]["fit_extra_normal_ids"]
            trigger_states = set(self.dev_states)
        elif stage == "select":
            candidates, states, split = self.all_candidates + ["matched_clean"], self.normal_states, "val"
            seeds = [self.p["sampling"]["val_seed"]]
            pair_ids = [x["id"] for x in self.p["prompts"][split]["pairs"]]
            extra_ids = [x["id"] for x in self.p["prompts"][split]["extra_normal"]]
            trigger_states = set(self.dev_states)
        elif stage == "heldout":
            self._check_selection(selection)
            assert selection is not None
            chosen = list(selection["selected_checkpoint_candidates"].values())
            candidates = list(dict.fromkeys([x for x in chosen if x is not None] + ["matched_clean"]))
            states, split, seeds = self.hold_states, "test", self.p["sampling"]["test_seeds"]
            pair_ids = [x["id"] for x in self.p["prompts"][split]["pairs"]]
            extra_ids = [x["id"] for x in self.p["prompts"][split]["extra_normal"]]
            trigger_states = set(states)
        else:
            raise EvidenceError(f"Unknown stage: {stage}")
        expected = set()
        for candidate in candidates:
            for state in states:
                for seed in seeds:
                    for prompt_id in pair_ids:
                        expected.add((candidate, state, split, prompt_id, "paired_normal", seed))
                        if state in trigger_states:
                            expected.add((candidate, state, split, prompt_id, "triggered", seed))
                    for prompt_id in extra_ids:
                        expected.add((candidate, state, split, prompt_id, "extra_normal", seed))
        return expected

    def validate_records(self, stage: str, records: Iterable[Mapping[str, Any]],
                         selection: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        expected = self.expected_keys(stage, selection)
        seen: set[tuple[Any, ...]] = set()
        checked = []
        for index, row in enumerate(records):
            if not isinstance(row, Mapping):
                raise EvidenceError(f"Image row {index} is not an object.")
            required = {*KEY_FIELDS, "vit_class", "clip_score", "protocol_sha256"}
            if not required <= row.keys():
                raise EvidenceError(f"Image row {index} lacks fields: {sorted(required - row.keys())}")
            if row["protocol_sha256"] != self.sha:
                raise EvidenceError(f"Image row {index} belongs to another protocol.")
            for name in KEY_FIELDS[:-1]:
                if not isinstance(row[name], str):
                    raise EvidenceError(f"Image row {index} {name} must be a string.")
            _count(row["seed"], "seed")
            _count(row["vit_class"], "vit_class", maximum=999)
            _number(row["clip_score"], "clip_score", maximum=100.0)
            key = tuple(row[name] for name in KEY_FIELDS)
            if key in seen:
                raise EvidenceError(f"Duplicate image identity: {key}")
            if key not in expected:
                raise EvidenceError(f"Unexpected image identity for {stage}: {key}")
            seen.add(key)
            checked.append(dict(row))
        missing = expected - seen
        if missing:
            raise EvidenceError(f"Incomplete {stage}: missing {len(missing)} of {len(expected)} images; first={sorted(missing)[0]}")
        return checked

    def _correct(self, row: Mapping[str, Any]) -> bool:
        prompt = self.prompts[(row["split"], row["prompt_id"])]
        if row["kind"] == "triggered":
            expected_ids = prompt["target_class_ids"]
        elif row["kind"] == "paired_normal":
            expected_ids = prompt["normal_class_ids"]
        else:
            expected_ids = prompt["class_ids"]
        if not expected_ids:
            raise EvidenceError(f"Unresolved classifier labels for {row['prompt_id']}.")
        return row["vit_class"] in expected_ids

    def _image_group(self, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        n = len(rows)
        successes = sum(self._correct(row) for row in rows)
        return {"successes": successes, "n": n,
                "rate": successes / n if n else None,
                "clip_mean": math.fsum(float(row["clip_score"]) for row in rows) / n if n else None}

    def _cell(self, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        kinds = {kind: [row for row in rows if row["kind"] == kind] for kind in KINDS}
        normal = kinds["paired_normal"] + kinds["extra_normal"]
        if not normal or len(kinds["paired_normal"]) != len(kinds["extra_normal"]):
            raise EvidenceError("Normal groups must both be present with the pre-registered equal sample count.")
        return {"ASR": self._image_group(kinds["triggered"]),
                "normal": self._image_group(normal),
                "paired_normal": self._image_group(kinds["paired_normal"]),
                "extra_normal": self._image_group(kinds["extra_normal"]),
                "independent_trigger_prompt_clusters": len({row["prompt_id"] for row in kinds["triggered"]}),
                "image_count": len(rows)}

    def aggregate(self, checked: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
        groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
        for row in checked:
            groups[(row["candidate"], row["state"])].append(row)
        result: dict[str, dict[str, Any]] = {}
        for (candidate, state), rows in sorted(groups.items()):
            result.setdefault(candidate, {})[state] = self._cell(rows)
            result[candidate][state]["per_seed"] = {
                str(seed): self._cell([row for row in rows if row["seed"] == seed])
                for seed in sorted({row["seed"] for row in rows})}
        return result

    def _report(self, stage: str, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        # Sorting makes the evidence digest independent of JSONL arrival order.
        normalized = [{key: row[key] for key in (*KEY_FIELDS, "vit_class", "clip_score", "protocol_sha256")}
                      for row in sorted(records, key=lambda r: tuple(r[k] for k in KEY_FIELDS))]
        return {"stage": stage, "protocol_sha256": self.sha,
                "input_image_count": len(records), "scored_records_sha256": _canonical_hash(normalized),
                "metrics": self.aggregate(records), "formal_FID_evaluated": False,
                "statistical_significance_or_SOTA_certified": False}

    def source_gate(self, records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        checked = self.validate_records("source", records)
        report = self._report("source_gate", checked)
        clean = report["metrics"]["clean"]["upload"]
        bd = report["metrics"]["original_backdoor"]["upload"]
        spec = self.p["source_gate"]
        gates = {
            "clean_normal_accuracy": clean["normal"]["rate"] >= spec["clean_normal_accuracy_min"],
            "backdoor_ASR": bd["ASR"]["rate"] >= spec["backdoor_ASR_min"],
            "backdoor_normal_accuracy": clean["normal"]["rate"] - bd["normal"]["rate"] <= spec["backdoor_normal_accuracy_drop_vs_clean_max"],
            "backdoor_normal_clip": clean["normal"]["clip_mean"] - bd["normal"]["clip_mean"] <= spec["backdoor_normal_clip_drop_vs_clean_max"],
        }
        report.update(gates=gates, passed=all(gates.values()),
                      status="passed" if all(gates.values()) else "stop_source_case",
                      budget_bucket="source_gate_extra_48_not_main_1664")
        return report

    def _responses(self, summary: Mapping[str, Any], expected_candidates: Sequence[str]) -> dict[str, Any]:
        if not isinstance(summary, Mapping) or summary.get("protocol_sha256") != self.sha:
            raise EvidenceError("Response summary does not match the frozen protocol.")
        unit_ids = summary.get("unit_ids")
        if (not isinstance(unit_ids, list) or len(unit_ids) != 24
                or not all(isinstance(value, str) for value in unit_ids)
                or set(unit_ids) != set(self.unit_ids)):
            raise EvidenceError("Response summary must identify all 24 distinct fixed training units.")
        rms = _number(summary.get("B_star_rms"), "B_star_rms")
        candidates = summary.get("candidates")
        if not isinstance(candidates, Mapping) or set(candidates) != set(expected_candidates):
            raise EvidenceError("Response candidate set is missing, extra or not appropriate for this stage.")
        cleaned = {}
        for name, response in candidates.items():
            if not isinstance(response, Mapping):
                raise EvidenceError(f"Response for {name} must be an object.")
            if _count(response.get("per_state_unit_count"), f"{name}.per_state_unit_count") != 24:
                raise EvidenceError(f"Response for {name} is not a full 24-unit cache average.")
            normal = response.get("normal_mse")
            backdoor = response.get("backdoor_mse")
            if not isinstance(normal, Mapping) or set(normal) != set(self.normal_states):
                raise EvidenceError(f"Wrong normal response states for {name}.")
            if not isinstance(backdoor, Mapping) or set(backdoor) != set(self.dev_states):
                raise EvidenceError(f"Wrong backdoor response states for {name}.")
            cleaned[name] = {
                "normal_mse": {state: _number(v, f"{name}.{state}.normal") for state, v in normal.items()},
                "backdoor_mse": {state: _number(v, f"{name}.{state}.backdoor") for state, v in backdoor.items()},
                "delta_l2": _number(response.get("delta_l2"), f"{name}.delta_l2"),
            }
            cleaned[name]["R"] = max(cleaned[name]["backdoor_mse"].values())
        return {"B_star_rms": rms, "candidates": cleaned, "response_summary_sha256": _canonical_hash(summary)}

    def _response_normal_gate(self, response: Mapping[str, Any], naive: Mapping[str, Any]) -> dict[str, Any]:
        states = {}
        for state in self.normal_states:
            candidate_rms = math.sqrt(response["normal_mse"][state])
            naive_rms = math.sqrt(naive["normal_mse"][state])
            limit = max(naive_rms, 1e-6) + 1e-6
            states[state] = {"candidate_rms": candidate_rms, "naive_rms": naive_rms,
                             "limit": limit, "passed": candidate_rms <= limit}
        return {"passed": all(x["passed"] for x in states.values()), "states": states}

    def _utility_gate(self, candidate: Mapping[str, Any], clean: Mapping[str, Any],
                      states: Sequence[str]) -> dict[str, Any]:
        spec = self.p["candidate_selection"]
        result = {}
        for state in states:
            acc_drop = clean[state]["normal"]["rate"] - candidate[state]["normal"]["rate"]
            clip_drop = clean[state]["normal"]["clip_mean"] - candidate[state]["normal"]["clip_mean"]
            acc_ok = acc_drop <= spec["normal_ACC_drop_vs_matched_clean_max"]
            clip_ok = clip_drop <= spec["normal_CLIP_drop_vs_matched_clean_max"]
            result[state] = {"normal_ACC_drop": acc_drop, "normal_CLIP_drop": clip_drop,
                             "ACC_passed": acc_ok, "CLIP_passed": clip_ok, "passed": acc_ok and clip_ok}
        return {"passed": all(x["passed"] for x in result.values()), "states": result}

    def static_screen(self, records: Iterable[Mapping[str, Any]], summary: Mapping[str, Any]) -> dict[str, Any]:
        checked = self.validate_records("screen", records)
        response = self._responses(summary, self.static)
        report = self._report("static_proxy_screen", checked)
        report["response_summary_sha256"] = response["response_summary_sha256"]
        report["B_star_rms"] = response["B_star_rms"]
        metrics, responses = report["metrics"], response["candidates"]
        gates, stop_reasons = {}, []
        if response["B_star_rms"] <= self.p["loss"]["fit_response_signal_rms_min_exclusive"]:
            stop_reasons.append({"reason": "unidentifiable_proxy_signal"})
        for candidate in self.static:
            normal = self._response_normal_gate(responses[candidate], responses["naive"])
            utility = self._utility_gate(metrics[candidate], metrics["matched_clean"], self.normal_states)
            gates[candidate] = {"response_normal": normal, "image_utility": utility,
                                "R": responses[candidate]["R"],
                                "minimum_development_ASR": min(metrics[candidate][s]["ASR"]["rate"] for s in self.dev_states)}
            for state, result in utility["states"].items():
                threshold = self.p["static_proxy_screen"]["normal_proxy_false_pass_stop"]["normal_ACC_drop_vs_matched_clean_at_least"]
                if result["normal_ACC_drop"] >= threshold and normal["passed"]:
                    stop_reasons.append({"reason": "normal_proxy_false_pass", "candidate": candidate, "state": state})
        # Qualification here is actual image utility, so a poor proxy gate cannot
        # hide a counterexample to the proxy's ordering of usable static models.
        qualified = [name for name in self.static if gates[name]["image_utility"]["passed"]]
        reversal = self.p["static_proxy_screen"]["reversed_ranking_stop"]
        for better_r in qualified:
            for worse_r in qualified:
                left, right = gates[better_r], gates[worse_r]
                if better_r == worse_r or right["R"] <= 0:
                    continue
                if (left["R"] <= (1.0 - reversal["relative_R_improvement_at_least"]) * right["R"]
                        and left["minimum_development_ASR"] <= right["minimum_development_ASR"] - reversal["minimum_development_ASR_drop_at_least"]):
                    stop_reasons.append({"reason": "proxy_ASR_ranking_reversal",
                                         "lower_R_candidate": better_r, "higher_R_candidate": worse_r})
        report.update(candidate_gates=gates, stop_reasons=stop_reasons, passed=not stop_reasons,
                      screening_information_sufficient=len(qualified) >= 2,
                      status="stop_proxy_failure" if stop_reasons else (
                          "screen_passed" if len(qualified) >= 2 else "screening_information_insufficient"))
        return report

    def select_candidates(self, records: Iterable[Mapping[str, Any]], summary: Mapping[str, Any]) -> dict[str, Any]:
        checked = self.validate_records("select", records)  # rejects every test row
        response = self._responses(summary, self.all_candidates)
        report = self._report("development_selection", checked)
        report["response_summary_sha256"] = response["response_summary_sha256"]
        report["selection_data_split"] = "val"
        report["heldout_used_for_selection"] = False
        report["B_star_rms"] = response["B_star_rms"]
        metrics, responses = report["metrics"], response["candidates"]
        signal_ok = response["B_star_rms"] > self.p["loss"]["fit_response_signal_rms_min_exclusive"]
        candidates = {}
        rc_pool = set(self.p["candidate_selection"]["pools"]["RC-TSSA-GD"])
        for name in self.all_candidates:
            normal = self._response_normal_gate(responses[name], responses["naive"])
            utility = self._utility_gate(metrics[name], metrics["matched_clean"], self.normal_states)
            rates = [metrics[name][state]["ASR"]["rate"] for state in self.dev_states]
            r_ok = (name not in rc_pool or responses[name]["R"] <=
                    self.p["candidate_selection"]["new_method_R_relative_max_vs_naive"] * responses["naive"]["R"])
            candidates[name] = {
                "candidate_id": self.candidate_ids[name], "normal_response_gate": normal,
                "image_utility_gate": utility, "new_method_R_gate": r_ok,
                "qualified": signal_ok and normal["passed"] and utility["passed"] and r_ok,
                "minimum_development_ASR": min(rates), "mean_development_ASR": math.fsum(rates) / len(rates),
                "R": responses[name]["R"], "delta_l2": responses[name]["delta_l2"],
            }
        def ranking_key(name: str) -> tuple[float, ...]:
            item = candidates[name]
            return (-item["minimum_development_ASR"], -item["mean_development_ASR"],
                    item["R"], item["delta_l2"], item["candidate_id"])
        selected: dict[str, str | None] = {"naive": "naive"}
        ranked = {}
        for family in ("Uniform", "TSSA", "RC-TSSA-GD"):
            valid = [name for name in self.p["candidate_selection"]["pools"][family] if candidates[name]["qualified"]]
            ranked[family] = sorted(valid, key=ranking_key)
            selected[family] = ranked[family][0] if ranked[family] else None
        if not signal_ok:
            status = "stop_unidentifiable_proxy_signal"
        elif selected["RC-TSSA-GD"] is None:
            status = "failed_no_qualified_RC_candidate"
        elif selected["Uniform"] is None or selected["TSSA"] is None:
            status = "ready_with_missing_qualified_controls"
        else:
            status = "ready_for_heldout"
        report.update(candidate_table=candidates, ranked_qualified_candidates=ranked,
                      selected_checkpoint_candidates=selected, status=status,
                      passed=signal_ok and selected["RC-TSSA-GD"] is not None,
                      frozen_before_heldout=True)
        report["selection_sha256"] = _canonical_hash(report)
        return report

    def _check_selection(self, selection: Mapping[str, Any] | None) -> None:
        if not isinstance(selection, Mapping):
            raise EvidenceError("Held-out reporting requires a frozen development selection artifact.")
        if (selection.get("stage") != "development_selection" or selection.get("protocol_sha256") != self.sha
                or selection.get("selection_data_split") != "val" or selection.get("heldout_used_for_selection") is not False
                or selection.get("frozen_before_heldout") is not True or not selection.get("passed")):
            raise EvidenceError("Selection is invalid, failed, or not exclusively based on development evidence.")
        payload = {key: value for key, value in selection.items() if key != "selection_sha256"}
        if selection.get("selection_sha256") != _canonical_hash(payload):
            raise EvidenceError("Frozen selection artifact was changed after its selection digest was computed.")
        chosen = selection.get("selected_checkpoint_candidates")
        if not isinstance(chosen, Mapping) or set(chosen) != {"naive", "Uniform", "TSSA", "RC-TSSA-GD"}:
            raise EvidenceError("Frozen selection has an invalid family set.")
        if chosen["naive"] != "naive" or chosen["RC-TSSA-GD"] is None:
            raise EvidenceError("A naive reference and a qualified RC candidate are required.")
        for family, name in chosen.items():
            if name is not None and name not in self.p["candidate_selection"]["pools"][family]:
                raise EvidenceError(f"Frozen {family} candidate is outside its registered pool.")

    def heldout_report(self, records: Iterable[Mapping[str, Any]], selection: Mapping[str, Any]) -> dict[str, Any]:
        checked = self.validate_records("heldout", records, selection)
        report = self._report("heldout_report", checked)
        metrics = report["metrics"]
        selected = dict(selection["selected_checkpoint_candidates"])
        frozen = {family: name for family, name in selected.items() if name is not None}
        family_metrics = {}
        for family, candidate in frozen.items():
            rates = [metrics[candidate][state]["ASR"]["rate"] for state in self.hold_states]
            family_metrics[family] = {
                "candidate": candidate, "minimum_heldout_ASR": min(rates),
                "mean_heldout_ASR": math.fsum(rates) / len(rates),
                "normal_utility_gate": self._utility_gate(metrics[candidate], metrics["matched_clean"], self.hold_states),
            }
        rc = selected["RC-TSSA-GD"]
        assert rc is not None
        comparisons = {}
        for family in ("naive", "Uniform", "TSSA"):
            control = selected[family]
            if control is None:
                comparisons[family] = {"available": False, "reason": "no_qualified_development_candidate"}
                continue
            comparisons[family] = {"available": True, "control_candidate": control,
                "states": {state: {
                    "ASR_difference": metrics[rc][state]["ASR"]["rate"] - metrics[control][state]["ASR"]["rate"],
                    "normal_ACC_difference": metrics[rc][state]["normal"]["rate"] - metrics[control][state]["normal"]["rate"],
                    "normal_CLIP_difference": metrics[rc][state]["normal"]["clip_mean"] - metrics[control][state]["normal"]["clip_mean"],
                } for state in self.hold_states}}
        report.update(selection_sha256=selection["selection_sha256"], selected_checkpoint_candidates=selected,
                      family_metrics=family_metrics, RC_vs_controls=comparisons, retuning_performed=False,
                      status="completed_with_missing_qualified_controls" if any(v is None for v in selected.values()) else "heldout_evaluated",
                      conclusion="Descriptive held-out evidence only; cell-level success counts, prompt clusters and utility limits remain authoritative.")
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--records", required=True, help="Already-scored per-image JSONL; never synthesized by this tool")
    parser.add_argument("--stage", choices=("source", "screen", "select", "heldout"), required=True)
    parser.add_argument("--responses", help="Required for screen/select")
    parser.add_argument("--selection", help="Frozen selection JSON, required for heldout")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    evaluator = MVPEvaluator.from_file(args.protocol)
    rows = read_jsonl(args.records)
    if args.stage in ("screen", "select"):
        if not args.responses:
            parser.error("--responses is required for screen/select")
        response = json.loads(Path(args.responses).read_text(encoding="utf-8"))
        report = evaluator.static_screen(rows, response) if args.stage == "screen" else evaluator.select_candidates(rows, response)
    elif args.stage == "heldout":
        if not args.selection:
            parser.error("--selection is required for heldout")
        selection = json.loads(Path(args.selection).read_text(encoding="utf-8"))
        report = evaluator.heldout_report(rows, selection)
    else:
        report = evaluator.source_gate(rows)
    output = Path(args.output)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8") as stream:
            stream.write(serialized)
    except FileExistsError as error:
        raise EvidenceError(f"Refusing to overwrite an existing evaluation artifact: {output}") from error
    print(json.dumps({"status": report["status"], "output": str(output), "protocol_sha256": evaluator.sha}))
    if report.get("passed") is False:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
