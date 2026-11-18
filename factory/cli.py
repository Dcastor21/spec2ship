"""spec2ship command-line interface.

Commands not built yet are stubs: they exit non-zero and name their
docs/PLAN.md task, so nothing reports success before it works.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from factory import __version__
from factory.gates import GateError, run_gates
from factory.sandbox import SandboxError
from factory.spec import lint_path

# The app's help text comes from the `main` callback docstring below.
app = typer.Typer(name="spec2ship", no_args_is_help=True, add_completion=False)

# Click already uses exit code 2 for usage errors, so "not built yet" gets 1.
NOT_IMPLEMENTED_EXIT_CODE = 1
# 1 means checks failed; 2 is Click's usage error; 3 means the gates could not run.
GATES_ERROR_EXIT_CODE = 3


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
    report = lint_path(path)
    for problem in report.problems:
        typer.echo(problem.render())
    if report.problems:
        count = len(report.problems)
        typer.echo(f"{count} problem{'s' if count != 1 else ''} found. Fix them and re-run.")
        raise typer.Exit(code=1)
    count = len(report.specs)
    typer.echo(f"ok: {count} spec{'s' if count != 1 else ''} passed the spec gate")


@app.command()
def gates(
    workspace: Annotated[Path, typer.Argument(help="Workspace directory to check.")],
    local: Annotated[
        bool,
        typer.Option("--local", help="Run without Docker. NOT isolated: trusted code only."),
    ] = False,
) -> None:
    """Run the quality gates on a workspace."""
    try:
        result = run_gates(workspace, mode="local" if local else "docker")
    except (GateError, SandboxError) as exc:
        typer.echo(f"spec2ship gates: {exc}", err=True)
        raise typer.Exit(code=GATES_ERROR_EXIT_CODE) from exc
    for check in result.checks:
        typer.echo(f"{'PASS' if check.passed else 'FAIL'}  {check.name:<12} {check.summary}")
    for check in result.checks:
        if not check.passed:
            typer.echo(f"\n--- {check.name} ---\n{check.details}")
    if not result.passed:
        typer.echo(f"\n{len(result.failed)} of {len(result.checks)} checks failed.")
        raise typer.Exit(code=1)
    typer.echo(f"\nok: all {len(result.checks)} checks passed")


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
