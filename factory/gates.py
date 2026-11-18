"""Quality gates: the deterministic checks that decide whether a workspace passes.

Agents propose; these decide. Two rules keep the agent from moving the goalposts:

1. Settings that decide pass or fail (strict typing, the coverage floor, which
   tests run, which paths are checked) are flags owned by the factory.
2. Every other setting the tools read from the workspace must be the factory's
   own: pyproject.toml, uv.lock and every gate-config file (conftest.py,
   ruff.toml, pytest.ini, .pth, ...) must be byte-identical to the repo's copy,
   and no new ones may appear. Otherwise the gates refuse to run.

T2.3 (refuse the write) and T1.6 (flag the diff) back this up; they are not the
only line. All checks always run, so a retry hears about every failure at once.
"""

from __future__ import annotations

import contextlib
import re
import sys
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from factory.policy import check_diff
from factory.sandbox import REPO_ROOT, Limits, Mode, SandboxResult, build_image, run
from factory.spec import is_gate_config

TARGET_DIR = "target"
TARGET_PACKAGE = "target/guard_ops"
TARGET_TESTS = "target/tests"
COVERAGE_FLOOR = 90  # percent of target/guard_ops; 99% at T1.2. Raise it, never lower it.
DOCKER_MYPY_CACHE = "/tmp/mypy_cache"  # noqa: S108 - the container's private tmpfs
LOCK_FILE = "uv.lock"

_ERROR_COUNT = re.compile(r"^Found \d+ errors?\b")
# Outcomes the target suite never has. Each one is a test that did not count.
_NOT_RUN = re.compile(r"\b\d+ (deselected|skipped|xfailed|xpassed)\b")
_FAILURES = re.compile(r"\b\d+ (failed|errors?)\b")


class GateError(ValueError):
    """The gates refuse to run on this workspace at all."""


class CheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    passed: bool
    summary: str  # one line, e.g. "Found 2 errors." or "1 failed, 19 passed in 1.7s"
    details: str  # the tail of the check's output


class GateResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    checks: list[CheckResult]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failed(self) -> list[str]:
        return [check.name for check in self.checks if not check.passed]


# --- config integrity -------------------------------------------------------


def config_problems(workspace: Path, reference: Path = REPO_ROOT) -> list[str]:
    """Every way the workspace's gate configuration differs from the factory's."""
    in_workspace = {
        path.relative_to(workspace)
        for path in workspace.rglob("*")
        if path.is_file() and is_gate_config(path.name)
    }
    in_reference = {
        path.relative_to(reference)
        for path in (reference / TARGET_DIR).rglob("*")
        if path.is_file() and is_gate_config(path.name)
    }
    expected = in_reference | {Path("pyproject.toml"), Path(LOCK_FILE)}

    problems = []
    for rel in sorted(in_workspace - expected):
        problems.append(f"{rel.as_posix()} is gate configuration the factory does not have")
    for rel in sorted(expected):
        mine, theirs = workspace / rel, reference / rel
        if not theirs.is_file():
            problems.append(f"{rel.as_posix()}: the factory's reference copy is missing")
        elif not mine.is_file():
            problems.append(f"{rel.as_posix()} is missing")
        elif mine.read_bytes() != theirs.read_bytes():
            problems.append(f"{rel.as_posix()} differs from the factory's copy")
    return problems


# --- the checks -------------------------------------------------------------


def check_commands(python: str, mypy_cache: str) -> list[tuple[str, list[str]]]:
    """The four checks, in order. Caches go nowhere the diff can see."""
    return [
        ("ruff check", [python, "-m", "ruff", "check", "--no-cache", TARGET_DIR]),
        ("ruff format", [python, "-m", "ruff", "format", "--check", "--no-cache", TARGET_DIR]),
        ("mypy", [python, "-m", "mypy", "--strict", "--cache-dir", mypy_cache, TARGET_DIR]),
        (
            "pytest",
            [
                python,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                # An empty marker expression overrides the factory's own
                # `-m "not docker and not live"` addopts: every target test runs.
                "-m",
                "",
                f"--cov={TARGET_PACKAGE}",
                "--cov-report=term-missing:skip-covered",
                f"--cov-fail-under={COVERAGE_FLOOR}",
                TARGET_TESTS,
            ],
        ),
    ]


def summarize(result: SandboxResult) -> str:
    """One line a person (or a retry prompt) can act on."""
    if result.timed_out:
        return f"timed out after {result.duration_s:.0f}s"
    if result.output_overflow:
        return "stopped: the check printed more output than the sandbox allows"
    out_lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    err_lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
    # pytest ends with "N passed" even when only coverage failed; failing tests come first.
    if out_lines and not _FAILURES.search(out_lines[-1]):
        for line in out_lines:
            if "Required test coverage" in line and "not reached" in line:
                return line.removeprefix("FAIL").strip()
    for line in reversed(out_lines):  # ruff and mypy end with hints after their count
        if _ERROR_COUNT.match(line):
            return line
    lines = out_lines or err_lines
    return lines[-1] if lines else f"exit code {result.exit_code}"


def _check(name: str, result: SandboxResult) -> CheckResult:
    summary = summarize(result)
    passed = result.ok
    if name == "pytest" and _NOT_RUN.search(summary):
        # Counting outcomes also catches a pytest.skip() built at runtime, which a diff
        # scan (T1.6) cannot see.
        passed, summary = False, f"{summary} (skipped, xfail or deselected tests are not allowed)"
    details = "\n".join(part for part in (result.stdout, result.stderr) if part.strip())
    return CheckResult(name=name, passed=passed, summary=summary, details=details)


def policy_check(diff: str) -> CheckResult:
    """The diff policy as one more check. Pure text: it never runs agent code."""
    violations = check_diff(diff)
    if not violations:
        return CheckResult(name="policy", passed=True, summary="no policy violations", details="")
    count = len(violations)
    rules = ", ".join(sorted({violation.rule for violation in violations}))
    return CheckResult(
        name="policy",
        passed=False,
        summary=f"{count} policy violation{'s' if count != 1 else ''}: {rules}",
        details="\n".join(violation.render() for violation in violations),
    )


def run_gates(
    workspace: Path,
    *,
    mode: Mode = "docker",
    limits: Limits | None = None,
    image: str | None = None,
    reference: Path = REPO_ROOT,
    diff: str | None = None,
) -> GateResult:
    """Run every check against `workspace`: a copy of target/ with the repo's pyproject.toml
    and uv.lock beside it, byte for byte."""
    if not (workspace / TARGET_DIR).is_dir():
        raise GateError(f"workspace {workspace} has no {TARGET_DIR}/ directory")
    problems = config_problems(workspace, reference)
    if problems:
        listing = "\n".join(f"  - {problem}" for problem in problems)
        raise GateError(
            f"workspace {workspace} has changed gate configuration, so the gates will not "
            f"run:\n{listing}\nRestore these files from the repo; only a human edits them."
        )

    with contextlib.ExitStack() as stack:
        if mode == "docker":
            image = image or build_image()
            python, cache = "python", DOCKER_MYPY_CACHE
        else:
            python = sys.executable
            cache = stack.enter_context(tempfile.TemporaryDirectory(prefix="s2s-mypy-"))
        checks = [
            _check(name, run(cmd, workspace, mode=mode, limits=limits, image=image))
            for name, cmd in check_commands(python, cache)
        ]
    if diff is not None:  # the agent's change, from the workspace's git (T2.3)
        checks.append(policy_check(diff))
    return GateResult(checks=checks)
