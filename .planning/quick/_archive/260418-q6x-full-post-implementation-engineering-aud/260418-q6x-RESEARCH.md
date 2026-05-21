# Quick Task 260418-q6x: Full Post-Implementation Engineering Audit - Research

**Researched:** 2026-04-18
**Domain:** FastAPI + React full-stack audit
**Confidence:** HIGH

## Summary

Commit 41803969 (HEAD) is the most recent audit remediation. The user wants a fresh full sweep. Prior audits have fixed 300+ findings cumulatively across 6 recent remediation commits. The codebase is in good shape -- no bare `except:`, no `dangerouslySetInnerHTML`, no `console.log` in production code, `as any` nearly eliminated (1 instance in a test). However, several recurring patterns and a few new items warrant attention.

**Primary recommendation:** Focus the audit on (1) SQL identifier quoting inconsistencies in `metadata.py` and `features/service.py`, (2) stale debug artifacts committed to git, (3) large file complexity in the top-10 files, (4) `except Exception` density in AI and ingest modules, and (5) React effect/timer cleanup in map components.

## Audit Dimensions

Based on prior audit patterns and current codebase analysis, the audit should cover these categories:

### 1. SQL Safety (P0)

**Status:** Partially addressed but inconsistencies remain.

**Findings to investigate:**

- `backend/app/processing/ingest/metadata.py` has 5 `text(f"...")` calls using `data.{table_name}` **without** `_qtable()` quoting (lines 89, 660, 866, 870, 882). These do call `_validate_table_name()` upstream but don't use the quoted form. The `_qtable()` function exists in the same file and properly quotes as `"data"."table_name"`. Inconsistent use means a future refactor could introduce an injection path. [VERIFIED: codebase grep]

- `backend/app/modules/catalog/features/service.py` uses `data.{table_name}` unquoted in 5 SQL strings (lines 129, 146, 177, 193, 221). Each caller validates via `_validate_table_name()` first, but the pattern is inconsistent with `_qtable()` usage elsewhere. [VERIFIED: codebase grep]

- `backend/app/modules/catalog/features/service.py:412` uses `text(f"DELETE FROM data.{table_name} WHERE gid = :gid")` -- validated but unquoted. [VERIFIED: codebase grep]

### 2. Exception Handling Breadth (P1)

**Status:** No bare `except:` clauses. But `except Exception` is heavily used.

**Files with highest `except Exception` density:**
| File | Count |
|------|-------|
| `processing/ai/router.py` | 10 |
| `processing/ingest/router.py` | 9 |
| `processing/ingest/tasks_common.py` | 5 |
| `processing/ingest/metadata.py` | 5 |
| `processing/ingest/tasks_vrt.py` | 4 |
| `processing/embeddings/service.py` | 4 |
| `platform/cache/redis.py` | 4 |

AI and ingest routers catching `Exception` broadly is a recurring pattern from prior audits. Many of these may be justified (catch-all for external process failures), but each should be reviewed for whether a narrower exception type is appropriate. [VERIFIED: grep counts]

### 3. Stale Artifacts in Git (P1)

Three debug/audit artifacts are tracked in git at the repo root:
- `app_structure.txt` (28KB, dated Apr 16)
- `builder-snapshot.md` (3.7KB, dated Apr 14)
- `layer-detail.md` (5.2KB, dated Apr 14)

These are not referenced by any code and appear to be temporary analysis files that were accidentally committed. [VERIFIED: `git ls-files` confirms tracked]

### 4. Missing Response Models (P2)

Three router files have zero `response_model` usage:
- `backend/app/processing/export/router.py` -- may be justified (streaming file responses)
- `backend/app/api/router.py` -- likely just the root/health endpoint
- `backend/app/modules/catalog/features/router.py` -- larger concern, serves GeoJSON

Each should be checked for whether response model documentation is appropriate. [VERIFIED: grep counts]

### 5. Frontend React Patterns (P2)

**useEffect density:** Map components have high effect counts (ViewerMap: 10, BuilderMap: 10, DatasetMap: 9, DatasetPage: 6). Prior audits have addressed some, but components with 9-10 effects are worth reviewing for consolidation opportunities or missing cleanup. [VERIFIED: grep counts]

**Timer/interval cleanup:** 10 files use `setTimeout`/`setInterval`. Each should have cleanup in `useEffect` return. Files to check:
- `hooks/use-hero-state.ts`
- `hooks/use-feature-editing.ts`
- `hooks/use-draft-editing.ts`
- `dataset/DistributionsList.tsx`

**Array index keys:** Several components use array index as React key. Most are in skeleton/placeholder components (acceptable) but `slider.tsx:53` and `BBoxPreview.tsx:119` may cause issues if lists reorder. [VERIFIED: grep]

### 6. Infinite staleTime / gcTime (P2)

Five query hooks use `staleTime: Infinity`:
- `use-map-thumbnail.ts` -- thumbnails can change on re-capture
- `use-ingest.ts` -- job formats are static, likely fine
- `use-settings.ts` -- settings can change via admin panel
- `use-edition.ts` -- edition is static per deployment, fine with `gcTime: Infinity`

The thumbnail and settings hooks may serve stale data after mutations. Check whether query invalidation covers these. [VERIFIED: grep]

### 7. Large File Complexity (P2-P3)

**Backend top-5 by LOC:**
| File | Lines | Concern |
|------|-------|---------|
| `catalog/datasets/domain/service.py` | 1384 | God service -- may benefit from splitting |
| `catalog/search/service.py` | 1326 | Complex but domain-appropriate |
| `catalog/search/router.py` | 1316 | Router+logic coupling |
| `processing/ingest/metadata.py` | 1198 | Many SQL operations, validated |
| `standards/stac/router.py` | 1150 | Serialization-heavy |

**Frontend top-5 by LOC:**
| File | Lines | Concern |
|------|-------|---------|
| `types/api.ts` | 1262 | Generated types, expected |
| `search/FilterPanel.tsx` | 864 | Complex filter UI |
| `dataset/DatasetMap.tsx` | 836 | Map + effects |
| `dataset/ReuploadDialog.tsx` | 743 | Multi-step wizard |
| `pages/DatasetPage.tsx` | 739 | Page orchestrator |

Files over 700 LOC should be checked for extraction opportunities. [VERIFIED: `wc -l`]

### 8. Event Listener Cleanup (P3)

10 files use `addEventListener`/`removeEventListener`. Focus on:
- `dataset/DatasetMap.tsx` -- 9 useEffects, high risk of stale listeners
- `viewer/hooks/use-viewer-layers.ts` -- map lifecycle listeners
- `builder/hooks/use-builder-layout.ts` -- container query listeners

### 9. Backend print() Statements (P3)

`backend/app/core/config.py` has 2 `print()` calls (lines 333, 343). These are in the config loading path -- may be intentional (pre-logger initialization), but should be checked. [VERIFIED: grep]

## Prior Audit Pattern Analysis

Recurring categories across the last 6 audit remediation commits:

| Category | Frequency | Status |
|----------|-----------|--------|
| `scalar_one()` crash paths -> `scalar_one_or_none()` | Recurring | Likely resolved |
| Missing Pydantic `max_length` / `min_length` constraints | Recurring | Check new schemas |
| Frontend `useMemo` missing deps / unnecessary re-renders | Recurring | Check new components |
| Dead imports / unused code | Recurring | Check after restructure |
| Missing error boundaries / error toasts | Mostly resolved | Verify coverage |
| SSRF validation gaps | Recent (2 commits) | New OGC adapter needs verification |
| Zombie subprocess cleanup | Recent (WFS) | Verify OGC API adapter |

## Scope Recommendation

**Wave 1 (P0-P1):** SQL quoting consistency, stale git artifacts, new OGC API adapter security review, `except Exception` triage in AI/ingest routers.

**Wave 2 (P2):** Response model gaps, staleTime/Infinity review, React effect consolidation in map components, new schema constraint audit.

**Wave 3 (P3):** Large file extraction opportunities, event listener cleanup, print() to structlog, array-index key review.

## Sources

### Primary (HIGH confidence)
- All findings verified via codebase grep and file reads against current HEAD (41803969)
- Line numbers and counts confirmed via direct inspection

### Assumptions
- None -- all claims derived from direct codebase analysis
