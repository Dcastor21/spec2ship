---
name: ship-check
description: Pre-release checklist for spec2ship before the repo link goes to a recruiter or hiring manager. Reports pass or fail per item; fixes nothing unless asked.
disable-model-invocation: true
---

Check each item and report a pass/fail list with a one-line reason. Fix nothing unless I ask.

**Code**
- [ ] `/gate` checks all pass on a clean checkout (`uv sync` first).
- [ ] No secrets: search for key patterns (`sk-`, `api_key =`, `Bearer `) in tracked files; `.env` is gitignored and not tracked.
- [ ] No `skip`/`xfail` added without a reason comment; coverage floor unchanged from `pyproject.toml` history.

**Evidence**
- [ ] `evals/results.md` exists and its numbers come from a real run (timestamp and run IDs present).
- [ ] At least one real PR opened by the factory exists and is linked in the README.
- [ ] GO-008's blocked run evidence is linked in the README.

**Docs**
- [ ] README has: one-line pitch, architecture diagram, 3-command quickstart, results table, guardrails table, roadmap, MIT license note.
- [ ] `docs/ARCHITECTURE.md` and ADRs 0001–0003 exist and are linked.
- [ ] Every README command actually works when copy-pasted.
- [ ] Demo recording linked (or flagged as Darnel's to-do).

**Repo**
- [ ] CI badge green on `main`.
- [ ] Repo description and topics set (suggest them).
- [ ] `develop` merged into `main`.

End with: ready to send, or the 3 things to fix first.
