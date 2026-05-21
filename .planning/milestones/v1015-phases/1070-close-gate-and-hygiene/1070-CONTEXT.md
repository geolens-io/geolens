# Phase 1070: Close Gate + Hygiene - Context

**Gathered:** 2026-05-20
**Status:** Closed
**Mode:** Auto-generated (autonomous mode)

<domain>
## Phase Boundary

Three hygiene closures + the v1015 pre-tag gates + tag cut:

1. **HYG-01:** Create 5 missing pending-todo files for v1014 deferred INFO findings.
2. **HYG-02:** Tick the 6 stale REQUIREMENTS.md checkboxes for already-implemented v1014 requirements (discovery: already ticked).
3. **HYG-03:** Close the 2 cheap v1014 INFO todos inline (HTTP 305 + GDAL_HTTP_FOLLOWLOCATION comment).

Pre-tag gates per the v1015 seed:
- typecheck 0 / vitest passing / e2e:smoke:builder pass / i18n parity / backend pytest passing
- Live Playwright MCP smoke on `localhost:8080` driven by orchestrator
- CHANGELOG `[1.5.0]` populated

Then cut local tag `v1015` + public tag `v1.5.0`.

</domain>

<decisions>
## Implementation Decisions

- Live MCP runs orchestrator-driven per user decision 2026-05-20 (AskUserQuestion).
- Container rebuild + restart was needed before smoke because the api image at smoke-time predates v1015.
- HYG-02 discovery: all 6 boxes were already ticked at v1014 archive — no retroactive edit needed; documented in HYG-02 SUMMARY.

</decisions>

<code_context>
## Existing Code Insights

- Pre-existing close-gate pattern from v1014 (Phase 1064) — CHANGELOG promotion, tag at the close-gate commit.

</code_context>

<specifics>
## Specific Ideas

- Tag pushes (`git push origin v1015 v1.5.0`) are explicitly NOT done by this phase — per v1014 precedent A-04, tags are local-only at close; the operator decides when to push public tags.

</specifics>

<deferred>
## Deferred Ideas

- Push tags to origin — operator decides when.

</deferred>
