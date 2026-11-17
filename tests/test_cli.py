"""Smoke tests for the spec2ship CLI surface."""

from __future__ import annotations

import pytest
import typer
from typer.core import TyperGroup
from typer.testing import CliRunner

from factory.cli import app

runner = CliRunner()

COMMANDS = {"lint", "gates", "run", "eval"}


def test_registers_exactly_the_planned_commands() -> None:
    group = typer.main.get_command(app)

    assert isinstance(group, TyperGroup)
    assert set(group.commands) == COMMANDS


def test_help_renders_every_command() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in COMMANDS:
        assert f" {command} " in result.output


def test_no_args_shows_help() -> None:
    result = runner.invoke(app, [])

    assert result.exit_code == 2  # click's no_args_is_help exits as a usage error
    assert "Usage" in result.output


@pytest.mark.parametrize(
    ("args", "task_id"),
    [
        (["lint", "specs/"], "T1.3"),
        (["gates", "runs/x/workspace"], "T1.5"),
        (["run", "specs/GO-001.yaml"], "T2.9"),
        (["eval", "--repeats", "2"], "T3.4"),
    ],
)
def test_unbuilt_commands_fail_loudly(args: list[str], task_id: str) -> None:
    result = runner.invoke(app, args)

    assert result.exit_code == 1
    assert "not implemented yet" in result.output
    assert task_id in result.output
