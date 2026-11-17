# spec2ship build plan

Work top to bottom, one task at a time (`/next`). Tick a task only when its **Done when** check passes and the reviewer has no must-fix items. Tasks marked ★ are the one-day cut line: if time runs short, finish those and move the rest to the README roadmap.

## Day 1: skeleton and gates (no LLM yet)

- [x] **T1.1 ★ Repo scaffold.** uv project on Python 3.12, package `factory`, Typer CLI entry point `spec2ship`, ruff, mypy (strict for `factory/`), pytest + pytest-cov with markers `docker` and `live` skipped by default, pre-commit, `.gitignore` (include `.env`, `runs/`), `.env.example`, MIT LICENSE, empty `docs/BUILD_LOG.md`.
  Done when: `uv run pytest -q` passes a smoke test and `uv run spec2ship --help` lists the commands.

- [x] **T1.2 ★ Target service.** `target/guard_ops`: FastAPI + SQLite with guards, sites/posts, shifts, tours with checkpoints and scan events, and incidents. About 15 tests in `target/tests`.
  Done when: target tests pass and `uv run uvicorn target.guard_ops.main:app` serves `/docs`.

- [ ] **T1.3 ★ Spec schema and spec gate.** `factory/spec.py`: Pydantic `Spec` (id, title, goal, acceptance_criteria ≥ 1, allowed_paths ≥ 1 glob, risk low/high, budget with max_attempts ≤ 5 and max_usd). `spec2ship lint <file|dir>` prints every problem with a fix hint.
  Done when: tests cover a valid spec and each rejection reason.

- [ ] **T1.4 Sandbox runner.** `factory/sandbox.py`: run a command in Docker (`python:3.12-slim` with deps), workspace mounted, `--network none`, CPU and memory limits, timeout, non-root user. Returns exit code, stdout, stderr, duration. A `local` mode (plain subprocess with timeout) for machines without Docker.
  Done when: `docker`-marked tests prove the timeout works and network calls fail.

- [ ] **T1.5 ★ Quality gates.** `factory/gates.py`: ruff check, ruff format --check, mypy, pytest with a coverage floor, run against a workspace. Returns `GateResult` made of `CheckResult(name, passed, summary, details)`. CLI `spec2ship gates <workspace>`.
  Done when: a deliberately broken change fails the right check and only that check.

- [ ] **T1.6 Diff policy.** `factory/policy.py`: given a unified diff, flag secrets (key patterns), banned calls in target code (`subprocess`, `eval`, `exec`, `os.system`) and deleted or skipped tests (removed `test_` functions, new `skip`/`xfail`). Runs as one more check in the gates.
  Done when: unit tests cover each rule with small sample diffs.

- [ ] **T1.7 ★ Specs and hidden tests.** 6 to 8 specs `specs/GO-001.yaml` … with matching suites in `acceptance/GO-00X/`. Ideas: missed tour checkpoints, shift overlap validation, incident severity filter, post coverage gaps, guard certification expiry, CSV export of scans. GO-008 deliberately requires a change outside its `allowed_paths`.
  Done when: `spec2ship lint specs/` passes and every acceptance suite **fails** on the unmodified target (proof it tests new behavior).

- [ ] **T1.8 CI.** `.github/workflows/ci.yml`: uv setup, ruff, mypy, pytest (no docker/live).
  Done when: green on push to `develop`.

## Day 2: the agent loop

- [ ] **T2.1 ★ LLM wrapper.** `factory/llm.py`: one function to call a model (LiteLLM or OpenRouter) and parse structured output into a Pydantic model, recording tokens and dollars into a `Usage` record. A `FakeLLM` with scripted responses for tests.
  Done when: unit tests run offline using `FakeLLM`.

- [ ] **T2.2 Graph skeleton.** `factory/graph.py`: `RunState` (spec, plan, workspace, diff, gate_result, acceptance_result, review, attempts, usage, events) and the full LangGraph with stub nodes, retry edge and budget stop.
  Done when: stub runs walk the happy path, the retry path and the budget-stop path.

- [ ] **T2.3 ★ Workspace and tools.** `factory/tools.py`: copy the target into `runs/<run-id>/workspace` (git init for clean diffs). Tools `read_file`, `write_file`, `list_files`, `run_tests` that refuse anything outside `allowed_paths` (glob match on resolved paths, block `..` and symlinks).
  Done when: tests prove traversal, symlink and out-of-scope writes are refused with clear errors.

- [ ] **T2.4 Planner node.** Prompt → `Plan(files_to_change, test_plan, risks)`. Files outside `allowed_paths` are rejected and the planner retries once.
  Done when: `FakeLLM` tests cover a valid plan and an out-of-scope plan.

- [ ] **T2.5 ★ Implementer node.** Tool-calling loop with a cap on tool calls per attempt. Writes code and its own tests. On retry it receives a short summary of the previous failures.
  Done when: a `live` run on GO-001 produces a diff (manual check).

- [ ] **T2.6 ★ Gates and acceptance nodes.** Run the gates in the sandbox. Then copy `acceptance/<spec-id>` into the workspace for that step only, run it, and delete it. Report failing test names, never test code.
  Done when: a test proves acceptance files never exist in the workspace during planner or implementer steps.

- [ ] **T2.7 Reviewer node.** Uses `S2S_REVIEWER_MODEL`. Rubric: correctness, scope, security, test quality. Returns `Review(verdict, comments[file, line, severity, reason])`. Changes requested loops back and counts as an attempt.
  Done when: `FakeLLM` tests cover approve and changes-requested.

- [ ] **T2.8 Tracing.** `factory/trace.py`: one JSONL event per node (timestamp, node, attempt, tokens, usd, summary) in `runs/<run-id>/trace.jsonl`. Langfuse only if its env vars are set.
  Done when: a run writes a readable trace and nothing breaks without Langfuse.

- [ ] **T2.9 ★ End-to-end CLI.** `spec2ship run <spec>` runs the graph and prints a summary table (stages, attempts, tokens, cost, outcome).
  Done when: GO-001 passes end to end on a live run.

## Day 3: release, evals and polish

- [ ] **T3.1 Risk scorer.** `factory/risk.py`: rules on paths touched, lines changed, auth or migration files, and the spec's own risk. Returns low/high with reasons.
  Done when: one unit test per rule.

- [ ] **T3.2 ★ Evidence bundle.** `factory/evidence.py` writes `runs/<run-id>/evidence.md`: spec, plan, gate table, acceptance result, review, attempts, tokens, cost, risk.
  Done when: generated for a real run and readable as a PR body.

- [ ] **T3.3 Release.** `factory/release.py`: branch, commit the workspace diff into the repo, `gh pr create` with `evidence.md` as the body, `needs-human` label when risk is high. Never merges. `--dry-run` is the default.
  Done when: a real PR is open on the spec2ship repo from GO-001.

- [ ] **T3.4 Evals.** `evals/run_all.py --repeats N`: runs every spec, writes `evals/results.md` with pass rate, mean attempts, mean cost and which stage caught each failure.
  Done when: `results.md` holds real numbers from a real run.

- [ ] **T3.5 Guardrail demo.** Show GO-008 being stopped by the allowlist, with its evidence.
  Done when: the README links to that evidence.

- [ ] **T3.6 (Optional) Factory Action.** `.github/workflows/factory.yml`: an issue labelled `spec` with a YAML spec in its body triggers a run that opens a PR.

- [ ] **T3.7 ★ Docs.** README (one-line pitch, architecture diagram, quickstart in 3 commands, results table, guardrails table, roadmap), `docs/ARCHITECTURE.md`, ADRs 0001 to 0003 (why LangGraph, why hidden tests, why a separate reviewer model).
  Done when: `/ship-check` passes its docs items.

- [ ] **T3.8 Demo recording.** 60 to 90 second terminal demo (asciinema or GIF) linked in the README. Darnel records this.

- [ ] **T3.9 ★ Ship.** `/ship-check` passes, merge `develop` → `main`, pin the repo, send the link.
