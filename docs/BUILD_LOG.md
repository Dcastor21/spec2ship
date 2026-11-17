# Build log

One line per finished task, newest last. Format: `YYYY-MM-DD · TX.Y · what changed · key decision and why`.

2026-11-17 · T1.1 · uv project on Python 3.12, `factory` package, Typer CLI `spec2ship` with stub lint/gates/run/eval, ruff (incl. bandit S rules), strict mypy, pytest + coverage floor 80, pre-commit, .gitignore, .env.example, MIT LICENSE; project moved from nested spec2ship/ to repo root so .claude/, pre-commit and CI load · Stub commands exit 1 naming their task so `--help` shows the planned surface and nothing silently succeeds; `--cov` lives in addopts so plain `pytest -q` (and CI) enforces the floor (use `--no-cov` for single files or `-m docker` subsets); pre-commit hooks are not active until `uv run pre-commit install` is run by hand.
