# Quick Task 260327-rkx: API Audit Follow-ups - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Task Boundary

Address four deferred API audit findings:
- M1: Batch N+1 queries in `list_collections_endpoint` (visibility filter complexity)
- M2: JOIN `forked_from_name` + `owner_username` into `get_map_with_layers`
- L4: Replace `_public_base_url` in datasets/router.py (different purpose than `get_public_api_url`)
- L5: Split `datasets/router.py` (1,650 lines) into sub-routers

</domain>

<decisions>
## Implementation Decisions

### L5: datasets/router.py Split Strategy
- Split by operation type: CRUD (create/read/update/delete), export/download, STAC/OGC, tiles/services
- Groups related operations together for clear module boundaries

### L4: _public_base_url Replacement
- Create a new dedicated helper like `get_dataset_service_url()` that encapsulates the different logic
- Purpose-specific, does not overload `get_public_api_url()`

### M1: N+1 Query Batching in list_collections
- Use SQLAlchemy eager loading / joinedload to fetch related data in fewer queries
- Standard ORM approach, maintains readability

### Claude's Discretion
- M2 implementation details (straightforward JOIN addition)

</decisions>

<specifics>
## Specific Ideas

- L5 sub-router files should follow existing naming convention in the routers directory
- L4 helper should live alongside the existing URL helpers
- M1 and M2 are independent query optimizations

</specifics>
