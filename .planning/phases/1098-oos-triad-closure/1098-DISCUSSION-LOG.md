# Phase 1098: OOS Triad Closure - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-24
**Phase:** 1098-oos-triad-closure
**Areas discussed:** OOS-01 fix shape, OOS-02 fix shape, OOS-03 fix layer, Plan structure

---

## Gray Area Selection

User selected all 4 presented gray areas (multiSelect). Also added a meta-instruction: *"use /gsd-autonomous and playwright MCP to get to the end of the milestone"* — captured as D-15 in CONTEXT.md (autonomous lifecycle directive for the v1023 chain).

---

## OOS-01 fix shape — maps/router.py LOC cap

| Option | Description | Selected |
|--------|-------------|----------|
| Decompose into facade + sub-routers | Phase 226/238/252 pattern. ~0.5-1 day. Cleanest; aligns with test's stated intent. Higher blast radius. | |
| Raise cap to 1850 (one final time) | 1-line edit. Smallest-milestone purity. Risk: 4th raise in a row, the test was designed to FORCE decomposition. | |
| Hybrid — trim before bumping | Audit for extractable surface (long docstrings, unused imports, dead code) to land back under 1800. If fails, raise cap. Compromise. | ✓ (Recommended, confirmed) |

**User's first response:** "What do you suggest?"

**Claude's recommendation rationale:**
- v1023 charter is explicit smallest-milestone hygiene; full decomposition blooms scope and is high blast radius for autonomous mode.
- The cap was raised at v1013 with "queued for v1014" — the pattern proves a hygiene milestone is the wrong vehicle for decomposition.
- 7 LOC over is small enough that mechanical cleanup likely clears it.
- Worst case fallback (cap-raise + backlog item) is 1-line + 1 backlog entry — autonomous-safe.

**User's choice:** "Yes, hybrid — trim first, cap-raise fallback (Recommended)"

**Notes:** Captured as D-01/D-02/D-03 in CONTEXT.md. Backlog entry shape pre-drafted in CONTEXT.md `<deferred>` section to make the fallback fully autonomous.

---

## OOS-02 fix shape — README signature-maps test

| Option | Description | Selected |
|--------|-------------|----------|
| Remove the test | Delete test_readme_signature_maps_list_intact entirely. The API-04/M-23 invariant it pinned was retired with the demo overlay apparatus. 8 sibling tests still cover real README invariants. | ✓ (Recommended) |
| Restore the signature-stories section to README | Revert README portion of 4a7d1a29. Adds back references to fixtures that no longer ship. Doc-lying regression. | |
| Demote test to a structural-presence assertion | Rewrite to assert SOMETHING still load-bearing (e.g., '## Features' section exists). Preserves a pin slot but the new assertion would be arbitrary. | |

**User's choice:** "Remove the test (Recommended)"

**Notes:** Captured as D-04/D-05/D-06/D-07. No README content change; sibling tests not swept (8 still pass).

---

## OOS-03 fix layer — SSRF flake

| Option | Description | Selected |
|--------|-------------|----------|
| Defensive rewrite — assert behavior, not identity | Replace identity check with behavioral assertion (drive 3xx through hook pipeline, assert SSRFError). Immune to module-level mock-patch contamination. Tests the actual contract. | ✓ (Recommended) |
| Hunt the leaker via bisect | Binary-search 70+ test files alphabetically before test_ssrf_redirect.py to find the contamination source. Hours of investigation. Risk: leaker might be a multi-test interaction. | |
| Autouse fixture that snapshots/restores security module state | Defensive against leakers without finding them. Doesn't fix the actual contamination — just isolates this test. | |

**User's choice:** "Defensive rewrite — assert behavior, not identity (Recommended)"

**Notes:** Captured as D-08/D-09/D-10/D-11. REQUIREMENTS.md framing "fix at production-code site" doesn't quite apply since production code is already correct — this is documented in CONTEXT.md domain section. Leaker hunt deferred (possibly never needed) in CONTEXT.md `<deferred>`.

---

## Plan structure

| Option | Description | Selected |
|--------|-------------|----------|
| 1 plan, 3 atomic edits + 1 verify gate | Plan 1098-01 covers all 3 OOS. Single ~37 min verify gate. Phase 1096 precedent. | ✓ (Recommended) |
| 3 plans, one per OOS (sequential) | 3× verify gate cost (~111 min total). Easier per-plan rollback. Misaligned with hygiene-milestone precedent. | |
| 2 plans: OOS-01+02 together, OOS-03 separately | Splits verification cost in half. Slight rationale gain if OOS-03 turns out to need more thought. | |

**User's choice:** "1 plan, 3 atomic edits + 1 verify gate (Recommended)"

**Notes:** Captured as D-12/D-13/D-14. Task sequencing rationale (run OOS-01 first since it has highest uncertainty with the trim/cap-fallback branch) captured in CONTEXT.md `<specifics>`.

---

## Claude's Discretion

Three sub-decisions delegated to planner:

1. **OOS-01 trim technique** — which mechanical cleanup approach (docstring compression vs import reorganization vs comment removal) per task at hand. Lowest-risk shape preferred.
2. **OOS-03 exact test fixture shape** — whether to drive 3xx through `client._event_hooks` iteration or invoke `_revalidate_redirect()` directly. Existing test patterns at `test_ssrf_redirect.py:22-97` serve as templates.
3. **OOS-03 constructor-arg assertions** — whether to keep `follow_redirects is True` + `max_redirects == 5` checks alongside the new behavioral assertion. D-11 says optional; planner picks.

## Deferred Ideas

1. **Phase 999.x — maps/router.py decomposition** — promoted to ROADMAP.md backlog IFF OOS-01 trim falls short. Pre-drafted entry shape in CONTEXT.md `<deferred>`.
2. **OOS-03 leaker hunt** — parked indefinitely. Defensive rewrite addresses the symptom permanently; cost-of-investigation high, value-of-fix low.
3. **Sibling sweep in test_phase_275_readme_accuracy.py** — deferred (probably never needed). 8 siblings all pass at discuss time.

## Meta-instruction (out-of-band)

User requested `/gsd-autonomous --use-playwright-mcp` for full v1023 lifecycle (Phase 1098 → 1099 → 1100 → audit → complete → cleanup). Autonomous-safe choices preferred at every fork — reflected in CONTEXT.md D-15 and in each gray-area recommendation (e.g., D-01's trim-with-fallback over decompose; D-08's behavioral rewrite over leaker-hunt).
