---
quick_id: 260425-sl1
description: Address backend test debt from audit 2026-04-25 (15 failures across 6 clusters)
status: ready_for_planning
gathered: 2026-04-26
---

# Quick Task 260425-sl1: Backend test debt — Context

**Source audit:** `docs-internal/audits/test-debt-backend-20260425.md`
**Pre-task baseline:** 1950 pass / 15 fail (99.24% on suite of 1965)
**Goal:** Restore green-baseline so future audits' green-baseline gates work cleanly.

<domain>
## Task Boundary

Address the 15 backend pytest failures listed in `docs-internal/audits/test-debt-backend-20260425.md`.
Each failure must end the task either:
1. **Fixed** — code or test corrected; assertion now passes.
2. **xfail'd** — annotated with `@pytest.mark.xfail(reason='audit 20260425 cluster N: <what>', strict=False)` so it visibly remains as known debt without breaking the green-baseline.

After this task, `pytest backend/` should produce **0 unexpected failures**. Every previously-failing test is either green or marked xfail with a traceable reason.

</domain>

<decisions>
## Implementation Decisions

### Scope (LOCKED)
- **All 15 failures in scope.** Not triage-only, not cheap-wins-only. Every failing test ends the task in a known state (fixed or xfail'd).

### Cluster 1 — STAC datetime fallback (LOCKED)
- **Keep code, fix test.** Current behavior at `backend/app/modules/catalog/search/service.py:1051-1057` is intentional — fallback to `record.created_at` ensures STAC validation passes.
- Update `test_datetime_null_when_no_temporal` to assert that `properties.datetime` equals the record's `created_at` (RFC 3339 / ISO 8601 with `Z` suffix), not `None`.
- The test name is now misleading; rename it to `test_datetime_falls_back_to_created_at_when_no_temporal` and update its docstring to cite the audit decision.

### Stubborn-cluster strategy (LOCKED)
- For any test we can't quickly root-cause within this task, mark `@pytest.mark.xfail(reason='audit 20260425 cluster N: <one-line summary>', strict=False)`.
- `strict=False` is intentional — if a future change happens to fix the underlying issue, the test starts passing as `XPASS` without breaking CI.
- Applies primarily to: cluster 3 (AI chat / chat streaming, 7 failures), cluster 4 (OGC catalog, 3 failures), cluster 6 (test pollution).

### Cluster 5 — Search date-range test (LOCKED)
- **Use `freezegun.freeze_time`** to make 'today / yesterday / tomorrow' deterministic.
- If `freezegun` isn't already a backend dev-dep, install it (or use `pytest-freezer` if that's the convention — planner/researcher to confirm).
- **Do not** widen the assertion range — that would mask the original intent.
- If `freezegun` import + setup turns out to be more than ~30 LOC of fixture refactor, fall back to xfail.

### Cluster 2 — STAC compliance (PARTIAL DECISION)
- The audit groups `test_raster_record_no_stac_extensions` and `test_no_bands_without_band_info` as "likely related to cluster 1." Researcher must confirm:
  - If the failures are in the same serializer trade-off as cluster 1 → fix the test (same precedent).
  - If they're a genuine compliance regression → fix the code.
  - If unclear after a brief look → xfail with cluster 2 reason and note for follow-up.

### Cluster 4 — OGC catalog (PARTIAL DECISION)
- Per-dataset collection extents and root links. Researcher confirms whether this is a serializer divergence (test wrong) or a router emission gap (code wrong).
- Default to xfail if root cause isn't obvious within ~10 minutes of investigation per failure.

### Cluster 6 — Test pollution (LOCKED)
- `test_load_public_url_overrides_unwraps_json_values` passes alone, fails in suite.
- **Do not** sink time into bisection in this task — xfail with cluster 6 reason.
- Recommendation in audit (run with `--randomly-seed` or bisect) is captured as a follow-up note, not in scope.

### Claude's Discretion
- Exact wording of xfail `reason=` strings (must include audit date and cluster number).
- Whether the renamed `test_datetime_falls_back_to_created_at_when_no_temporal` keeps the original test class location.
- Whether to add a single helper `pytest.fixture` for any shared setup that emerges (don't refactor for the sake of it).

</decisions>

<specifics>
## Specific References

- Audit doc: `docs-internal/audits/test-debt-backend-20260425.md`
- STAC fallback site: `backend/app/modules/catalog/search/service.py:1051-1057`
- Failing test files (all under `backend/tests/`):
  - `test_ai_chat.py` (cluster 3)
  - `test_chat_streaming.py` (cluster 3)
  - `test_ogc_collection_metadata.py`, `test_ogc_features.py` (cluster 4)
  - `test_search.py` (cluster 5)
  - `test_public_urls.py` (cluster 6)
  - `test_stac_record_output.py` (clusters 1 + 2)

## xfail reason-string format (canonical)

```python
@pytest.mark.xfail(
    reason="audit 20260425 cluster N: <one-line cause>",
    strict=False,
)
```

Examples (planner can refine):
- `"audit 20260425 cluster 3: AI chat fixture/protocol drift, see docs-internal/audits/test-debt-backend-20260425.md"`
- `"audit 20260425 cluster 4: OGC collection serializer divergence, see audit"`
- `"audit 20260425 cluster 6: test pollution — passes alone, fails in suite"`

</specifics>

<canonical_refs>
## Canonical References

- Audit document: `docs-internal/audits/test-debt-backend-20260425.md` — full failure list, triage-by-cluster, recommendations
- Frontend equivalent precedent: commit `6d72b72a` — fixed 9 `AppLayout.test.tsx` failures via single missing mock (no analog single-fix exists for backend, per audit)

</canonical_refs>
