"""Pre-registered source and merge confirmation with authenticated gates."""
from __future__ import annotations

import json

from evidence import CLASSES, VERSIONS
from generation import run_image
from preflight import FrozenPlan
from selection_audit import verify_selection


def run_confirmation(plan, runtime, bindings, image_ledger, localization_ledger, scorer, image_dir):
    """Run baselines first, then conditional versions, without changing plans."""
    from tssa_mvp_score import IndependentScorer

    if not isinstance(plan, FrozenPlan) or plan.run_id != bindings.run_id or plan.manifest_sha != bindings.manifest_sha:
        raise ValueError("confirmation requires the same reviewed frozen plan")
    if image_ledger.bindings is not bindings:
        raise ValueError("confirmation ledger must use the authenticated bindings")
    if not isinstance(scorer, IndependentScorer) or scorer.root != runtime.assets.models_root.resolve():
        raise ValueError("confirmation requires the pinned independent offline scorer")
    localize = [row["id"] for row in plan.rows if row["partition"] == "localize"]
    verification = verify_selection(runtime, bindings, localization_ledger, localize)

    def execute(state, versions):
        for version in versions:
            for category in CLASSES:
                for context in sorted(image_ledger.ids[state]):
                    key = (state, context, category)
                    row = json.loads(bindings.prompt_rows[key])
                    for seed in bindings.seeds:
                        run_image(runtime, scorer, image_ledger, image_dir, state, version, category,
                                  context, seed, bindings.input_hashes[key], bindings.mask_hashes[version],
                                  row["prompt"], row["score_prompt"], row["tokenization"])

    execute("source", ("clean", "backdoor"))
    source_baseline = image_ledger.evaluate_gate("source_baseline", image_dir)
    if source_baseline["value"] != "pass":
        return {"outcome": "inconclusive", "reason": "source_baseline_ineligible", "merge": "skipped",
                "selection": verification, "source_baseline": source_baseline}
    execute("source", VERSIONS[2:])
    source_result = image_ledger.evaluate_gate("source_result", image_dir)
    if source_result["value"] != "pass":
        reason = source_result["result"]["decision"]["reason"]
        return {"outcome": "inconclusive" if reason == "no_eligible_amplitude" else "negative", "reason": reason,
                "merge": "skipped", "selection": verification, "source_baseline": source_baseline, "source_result": source_result}
    execute("merge", ("clean", "backdoor"))
    merge_baseline = image_ledger.evaluate_gate("merge_baseline", image_dir)
    if merge_baseline["value"] != "pass":
        return {"outcome": "inconclusive", "reason": "merge_baseline_ineligible", "merge": "skipped_after_baseline",
                "selection": verification, "source_baseline": source_baseline, "source_result": source_result, "merge_baseline": merge_baseline}
    execute("merge", VERSIONS[2:])
    merge_result = image_ledger.evaluate_gate("merge_result", image_dir)
    reason = merge_result["result"]["decision"]["reason"]
    return {"outcome": "positive" if merge_result["value"] == "pass" else "inconclusive" if reason == "no_eligible_amplitude" else "negative",
            "reason": reason, "merge": "completed",
            "selection": verification, "source_baseline": source_baseline, "source_result": source_result,
            "merge_baseline": merge_baseline, "merge_result": merge_result}
