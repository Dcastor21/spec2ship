# Building spec2ship with Claude Code

## One-time setup (Windows 11)

1. Work inside **WSL2 (Ubuntu)**: Docker Desktop's WSL backend, uv and paths all behave like Linux there. Open the folder in VS Code with the WSL extension.
2. Install uv (`curl -LsSf https://astral.sh/uv/install.sh | sh`), Docker Desktop, the GitHub CLI (`gh auth login`), and Claude Code.
3. Create the repo and drop this kit in:
   ```bash
   mkdir spec2ship && cd spec2ship
   git init -b main && git switch -c develop
   # unzip the kit here so CLAUDE.md, docs/ and .claude/ sit at the repo root
   git add -A && git commit -m "chore: add Claude Code kit and build plan"
   ```
4. Create the GitHub repo (`gh repo create spec2ship --public --source . --push`). That first push is yours; Claude Code is set to ask before any push.
5. Start Claude Code in the repo, run `/hooks` to confirm the two hooks are registered, and `/agents` to confirm `reviewer` shows up.

What the kit gives you:

| Piece | What it does |
| --- | --- |
| `CLAUDE.md` | Project rules, pipeline, guardrail invariants, commands |
| `docs/PLAN.md` | 26 tasks with "Done when" checks; ★ marks the one-day cut |
| `/next [task]` | Runs one task end to end: plan, build, gate, review, tick, log, commit |
| `/gate` | Runs every check and reports; fixes nothing |
| `reviewer` subagent | Independent read-only review of each diff |
| `/adr <title>` | Writes a decision record you can repeat in an interview |
| `/explain <part>` | Interview prep from the real code, with follow-up questions |
| `/ship-check` | Pre-send checklist before the link goes to the recruiter |
| PreToolUse hook | Blocks edits to `.env`, `.git/`, and `acceptance/` once frozen |
| PostToolUse hook | Runs ruff on every edited Python file and feeds errors back |

The kit applies spec2ship's own idea to Claude Code: a spec (`PLAN.md`), deterministic gates (hooks and `/gate`), an independent reviewer, and evidence (`BUILD_LOG.md`, ADRs). That's a good story for the interview too.

## 1. Kickoff prompt (paste into the first session, in plan mode)

Switch to plan mode first (Shift+Tab cycles modes), then paste:

```
You're helping me build spec2ship, a portfolio repo for a Senior AI Engineer role. The team I'm interviewing with is building a "software factory": AI agents carry work from a well-formed spec through code, tests, review and release, inside guardrails engineers design. spec2ship is a small, working version of that, and I have about 3 days.

Read CLAUDE.md and docs/PLAN.md first. They are the source of truth.

Ground rules:
- Agents propose, deterministic gates decide. Never make a gate pass by weakening it. That applies to you too.
- One task at a time from docs/PLAN.md, in order, using the /next workflow: restate the goal and "Done when", plan, build with tests, run gates, get the reviewer subagent's review, tick the task, log it in docs/BUILD_LOG.md, commit locally.
- When you choose between approaches, give me the tradeoff in 2–3 plain sentences. I have to explain every decision in interviews.
- Ask before adding dependencies. Never push.
- I'm on Windows 11 working in WSL2. Keep everything cross-platform.

Before writing any code:
1. Review CLAUDE.md and PLAN.md and flag up to 5 things that are unclear, risky, or likely to blow the 3-day budget, each with a suggested fix.
2. Recommend the dependency set for the whole project (LangGraph, Pydantic, Typer, LiteLLM or OpenRouter, FastAPI, pytest-cov, etc.) with one line on why each, and which models you'd use for implementer vs reviewer given I want to keep cost near $0.
3. Propose the exact steps for T1.1.

Wait for my OK, then run /next T1.1.
```

## 2. Start of each work session

```
New session. Read CLAUDE.md, the unchecked tasks in docs/PLAN.md, and the last 10 lines of docs/BUILD_LOG.md. Tell me in 3 lines where we are and what's next, then run /next.
```

## 3. After the hidden tests exist (end of T1.7)

Freeze them so nobody, Claude included, can edit the grader:

```bash
touch .claude/FREEZE_ACCEPTANCE
```

## 4. When a task goes sideways

```
Stop. Don't change more code yet. Show me: the failing check, the smallest reproduction, your top 2 hypotheses with how you'd confirm each, and whether the task in PLAN.md itself needs to change. Then wait.
```

## 5. If you're out of time (one-day cut)

```
We're switching to the one-day cut. List the ★ tasks in docs/PLAN.md that aren't done, estimate each in hours, and propose the order. Move every non-★ task into a "Roadmap" section of the README with one line each on what it would add. Then continue with /next on the first ★ task.
```

## 6. Before the interview

```
/explain the full pipeline
/explain tools.py
/explain hidden tests
/explain reviewer
```

Then:

```
Act as a senior engineer on a team building an AI software factory. Interview me about spec2ship for 15 minutes: one question at a time, follow up on weak answers, and at the end tell me the 3 answers I should tighten.
```

## 7. Before sending the link

```
/ship-check
```
