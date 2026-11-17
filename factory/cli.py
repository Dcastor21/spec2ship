"""spec2ship command-line interface.

Every command is a stub until its docs/PLAN.md task lands. A stub exits
non-zero and names that task, so nothing reports success before it works.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from factory import __version__

# The app's help text comes from the `main` callback docstring below.
app = typer.Typer(name="spec2ship", no_args_is_help=True, add_completion=False)

# Click already uses exit code 2 for usage errors, so "not built yet" gets 1.
NOT_IMPLEMENTED_EXIT_CODE = 1


def _not_implemented(command: str, task_id: str) -> NoReturn:
    typer.echo(
        f"spec2ship {command}: not implemented yet. It lands in {task_id} (see docs/PLAN.md).",
        err=True,
    )
    raise typer.Exit(code=NOT_IMPLEMENTED_EXIT_CODE)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"spec2ship {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Spec in, reviewed pull request out. Agents propose, deterministic gates decide."""


@app.command()
def lint(
    path: Annotated[Path, typer.Argument(help="A spec file or a directory of specs.")],
) -> None:
    """Check specs against the spec gate."""
    _not_implemented("lint", "T1.3")


@app.command()
def gates(
    workspace: Annotated[Path, typer.Argument(help="Workspace directory to check.")],
) -> None:
    """Run the quality gates on a workspace."""
    _not_implemented("gates", "T1.5")


@app.command()
def run(
    spec: Annotated[Path, typer.Argument(help="Spec file to build.")],
) -> None:
    """Run the factory on one spec, end to end."""
    _not_implemented("run", "T2.9")


@app.command(name="eval")
def eval_() -> None:
    """Run every spec and report pass rate and cost."""
    _not_implemented("eval", "T3.4")
