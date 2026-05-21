# Quick Task 260322-kec: FK enhancements + panel activation + record_type validation - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Task Boundary

Part A of 3-part follow-up series. Focus: FK relationship feature enhancements.

1. **FK auto-detection** — When a dataset has columns with `semantic_role: 'foreign_key'` in column_info, auto-detect potential FK targets by matching column names/values across other datasets
2. **RelatedRecordsPanel read-only activation** — Currently only activates via drawing store (editing mode). Should also activate when user clicks a feature in read-only mode (e.g., from feature popup or attribute table row click)
3. **record_type='table' validation** — Verify the migration 0002 approach is correct and non-spatial datasets properly get `record_type='table'` through the full pipeline

</domain>

<decisions>
## Implementation Decisions

### Scope
- This task covers items 1, 2, and 4 from the follow-up list
- Excel/JSON ingestion deferred to backlog (too large for quick task)

### Claude's Discretion
- FK auto-detection matching strategy (column name matching vs. value sampling)
- How read-only feature selection integrates with existing popup/table click handlers
- Whether record_type validation needs code changes or just verification

</decisions>

<specifics>
## Specific Ideas

- Existing `column_info` already has `semantic_role: 'foreign_key'` — leverage this for detection
- Drawing store has `selectedFeature` with `{ gid: number }` — need a parallel path for read-only feature selection
- Feature popup already shows feature attributes — could add "View related records" action there

</specifics>
