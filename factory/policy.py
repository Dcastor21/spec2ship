"""Diff policy: flag changes the gates alone might let through.

Given a unified diff (what the agent changed), report every added secret,
banned call, removed or hidden test, gate-weakening comment, pytest hook or
plugin, and gate-configuration change. Rules match lines, not parsed code: a
diff holds fragments, and simple patterns are easy to read and to defend.

This is a tripwire next to other layers, not a proof of safety. Known limits,
each covered elsewhere:
- Dynamic or aliased calls (`getattr(builtins, "ev" + "al")`, `m = pytest.mark`
  then `@m.skip`, decorators split over lines). The sandbox contains the run,
  and the pytest gate fails on any skipped, xfail or deselected test at runtime.
- A test emptied in place (its def kept, its asserts removed). The hidden
  acceptance tests and the reviewer model catch that.
- Secrets split across lines or encoded.

Only added lines are judged, except removed tests. Every finding's text is
scrubbed of anything that looks like a secret, because findings reach traces
and evidence. A diff that cannot be parsed fails closed.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict

from factory.spec import is_gate_config

Rule = Literal[
    "secret",
    "banned-call",
    "deleted-test",
    "skipped-test",
    "test-marker",
    "gate-comment",
    "pytest-hook",
    "gate-config",
    "malformed-diff",
]

TARGET_ROOT = "target/"
ALLOWED_MARKERS = frozenset({"parametrize", "usefixtures"})
MAX_SHOWN = 120

_QUOTED_SECRET = re.compile(
    # No letter before the keyword, so db_password, API_TOKEN and "api_key": match.
    r"(?i)(?<![a-z])(?:api[_-]?key|secret|token|passw(?:or)?d|auth)\w*['\"]?\s*[:=]\s*"
    r"['\"]([^'\"\s]{8,})['\"]"
)
_UNQUOTED_SECRET = re.compile(  # .env and YAML style; not used on .py, where it misfires
    r"(?i)^\s*(?:export\s+)?\w*(?:api[_-]?key|secret|token|passw(?:or)?d)\w*\s*[:=]\s*"
    r"([^\s'\"#]{8,})"
)
_SECRETS: list[tuple[str, re.Pattern[str]]] = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("API key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b")),
    ("GitHub token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("bearer token", re.compile(r"\bBearer\s+([A-Za-z0-9._~+/=-]{20,})")),
    ("hard-coded credential", _QUOTED_SECRET),
]
_OS_CALLS = r"(?:system|popen|exec\w*|spawn\w*|posix_spawn\w*|fork\w*)"
_BANNED_CALLS: list[tuple[str, re.Pattern[str]]] = [
    (
        "subprocess",
        re.compile(
            r"\bimport\s+subprocess\b|\bfrom\s+subprocess\b|\bsubprocess\."
            r"|\bcreate_subprocess_\w+"
        ),
    ),
    (
        "os process call",
        re.compile(rf"\bos\.{_OS_CALLS}\s*\(|\bfrom\s+os\s+import\b.*\b{_OS_CALLS}\b"),
    ),
    ("pty", re.compile(r"\bimport\s+pty\b|\bfrom\s+pty\b|\bpty\.")),
    ("dynamic import", re.compile(r"\b__import__\s*\(|\bimportlib\b")),
    ("eval", re.compile(r"(?:(?<![\w.])|(?<=builtins\.))eval\s*\(")),
    ("exec", re.compile(r"(?:(?<![\w.])|(?<=builtins\.))exec\s*\(")),
]
_TEST_DEF = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)\s*\(")
_TEST_CLASS = re.compile(r"^\s*class\s+(Test\w*)\b")
_SKIP = re.compile(
    r"\bpytest\.(?:mark\.(?:skip|skipif|xfail)\b|skip\s*\(|xfail\s*\(|importorskip\s*\()"
    r"|\bfrom\s+pytest\s+import\b.*\b(?:skip|xfail|importorskip)\b"
    r"|\bunittest\.(?:skip\w*|expectedFailure)\b"
    r"|^\s*__test__\s*="
)
_MARKER = re.compile(r"\bpytest\.mark\.(\w+)")
_PYTESTMARK = re.compile(r"^\s*pytestmark\s*=")
_GATE_COMMENTS: list[tuple[str, re.Pattern[str]]] = [
    # coverage's own default exclusion pattern, so "# pragma no cover" counts too
    ("pragma: no cover", re.compile(r"(?i)#\s*pragma[:\s]?\s*no\s*(?:cover|branch)")),
    ("type: ignore", re.compile(r"(?i)#\s*type:\s*ignore")),
    ("noqa", re.compile(r"(?i)#\s*(?:(?:ruff|flake8)\s*:\s*)?noqa\b")),
    ("mypy directive", re.compile(r"(?i)#\s*mypy\s*:")),
    ("pyright: ignore", re.compile(r"(?i)#\s*pyright:\s*ignore")),
]
# Any pytest_* name: a hook, a hook bound by assignment or import, or pytest_plugins.
_PYTEST_NAME = re.compile(r"\b(pytest_[a-z_]+)\b")
_HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_GIT_HEADER = re.compile(r'^diff --git ("(?:[^"\\]|\\.)*"|\S+) ("(?:[^"\\]|\\.)*"|\S+)$')
_C_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


class MalformedDiffError(ValueError):
    """The diff could not be read reliably; the policy fails closed."""


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


def _unquote(raw: str) -> str:
    """Undo git's C-style path quoting ("caf\\303\\251.py" -> "café.py")."""
    if not (len(raw) >= 2 and raw[0] == raw[-1] == '"'):
        return raw
    out = bytearray()
    body, i = raw[1:-1], 0
    while i < len(body):
        char = body[i]
        if char != "\\" or i + 1 == len(body):
            out += char.encode("utf-8")
            i += 1
        elif body[i + 1 : i + 4].isdigit() and len(body[i + 1 : i + 4]) == 3:
            out.append(int(body[i + 1 : i + 4], 8) & 0xFF)
            i += 4
        else:
            out.append(_C_ESCAPES.get(body[i + 1], ord(body[i + 1])))
            i += 2
    return out.decode("utf-8", errors="replace")


def _clean_path(raw: str) -> str | None:
    raw = raw.strip()
    if not raw.startswith('"'):
        raw = raw.split("\t", 1)[0].strip()
    path = _unquote(raw)
    if path == "/dev/null":
        return None
    return path[2:] if path[:2] in ("a/", "b/") else path


def parse_diff(diff: str) -> list[FileDiff]:
    """Split a unified diff (git or plain) into per-file added and removed lines.

    Hunk bodies are read by the line counts in their @@ header, so a removed line
    that starts with "--" is never taken for the next file's header. Anything that
    breaks those counts raises MalformedDiffError rather than being skipped.
    """
    files: list[FileDiff] = []
    current: FileDiff | None = None
    header_open = False  # inside a file header, before its first hunk
    old_left = new_left = new_line = 0
    for number, raw in enumerate(diff.splitlines(), start=1):
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
            elif not line.startswith("\\"):  # "\ No newline at end of file" is fine
                raise MalformedDiffError(f"line {number}: hunk ended before its @@ counts")
            if old_left < 0 or new_left < 0:
                raise MalformedDiffError(f"line {number}: hunk is longer than its @@ counts")
        elif line.startswith("diff --git "):
            match = _GIT_HEADER.match(line)
            parts = [match.group(1), match.group(2)] if match else line.split(" ")[2:]
            current = FileDiff(_clean_path(parts[0]), _clean_path(parts[-1]))
            files.append(current)
            header_open = True
        elif line.startswith("--- "):
            if current is None or not header_open:  # a plain diff: no "diff --git" line
                current = FileDiff(None, None)
                files.append(current)
                header_open = True
            current.old_path = _clean_path(line[4:])
        elif line.startswith("+++ ") and current is not None:
            current.new_path = _clean_path(line[4:])
        elif line.startswith("rename from ") and current is not None:
            current.old_path = _clean_path(line[len("rename from ") :])
        elif line.startswith("rename to ") and current is not None:
            current.new_path = _clean_path(line[len("rename to ") :])
        elif (match := _HUNK.match(line)) and current is not None:
            old_left = int(match.group(1) or "1")
            new_line = int(match.group(2))
            new_left = int(match.group(3) or "1")
            header_open = False
        elif current is not None and not header_open and line[:1] in ("+", "-", " "):
            raise MalformedDiffError(f"line {number}: diff content outside any hunk")
    if old_left > 0 or new_left > 0:
        raise MalformedDiffError("diff ends inside a hunk")
    return files


# --- rules ------------------------------------------------------------------


def _redact(value: str) -> str:
    return f"{value[:4]}… ({len(value)} chars, redacted)"


def _scrub(text: str) -> str:
    """Remove anything that looks like a secret from text that will be shown."""
    for _, pattern in _SECRETS:
        text = pattern.sub(lambda m: _redact(m.group(m.lastindex or 0)), text)
    return text


def _shown(text: str) -> str:
    text = _scrub(text.strip())
    return text if len(text) <= MAX_SHOWN else text[: MAX_SHOWN - 1] + "…"


def _is_python(path: str) -> bool:
    return path.lower().endswith(".py")


def _is_test_module(path: str) -> bool:
    """A file pytest collects tests from by default."""
    name = PurePosixPath(path).name.lower()
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def _secrets(f: FileDiff) -> Iterator[Violation]:
    patterns = list(_SECRETS)
    if not _is_python(f.path):
        patterns.append(("hard-coded credential", _UNQUOTED_SECRET))
    for number, text in f.added:
        for label, pattern in patterns:
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

        def found(rule: Rule, detail: str, number: int = number) -> Violation:
            return Violation(rule=rule, path=f.path, line=number, detail=detail)

        if in_target:
            for label, pattern in _BANNED_CALLS:
                if pattern.search(text):
                    yield found("banned-call", f"{label}: {shown}")
        if _SKIP.search(text):
            yield found("skipped-test", shown)
        elif [m for m in _MARKER.findall(text) if m not in ALLOWED_MARKERS] or _PYTESTMARK.match(
            text
        ):
            yield found("test-marker", shown)
        for label, pattern in _GATE_COMMENTS:
            if pattern.search(text):
                yield found("gate-comment", f"{label}: {shown}")
        if name := _PYTEST_NAME.search(text):
            yield found("pytest-hook", f"{name.group(1)}: {shown}")


def _deleted_tests(files: list[FileDiff]) -> Iterator[Violation]:
    # A test counts as moved only if it reappears where pytest still collects it.
    kept = {
        m.group(1)
        for f in files
        if f.new_path and _is_test_module(f.new_path)
        for _, text in f.added
        if (m := _TEST_DEF.match(text) or _TEST_CLASS.match(text))
    }
    for f in files:
        if f.old_path and _is_test_module(f.old_path):
            if f.new_path and not _is_test_module(f.new_path):
                yield Violation(
                    rule="deleted-test",
                    path=f.old_path,
                    line=None,
                    detail=f"test module renamed to {f.new_path}, which pytest does not collect",
                )
            for text in f.removed:
                m = _TEST_DEF.match(text) or _TEST_CLASS.match(text)
                if m and m.group(1) not in kept:
                    yield Violation(
                        rule="deleted-test", path=f.path, line=None, detail=f"removed {m.group(1)}"
                    )


def check_diff(diff: str) -> list[Violation]:
    """Every policy violation in `diff`, in file order. A diff that can't be parsed is one."""
    try:
        files = parse_diff(diff)
    except MalformedDiffError as exc:
        return [Violation(rule="malformed-diff", path="(diff)", line=None, detail=str(exc))]
    violations: list[Violation] = []
    for f in files:
        violations += [
            Violation(
                rule="gate-config",
                path=path,
                line=None,
                detail="changes test or gate configuration; only a human edits it",
            )
            for path in sorted(f.paths)
            if is_gate_config(path)
        ]
        violations += _secrets(f)
        violations += _line_rules(f)
    violations += _deleted_tests(files)
    return violations
