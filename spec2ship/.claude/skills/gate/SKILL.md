---
name: gate
description: Run every quality gate for spec2ship (lint, format, types, tests with coverage) and report pass or fail per check without changing code.
disable-model-invocation: true
allowed-tools: Bash(uv run *)
---

Run these in order and keep going even if one fails:

1. `uv run ruff check .`
2. `uv run ruff format --check .`
3. `uv run mypy factory`
4. `uv run pytest -q --cov=factory --cov-report=term-missing`
5. If "$ARGUMENTS" contains `docker`: `uv run pytest -q -m docker`

Report a table: check, pass/fail, one-line summary (error count, failing test names, coverage %). Then list the 3 most important failures with file:line.

Do **not** fix anything unless I ask. This command reports; it doesn't repair.
