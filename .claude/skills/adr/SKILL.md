---
name: adr
description: Write an Architecture Decision Record in docs/adr/ explaining a spec2ship design decision, the alternatives and the tradeoffs, in plain language Darnel can repeat in an interview.
argument-hint: "[decision title]"
---

Write an ADR for: $ARGUMENTS

1. Find the next number in `docs/adr/` (0001, 0002, …) and create `docs/adr/NNNN-<kebab-title>.md` from `docs/adr/0000-template.md`.
2. Fill every section from what's actually in the code and `docs/BUILD_LOG.md`. Don't invent benchmarks or numbers.
3. List at least two real alternatives and why each lost.
4. Keep it under 300 words. Short sentences, no jargon without a one-line definition.
5. Add a link to the ADR in `docs/ARCHITECTURE.md` under "Decisions" (create the section if needed).
6. Reply with the 30-second spoken version of the decision.
