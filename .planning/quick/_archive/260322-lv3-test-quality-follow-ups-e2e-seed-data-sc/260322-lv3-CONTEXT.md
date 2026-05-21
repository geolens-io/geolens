# Quick Task 260322-lv3: Test & Quality follow-ups - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Task Boundary

Three test & quality items:

1. **E2e seed data script** — Playwright tests fail because dev DB lacks required datasets. Create a reliable seed script that populates test fixtures (Admin 0 Countries, etc.) so e2e tests can run.
2. **Retroactive verification of 260320-m42 and 260321-f9l** — Both show "Complete" not "Verified". Run code-level verification to confirm they're solid and update STATE.md.
3. **Non-spatial CSV end-to-end integration test** — Extend the CSV upload test to verify the full pipeline: upload → ingest task → table created → record_type='table' → queryable via features API.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
- Seed script format (Python script, SQL fixture, or pytest fixture)
- Which datasets the seed script creates
- Verification approach for the two retroactive items
- Whether the CSV e2e test uses the existing test DB or a fresh fixture

</decisions>
