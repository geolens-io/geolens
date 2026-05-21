# Quick Task 260322-ljk: Resolve outstanding audit gaps - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Task Boundary

Part C of 3-part follow-up series. Resolve two audits with non-Verified status:

1. **260322 vector detail map (Gaps):** Gap 1 (multi-part geometry) was fixed by 260320-m42 — verify it's resolved. Gap 2 (stale Playwright selectors) needs fixing so e2e tests actually run.
2. **260319-qu1 detail data page map (Needs Review):** 6 human verification items requiring live browser. Run Playwright tests to confirm rendering, editing, fullscreen behavior.

</domain>

<decisions>
## Implementation Decisions

### Approach
- Fix stale Playwright selectors to unblock e2e test suite
- Run Playwright tests to verify live browser behavior for both audits
- Update audit statuses to Verified once gaps are confirmed resolved

### Claude's Discretion
- Which Playwright selectors need updating
- Whether to add new e2e test cases or fix existing ones
- How to verify the multi-part geometry fix is still intact

</decisions>
