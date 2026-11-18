"""Tests for the spec2ship CLI: wiring, help, version, lint, and the remaining stubs."""

from __future__ import annotations

import re
from importlib.metadata import entry_points
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from factory import __version__
from factory.cli import NOT_IMPLEMENTED_EXIT_CODE, app

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
        (["gates", "runs/demo/workspace"], "T1.5"),
        (["run", "specs/GO-001.yaml"], "T2.9"),
        (["eval"], "T3.4"),
    ],
)
def test_unbuilt_commands_fail_and_name_their_task(args: list[str], task_id: str) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == NOT_IMPLEMENTED_EXIT_CODE
    assert "not implemented yet" in result.stderr
    assert task_id in result.stderr
