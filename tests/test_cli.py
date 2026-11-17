"""Smoke tests for the spec2ship CLI skeleton (T1.1)."""

from __future__ import annotations

import re
from importlib.metadata import entry_points

import pytest
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


@pytest.mark.parametrize(
    ("args", "task_id"),
    [
        (["lint", "specs"], "T1.3"),
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
