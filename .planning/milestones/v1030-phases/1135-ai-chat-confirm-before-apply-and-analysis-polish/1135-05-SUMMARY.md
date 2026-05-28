---
phase: 1135-ai-chat-confirm-before-apply-and-analysis-polish
plan: "05"
subsystem: ai
tags: [python, fastapi, ai, docstring, testing, cache]

requires:
  - phase: 1134
    provides: stabilized _validate_chat_layers dispatcher contract

provides:
  - _validate_chat_layers docstring with Pitfall #5 visibility-filter rationale (router.py)
  - _schema_cache_key docstring with (map_id, content_hash) load-bearing contract anchor (sql_generator.py)
  - 4 pytest regression tests pinning both contracts (test_ai_chat_actions_phase1135.py)

affects:
  - any future refactor of _validate_chat_layers or _schema_cache_key
  - AI-04 requirement closure

tech-stack:
  added: []
  patterns:
    - "Pitfall-anchor docstring pattern: cross-reference Pitfall #N + version tag + explicit
      NOT-a-filter assertion in the docstring, so future refactors find the WHY before the WHERE"

key-files:
  created:
    - backend/tests/test_ai_chat_actions_phase1135.py
  modified:
    - backend/app/processing/ai/router.py
    - backend/app/processing/ai/sql_generator.py

key-decisions:
  - "Visibility filter decision: _validate_chat_layers does NOT filter by layer.visible; analysis sees all layers regardless of visibility state (Pitfall #5 AI-04)"
  - "Cache key contract: (map_id, content_hash) tuple is load-bearing — no dataset_id-only shortcut (PERF-04 Phase 274 preserved)"
  - "ChatMapLayer has 'id' + 'name' as required fields (not 'layer_id') — test fixture corrected from plan template"

patterns-established:
  - "Pitfall-anchor docstring: explicit NOT-a-gate assertion + version anchor in docstring so future refactors find the design decision"

requirements-completed:
  - AI-04

duration: 12min
completed: 2026-05-27
---

# Phase 1135 Plan 05: Pitfall #5 Docstring + Schema Cache Key Pin Summary

**Pitfall #5 visibility-filter rationale documented in `_validate_chat_layers` docstring and (map_id, content_hash) cache-key contract pinned by 4 pure-Python regression tests**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-05-27T18:11:00Z
- **Completed:** 2026-05-27T18:23:56Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Extended `_validate_chat_layers` docstring in `router.py` with the Pitfall #5 paragraph explicitly documenting that analysis sees all layers regardless of `visible` state, with rationale and the "add `include_hidden: bool` instead" future-requirement guidance
- Reinforced module-level cache comment + `_schema_cache_key` docstring in `sql_generator.py` with `Pitfall #5 anchor (v1030 Phase 1135 AI-04)` and explicit "do NOT shortcut to dataset_id-only key" warnings — preserves PERF-04 Phase 274 contract
- Created `backend/tests/test_ai_chat_actions_phase1135.py` with 4 pure-Python regression tests: docstring keyword pin (Pitfall #5 / visibility / regardless), cross-map isolation, cache-hit baseline, and content-hash partition within same map

## Task Commits

1. **Task 1: Extend _validate_chat_layers and _schema_cache_key docstrings** - `e7a0f4fc` (docs)
2. **Task 2: Backend regression test file** - `88eb2f3d` (test)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `backend/app/processing/ai/router.py` - `_validate_chat_layers` docstring extended with Pitfall #5 visibility-filter rationale paragraph (no production code change)
- `backend/app/processing/ai/sql_generator.py` - Module-level cache comment + `_schema_cache_key` docstring reinforced with Pitfall #5 cross-reference and (map_id, content_hash) load-bearing contract assertion
- `backend/tests/test_ai_chat_actions_phase1135.py` - NEW: 4 regression tests pinning docstring anchors and cache-key isolation contracts

## Docstring Diffs (Before → After)

### `_validate_chat_layers` (router.py lines 102-109 before, extended after)

**Before:**
```
Validate map ownership and overwrite layer metadata with authoritative DB values.

- Verifies the map exists and is owned by the current user.
- Resolves each layer's dataset_table_name from the DB by dataset_id.
- Rejects layers whose datasets the user cannot access.

Returns (validated_layers, basemap_style).
```

**After (paragraph added before `Returns`):**
```
    **Visibility decision (Pitfall #5 — v1030 Phase 1135 AI-04):** This function
    does NOT filter layers by their ``visible`` state, even if the frontend
    sends a ``visible`` field on the ChatMapLayer model. AI chat analysis sees
    every layer present in the map regardless of visibility. Rationale:
    visibility is a viewer-only decluttering signal (users hide layers to
    reduce visual noise, not to say "do not analyze these"). When a user asks
    "summarize this layer" or "which counties are in the AOI", the AI must
    have the full layer manifest to answer correctly; filtering by visibility
    would silently exclude data the user expects to be analyzed.

    If a future requirement DOES want to scope analysis to visible layers
    only, add an explicit ``include_hidden: bool`` parameter rather than
    silently changing the contract here.
```

### `_schema_cache_key` (sql_generator.py lines 30-37 + 43-48)

**Module-level comment — before:**
```python
# PERF-04 (Phase 274): the cache key is partitioned by (map_id, content_hash)
# so two different maps that share an identical layer signature (e.g. both
# referencing the same Natural Earth dataset) get independent cache entries.
# Without the map_id partition, one map's prompt-context edits could be
# served back to a different map on the next chat turn.
```

**After:**
```python
# PERF-04 (Phase 274) + Pitfall #5 anchor (v1030 Phase 1135 AI-04): the cache
# key is partitioned by (map_id, content_hash) so two different maps that
# share an identical layer signature (e.g. both referencing the same Natural
# Earth dataset) get independent cache entries. Without the map_id partition,
# one map's prompt-context edits could be served back to a different map on
# the next chat turn. Do NOT shortcut to a dataset_id-only key — the
# (map_id, content_hash) tuple is load-bearing across multi-map chat sessions
# and must NOT be relaxed without a Future Requirement entry first.
```

**`_schema_cache_key` docstring — before:**
```
Build a deterministic cache key partitioned by (map_id, content_hash).

PERF-04 (Phase 274): adding map_id prevents cross-map cache pollution
when two different maps reference the same dataset. Cache entries
evict on either the 60s TTL or when len(_schema_cache) >= _SCHEMA_CACHE_MAX.
```

**After:**
```
Build a deterministic cache key partitioned by (map_id, content_hash).

PERF-04 (Phase 274) + Pitfall #5 (v1030 Phase 1135 AI-04): adding map_id
prevents cross-map cache pollution when two different maps reference the
same dataset. The (map_id, content_hash) tuple shape is load-bearing —
do NOT shortcut to (dataset_id,) only. Cache entries evict on either the
60s TTL or when len(_schema_cache) >= _SCHEMA_CACHE_MAX.
```

## Test Results

All 4 tests passed: `4 passed in 2.03s`

| Test | Description | Result |
|------|-------------|--------|
| `test_validate_chat_layers_docstring_pins_visibility_decision` | Asserts docstring contains "Pitfall #5", "visibility", "regardless" | PASS |
| `test_schema_cache_key_isolates_by_map_id` | map-A vs map-B produce distinct keys, same content_hash | PASS |
| `test_schema_cache_key_stable_for_same_map_id` | Same layers + same map_id = equal keys (cache-hit baseline) | PASS |
| `test_schema_cache_key_isolates_by_content_hash_same_map_id` | Different table_name under same map_id = distinct keys | PASS |

## Production Code Unchanged Verification

No production code lines changed — only docstring/comment additions:

- `_validate_chat_layers` function body (lines 110-175): unchanged
- `_schema_cache_key` function body (hash computation, return): unchanged
- `_schema_cache: dict[tuple[str, str], tuple[float, str]] = {}` type annotation: unchanged (verified by grep)
- `_SCHEMA_CACHE_TTL = 60.0` and `_SCHEMA_CACHE_MAX = 64`: unchanged

## Deviation Note: Test Fixture Field Names

The plan template used `layer_id=` in the fixture but `ChatMapLayer` requires `id` and `name` (confirmed by reading `schemas.py`). The fixture was corrected to `id="layer-1", name="Test Layer"` — this is a correction to the plan template, not a deviation from the intent.

## Cross-References

- **AI-04 ROADMAP success criterion:** `_validate_chat_layers` visibility-filter decision documented explicitly in `router.py` docstring (CONTEXT.md listed `chat_actions.py` as approximate; canonical home confirmed as `router.py:94-175`)
- **Pitfall #5:** Users hide layers for visual decluttering, not "do not analyze these" — AI must see all layers for correct analysis
- **Phase 274 PERF-04:** `(map_id, content_hash)` partition preserved; tests 2/3/4 pin it as a regression net
- **CONTEXT.md discrepancy resolved:** `_validate_chat_layers` is in `router.py`, not `chat_actions.py`

## Deviations from Plan

None — plan executed exactly as written (fixture field name correction is a plan template fix, not a behavior deviation).

## Issues Encountered

None.

## Next Phase Readiness

- AI-04 requirement closed; Pitfall #5 anchors are now findable in both files and pinned by tests
- Plans 01-04 and 06 in Phase 1135 are unaffected (this plan is Wave 1 parallel with Plan 01, touching only backend files)

---
*Phase: 1135-ai-chat-confirm-before-apply-and-analysis-polish*
*Completed: 2026-05-27*
