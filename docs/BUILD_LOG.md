# Build log

One line per finished task, newest last. Format: `YYYY-MM-DD · TX.Y · what changed · key decision and why`.

- 2026-11-17 · T1.1 · uv project (Python 3.12, uv_build, `factory/` at the root), Typer CLI with `lint`/`gates`/`run`/`eval` stubs that exit 1 and name their task, ruff (incl. bandit `S`), mypy strict on `factory/`, pytest + coverage (floor 85%, now 100%), local pre-commit hooks, `.gitignore`, `.gitattributes`, `.env.example`, MIT LICENSE; `lint_on_edit.py` hook now passes `--` before the payload path · Gate settings are fixed on day one so they can only get stricter. pytest never collects `acceptance/` or `runs/`, so the hidden tests can't turn the factory's own run red or leak in. `.gitattributes` forces LF because T1.6 parses diffs. Open for T1.2: keep `target/tests` in `testpaths` (needs `--import-mode=importlib` and target deps in this venv) or give the target its own pytest config.
