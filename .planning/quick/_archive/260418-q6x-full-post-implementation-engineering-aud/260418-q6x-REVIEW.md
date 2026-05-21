---
phase: 260418-q6x
reviewed: 2026-04-18T00:00:00Z
depth: quick
files_reviewed: 14
files_reviewed_list:
  - backend/app/modules/catalog/features/service.py
  - backend/app/processing/ai/router.py
  - backend/app/processing/embeddings/service.py
  - backend/app/processing/ingest/metadata.py
  - backend/app/processing/ingest/router.py
  - backend/app/processing/ingest/tasks_common.py
  - backend/app/processing/ingest/tasks_vrt.py
  - frontend/src/components/admin/ApiKeyRevealDialog.tsx
  - frontend/src/components/builder/StyleSpecView.tsx
  - frontend/src/components/dataset/DistributionsList.tsx
  - frontend/src/components/dataset/tabs/AccessTab.tsx
  - frontend/src/components/dataset/tabs/OverviewTab.tsx
  - frontend/src/components/map/FeaturePopup.tsx
  - frontend/src/components/maps/hooks/use-map-thumbnail.ts
findings:
  critical: 0
  warning: 1
  info: 0
  total: 1
status: issues_found
---

# 260418-q6x: Code Review Report

**Reviewed:** 2026-04-18
**Depth:** quick
**Files Reviewed:** 14 (docs/audits/post-impl-20260418.md excluded — not source)
**Status:** issues_found

## Summary

This is a remediation-pass review for the 260418-q6x post-implementation audit. The audit
targeted SQL identifier quoting hardening, broad-exception annotation, React timer cleanup,
and TanStack Query cache hygiene. The remediation doc (`post-impl-20260418.md`) lists all
20 findings as Fixed or Deferred.

All primary remediations verified clean via pattern scan:

- Timer cleanup (T-01 through T-06): all six components use the `timerRef` + `useEffect`
  cleanup pattern correctly. No fire-and-forget `setTimeout` remains.
- Cache hygiene (C-01): `use-map-thumbnail.ts` uses `staleTime: 60 * 1000`. No
  `staleTime: Infinity` found in the reviewed files.
- Exception annotation (E-01 through E-06): all `except Exception` blocks carry
  `# broad: <justification>` comments.
- No hardcoded secrets, empty catch blocks, dangerous functions, or debug artifacts found.

One residual SQL quoting inconsistency was found that was not addressed by the remediation
pass.

## Warnings

### WR-01: Unquoted schema.table interpolation in `construct_user_geometry_column`

**File:** `backend/app/processing/ingest/tasks_common.py:296`

**Issue:** The function at line 268 imports `_validate_table_name` but not `_qtable`. At
line 296 it interpolates the table name as `data.{table_name}` — an unquoted
`schema.table` string — while every other SQL site in this file and across `metadata.py`
and `features/service.py` uses `_qtable(table_name)`, which produces `"data"."table_name"`
with proper double-quoting.

The validator (`^[a-z0-9_]+$`) rules out injection today because it rejects any character
that would require quoting. However, the inconsistency means this site is one regex-change
away from being unsafe, and it contradicts the stated goal of Q-05/Q-06/Q-07 (all
`data.{table_name}` patterns consolidated to `_qtable`). The audit doc marks all Q-series
findings as Fixed, but this instance was missed.

**Fix:**
```python
# Line 268: add _qtable to the import
from app.processing.ingest.metadata import _validate_table_name, _qtable

# Line 274: remove the now-redundant explicit validate call
# (_qtable calls _validate_table_name internally)

# Line 296: replace unquoted interpolation
result = await session.execute(
    _text(
        f"SELECT GeometryType(geom) FROM {_qtable(table_name)} "
        f"WHERE geom IS NOT NULL LIMIT 1"
    )
)
```

---

_Reviewed: 2026-04-18_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: quick_
