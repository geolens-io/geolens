# Quick Task 260322-hv0: Non-spatial table support (related records focus) - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Task Boundary

Review and implement non-spatial table support with related records (foreign-key joins) as the primary focus. Covers ingestion of CSV files, backend relationship modeling, and frontend data grid presentation.

</domain>

<decisions>
## Implementation Decisions

### Related Records Definition
- Foreign-key joins between tables — e.g., parcels.owner_id → owners.id
- Auto-detect from column_info `foreign_key` type or let users define manually
- NOT parent-child hierarchy, NOT embedding-similarity (that already exists as "related datasets")

### Ingestion Scope
- CSV only for now — most common non-spatial format
- ogr2ogr can handle CSV natively
- Can extend to Excel/JSON in a future task

### Table UI Presentation
- Data grid tab on dataset detail page — paginated table view
- For spatial datasets with FK relationships, show related table data in a sub-panel or expandable rows
- Non-spatial datasets get the data grid as their primary view (no map tab)

### Claude's Discretion
- Exact data grid component choice (reuse existing table components vs. new)
- FK relationship storage schema (new table vs. JSON in existing model)
- Pagination strategy for related records

</decisions>

<specifics>
## Specific Ideas

- Existing `foreign_key` column type in column_info can serve as FK detection hint
- `geometry_type: None` already supported in Dataset model — non-spatial path exists but may not be fully wired
- Related datasets endpoint (`/datasets/{id}/related/`) currently uses embeddings — new FK-based relationships are separate

</specifics>

<canonical_refs>
## Canonical References

No external specs — requirements fully captured in decisions above

</canonical_refs>
