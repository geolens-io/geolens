# Phase 1064: Close gate - Context

**Gathered:** 2026-05-20
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped per workflow.skip_discuss)

<domain>
## Phase Boundary

Verify all 27 prior remediation requirements satisfied through `e2e/sec-audit.spec.ts` + backend pytest smoke gates + a live Playwright MCP smoke pass against `localhost:8080`. Confirm `/sec-audit` re-run flips merge gate from BLOCK → PASS. Populate CHANGELOG `[1.4.0]`. Cut local tag `v1014` + public tag `v1.4.0`.

**Requirements:** SEC-CTRL-01 (1 total)

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion + user direction

1. **MCP smoke is orchestrator-driven, not executor-delegated** — per user instruction "Use Playwright MCP (orchestrator-driven) as needed during execution and run a live MCP smoke check at end-of-milestone before close gate." MCP belongs to the close-gate orchestrator. The single Plan 01 task that uses MCP should be a NEGATIVE-CONTROL on the visibility-filter surfaces (STAC `/stac/items/{id}` of a private record while anonymous → expect 404; `/datasets/{id}/related/` of a private record while anonymous → expect 404; embed iframe of a shared map from a non-allowlisted origin → expect CSP-block).

2. **No public tag push** — per A-04 convention from v1013, tags are cut locally only. User pushes manually with `git push origin v1014 v1.4.0` when ready.

3. **Pre-existing test failures exempt** — Phase 1061/1062/1063 reviews already documented 7 pre-existing failures (`test_maps_style_json.py`, `test_phase_275_compose_alignment.py`). These are tracked outside v1014 scope.

4. **CHANGELOG framing:** Security-headline. Group by HIGH / MEDIUM / LOW with one line per req (SEC-S0x / SEC-FU-0x label + 1-line summary). Include the AGENTS.md guardrail (SEC-GUARD-01) as a process improvement.

### Plan breakdown

- **Plan 01:** Smoke gates + regression suite (e2e/sec-audit.spec.ts + backend pytest + frontend lint + typecheck + i18n parity)
- **Plan 02:** Live Playwright MCP smoke (orchestrator-driven verification of visibility-filter + SSRF + embed CSP surfaces)
- **Plan 03:** Re-run `/sec-audit` mentally OR via a focused audit pass — confirm merge gate flips BLOCK → PASS
- **Plan 04:** CHANGELOG `[1.4.0]` + local tag `v1014` + public tag `v1.4.0`

</decisions>

<code_context>
## Existing Code Insights

- **CHANGELOG.md** convention: `[Unreleased]` block at top, promoted to `[N.N.N] — YYYY-MM-DD` on tag-cut. v1.3.0 entry (Phase 1060 close) is the precedent.
- **Tag convention:** local `v1014` + public `v1.4.0`. Created locally; user pushes manually.
- **e2e/sec-audit.spec.ts:** 18 tests pinning S01-S13 (extended in Phase 1061 Plan 05 + Phase 1062). Env-var-gated fixtures may need provisioning.

</code_context>

<deferred>
## Deferred Ideas

None — this is the close gate.

</deferred>
