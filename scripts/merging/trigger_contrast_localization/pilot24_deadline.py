"""Pure deadline decisions; the reviewed launcher must enforce them externally."""
from __future__ import annotations

from datetime import datetime, timezone
import math


def _utc(value):
    if not isinstance(value, str):
        raise ValueError("UTC timestamp is required")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset().total_seconds() != 0:
        raise ValueError("timestamp must explicitly use UTC")
    return result.astimezone(timezone.utc)


def deadline_state(t0_utc, now_utc, *, previous_observed_utc=None):
    t0, now = _utc(t0_utc), _utc(now_utc)
    previous = _utc(previous_observed_utc) if previous_observed_utc else t0
    if previous < t0 or now < previous:
        raise ValueError("time moved backwards or predates the fixed T0")
    elapsed = (now - t0).total_seconds()
    return {"elapsed_seconds": elapsed, "generation_permitted": elapsed < 22 * 3600,
            "compute_permitted": elapsed < 22.25 * 3600,
            "report_overdue": elapsed >= 24 * 3600,
            "feasibility_due": elapsed >= 2 * 3600}


def assess_throughput(t0_utc, now_utc, *, finished, by_worker, remaining_attempts, seconds_per_attempt):
    """Evaluate a measured plan; no extra images are authorized for timing."""
    state = deadline_state(t0_utc, now_utc)
    if (type(finished) is not int or finished < 0 or not isinstance(by_worker, dict)
            or any(type(v) is not int or v < 0 for v in by_worker.values())
            or type(remaining_attempts) is not int or remaining_attempts < 0
            or not isinstance(seconds_per_attempt, (int, float)) or isinstance(seconds_per_attempt, bool)
            or not math.isfinite(seconds_per_attempt) or seconds_per_attempt <= 0):
        raise ValueError("invalid throughput observation")
    if sum(by_worker.values()) != finished or not by_worker:
        raise ValueError("worker counts must reconcile to completed observations")
    # Caller must separately validate four-class coverage, active workers, and
    # that the estimate incorporates the measured parallel aggregate rate.
    eligible = finished >= 64 and all(v >= 16 for v in by_worker.values())
    estimated = remaining_attempts * seconds_per_attempt
    available = max(0, 22 * 3600 - state["elapsed_seconds"])
    return {**state, "sample_count_eligible": eligible, "class_coverage_verified": False,
            "estimated_remaining_seconds": estimated, "available_seconds": available,
            "capacity_sufficient_if_coverage_verified": estimated <= available if eligible else None,
            "decision": "requires_class_and_rate_validation" if eligible else "insufficient_throughput_samples"}
