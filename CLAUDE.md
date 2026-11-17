# spec2ship

spec2ship is a small, working **software factory**: a spec goes in, and a reviewed pull request comes out. AI agents do the work inside guardrails, and deterministic gates decide what passes. It is a portfolio project for a Senior AI Engineer role on a team building exactly this, so every part must be explainable, tested and honest.

**Core principle: agents propose, deterministic gates decide.**

## Pipeline

```
spec (YAML) → spec gate → planner → implementer → quality gates → hidden acceptance tests → reviewer → risk score → release PR
                                         ↑______________ retry on any failure, max_attempts (default 3) ______________|
```

- A spec that fails the spec gate goes back to its author and costs zero tokens.
- The implementer never sees `acceptance/`. On failure it gets failing test **names** only.
- The reviewer is a **different model** with a rubric. It approves or requests changes.
- Release only **opens** a PR with an evidence bundle. A human merges.

## Repo map

```
factory/            the factory itself (Python package, CLI entry: spec2ship)
  spec.py           Pydantic Spec model + spec gate
  graph.py          LangGraph state machine
  agents/           planner.py, implementer.py, reviewer.py
  llm.py            the only place models are called (LiteLLM/OpenRouter), tracks tokens and cost
  tools.py          workspace tools behind the path allowlist
  sandbox.py        Docker runner: --network none, limits, timeout, non-root
  gates.py          ruff, format, mypy, pytest + coverage
  policy.py         diff policy: secrets, banned calls, deleted/skipped tests
  risk.py           low/high risk with reasons
  evidence.py       runs/<run-id>/evidence.md
  release.py        branch + gh pr create (never merges)
  trace.py          runs/<run-id>/trace.jsonl (+ optional Langfuse)
  cli.py            spec2ship lint | gates | run | eval
target/guard_ops/   FastAPI demo service the factory modifies
target/tests/       the target's own tests
specs/              GO-001 ... GO-008 example specs
acceptance/         hidden acceptance tests, one folder per spec id
evals/              run_all.py → results.md
docs/               PLAN.md (task list), BUILD_LOG.md, ARCHITECTURE.md, adr/
runs/               per-run artifacts (gitignored)
```

## Commands

```bash
uv sync                                   # install
uv run pytest -q                          # tests (docker and live markers skipped by default)
uv run pytest -q -m docker                # sandbox tests, needs Docker running
uv run ruff check . && uv run ruff format --check .
uv run mypy factory
uv run spec2ship lint specs/
uv run spec2ship run specs/GO-001.yaml    # live run, needs API keys in .env
uv run python evals/run_all.py --repeats 3
```

## Conventions

- Python 3.12, uv, type hints everywhere, `mypy --strict` on `factory/`.
- Pydantic v2 models for everything that crosses a boundary: Spec, Plan, CheckResult, GateResult, Review, Evidence, Usage.
- LangGraph nodes take state and return updates. Side effects live only in `tools.py`, `sandbox.py`, `release.py` and `trace.py`.
- All model calls go through `factory/llm.py`. Models come from env: `S2S_PLANNER_MODEL`, `S2S_IMPLEMENTER_MODEL`, `S2S_REVIEWER_MODEL`. The reviewer default must differ from the implementer default.
- Unit tests never hit the network: use the fake LLM in `factory/llm.py`. Real-model tests are marked `@pytest.mark.live` and skipped by default.
- Small modules, short functions, no abstractions until there are two real uses.
- Clear errors: every rejection says what failed and how to fix it.
- Git: work on `develop`, conventional commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`), merge to `main` by PR.

## Guardrail invariants: never break these

1. Implementer tools refuse any path outside `spec.allowed_paths`, including `..` and symlinks. Enforced in code and covered by tests.
2. `acceptance/` is never present in the workspace while the planner or implementer runs.
3. Sandbox runs use no network, a timeout and resource limits.
4. `max_attempts` and `max_usd` are always enforced. Hitting a budget stops the run and writes evidence. It never continues silently.
5. Never make a gate pass by deleting, skipping or weakening tests, lint rules, coverage floors or type settings. This applies to you, Claude Code, as much as to the factory's agents.
6. No secrets in code, logs, traces or evidence. Keys come from env; `.env` is gitignored.
7. Release never merges. It opens a PR, labelled `needs-human` when risk is high.

## How to work in this repo (Claude Code)

- `docs/PLAN.md` is the task list. Do one task at a time, in order, using `/next`.
- Before coding, restate the task and its **Done when** check. If it's ambiguous, ask one question.
- After coding: run `/gate`, then ask the `reviewer` subagent to review the diff, fix must-fix items, tick the task, and add a line to `docs/BUILD_LOG.md`.
- **Explain the why.** When you choose between approaches, give the tradeoff in 2 or 3 plain sentences. Darnel must be able to defend every decision in an interview. Record significant ones with `/adr`.
- Ask before adding a dependency. Prefer the stdlib and what's already installed.
- If `PLAN.md` is wrong or underspecified, say so and propose an edit. Don't improvise silently.
- Never push. Never edit `.git/` or `.env`. Commit locally only when a task's gates pass.

## Domain: guard_ops

`target/guard_ops` models physical-security workforce operations: guards, sites and posts, shifts, guard tours with checkpoints and scan events, and incident reports. Keep it small and realistic. It is a demo target, not a claim about any company's real system.

## Environment

Darnel is on Windows 11. Prefer WSL2 (Ubuntu) for development so Docker, uv and paths behave like Linux. Keep scripts cross-platform: Python over bash, `pathlib` over string paths.
