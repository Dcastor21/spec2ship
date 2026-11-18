"""Diff policy: flag changes the gates alone might let through.

Given a unified diff (what the agent changed), report every added secret,
banned call, removed or skipped test, gate-weakening comment, pytest hook and
gate-configuration change. Rules match lines, not parsed code: a diff holds
fragments, and simple patterns are easy to read and to defend. This is a
tripwire next to the gates and the hidden tests, not a proof of safety.

Only added lines are judged, except deleted tests, which come from removed
lines. Secrets are reported redacted, because findings reach traces and evidence.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict

from factory.spec import GATE_CONFIG_NAMES

Rule = Literal[
    "secret",
    "banned-call",
    "deleted-test",
    "skipped-test",
    "test-marker",
    "gate-comment",
    "pytest-hook",
    "gate-config",
]

TARGET_ROOT = "target/"
ALLOWED_MARKERS = frozenset({"parametrize", "usefixtures"})
MAX_SHOWN = 120

_SECRETS: list[tuple[str, re.Pattern[str]]] = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("API key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b")),
    ("GitHub token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    (
        "hard-coded credential",
        re.compile(
            # No letter before the keyword, so db_password and API_TOKEN match.
            r"(?i)(?<![a-z])(?:api[_-]?key|secret|token|passw(?:or)?d)\w*\s*[:=]\s*"
            r"['\"]([^'\"\s]{8,})['\"]"
        ),
    ),
]
_BANNED_CALLS: list[tuple[str, re.Pattern[str]]] = [
    ("subprocess", re.compile(r"\bimport\s+subprocess\b|\bfrom\s+subprocess\b|\bsubprocess\.")),
    ("os.system", re.compile(r"\bos\.(?:system|popen)\s*\(")),
    ("eval", re.compile(r"(?<![\w.])eval\s*\(")),
    ("exec", re.compile(r"(?<![\w.])exec\s*\(")),
]
_TEST_DEF = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)\s*\(")
_SKIP = re.compile(
    r"\bpytest\.(?:mark\.(?:skip|skipif|xfail)\b|skip\s*\(|xfail\s*\(|importorskip\s*\()"
)
_MARKER = re.compile(r"\bpytest\.mark\.(\w+)")
_PYTESTMARK = re.compile(r"^\s*pytestmark\s*=")
_GATE_COMMENTS: list[tuple[str, re.Pattern[str]]] = [
    ("pragma: no cover", re.compile(r"#\s*pragma:\s*no\s*(?:cover|branch)", re.IGNORECASE)),
    ("type: ignore", re.compile(r"#\s*type:\s*ignore", re.IGNORECASE)),
    ("noqa", re.compile(r"#\s*noqa\b", re.IGNORECASE)),
    ("pyright: ignore", re.compile(r"#\s*pyright:\s*ignore", re.IGNORECASE)),
]
_PYTEST_HOOK = re.compile(r"^\s*(?:async\s+)?def\s+(pytest_\w+)\s*\(")
_HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class Violation(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule: Rule
    path: str
    line: int | None  # line in the new file; None for file-level or removed-line findings
    detail: str

    def render(self) -> str:
        where = f"{self.path}:{self.line}" if self.line is not None else self.path
        return f"{where} [{self.rule}] {self.detail}"


# --- parsing ----------------------------------------------------------------


@dataclass
class FileDiff:
    old_path: str | None  # None for a new file
    new_path: str | None  # None for a deleted file
    added: list[tuple[int, str]] = field(default_factory=list)  # (new line number, text)
    removed: list[str] = field(default_factory=list)

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or "?"

    @property
    def paths(self) -> set[str]:
        return {p for p in (self.old_path, self.new_path) if p}


def _strip_prefix(raw: str) -> str | None:
    raw = raw.split("\t", 1)[0].strip()
    if raw == "/dev/null":
        return None
    return raw[2:] if raw[:2] in ("a/", "b/") else raw


def parse_diff(diff: str) -> list[FileDiff]:
    """Split a unified diff (git or plain) into per-file added and removed lines.

    Hunk bodies are read by the line counts in their @@ header, so a removed line
    that happens to start with "--" is never mistaken for the next file's header.
    """
    files: list[FileDiff] = []
    current: FileDiff | None = None
    header_open = False  # inside a file header, before its first hunk
    old_left = new_left = new_line = 0
    for raw in diff.splitlines():
        line = raw.rstrip("\r")
        if current is not None and (old_left > 0 or new_left > 0):
            if line.startswith("+"):
                current.added.append((new_line, line[1:]))
                new_line, new_left = new_line + 1, new_left - 1
            elif line.startswith("-"):
                current.removed.append(line[1:])
                old_left -= 1
            elif line.startswith(" ") or line == "":
                new_line, old_left, new_left = new_line + 1, old_left - 1, new_left - 1
            # "\ No newline at end of file" carries no content and no count
        elif line.startswith("diff --git "):
            parts = line.split(" ")
            current = FileDiff(_strip_prefix(parts[2]), _strip_prefix(parts[-1]))
            files.append(current)
            header_open = True
        elif line.startswith("--- "):
            if current is None or not header_open:  # a plain diff: no "diff --git" line
                current = FileDiff(None, None)
                files.append(current)
                header_open = True
            current.old_path = _strip_prefix(line[4:])
        elif line.startswith("+++ ") and current is not None:
            current.new_path = _strip_prefix(line[4:])
        elif line.startswith(("rename from ", "rename to ")) and current is not None:
            name = line.split(" ", 2)[2]
            if line.startswith("rename from "):
                current.old_path = name
            else:
                current.new_path = name
        elif (match := _HUNK.match(line)) and current is not None:
            old_left = int(match.group(1) or "1")
            new_line = int(match.group(2))
            new_left = int(match.group(3) or "1")
            header_open = False
    return files


# --- rules ------------------------------------------------------------------


def _shown(text: str) -> str:
    text = text.strip()
    return text if len(text) <= MAX_SHOWN else text[: MAX_SHOWN - 1] + "…"


def _redact(value: str) -> str:
    return f"{value[:4]}… ({len(value)} chars, redacted)"


def _is_gate_config(path: str) -> bool:
    name = PurePosixPath(path).name.lower().rstrip(". ")
    return name in GATE_CONFIG_NAMES or name.endswith(".pth")


def _is_python(path: str) -> bool:
    return path.lower().endswith(".py")


def _secrets(f: FileDiff) -> Iterator[Violation]:
    for number, text in f.added:
        for label, pattern in _SECRETS:
            if match := pattern.search(text):
                value = match.group(match.lastindex or 0)
                yield Violation(
                    rule="secret", path=f.path, line=number, detail=f"{label} {_redact(value)}"
                )
                break


def _line_rules(f: FileDiff) -> Iterator[Violation]:
    if not _is_python(f.path):
        return
    in_target = f.path.startswith(TARGET_ROOT)
    for number, text in f.added:
        shown = _shown(text)
        if in_target:
            for label, pattern in _BANNED_CALLS:
                if pattern.search(text):
                    yield Violation(
                        rule="banned-call", path=f.path, line=number, detail=f"{label}: {shown}"
                    )
        if _SKIP.search(text):
            yield Violation(rule="skipped-test", path=f.path, line=number, detail=shown)
        else:
            custom = [m for m in _MARKER.findall(text) if m not in ALLOWED_MARKERS]
            if custom or _PYTESTMARK.match(text):
                yield Violation(rule="test-marker", path=f.path, line=number, detail=shown)
        for label, pattern in _GATE_COMMENTS:
            if pattern.search(text):
                yield Violation(
                    rule="gate-comment", path=f.path, line=number, detail=f"{label}: {shown}"
                )
        if hook := _PYTEST_HOOK.match(text):
            yield Violation(
                rule="pytest-hook", path=f.path, line=number, detail=f"def {hook.group(1)}"
            )


def _deleted_tests(files: list[FileDiff]) -> Iterator[Violation]:
    # A test renamed or moved within the same diff is not deleted.
    added = {m.group(1) for f in files for _, text in f.added if (m := _TEST_DEF.match(text))}
    for f in files:
        for text in f.removed:
            if (m := _TEST_DEF.match(text)) and m.group(1) not in added:
                yield Violation(
                    rule="deleted-test", path=f.path, line=None, detail=f"removed {m.group(1)}"
                )


def check_diff(diff: str) -> list[Violation]:
    """Every policy violation in `diff`, in file order."""
    files = parse_diff(diff)
    violations: list[Violation] = []
    for f in files:
        for path in sorted(f.paths):
            if _is_gate_config(path):
                violations.append(
                    Violation(
                        rule="gate-config",
                        path=path,
                        line=None,
                        detail="changes test or gate configuration; only a human edits it",
                    )
                )
        violations += _secrets(f)
        violations += _line_rules(f)
    violations += _deleted_tests(files)
    return violations
