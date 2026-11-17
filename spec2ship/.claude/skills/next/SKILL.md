---
name: next
description: Pick up the next unchecked task in docs/PLAN.md (or the task ID given), implement it end to end, run the gates, get an independent review, and tick it off.
argument-hint: "[task-id, e.g. T1.3]"
disable-model-invocation: true
---

Work one task from `docs/PLAN.md`, start to finish.

1. **Pick.** If "$ARGUMENTS" names a task ID, use it. Otherwise take the first unchecked task. Read `docs/BUILD_LOG.md` for what's already done.
2. **Restate.** In 2 or 3 lines: the goal, the files you expect to touch, and the exact **Done when** check. If anything is ambiguous, ask me one question and stop.
3. **Decide.** If there's a real design choice, give the options and the tradeoff in 2 or 3 sentences, pick one, and say why. Ask before adding any dependency.
4. **Build.** Write the tests first where practical, then the code. Stay inside the task's scope.
5. **Gate.** Run, in order: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy factory`, `uv run pytest -q`. Fix failures, at most 3 rounds. Never delete, skip or weaken a test, lint rule, coverage floor or type setting to get green. If still red after 3 rounds, stop and report what's failing and your best diagnosis.
6. **Review.** Ask the `reviewer` subagent to review the diff for this task ID. Fix every must-fix item, then re-run the gates.
7. **Close.** Tick the task in `docs/PLAN.md`. Append to `docs/BUILD_LOG.md`: date, task ID, what changed, the key decision and why. If the decision is architectural, run `/adr` for it.
8. **Commit.** `git add` the task's files and commit on the current branch with a conventional commit message (`feat(spec): add spec gate (T1.3)`). Never push.
9. **Report.** End with: what changed, gate results, reviewer verdict, a 2-sentence "why it's built this way" I can say in an interview, and the next task ID.
