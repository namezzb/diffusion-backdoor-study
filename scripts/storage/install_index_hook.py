#!/usr/bin/env python3
"""Enable this repository's reviewed pre-commit index check, without replacing another hook setup."""
from pathlib import Path
import subprocess


def main():
    root = Path(__file__).resolve().parents[2]
    actual = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=root, text=True).strip()).resolve()
    if actual != root:
        raise SystemExit("Refusing to change hooks outside this research checkout.")
    current = subprocess.run(["git", "config", "--get", "core.hooksPath"], cwd=root, text=True, capture_output=True)
    if current.returncode not in (0, 1):
        raise SystemExit("Cannot inspect current hook configuration.")
    if current.stdout.strip() not in ("", ".githooks"):
        raise SystemExit("Another hooksPath is configured; preserve it and integrate the index check explicitly.")
    old_hook = Path(subprocess.check_output(["git", "rev-parse", "--git-path", "hooks/pre-commit"], cwd=root, text=True).strip())
    if not old_hook.is_absolute():
        old_hook = root / old_hook
    if not current.stdout.strip() and (old_hook.exists() or old_hook.is_symlink()):
        raise SystemExit("An existing pre-commit hook is present; preserve it and integrate the index check explicitly.")
    hook = root / ".githooks" / "pre-commit"
    if hook.is_symlink() or not hook.is_file():
        raise SystemExit("Missing regular repository hook.")
    hook.chmod(hook.stat().st_mode | 0o111)
    subprocess.run(["git", "config", "--local", "core.hooksPath", ".githooks"], cwd=root, check=True)
    print("Enabled the research index check for this checkout. No server or experiment was started.")


if __name__ == "__main__":
    main()
