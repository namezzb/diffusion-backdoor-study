"""Verify immutable v1 source copies and a fresh, process-bound v2 GPU permit.

These are admission checks, not a licence to retry an unknown v2 writer. A
reviewed bundle pins the proof digest; observations remain operator evidence,
not a claim that an inaccessible legacy machine has stopped.

Isolation schema (version 1): run_id, parent_run_id, mode, parent_manifest ref,
parent_code_root, context_ids ref, old_output_roots [{server,path}], snapshot_root,
output_root, source_writer_state='unknown', legacy_occupancy_bound ref, freeze
{source_imports,merge_imports,no_reuse_reason,late_parent_results='not_admitted'},
copies [{role,path,sha256,origin:{server,path,sha256}}], imports []. Required copy
roles are selection, localization_terminal, localization_ledger, and mask:<name>
for all eight masks. A ref is exactly {path,sha256}. All copies are byte copies
with no write permission bits, no hardlinks, no symlink ancestry and no SQLite
sidecars. Imports additionally bind an actual copied complete v1 ledger row;
see _validate_imports for the deliberately explicit record schema.

Permission schema: run_id, manifest_sha256, assignment_sha256, worker_id, server,
gpu_uuid, observed_at_utc, expires_at_utc, allowed, launcher {pid,uid,start_ticks},
effective_gpu_cap, other_or_unknown_occupied_gpus, approved_gpu_uuids,
platform_evidence ref, probe_evidence ref. Validation precedes CUDA in the same
supervised launch family. A resident, already admitted runtime does not need
this cold-start check before every forward or every stage.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import socket
import sqlite3
import stat
import subprocess
import xml.etree.ElementTree as ET

from pilot24_inputs import RUN, PARENT, SEED, VERSIONS, CLASSES

UTC = timezone.utc
PARENT_MANIFEST_SHA256 = "c597deebc3c2256401ee89b47f96ba9caa4bd92502019e3f257cfde7cddd1aaa"
HISTORICAL_RECONCILIATION_SHA256 = "c79e26582268a4349a74059051127165443203d5116a9b0d47513b1e1092423b"
MAX_AGE_SECONDS = 120
UUID_RE = re.compile(r"GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
XORG_PATHS = {"/usr/lib/xorg/Xorg", "/usr/bin/Xorg", "/usr/libexec/Xorg"}
_READONLY_HASH_CACHE = {}
_SQLITE_CHECK_CACHE = set()


def _now():
    return datetime.now(UTC)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return _sha(json.dumps(value, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"), allow_nan=False).encode())


def _int(value, minimum=0):
    return type(value) is int and value >= minimum


def _path(value):
    if not isinstance(value, (str, Path)) or not str(value):
        raise ValueError("absolute ordinary path required")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("absolute canonical path required")
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlinked path or ancestry")
    return path


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            info.st_mode, info.st_nlink, info.st_uid, info.st_gid)


def _file(path, *, readonly=False, contents=True):
    path = _path(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError("ordinary file with no hardlinks required")
        if readonly and before.st_mode & 0o222:
            raise ValueError("snapshot copy must have no write permission bits")
        cached = _READONLY_HASH_CACHE.get(str(path))
        if readonly and not contents and cached is not None and cached[0] == _identity(before):
            if _identity(before) != _identity(path.stat()):
                raise ValueError("file changed during cached authentication")
            return None, cached[1]
        digest, chunks = hashlib.sha256(), []
        with os.fdopen(fd, "rb", closefd=False) as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                if contents:
                    chunks.append(chunk)
        after = os.fstat(fd)
        current = path.stat()
        if _identity(before) != _identity(after) or _identity(after) != _identity(current):
            raise ValueError("file changed during authentication")
        if readonly:
            _READONLY_HASH_CACHE[str(path)] = (_identity(after), digest.hexdigest())
        return (b"".join(chunks) if contents else None), digest.hexdigest()
    finally:
        os.close(fd)


def _read(path, *, readonly=False):
    return _file(path, readonly=readonly)[0]


def _ref(item, *, readonly=False, contents=True):
    if (not isinstance(item, dict) or set(item) != {"path", "sha256"}
            or not isinstance(item["sha256"], str) or not SHA_RE.fullmatch(item["sha256"])):
        raise ValueError("path and SHA256 reference required")
    raw, digest = _file(item["path"], readonly=readonly, contents=contents)
    if digest != item["sha256"]:
        raise ValueError("referenced content hash differs")
    return raw


def _json_ref(item, **kwargs):
    value = json.loads(_ref(item, **kwargs))
    if not isinstance(value, dict):
        raise ValueError("JSON object evidence required")
    return value


def _instant(value):
    if not isinstance(value, str):
        raise ValueError("UTC timestamp required")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset().total_seconds() != 0:
        raise ValueError("timestamp must be UTC")
    return result


def _disjoint(a, b):
    return not (a == b or a.is_relative_to(b) or b.is_relative_to(a))


def _sqlite(path, *, check=True):
    path = _path(path)
    if any(Path(str(path) + suffix).exists() or Path(str(path) + suffix).is_symlink()
           for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("snapshot must be a standalone SQLite backup")
    info = path.stat()
    if info.st_mode & 0o222 or info.st_nlink != 1:
        raise ValueError("sealed standalone SQLite copy required")
    identity = (str(path), _identity(info))
    hashed = _READONLY_HASH_CACHE.get(str(path), (None,))[0] == _identity(info)
    db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    db.execute("PRAGMA query_only=ON")
    if check and (not hashed or identity not in _SQLITE_CHECK_CACHE) and db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
        db.close()
        raise ValueError("invalid SQLite snapshot")
    if _identity(info) != _identity(path.stat()):
        db.close()
        raise ValueError("SQLite changed during verification")
    if check and hashed:
        _SQLITE_CHECK_CACHE.add(identity)
    return db


def _legacy_bound(ref):
    bound = _json_ref(ref)
    uuids = bound.get("gpu_uuids")
    if (bound.get("run_id") != PARENT or bound.get("server") != "school103"
            or not isinstance(uuids, list) or not uuids or len(set(uuids)) != len(uuids)
            or any(not isinstance(u, str) or not UUID_RE.fullmatch(u) for u in uuids)
            or not _int(bound.get("upper_bound"), 1) or bound["upper_bound"] != len(uuids)
            or bound["upper_bound"] > 4):
        raise ValueError("legacy occupancy needs a concrete single-device launch boundary")
    records = bound.get("launch_records")
    if not isinstance(records, list) or not records:
        raise ValueError("legacy launch records required")
    observed = set()
    for record in records:
        launch = _json_ref(record)
        if (launch.get("run_id") != PARENT or launch.get("gpu_uuid") not in uuids
                or launch.get("manifest_sha256") != PARENT_MANIFEST_SHA256):
            raise ValueError("legacy launch record does not bind run and GPU")
        observed.add(launch["gpu_uuid"])
    if observed != set(uuids):
        raise ValueError("legacy GPU upper bound lacks launch evidence")
    return bound


def _validate_imports(proof, copies, selection):
    """An import row binds key, origin_key, origin_attempt, ledger/image refs,
    input_sha256, mask_sha256, model_bundle_sha256, scorer_sha256 and scores.
    Model/scorer digests must also equal the enclosing freeze record; the runtime
    must match those digests to the actual prepared model/scorer identities.
    """
    frozen = proof.get("freeze")
    rows = proof.get("imports")
    if (not isinstance(frozen, dict) or not isinstance(rows, list)
            or not _int(frozen.get("source_imports")) or not _int(frozen.get("merge_imports"))
            or frozen.get("late_parent_results") != "not_admitted"):
        raise ValueError("explicit frozen import counts and cutoff policy required")
    if not rows and not (isinstance(frozen.get("no_reuse_reason"), str)
                         and frozen["no_reuse_reason"].strip()):
        raise ValueError("R=0 requires an explicit no-reuse reason")
    if rows:
        parent = _json_ref(proof["parent_manifest"])
        assets, code = parent["asset_sha256"], parent["code_sha256"]
        source_model = _digest(assets)
        # The pinned v1 main constructs IndependentScorer(device='cpu').
        source_scorer = _digest({"assets": {name: value for name, value in assets.items()
            if name.split('/')[0] in ("vit", "clip")}, "code": {name: code[name] for name in
            ("scripts/merging/tssa_mvp_score.py", "scripts/merging/tssa_sd_runtime.py")},
            "dtype": "float32", "device": "cpu", "image_source": "saved_rgb_png",
            "score_prompt": "untriggered_paired_prompt"})
        if frozen.get("model_bundle_sha256") != source_model or frozen.get("scorer_sha256") != source_scorer:
            raise ValueError("imported model/scorer does not match the actual pinned CPU v1 source")
    ids = _json_ref(proof["context_ids"])
    if ids.get("run_id") != RUN or ids.get("generation_seed") != SEED:
        raise ValueError("wrong frozen context identity")
    allowed = {"source": set(ids["source_context_ids"]), "merge": set(ids["merge_context_ids"])}
    counts = {"source": 0, "merge": 0}
    seen, origins, checked_ledgers = set(), set(), set()
    for row in rows:
        key, origin = tuple(row.get("key", ())), tuple(row.get("origin_key", ()))
        if (len(key) != 6 or key[0] != RUN or key[1] not in allowed
                or key[2] not in VERSIONS or key[3] not in CLASSES
                or key[4] not in allowed[key[1]] or key[5] != SEED
                or origin != (PARENT, *key[1:]) or key in seen
                or not _int(row.get("origin_attempt"), 1)):
            raise ValueError("invalid or duplicate imported unit")
        for name in ("input_sha256", "mask_sha256", "model_bundle_sha256", "scorer_sha256"):
            if not isinstance(row.get(name), str) or not SHA_RE.fullmatch(row[name]):
                raise ValueError("complete import provenance digests required")
        if (row["mask_sha256"] != selection["mask_sha256"][key[2]]
                or any(row[name] != frozen.get(name) for name in ("model_bundle_sha256", "scorer_sha256"))):
            raise ValueError("imported model/scorer/mask identity differs")
        for kind in ("ledger", "image"):
            ref = row[kind]
            if copies.get(str(_path(ref["path"]))) != ref["sha256"]:
                raise ValueError("import is not in the authenticated copied source package")
        origin_id = (row["ledger"]["sha256"], origin, row["origin_attempt"])
        if origin_id in origins:
            raise ValueError("duplicate historical attempt")
        db = _sqlite(row["ledger"]["path"], check=row["ledger"]["path"] not in checked_ledgers)
        try:
            meta = json.loads(db.execute("SELECT value FROM metadata WHERE id=1").fetchone()[0])
            selection_ref = next(item for item in proof["copies"] if item["role"] == "selection")
            if (meta.get("run_id") != PARENT or meta.get("manifest_sha") != proof["parent_manifest"]["sha256"]
                    or meta.get("selection_sha") != selection_ref["sha256"]):
                raise ValueError("import ledger metadata differs")
            saved = db.execute("SELECT status,input_sha,mask_sha,image_sha,scores FROM attempts WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=?", origin).fetchone()
            count = db.execute("SELECT COUNT(*) FROM attempt_history WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=?", origin).fetchone()[0]
            if (saved is None or saved[:4] != ("complete", row["input_sha256"], row["mask_sha256"], row["image"]["sha256"])
                    or json.loads(saved[4]) != row.get("scores") or row["origin_attempt"] != count + 1):
                raise ValueError("import is not the exact completed historical attempt")
        finally:
            db.close()
        checked_ledgers.add(row["ledger"]["path"])
        from PIL import Image
        with Image.open(row["image"]["path"]) as image:
            if image.format != "PNG" or image.size != (512, 512):
                raise ValueError("invalid imported PNG")
            image.load()
        seen.add(key)
        origins.add(origin_id)
        counts[key[1]] += 1
    if counts != {"source": frozen["source_imports"], "merge": frozen["merge_imports"]}:
        raise ValueError("frozen R differs from authenticated unique imports")


def validate_source_isolation(path, expected_sha256, *, output_root=None):
    """Validate actual copies without pretending the legacy writer has exited."""
    proof = _json_ref({"path": str(path), "sha256": expected_sha256})
    if (proof.get("schema_version") != 1 or proof.get("run_id") != RUN
            or proof.get("parent_run_id") != PARENT
            or proof.get("mode") != "immutable_snapshot_namespace_isolation"
            or proof.get("source_writer_state") != "unknown"):
        raise ValueError("reviewed immutable namespace isolation required")
    parent = _json_ref(proof["parent_manifest"])
    if (proof["parent_manifest"]["sha256"] != PARENT_MANIFEST_SHA256
            or parent.get("run_id") != PARENT):
        raise ValueError("wrong frozen v1 identity")
    code_root = _path(proof["parent_code_root"])
    sources = parent.get("code_sha256", {})
    prefix = "scripts/merging/trigger_contrast_localization/"
    if not {prefix + "main.py", prefix + "run_store.py", prefix + "resource_gate.py"} <= set(sources):
        raise ValueError("parent writing/device boundary code must be bound")
    for relative, sha in sources.items():
        rel = Path(relative)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("escaped parent code path")
        _ref({"path": str(code_root / rel), "sha256": sha})
    # The authenticated fixed parent implementation funnels writes through
    # prepare_run_root, whose exact run_id/output_root check is itself pinned.
    main = ast.parse(_read(code_root / (prefix + "main.py")))
    if not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "prepare_run_root" for n in ast.walk(main)):
        raise ValueError("parent main lacks its reviewed output-root boundary")
    snapshot, target = _path(proof["snapshot_root"]), _path(proof["output_root"])
    if not snapshot.is_dir() or snapshot.stat().st_mode & 0o222:
        raise ValueError("sealed readonly source directory required")
    if target.name != RUN or not _disjoint(snapshot, target):
        raise ValueError("independent v2 output root required")
    if output_root is not None and not _path(output_root).is_relative_to(target):
        raise ValueError("worker output escapes isolated v2 root")
    roots = proof.get("old_output_roots")
    if not isinstance(roots, list) or not roots:
        raise ValueError("legacy write roots required")
    if not any(r.get("server") == parent.get("server") and r.get("path") == parent.get("output_root") for r in roots):
        raise ValueError("actual parent output root must be excluded")
    for item in roots:
        if not isinstance(item.get("server"), str) or not item["server"]:
            raise ValueError("legacy root must identify its server")
        old = _path(item["path"])
        if not _disjoint(old, snapshot) or not _disjoint(old, target):
            raise ValueError("legacy/v2/snapshot roots overlap")
    entries = proof.get("copies")
    if not isinstance(entries, list) or not entries:
        raise ValueError("actual source copies are required, even when R=0")
    roles, copies = {}, {}
    for item in entries:
        copied = _path(item["path"])
        if not copied.is_relative_to(snapshot) or copied == snapshot:
            raise ValueError("copied source escapes snapshot root")
        if any(p.stat().st_mode & 0o222 for p in copied.parents if p == snapshot or p.is_relative_to(snapshot)):
            raise ValueError("snapshot directory ancestry must be readonly")
        role, origin = item.get("role"), item.get("origin")
        if (not isinstance(role, str) or not role or role in roles or str(copied) in copies
                or not isinstance(origin, dict) or not origin.get("server")
                or origin.get("sha256") != item.get("sha256")):
            raise ValueError("unique copied-source role and historical hash required")
        old = _path(origin["path"])
        if old == copied or old.is_relative_to(target):
            raise ValueError("copy origin cannot be the v2 destination")
        need_bytes = role in ("selection", "localization_terminal") or role.startswith("mask:")
        raw = _ref({"path": str(copied), "sha256": item["sha256"]}, readonly=True, contents=need_bytes)
        roles[role], copies[str(copied)] = (copied, raw), item["sha256"]
    if not {"selection", "localization_terminal", "localization_ledger"} <= set(roles):
        raise ValueError("copied localization sources required")
    selection = json.loads(roles["selection"][1])
    terminal = json.loads(roles["localization_terminal"][1])
    for item in (selection, terminal):
        if item.get("run_id") != PARENT or item.get("manifest_sha256") != proof["parent_manifest"]["sha256"]:
            raise ValueError("localization source identity differs")
    if selection.get("status") != "frozen" or terminal.get("phase") != "localize" or terminal.get("status") != "complete":
        raise ValueError("completed frozen localization required")
    for version in VERSIONS:
        role = "mask:" + version
        if role not in roles or _sha(roles[role][1]) != selection.get("mask_sha256", {}).get(version):
            raise ValueError("missing copied frozen mask")
        mask_path = roles["selection"][0].parent / selection["mask_files"][version]
        if _path(mask_path) != roles[role][0]:
            raise ValueError("selection mask path is not its authenticated copy")
    history = proof.get("historical_reconciliation")
    if (not isinstance(history, dict) or set(history) != {"path", "sha256"}
            or history["sha256"] != HISTORICAL_RECONCILIATION_SHA256
            or copies.get(history["path"]) != history["sha256"]
            or "historical_reconciliation" not in roles
            or str(roles["historical_reconciliation"][0]) != history["path"]):
        raise ValueError("pinned historical reconciliation copy required")
    observed = _json_ref(history)
    if (observed.get("manifest_sha256") != PARENT_MANIFEST_SHA256
            or observed.get("status") != "provisional_not_executable"
            or observed.get("charged_attempts") != len(observed.get("records", []))
            or observed["charged_attempts"] < 734):
        raise ValueError("historical reconciliation identity or accounting differs")
    db = _sqlite(roles["localization_ledger"][0])
    try:
        meta = json.loads(db.execute("SELECT value FROM metadata WHERE id=1").fetchone()[0])
        if meta.get("run_id") != PARENT or meta.get("manifest_sha") != proof["parent_manifest"]["sha256"]:
            raise ValueError("localization ledger identity differs")
    finally:
        db.close()
    _legacy_bound(proof["legacy_occupancy_bound"])
    _validate_imports(proof, copies, selection)
    return proof


def _host_identity():
    return {"hostname": socket.gethostname(), "machine_id_sha256": _sha(Path("/etc/machine-id").read_bytes()),
            "account_uid": os.geteuid()}


def _process_identity(pid):
    raw = (Path("/proc") / str(pid) / "stat").read_text()
    fields = raw[raw.rfind(")") + 2:].split()
    return {"pid": pid, "uid": (Path("/proc") / str(pid)).stat().st_uid,
            "start_ticks": int(fields[19]), "parent_pid": int(fields[1]), "state": fields[0]}


def _launcher(value):
    if (not isinstance(value, dict) or set(value) != {"pid", "uid", "start_ticks"}
            or not _int(value["pid"], 1) or not _int(value["uid"]) or not _int(value["start_ticks"], 1)):
        raise ValueError("launcher PID/UID/start ticks required")
    ancestor, found = os.getpid(), False
    for _ in range(128):
        live = _process_identity(ancestor)
        if ancestor == value["pid"]:
            found = True
            break
        if live["parent_pid"] <= 0 or live["parent_pid"] == ancestor:
            break
        ancestor = live["parent_pid"]
    if (not found or live["state"] in ("Z", "X") or live["uid"] != os.geteuid()
            or any(live[name] != value[name] for name in value)):
        raise ValueError("permission belongs to a different/dead launcher process")
    return {os.getpid(), value["pid"]}


def _system_xorg(pid, name, kind):
    if kind != "G" or Path(name).name != "Xorg":
        return False
    try:
        owners = {0}
        try:
            owners.add(pwd.getpwnam("gdm").pw_uid)
        except KeyError:
            pass
        process = Path("/proc") / str(pid)
        uid = process.stat().st_uid
        try:
            executable = process.joinpath("exe").resolve(strict=True)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EPERM):
                raise
            command = os.fsdecode(process.joinpath("cmdline").read_bytes().split(b"\0", 1)[0])
            if command not in XORG_PATHS:
                return False
            executable = Path(command).resolve(strict=True)
        info = executable.stat()
        return (uid in owners and str(executable) in XORG_PATHS and info.st_uid == 0
                and stat.S_ISREG(info.st_mode) and info.st_mode & stat.S_IXUSR and not info.st_mode & 0o022
                and process.stat().st_uid == uid)
    except (OSError, ValueError):
        return False


def _gpu(xml, uuid, own_pids):
    root = ET.fromstring(xml)
    matches = [g for g in root.findall("gpu") if g.findtext("uuid") == uuid]
    if root.tag != "nvidia_smi_log" or len(matches) != 1 or matches[0].findtext("compute_mode") != "Default":
        raise ValueError("GPU UUID or compute mode is not available")
    processes = matches[0].find("processes")
    if processes is None or (processes.text and processes.text.strip()):
        raise ValueError("GPU process inventory unavailable")
    for process in processes:
        pid = process.findtext("pid", "")
        name, kind = process.findtext("process_name", ""), process.findtext("type", "")
        if process.tag != "process_info" or not pid.isdigit():
            raise ValueError("ambiguous GPU process")
        pid = int(pid)
        if pid in own_pids and _process_identity(pid)["uid"] == os.geteuid():
            continue
        if not _system_xorg(pid, name, kind):
            raise ValueError("GPU contains another or unverified process")


def _live_gpu_xml():
    return subprocess.run(["nvidia-smi", "-q", "-x"], check=True, capture_output=True, timeout=15).stdout


def validate_worker_permission(prepared, permission_path, permission_sha):
    """Verify a fresh permit and actual local GPU state before first CUDA use."""
    permit = _json_ref({"path": str(permission_path), "sha256": permission_sha})
    assignment, bundle = prepared.assignment, prepared.bundle
    if (permit.get("run_id") != RUN or permit.get("manifest_sha256") != prepared.manifest_sha256
            or permit.get("assignment_sha256") != prepared.assignment_sha256 or permit.get("allowed") is not True
            or any(permit.get(k) != assignment.get(k) for k in ("worker_id", "server", "gpu_uuid"))):
        raise ValueError("permit does not bind this exact reviewed assignment")
    uuid = permit.get("gpu_uuid")
    if not isinstance(uuid, str) or not UUID_RE.fullmatch(uuid):
        raise ValueError("full GPU UUID required")
    now = _now()
    observed, expires = _instant(permit.get("observed_at_utc")), _instant(permit.get("expires_at_utc"))
    if not observed <= now < expires or not 0 < (expires - observed).total_seconds() <= MAX_AGE_SECONDS:
        raise ValueError("GPU startup permission expired or future-dated")
    own = _launcher(permit.get("launcher"))
    cap, other, approved = (permit.get(k) for k in ("effective_gpu_cap", "other_or_unknown_occupied_gpus", "approved_gpu_uuids"))
    if (not _int(cap, 1) or cap > 4 or not _int(other) or not isinstance(approved, list)
            or any(not isinstance(u, str) or not UUID_RE.fullmatch(u) for u in approved)
            or len(set(u.lower() for u in approved)) != len(approved) or uuid not in approved
            or len(approved) + other > cap):
        raise ValueError("aggregate known/unknown occupancy exceeds the effective GPU cap")
    isolation_ref = bundle["inputs"]["source_isolation"]
    isolation = validate_source_isolation(isolation_ref["path"], isolation_ref["sha256"],
                                          output_root=assignment.get("output_root"))
    bound = _legacy_bound(isolation["legacy_occupancy_bound"])
    if other < bound["upper_bound"] or set(bound["gpu_uuids"]) & set(approved):
        raise ValueError("unknown legacy GPU occupancy was not reserved")
    platform = _json_ref(permit["platform_evidence"])
    if (platform.get("source") != "https://gpu.orz2333.fun/"
            or any(platform.get(k) != permit[k] for k in ("effective_gpu_cap", "other_or_unknown_occupied_gpus", "approved_gpu_uuids"))):
        raise ValueError("platform observation does not support aggregate allocation")
    _ref(platform["raw_capture"])
    occupied = platform.get("other_occupancy")
    if not isinstance(occupied, list):
        raise ValueError("occupied GPU evidence required")
    total, legacy_present = 0, False
    for item in occupied:
        if not _int(item.get("count"), 1) or not isinstance(item.get("reason"), str) or not item["reason"]:
            raise ValueError("invalid occupied GPU evidence")
        _ref(item["evidence"])
        if item["evidence"] == isolation["legacy_occupancy_bound"]:
            if item["count"] != bound["upper_bound"]:
                raise ValueError("legacy occupancy count differs from evidence")
            legacy_present = True
        total += item["count"]
    if total != other or not legacy_present:
        raise ValueError("aggregate occupancy lacks concrete source evidence")
    cards = platform.get("gpus")
    if not isinstance(cards, list):
        raise ValueError("platform per-GPU observation required")
    for approved_uuid in approved:
        card = [c for c in cards if c.get("gpu_uuid") == approved_uuid]
        if (len(card) != 1 or card[0].get("disabled") is not False
                or card[0].get("sampling_valid") is not True or card[0].get("allocation_conflict") is not False
                or (approved_uuid == uuid and card[0].get("server") != assignment["server"])):
            raise ValueError("platform GPU permission is disabled, conflicting or unknown")
    probe = _json_ref(permit["probe_evidence"])
    host = _host_identity()
    if (probe.get("server") != assignment["server"] or probe.get("gpu_uuid") != uuid
            or any(probe.get(k) != v for k, v in host.items())):
        raise ValueError("probe belongs to another host, account or GPU")
    for evidence in (platform, probe):
        stamp = _instant(evidence.get("observed_at_utc"))
        if not stamp <= observed <= now or (now - stamp).total_seconds() > MAX_AGE_SECONDS:
            raise ValueError("platform or probe evidence is stale")
    _gpu(_ref(probe["raw_nvidia_smi_xml"]), uuid, own)
    _gpu(_live_gpu_xml(), uuid, own)
    if _now() >= expires:
        raise ValueError("permission expired during GPU checks")
    return permit
