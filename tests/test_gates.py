"""Quality gates (T1.5): each deliberate break fails the right check and only that check.

These run the real tools in local mode on a copy of the target. The same checks
run in Docker in test_gates_docker.py.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from factory.gates import (
    COVERAGE_FLOOR,
    GateError,
    _check,
    check_commands,
    config_problems,
    run_gates,
    summarize,
)
from factory.sandbox import REPO_ROOT, SandboxResult, build_image

CHECKS = ["ruff check", "ruff format", "mypy", "pytest"]


def make_workspace(root: Path) -> Path:
    """What T2.3 will build: target/ plus the root pyproject.toml and uv.lock."""
    workspace = root / "workspace"
    shutil.copytree(
        REPO_ROOT / "target",
        workspace / "target",
        ignore=shutil.ignore_patterns("__pycache__", "*.db"),
    )
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copyfile(REPO_ROOT / name, workspace / name)
    return workspace


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not in {path}; the break no longer applies"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def break_lint(ws: Path) -> None:  # an unused import
    edit(ws / "target/guard_ops/db.py", "import sqlite3\n", "import os\nimport sqlite3\n")


def break_format(ws: Path) -> None:  # single quotes: valid lint, wrong format
    edit(ws / "target/guard_ops/main.py", 'return {"status": "ok"}', "return {'status': 'ok'}")


def break_types(ws: Path) -> None:  # a str returned where the annotation says int
    edit(
        ws / "target/guard_ops/db.py",
        "def utc_text(value: datetime) -> str:",
        "def utc_text(value: datetime) -> int:",
    )


def break_tests(ws: Path) -> None:  # behaviour the target's own tests pin down
    edit(ws / "target/guard_ops/main.py", 'return {"status": "ok"}', 'return {"status": "down"}')


def break_coverage(ws: Path) -> None:  # valid, typed, formatted, and never run
    body = "".join("    total += 1\n" for _ in range(60))
    code = (
        f'"""Never imported."""\n\n\ndef unused() -> int:\n    total = 0\n{body}    return total\n'
    )
    (ws / "target/guard_ops/unused.py").write_text(code, encoding="utf-8")


def break_tests_and_hide_them(ws: Path) -> None:  # the reviewer's bypass: deselect by marker
    break_tests(ws)
    test_app = ws / "target/tests/test_app.py"
    edit(test_app, "from fastapi.testclient", "import pytest\nfrom fastapi.testclient")
    edit(test_app, "def test_health(", "@pytest.mark.live\ndef test_health(")


def break_tests_and_hide_them_in_a_class(ws: Path) -> None:  # pytest skips a class with __init__
    break_tests(ws)
    edit(
        ws / "target/tests/test_app.py",
        "def test_health(client: TestClient) -> None:\n"
        '    response = client.get("/health")\n'
        "    assert response.status_code == 200\n"
        '    assert response.json() == {"status": "ok"}\n',
        "class TestHealth:\n"
        "    def __init__(self) -> None:\n"
        '        self.path = "/health"\n\n'
        "    def test_health(self, client: TestClient) -> None:\n"
        "        response = client.get(self.path)\n"
        "        assert response.status_code == 200\n"
        '        assert response.json() == {"status": "ok"}\n',
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return make_workspace(tmp_path)


def test_unmodified_target_passes_every_check(workspace: Path) -> None:
    result = run_gates(workspace, mode="local")
    assert [check.name for check in result.checks] == CHECKS
    assert result.passed, [c.details for c in result.checks if not c.passed]
    assert result.failed == []


@pytest.mark.parametrize(
    ("breaker", "failing", "summary_fragment"),
    [
        (break_lint, "ruff check", "Found 1 error"),
        (break_format, "ruff format", "would be reformatted"),
        (break_types, "mypy", "Found 1 error"),
        (break_tests, "pytest", "1 failed"),
        (break_coverage, "pytest", f"Required test coverage of {COVERAGE_FLOOR}% not reached"),
        (break_tests_and_hide_them, "pytest", "1 failed"),
        (break_tests_and_hide_them_in_a_class, "pytest", "1 error"),
    ],
    ids=["lint", "format", "types", "tests", "coverage", "marker-deselect", "uncollectable-class"],
)
def test_a_break_fails_the_right_check_and_only_that_check(
    workspace: Path,
    breaker: Callable[[Path], None],
    failing: str,
    summary_fragment: str,
) -> None:
    breaker(workspace)
    result = run_gates(workspace, mode="local")
    assert result.failed == [failing], {c.name: c.summary for c in result.checks}
    (check,) = [c for c in result.checks if c.name == failing]
    assert summary_fragment in check.summary
    assert check.details


def test_gate_settings_come_from_the_factory_not_the_workspace() -> None:
    commands = dict(check_commands("python", "/cache"))
    assert "--strict" in commands["mypy"]
    assert f"--cov-fail-under={COVERAGE_FLOOR}" in commands["pytest"]
    assert "target/tests" in commands["pytest"]
    assert all("--no-cache" in commands[name] for name in ("ruff check", "ruff format"))


def test_workspace_without_target_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(GateError, match="has no target"):
        run_gates(tmp_path, mode="local")


def _append(path: Path, text: str) -> None:
    path.write_bytes(path.read_bytes() + text.encode())


@pytest.mark.parametrize(
    ("tamper", "problem"),
    [
        (lambda ws: _append(ws / "pyproject.toml", "\n# x\n"), "pyproject.toml differs"),
        (lambda ws: _append(ws / "uv.lock", "\n"), "uv.lock differs"),
        (
            lambda ws: _append(ws / "target/tests/conftest.py", "\n# x\n"),
            "target/tests/conftest.py differs",
        ),
        (lambda ws: (ws / "target/tests/conftest.py").unlink(), "conftest.py is missing"),
        (
            lambda ws: (ws / "target/ruff.toml").write_text("[lint]\nselect = []\n"),
            "target/ruff.toml is gate configuration the factory does not have",
        ),
        (
            lambda ws: (ws / "target/guard_ops/pytest.ini").write_text("[pytest]\n"),
            "target/guard_ops/pytest.ini is gate configuration",
        ),
        (
            lambda ws: (ws / "target/guard_ops/hook.pth").write_text("import os\n"),
            "target/guard_ops/hook.pth is gate configuration",
        ),
    ],
    ids=[
        "pyproject",
        "lock",
        "conftest-edit",
        "conftest-deleted",
        "ruff-toml",
        "pytest-ini",
        "pth",
    ],
)
def test_changed_gate_config_stops_the_gates_before_any_check(
    workspace: Path, tamper: Callable[[Path], object], problem: str
) -> None:
    tamper(workspace)
    with pytest.raises(GateError, match="changed gate configuration") as caught:
        run_gates(workspace, mode="local")
    assert problem in str(caught.value)


@pytest.mark.parametrize("outcome", ["1 deselected", "1 skipped", "1 xfailed", "1 xpassed"])
def test_a_target_test_that_did_not_count_fails_the_pytest_check(outcome: str) -> None:
    hidden = result(exit_code=0, stdout=f"19 passed, {outcome} in 1.2s\n")
    check = _check("pytest", hidden)
    assert not check.passed
    assert "skipped, xfail or deselected tests are not allowed" in check.summary


def test_missing_reference_copy_is_a_problem_not_a_crash(workspace: Path, tmp_path: Path) -> None:
    reference = tmp_path / "reference"
    shutil.copytree(workspace / "target", reference / "target")
    shutil.copyfile(workspace / "pyproject.toml", reference / "pyproject.toml")
    problems = config_problems(workspace, reference)
    assert problems == ["uv.lock: the factory's reference copy is missing"]


def result(**overrides: object) -> SandboxResult:
    fields: dict[str, object] = {
        "mode": "local",
        "isolated": False,
        "command": ["x"],
        "exit_code": 1,
        "timed_out": False,
        "output_overflow": False,
        "stdout": "",
        "stderr": "",
        "duration_s": 3.0,
    }
    return SandboxResult.model_validate(fields | overrides)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"timed_out": True, "exit_code": None}, "timed out after 3s"),
        ({"output_overflow": True, "exit_code": None}, "stopped: the check printed"),
        ({"stdout": "a\n\nFound 2 errors.\n"}, "Found 2 errors."),
        ({"stdout": "Found 1 error.\n[*] 1 fixable with `--fix`.\n"}, "Found 1 error."),
        ({"stderr": "boom: no such module\n"}, "boom: no such module"),
        ({}, "exit code 1"),
        (
            {"stdout": "FAIL Required test coverage of 90% not reached. Total: 80%\n20 passed\n"},
            "Required test coverage of 90% not reached. Total: 80%",
        ),
        (
            {
                "stdout": "FAIL Required test coverage of 90% not reached. Total: 80%\n"
                "1 failed, 19 passed in 1.4s\n"
            },
            "1 failed, 19 passed",
        ),
    ],
    ids=[
        "timeout",
        "overflow",
        "last-stdout-line",
        "ruff-hint-after-count",
        "stderr-only",
        "silent",
        "coverage",
        "failures-beat-coverage",
    ],
)
def test_summary_is_one_actionable_line(overrides: dict[str, object], expected: str) -> None:
    assert summarize(result(**overrides)).startswith(expected)


@pytest.mark.docker
def test_gates_pass_and_fail_the_same_way_in_docker(tmp_path: Path) -> None:
    image = build_image()
    clean = make_workspace(tmp_path / "clean")
    result = run_gates(clean, image=image)
    assert result.passed, {c.name: c.details for c in result.checks if not c.passed}

    broken = make_workspace(tmp_path / "broken")
    break_types(broken)
    assert run_gates(broken, image=image).failed == ["mypy"]
