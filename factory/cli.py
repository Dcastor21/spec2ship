"""Command-line entry point: `spec2ship lint | gates | run | eval`.

Each command is a stub until the task named in its error message lands, so
`--help` shows the full planned surface and a premature call fails loudly
instead of silently doing nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer

app = typer.Typer(
    name="spec2ship",
    help="A spec goes in, a reviewed pull request comes out.",
    no_args_is_help=True,
    add_completion=False,
)


def _not_implemented(command: str, task_id: str) -> NoReturn:
    typer.echo(
        f"spec2ship {command}: not implemented yet. It lands in {task_id} (see docs/PLAN.md).",
        err=True,
    )
    raise typer.Exit(code=1)


@app.command()
def lint(
    path: Annotated[Path, typer.Argument(help="A spec file or a directory of specs.")],
) -> None:
    """Check specs against the spec gate and print every problem with a fix hint."""
    _not_implemented("lint", "T1.3")


@app.command()
def gates(
    workspace: Annotated[Path, typer.Argument(help="Workspace to run the quality gates in.")],
) -> None:
    """Run ruff, format, mypy and pytest with coverage against a workspace."""
    _not_implemented("gates", "T1.5")


@app.command()
def run(
    spec: Annotated[Path, typer.Argument(help="Spec file to build and ship.")],
) -> None:
    """Run the full factory on one spec: plan, implement, gate, review, release."""
    _not_implemented("run", "T2.9")


@app.command(name="eval")
def eval_(
    repeats: Annotated[int, typer.Option(min=1, help="Runs per spec.")] = 1,
) -> None:
    """Run every spec and report pass rate, attempts and cost."""
    _not_implemented("eval", "T3.4")
