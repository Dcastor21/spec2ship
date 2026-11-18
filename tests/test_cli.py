"""Tests for the spec2ship CLI: wiring, help, version, lint, and the remaining stubs."""

from __future__ import annotations

import re
from importlib.metadata import entry_points
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from factory import __version__, cli
from factory.cli import GATES_ERROR_EXIT_CODE, NOT_IMPLEMENTED_EXIT_CODE, app
from factory.gates import CheckResult, GateResult

runner = CliRunner()

COMMAND_HELP = {
    "lint": "Check specs against the spec gate.",
    "gates": "Run the quality gates on a workspace.",
    "run": "Run the factory on one spec, end to end.",
    "eval": "Run every spec and report pass rate and cost.",
}


def test_console_script_points_at_the_cli() -> None:
    scripts = entry_points(group="console_scripts", name="spec2ship")
    assert [ep.value for ep in scripts] == ["factory.cli:app"]


def test_help_lists_every_command() -> None:
    result = runner.invoke(app, ["--help"], terminal_width=200)
    assert result.exit_code == 0, result.output
    for name, summary in COMMAND_HELP.items():
        # The command name and its summary must sit together on one row.
        assert re.search(rf"\b{name}\s+{re.escape(summary)}", result.output), name


def test_version_flag_prints_the_package_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"spec2ship {__version__}"


SPEC = {
    "id": "GO-001",
    "title": "Report missed tour checkpoints",
    "goal": "Supervisors can see which checkpoints a finished tour skipped.",
    "acceptance_criteria": ["GET /tours/{id}/missed lists checkpoints never scanned"],
    "allowed_paths": ["target/guard_ops/routes/tours.py"],
    "risk": "low",
}


def test_lint_passes_a_valid_spec_directory(tmp_path: Path) -> None:
    (tmp_path / "GO-001.yaml").write_text(yaml.safe_dump(SPEC), encoding="utf-8")
    result = runner.invoke(app, ["lint", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "ok: 1 spec passed the spec gate" in result.output


def test_lint_prints_every_problem_with_a_fix_and_fails(tmp_path: Path) -> None:
    bad = SPEC | {"risk": "medium", "allowed_paths": ["acceptance/GO-001/test_x.py"]}
    (tmp_path / "GO-001.yaml").write_text(yaml.safe_dump(bad), encoding="utf-8")
    result = runner.invoke(app, ["lint", str(tmp_path)])
    assert result.exit_code == 1
    assert "allowed_paths[0]: path 'acceptance/GO-001/test_x.py' is not inside target/" in (
        result.output
    )
    assert result.output.count("  fix: ") == 2
    assert "2 problems found" in result.output


@pytest.mark.parametrize(
    ("args", "task_id"),
    [
        (["run", "specs/GO-001.yaml"], "T2.9"),
        (["eval"], "T3.4"),
    ],
)
def test_unbuilt_commands_fail_and_name_their_task(args: list[str], task_id: str) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == NOT_IMPLEMENTED_EXIT_CODE
    assert "not implemented yet" in result.stderr
    assert task_id in result.stderr


def gate_result(*failing: str) -> GateResult:
    names = ["ruff check", "ruff format", "mypy", "pytest"]
    return GateResult(
        checks=[
            CheckResult(
                name=name,
                passed=name not in failing,
                summary="Found 1 error." if name in failing else "ok",
                details=f"{name} details",
            )
            for name in names
        ]
    )


def test_gates_reports_each_check_and_fails_with_details(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, object] = {}

    def fake(workspace: Path, *, mode: str, diff: str | None) -> GateResult:
        seen["mode"], seen["diff"] = mode, diff
        return gate_result("mypy")

    monkeypatch.setattr(cli, "run_gates", fake)
    result = runner.invoke(app, ["gates", str(tmp_path)])
    assert result.exit_code == 1
    assert seen["mode"] == "docker"
    assert "FAIL  mypy         Found 1 error." in result.output
    assert "PASS  pytest" in result.output
    assert "--- mypy ---\nmypy details" in result.output
    assert "ruff check details" not in result.output
    assert "1 of 4 checks failed." in result.output


def test_gates_passes_and_local_flag_selects_local_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, object] = {}

    def fake(workspace: Path, *, mode: str, diff: str | None) -> GateResult:
        seen["mode"], seen["diff"] = mode, diff
        return gate_result()

    monkeypatch.setattr(cli, "run_gates", fake)
    result = runner.invoke(app, ["gates", str(tmp_path), "--local"])
    assert result.exit_code == 0, result.output
    assert seen["mode"] == "local"
    assert "ok: all 4 checks passed" in result.output


def test_gates_on_a_bad_workspace_exits_3_with_the_reason(tmp_path: Path) -> None:
    result = runner.invoke(app, ["gates", str(tmp_path), "--local"])
    assert result.exit_code == GATES_ERROR_EXIT_CODE == 3
    assert "has no target" in result.stderr


def test_gates_reads_the_diff_file_and_passes_it_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, object] = {}

    def fake(workspace: Path, *, mode: str, diff: str | None) -> GateResult:
        seen["diff"] = diff
        return gate_result()

    monkeypatch.setattr(cli, "run_gates", fake)
    patch = tmp_path / "change.diff"
    text = "--- a/x.py\n+++ b/x.py\n"
    patch.write_bytes(text.encode("utf-8"))
    result = runner.invoke(app, ["gates", str(tmp_path), "--diff", str(patch)])
    assert result.exit_code == 0, result.output
    assert seen["diff"] == text


def test_gates_with_a_missing_diff_file_exits_3(tmp_path: Path) -> None:
    result = runner.invoke(app, ["gates", str(tmp_path), "--diff", str(tmp_path / "nope.diff")])
    assert result.exit_code == GATES_ERROR_EXIT_CODE
    assert "could not read --diff" in result.stderr
