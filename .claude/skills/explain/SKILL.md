---
name: explain
description: Interview prep. Explain how a spec2ship component works and why it's built that way, as Darnel would say it to a senior engineer, with likely follow-up questions.
argument-hint: "[component or file, e.g. tools.py or 'hidden tests']"
---

Explain **$ARGUMENTS** from the actual code in this repo. Read the relevant files first; quote file:line where it helps.

Give me:

1. **30-second version.** What it does, the one design choice that matters, and why.
2. **2-minute version.** How data flows through it, which guardrail it enforces, what failure it prevents, and the tradeoff we accepted.
3. **Likely follow-ups.** 4 or 5 questions a senior AI or platform engineer would ask (scaling, failure modes, cost, security, how it changes for 50 teams), each with a short honest answer. If the honest answer is "not handled yet", say so and say how I'd add it.
4. **Weak spot.** The one thing I should admit before they find it, and how I'd phrase it.

Plain language, short sentences. No marketing words.
