"""Normalize the member /api/me response without granting GPU permission.

Only documented front-end fields and observed API fields are consumed. Unknown
or historical observations must never become an empty, available GPU.
"""
from __future__ import annotations

from collections import Counter
import math
import re
from typing import Any


STATUS_LABELS = {
    "free": "空闲", "mine": "本人使用", "others": "他人使用",
    "shared": "共同使用", "disabled": "禁用", "stale": "过期",
    "unknown": "未知", "fault": "故障",
}
METRICS = ("memory_used", "memory_total", "utilization_gpu", "temperature",
           "power_draw", "power_limit", "utilization_memory", "fan_speed")
GPU_UUID = re.compile(r"GPU-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.I)


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value if math.isfinite(value) else None
    return None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _clean(value: Any) -> Any:
    """Keep JSON types, replacing nonfinite floats rather than emitting NaN."""
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _age(stamp: Any, now: float) -> float | None:
    stamp = _number(stamp)
    if stamp is None or stamp <= 0 or stamp > now + 30:
        return None
    return max(0.0, now - stamp)


def _maintenance(items: list, host_id: str | None, index: Any, now: float) -> bool:
    for item in items:
        if not isinstance(item, dict) or item.get("host_id") != host_id:
            continue
        status = item.get("status")
        start = _number(item.get("start_at"))
        if status not in ("active", "checking") and not (
            status == "scheduled" and start is not None and start <= now
        ):
            continue
        details = item.get("details")
        indexes = details.get("gpu_indexes") if isinstance(details, dict) else None
        # An active maintenance record with an unreadable scope is not free.
        if not isinstance(indexes, list) or not indexes or index in indexes:
            return True
    return False


def normalize(payload: dict, *, fetched_at: float, now: float, source: str,
              cache_state: str, max_sample_age: float = 120) -> dict:
    """Return a stable, JSON-serializable observation, raising on invalid roots.

    ``fresh`` is a new HTTP result; ``cached`` is an explicitly reusable cache.
    Other cache states preserve observations as stale. Timestamps are Unix
    seconds; metric units match the API (MiB, percent, degrees C, watts).
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("hosts"), list):
        raise ValueError("平台响应缺少 hosts 数组")
    if not _text(payload.get("username")):
        raise ValueError("平台响应缺少登录账号")
    if (_number(now) is None or _number(fetched_at) is None
            or _number(max_sample_age) is None or max_sample_age <= 0):
        raise ValueError("查询时间和采样有效期必须是有效数值")
    cache_age = max(0.0, now - fetched_at)
    cache_valid = (cache_state in ("fresh", "cached") and fetched_at <= now + 30
                   and cache_age <= max_sample_age)
    maintenance = payload.get("maintenance")
    maintenance = maintenance if isinstance(maintenance, list) else []
    account = {key: _clean(payload.get(key)) for key in (
        "username", "role", "registered", "usage", "limit", "quota", "active_ban")}
    hosts = []
    counts = Counter({key: 0 for key in STATUS_LABELS})
    for raw in payload["hosts"]:
        if not isinstance(raw, dict):
            raise ValueError("平台 hosts 含非对象记录")
        host_id = _text(raw.get("id")) or _text(raw.get("host_id"))
        sampled_at = raw.get("gpu_sampled_at")
        if sampled_at is None:
            sampled_at = raw.get("sampled_at")
        sample_age = _age(sampled_at, now)
        sample_clock_skew = (max(0.0, sampled_at - now)
                             if _number(sampled_at) is not None else None)
        server_age = _number(raw.get("age_seconds"))
        if sample_age is not None and server_age is not None and server_age >= 0:
            sample_age = max(sample_age, server_age + cache_age)
        proc_age = _age(raw.get("processes_sampled_at"), now)
        issues = []
        if not host_id:
            issues.append("服务器身份缺失")
        if raw.get("online") is not True:
            issues.append("服务器离线或在线状态未知")
        if sample_age is None:
            issues.append("GPU采样时间缺失或无效")
        if proc_age is None:
            issues.append("进程采样时间缺失或无效")
        stale = (not cache_valid or raw.get("online") is False
                 or raw.get("gpu_data_stale") is True
                 or (sample_age is not None and sample_age > max_sample_age)
                 or (proc_age is not None and proc_age > max_sample_age))
        if stale:
            issues.append("缓存、GPU或进程采样已过期")
        if raw.get("processes_complete") is not True:
            issues.append("进程列表采样不完整")
        if raw.get("process_state_complete") is not True:
            issues.append("进程状态采样不完整")
        if raw.get("process_error"):
            issues.append("进程查询异常")
        if raw.get("gpu_error"):
            issues.append("GPU查询异常")
        if raw.get("gpu_sample_pending"):
            issues.append("GPU采样尚未完成")
        raw_gpus = raw.get("gpus")
        if not isinstance(raw_gpus, list):
            issues.append("GPU列表缺失或无效")
            raw_gpus = []
        raw_processes = raw.get("processes")
        if not isinstance(raw_processes, list):
            issues.append("进程列表缺失或无效")
            raw_processes = []
        gpu_uuids = [_text(g.get("uuid")) for g in raw_gpus if isinstance(g, dict)]
        if len(set(gpu_uuids)) != len(gpu_uuids):
            issues.append("GPU UUID重复")
        by_uuid: dict[str, list] = {}
        for proc in raw_processes:
            if not isinstance(proc, dict) or not _text(proc.get("gpu_uuid")):
                issues.append("存在无法关联GPU的进程")
                continue
            uuid = proc["gpu_uuid"]
            if uuid not in gpu_uuids:
                issues.append("进程引用未采样GPU")
            by_uuid.setdefault(uuid, []).append(proc)
        inventory = raw.get("gpu_inventory")
        faults = ([g for g in inventory if isinstance(g, dict)
                   and g.get("sampling_available") is False]
                  if raw.get("gpu_inventory_complete") is True
                  and isinstance(inventory, list) else [])
        expected = _number(raw.get("expected_gpu_count"))
        expected = int(expected) if expected is not None and expected >= 0 and expected == int(expected) else None
        missing = max(0, (expected or 0) - len(raw_gpus) - len(faults))
        if missing:
            issues.append("GPU采样数量少于预期")
        gpus = []
        for gpu in raw_gpus + faults:
            if not isinstance(gpu, dict):
                gpu = {}
            uuid = _text(gpu.get("uuid"))
            processes = []
            for proc in by_uuid.get(uuid, []):
                user = _text(proc.get("user")) or "unknown"
                own = proc.get("own") is True or user == payload["username"]
                processes.append({"user": user, "own": own, **{
                    key: _clean(proc.get(key)) for key in (
                        "gpu_uuid", "memory_used", "started_at", "state", "process_missing")}})
            users = sorted({p["user"] for p in processes})
            observed_status = None
            if processes:
                observed_status = ("unknown" if "unknown" in users else "shared" if len(users) > 1
                                   else "mine" if all(p["own"] for p in processes) else "others")
            reasons = list(dict.fromkeys(issues))
            mode = _text(gpu.get("compute_mode"))
            metrics = {k: _number(gpu.get(k)) for k in METRICS}
            memory_used, memory_total, utilization = (
                metrics["memory_used"], metrics["memory_total"], metrics["utilization_gpu"])
            metrics_valid = (memory_used is not None and memory_total is not None
                             and 0 <= memory_used <= memory_total and memory_total > 0
                             and utilization is not None and 0 <= utilization <= 100)
            if not uuid or not GPU_UUID.fullmatch(uuid):
                reasons.append("完整GPU UUID缺失")
            index = gpu.get("index")
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                reasons.append("GPU编号缺失或无效")
            if mode is None or mode.lower() not in (
                    "default", "exclusive_process", "exclusive_thread", "exclusive process", "exclusive thread", "prohibited"):
                reasons.append("计算模式未知")
            if not metrics_valid:
                reasons.append("显存或利用率指标缺失或无效")
            maintained = _maintenance(maintenance, host_id, gpu.get("index"), now)
            if (mode and mode.lower() == "prohibited") or maintained:
                status = "disabled"
                reasons.append("维护中" if maintained else "计算模式为Prohibited")
            elif gpu.get("sampling_available") is False or raw.get("gpu_error"):
                status = "fault"
                reasons.append(_text(gpu.get("sampling_error")) or "GPU采样故障")
            elif stale:
                status = "stale"
            elif reasons:
                status = "unknown"
            elif processes:
                if "unknown" in users:
                    status = "unknown"
                    reasons.append("进程属主未知")
                elif len(users) > 1:
                    status = "shared"
                else:
                    status = "mine" if all(p["own"] for p in processes) else "others"
            elif utilization > 5 or memory_used > 256:
                status = "unknown"
                reasons.append("无已知进程但存在资源占用")
            else:
                status = "free"
            counts[status] += 1
            gpus.append({
                **{k: _clean(gpu.get(k)) for k in ("index", "name", "bus_id")},
                "uuid": uuid, "compute_mode": mode, **metrics,
                "status": status, "status_label": STATUS_LABELS[status],
                "observed_status": observed_status,
                "reasons": reasons, "users": users, "processes": processes,
                "own": any(p["own"] for p in processes),
                "sampled_at": _number(sampled_at), "sample_age_seconds": sample_age,
                "sample_clock_skew_seconds": sample_clock_skew,
            })
        hosts.append({
            "id": host_id, "label": _text(raw.get("label")) or host_id,
            "group": _text(raw.get("group")), "online": raw.get("online") is True,
            "sampled_at": _number(sampled_at), "received_at": _number(raw.get("received_at")),
            "sample_age_seconds": sample_age,
            "sample_clock_skew_seconds": sample_clock_skew,
            "process_sample_age_seconds": proc_age,
            "processes_complete": raw.get("processes_complete") is True,
            "process_state_complete": raw.get("process_state_complete") is True,
            "expected_gpu_count": expected, "reported_gpu_count": len(gpus),
            "unreported_gpu_count": missing, "issues": list(dict.fromkeys(issues)), "gpus": gpus,
        })
    return {
        "schema_version": 1, "fetched_at": fetched_at, "cache_age_seconds": cache_age,
        "source": source, "cache_state": cache_state, "account": account,
        "policy": {"rules": _clean(payload.get("rules")),
                   "maintenance": _clean(maintenance), "gpu_requests": _clean(payload.get("gpu_requests")),
                   "rectifications": _clean(payload.get("rectifications")),
                   "cases": _clean(payload.get("cases")),
                   "query_is_authorization": False},
        "hosts": hosts,
        "summary": {"hosts": len(hosts), "total_gpus": sum(counts.values()),
                    "status_counts": dict(counts),
                    **{f"{k}_gpus": v for k, v in counts.items()},
                    "unreported_gpus": sum(h["unreported_gpu_count"] for h in hosts)},
    }
