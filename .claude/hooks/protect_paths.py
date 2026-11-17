"""PreToolUse hook: block Claude Code from editing protected paths.

Reads the hook payload (JSON) on stdin. Exit code 2 blocks the edit and the
message on stderr goes back to Claude so it can change course.

Always protected: .env files (not .env.example) and anything under .git/.
Freeze switch: once the hidden acceptance tests are written (task T1.7),
create an empty file .claude/FREEZE_ACCEPTANCE to block edits under
acceptance/. That stops anyone, Claude Code included, from "fixing" a
failing run by editing the tests it is graded against.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def blocked_reason(file_path: str, project_dir: Path) -> str | None:
    path = Path(file_path.replace("\\", "/"))
    parts = path.parts
    name = path.name

    if ".git" in parts:
        return "edits inside .git/ are not allowed"
    if name == ".env" or (name.startswith(".env.") and not name.endswith(".example")):
        return "secrets files (.env) are off limits; edit .env.example instead"
    if "acceptance" in parts and (project_dir / ".claude" / "FREEZE_ACCEPTANCE").exists():
        return (
            "acceptance/ is frozen (.claude/FREEZE_ACCEPTANCE exists). Hidden tests are the "
            "grader; fix the code, not the tests. Ask Darnel if a test is genuinely wrong."
        )
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0  # never block on a payload we can't read

    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not file_path:
        return 0

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", payload.get("cwd", ".")))
    reason = blocked_reason(file_path, project_dir)
    if reason:
        print(f"Blocked edit to {file_path}: {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
