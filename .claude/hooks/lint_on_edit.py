"""PostToolUse hook: format and lint every Python file Claude Code edits.

Runs `ruff format` then `ruff check --fix` on the edited file. If lint errors
remain, prints them to stderr and exits 2 so Claude sees them right away and
fixes them in the same turn. Does nothing until the project has a
pyproject.toml and ruff installed (before task T1.1 is done).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    # Fixed `uv run ruff ...` argv list, no shell; the only variable is the edited file path.
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=45)  # noqa: S603


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    file_path = (payload.get("tool_input") or {}).get("file_path")
    if not file_path or not file_path.endswith(".py"):
        return 0

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", payload.get("cwd", ".")))
    if not (project_dir / "pyproject.toml").exists() or not Path(file_path).exists():
        return 0
    if shutil.which("uv") is None:
        return 0
    if run(["uv", "run", "ruff", "--version"], project_dir).returncode != 0:
        return 0  # ruff not installed yet

    run(["uv", "run", "ruff", "format", file_path], project_dir)
    check = run(["uv", "run", "ruff", "check", "--fix", file_path], project_dir)
    if check.returncode != 0:
        print(f"ruff found problems in {file_path}:\n{check.stdout}{check.stderr}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
