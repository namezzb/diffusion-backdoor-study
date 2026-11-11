#!/usr/bin/env python3
"""Project adapter for an agent-driven autoresearch loop (Python standard library)."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
MARKER = "AUTORESEARCH_METRICS "


def git(work, *args):
    return subprocess.check_output(
        ["git", "-C", str(work), *args], text=True, stderr=subprocess.STDOUT
    ).strip()


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate(config):
    metric = config["metric"]
    if metric["direction"] not in ("min", "max") or not metric["name"]:
        raise ValueError("metric requires name and direction=min|max")
    if not number(metric.get("min_delta", 0)) or metric.get("min_delta", 0) < 0:
        raise ValueError("min_delta must be finite and nonnegative")
    for key in ("max_attempts", "max_seconds", "attempt_timeout"):
        if not number(config[key]) or config[key] <= 0:
            raise ValueError(f"{key} must be positive and finite")
    if type(config["max_attempts"]) is not int:
        raise ValueError("max_attempts must be an integer including baseline and failures")
    if config.get("compute") not in ("cpu", "managed_gpu"):
        raise ValueError("compute must be cpu or managed_gpu")
    for key in ("command", "guard", "cleanup"):
        value = config.get(key)
        required = key == "command" or config["compute"] == "managed_gpu"
        if required or value is not None:
            if not isinstance(value, list) or not value or not all(isinstance(x, str) and x for x in value):
                raise ValueError(f"{key} must be a nonempty argv list (no implicit shell)")
    for bound in config.get("constraints", []):
        if bound["op"] not in ("<=", ">=") or not number(bound["value"]):
            raise ValueError("constraint needs op <=|>= and a finite value")


def append(run, event):
    event.setdefault("time", time.time())
    title = f"{event['event']} · attempt {event.get('attempt', '-')}"
    # One record per fenced block; results remain readable and recoverable Markdown.
    with (run / "RESULTS.md").open("a") as f:
        f.write(f"\n## {title}\n\n```json\n{json.dumps(event, ensure_ascii=False, allow_nan=False)}\n```\n")
        f.flush()
        os.fsync(f.fileno())


def history(run):
    text = (run / "RESULTS.md").read_text()
    blocks = re.findall(r"^```json\n(.*?)\n```$", text, re.M | re.S)
    # A partially written block must be repaired using its actual evidence, not ignored.
    if text.count("```json\n") != len(blocks):
        raise ValueError("RESULTS.md has an incomplete record; preserve and repair it before resuming")
    return [json.loads(block) for block in blocks]


def status(run):
    events = history(run)
    starts = {e["attempt"]: e for e in events if e["event"] == "started"}
    finishes = {e["attempt"]: e for e in events if e["event"] == "finished"}
    pending = [e for key, e in starts.items() if key not in finishes]
    kept = [e for e in finishes.values() if e["decision"] in ("baseline", "keep")]
    return {
        "run": str(run), "attempts": len(starts),
        "compute_seconds": sum(e["seconds"] for e in finishes.values()),
        "best": kept[-1] if kept else None, "pending": pending,
        "stopped": (run / "STOP").exists(),
    }


def create_run(run, template):
    if run.exists():
        raise ValueError(f"run already exists; use status/run to resume: {run}")
    config = json.loads((template / "config.json").read_text())
    validate(config)
    for folder in ("candidate", "evaluation"):
        source = template / folder
        if not source.is_dir() or source.is_symlink():
            raise ValueError(f"template missing regular directory {folder}")
        if any(p.is_symlink() for p in source.rglob("*")):
            raise ValueError("template source must not contain symlinks; reference external assets in config")
    run.mkdir(parents=True)
    (run / "protocol.json").write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    for source, target in (("candidate", "work"), ("evaluation", "evaluation")):
        shutil.copytree(template / source, run / target, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
    brief = template / "BRIEF.md"
    (run / "BRIEF.md").write_text(brief.read_text() if brief.exists() else f"# Research goal\n\n{config['goal']}\n")
    (run / "RESULTS.md").write_text("# Experiment results\n\nAttempts, failures and measured outcomes are append-only.\n")
    (run / "MEMORY.md").write_text("# Research memory\n\nRead RESULTS.md for measured facts. Record hypotheses, dead ends and next steps here.\n")
    (run / "work" / ".gitignore").write_text("__pycache__/\n*.pyc\n")
    git(run / "work", "init", "-b", "codex/autoresearch")
    git(run / "work", "add", "--all")
    git(run / "work", "-c", "user.name=Autoresearch", "-c", "user.email=autoresearch@localhost", "commit", "-m", "baseline input")
    return status(run)


def check_work(run):
    work = run / "work"
    if not (work / ".git").is_dir() or Path(git(work, "rev-parse", "--show-toplevel")).resolve() != work.resolve():
        raise ValueError("expected the isolated run/work Git repository; refusing parent-repo operations")
    return work


def argv(command, run):
    values = {"{python}": sys.executable, "{run}": str(run), "{workspace}": str(run / "work")}
    result = []
    for part in command:
        for key, value in values.items():
            part = part.replace(key, value)
        result.append(part)
    return result


def terminate_group(proc):
    # This group was created by this runner, never a user's unrelated process.
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()


def execute(command, run, log, deadline, ignore_stop=False):
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["AUTORESEARCH_RUN_DIR"] = str(run)
    with log.open("a") as out:
        out.write("\nCOMMAND " + json.dumps(argv(command, run), ensure_ascii=False) + "\n")
        out.flush()
        proc = subprocess.Popen(argv(command, run), cwd=run / "work", stdout=out,
                                stderr=subprocess.STDOUT, start_new_session=True, env=env)
        try:
            while proc.poll() is None:
                if not ignore_stop and (run / "STOP").exists():
                    terminate_group(proc)
                    return "stopped"
                if time.monotonic() >= deadline:
                    terminate_group(proc)
                    return "timeout"
                time.sleep(0.05)
            return proc.returncode
        except BaseException:
            terminate_group(proc)
            raise
        finally:
            # Reap descendants even if the command's top-level process exited first.
            terminate_group(proc)


def metrics_from(log):
    lines = [line[len(MARKER):] for line in log.read_text().splitlines() if line.startswith(MARKER)]
    if len(lines) != 1:
        raise ValueError("evaluation must emit exactly one AUTORESEARCH_METRICS JSON object")
    metrics = json.loads(lines[0])
    if not isinstance(metrics, dict) or not metrics or not all(number(v) for v in metrics.values()):
        raise ValueError("metrics must be a nonempty object of finite numbers")
    return metrics


def rollback(run, best):
    if best:
        # Only the isolated candidate repository is reset. Rejected commits remain in history/reflog.
        git(check_work(run), "reset", "--hard", best["commit"])


def run_attempt(run, hypothesis):
    config = json.loads((run / "protocol.json").read_text())
    validate(config)
    state = status(run)
    if state["pending"]:
        raise ValueError("unfinished attempt: confirm its processes exited, then use recover; no automatic rerun")
    if state["stopped"]:
        raise ValueError("STOP is present; use resume only when the user resumes this run")
    if state["attempts"] >= config["max_attempts"] or state["compute_seconds"] >= config["max_seconds"]:
        raise ValueError("run budget exhausted (baseline and failed attempts included)")
    work = check_work(run)
    git(work, "add", "--all")
    if git(work, "status", "--porcelain"):
        git(work, "-c", "user.name=Autoresearch", "-c", "user.email=autoresearch@localhost", "commit", "-m", "experiment: " + hypothesis)
    commit = git(work, "rev-parse", "HEAD")
    attempt = state["attempts"] + 1
    append(run, {"event": "started", "attempt": attempt, "commit": commit,
                 "hypothesis": hypothesis, "runner_pid": os.getpid()})
    start = time.monotonic()
    deadline = start + min(config["attempt_timeout"], config["max_seconds"] - state["compute_seconds"])
    attempt_dir = run / "attempts" / f"{attempt:04d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    decision, metrics, error = "crash", None, None
    cleanup_ok = True
    try:
        if config.get("guard"):
            result = execute(config["guard"], run, attempt_dir / "guard.log", deadline)
            if result != 0:
                decision = "resource_blocked"
                raise ValueError(f"guard returned {result}; evaluation not started")
        result = execute(config["command"], run, attempt_dir / "output.log", deadline)
        if result != 0:
            decision = "stopped" if result == "stopped" else "crash"
            raise ValueError(f"evaluation returned {result}")
        metrics = metrics_from(attempt_dir / "output.log")
        value = metrics[config["metric"]["name"]]
        for bound in config.get("constraints", []):
            observed = metrics[bound["name"]]
            passes = observed <= bound["value"] if bound["op"] == "<=" else observed >= bound["value"]
            if not passes:
                decision = "constraint_failed"
                raise ValueError(f"constraint failed: {bound['name']} {bound['op']} {bound['value']}")
        best = state["best"]
        if best is None:
            decision = "baseline"
        else:
            previous = best["metrics"][config["metric"]["name"]]
            gain = previous - value if config["metric"]["direction"] == "min" else value - previous
            decision = "keep" if gain > config["metric"].get("min_delta", 0) else "discard"
    except KeyboardInterrupt:
        decision, error = "stopped", "runner interrupted"
    except Exception as exc:
        error = str(exc) or type(exc).__name__
    finally:
        if config.get("cleanup"):
            try:
                result = execute(config["cleanup"], run, attempt_dir / "cleanup.log", time.monotonic() + 30, ignore_stop=True)
                cleanup_ok = result == 0
            except (Exception, KeyboardInterrupt) as exc:
                cleanup_ok = False
                error = f"{error or ''}; cleanup: {exc}"
            if not cleanup_ok:
                decision = "cleanup_failed"
                (run / "STOP").write_text("Cleanup failed: verify this run's processes exited before resuming.\n")
        if decision not in ("baseline", "keep"):
            rollback(run, state["best"])
        event = {"event": "finished", "attempt": attempt, "decision": decision,
                 "commit": commit, "metrics": metrics, "seconds": time.monotonic() - start,
                 "hypothesis": hypothesis, "error": error, "cleanup_ok": cleanup_ok}
        append(run, event)
    return event


def recover(run, note):
    state = status(run)
    for pending in state["pending"]:
        # Caller confirms local AND remote processes exited; PIDs alone are not authoritative.
        append(run, {"event": "finished", "attempt": pending["attempt"], "decision": "interrupted",
                     "commit": pending["commit"], "metrics": None,
                     "seconds": max(0, time.time() - pending["time"]),
                     "hypothesis": pending["hypothesis"], "error": note})
    if state["pending"]:
        rollback(run, state["best"])
    return status(run)


def run_path(slug):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", slug):
        raise ValueError("run name must contain only lowercase letters, digits, - or _")
    return ROOT / "runs" / slug


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    new = commands.add_parser("new", help="copy a fixed template into a new isolated run")
    new.add_argument("name")
    new.add_argument("--template", type=Path, default=ROOT / "examples" / "polynomial")
    trial = commands.add_parser("run", help="evaluate the current candidate once; the agent supplies hypotheses")
    trial.add_argument("name")
    trial.add_argument("--hypothesis", required=True)
    for action in ("status", "stop", "resume"):
        commands.add_parser(action).add_argument("name")
    rec = commands.add_parser("recover", help="record a lost attempt without erasing its consumed budget")
    rec.add_argument("name")
    rec.add_argument("--confirmed-exited", action="store_true", required=True)
    rec.add_argument("--note", required=True)
    args = parser.parse_args()
    try:
        run = run_path(args.name)
        if args.action == "new":
            result = create_run(run, args.template.resolve())
        elif args.action == "run":
            def interrupted(signum, frame):
                raise KeyboardInterrupt
            signal.signal(signal.SIGTERM, interrupted)
            result = run_attempt(run, args.hypothesis)
        elif args.action == "recover":
            result = recover(run, args.note)
        else:
            if args.action == "stop":
                (run / "STOP").write_text("User requested stop.\n")
            elif args.action == "resume":
                (run / "STOP").unlink(missing_ok=True)
            result = status(run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.action == "run" and result["decision"] not in ("baseline", "keep", "discard"):
            return 1
        return 0
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        print(f"autoresearch: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
