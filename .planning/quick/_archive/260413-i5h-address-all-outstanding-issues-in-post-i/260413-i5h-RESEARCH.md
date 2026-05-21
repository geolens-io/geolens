# Quick Task 260413-i5h: Audit Remediation - Research

**Researched:** 2026-04-13
**Domain:** FastAPI backend + React frontend audit fixes
**Confidence:** HIGH

## Summary

25 remaining audit findings across P1-P3. Four items require targeted research; the rest are straightforward refactors. All four research questions have clear answers.

## Key Research Findings

### 1. Per-Request Caching for `get_user_roles()` (P1 #1)

**Problem:** `get_user_roles()` fires a DB query on every call. Many endpoints call it multiple times per request (e.g., search router calls it, then passes roles to service which calls visibility helpers). [VERIFIED: codebase grep shows 40+ call sites across routers]

**Pattern:** Use a FastAPI dependency that caches on `request.state`. The codebase already uses `request.state` (found in `ogc/errors.py`). [VERIFIED: codebase grep]

**Recommended approach:**

```python
# In auth/dependencies.py — add a cached dependency
async def get_cached_user_roles(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(current_user_optional),
) -> set[str]:
    """Return user roles, cached for the lifetime of this request."""
    if user is None:
        return set()
    cached = getattr(request.state, "_user_roles", None)
    if cached is not None:
        return cached
    roles = await get_user_roles(db, user)
    request.state._user_roles = roles
    return roles
```

**Why not `functools.lru_cache`:** LRU cache persists across requests — stale roles after permission changes. `request.state` is per-request by design. [ASSUMED — standard FastAPI pattern, not verified against docs this session]

**Migration:** Expose `get_cached_user_roles` as a FastAPI `Depends()`. Callers that already have `request` in scope can switch. For service-layer calls that receive `db` + `user` but no `request`, keep using the direct function — the caching dependency handles the hot path (router-level calls).

**Confidence:** HIGH

### 2. `asyncio.gather()` for Facet Queries (P1 #2)

**Problem:** 5 facet queries (keyword, org, srid, collections, record_type counts) run sequentially in `search/service.py:354-567`. Each is an independent SELECT. [VERIFIED: read source]

**Critical constraint:** SQLAlchemy `AsyncSession` is NOT safe to share across concurrent tasks. A single session uses one underlying DB connection, and concurrent `.execute()` calls on the same session will corrupt state. [VERIFIED: SQLAlchemy docs explicitly warn against this]

**Recommended approach:** Do NOT use `asyncio.gather()` with the same session. Instead:

**Option A (recommended): Single combined query or sequential with comment.**
The facet queries are all lightweight aggregations against indexed columns. On a catalog of typical size (<100K records), each takes <10ms. The sequential overhead (~50ms total) is negligible compared to network latency. Add a comment explaining why they're sequential:

```python
# Facet queries are intentionally sequential — SQLAlchemy AsyncSession
# is not safe for concurrent execute() on the same connection.
```

**Option B (if latency matters): Create separate sessions per gather task.**

```python
async def _run_facet(query):
    async with async_session() as s:
        return (await s.execute(query)).all()

kw_rows, org_rows, srid_rows, coll_rows = await asyncio.gather(
    _run_facet(kw_stmt), _run_facet(org_stmt),
    _run_facet(srid_stmt), _run_facet(coll_facet_stmt),
)
```

This burns 4 connections from the pool simultaneously. With default `pool_size=5`, this could starve other requests under load.

**Recommendation:** Option A — leave sequential, add explanatory comment. The audit finding assumes parallelism is free; it is not with SQLAlchemy async. If profiling shows facets are a bottleneck (unlikely), Option B with pool size increase.

**Confidence:** HIGH

### 3. `quicklook_url` Backend Field Removal (P2 #10)

**Current state:**
- `RasterMetadata.quicklook_url` field defined in `datasets/schemas.py:132` [VERIFIED]
- Computed in `datasets/helpers.py:70` as `/api/datasets/{id}/quicklook?size=256` [VERIFIED]
- Frontend does NOT read this field — it constructs the URL from `has_quicklook` boolean + dataset ID client-side in `SearchResultCard.tsx:155-156` [VERIFIED: grep shows no frontend import of quicklook_url]
- The quicklook GET endpoint itself (`/api/datasets/{id}/quicklook`) serves PNG images and must stay [VERIFIED]
- Only test reference: `SourcesTab.test.tsx:66` sets `quicklook_url: null` in fixture data [VERIFIED]

**STAC/OGC concern:** The `quicklook_url` field is inside `RasterMetadata`, which is a GeoLens-specific schema, NOT part of the STAC or OGC response. STAC uses `assets.thumbnail.href` and the OGC router has its own response builder. No external standard depends on this field. [VERIFIED: field is in datasets/schemas.py RasterMetadata, not in ogc/ or stac paths]

**Action:** Safe to remove `quicklook_url` from `RasterMetadata` schema and `helpers.py` computation. Update `SourcesTab.test.tsx` fixture. Keep the GET endpoint.

**Confidence:** HIGH

### 4. `config_ops/service.py` HTTPException Pattern (P2 #5)

**Problem:** Service layer raises `HTTPException` directly (lines 226, 243, 286, 305, 330). Service layers should raise domain exceptions; routers catch and translate.

**Existing codebase pattern:** The codebase already has domain exceptions: [VERIFIED: grep]
- `IngestionError` (ingest/ogr.py)
- `ExportError` (export/ogr.py)
- `DependentVrtError` (datasets/service.py)
- `EmbeddingUnavailableError` (embeddings/service.py)
- `SandboxError` (sandbox/schemas.py)
- `AuthenticationError` (auth/providers/__init__.py)

**Pattern:** Simple exception classes, caught in routers with try/except that maps to HTTPException.

**Recommended approach:**

```python
# config_ops/exceptions.py
class ConfigValidationError(Exception):
    """Raised when config import validation fails."""
    pass

class ConfigLockedError(Exception):
    """Raised when config is locked to env vars."""
    pass
```

Router catches:
```python
except ConfigLockedError:
    raise HTTPException(403, "Configuration locked to environment variables")
except ConfigValidationError as e:
    raise HTTPException(422, str(e))
```

**Three HTTPException sites to convert:** env-only lock (line 286→ConfigLockedError), permission matrix validation (line 305→ConfigValidationError), provider secret validation (lines 226, 243→ConfigValidationError), setting validator failure (line 330→ConfigValidationError).

**Confidence:** HIGH

## Additional Notes on Remaining Items

### Straightforward Refactors (no research needed)

- **#4 `_build_layer_response` 10 params:** Extract a dataclass/TypedDict for dataset metadata params. [VERIFIED: read source, 12 params total]
- **#6 `toViewerSyncInput`/`toAdapterInput` dup:** Merge into single mapper or extract shared fields.
- **#7-8 Silent query errors:** Add `onError` toast callbacks to TanStack Query hooks.
- **#9 `duplicate_feature_count` fields:** `dataset_feature_count` and `dataset_feature_count_total` in MapLayerResponse are always set to the same value (line 120). Remove one. [VERIFIED: read source]
- **#11-12 Type cast comments:** Replace `as` casts with proper type narrowing or runtime checks.
- **#13-16 P3 deduplication:** Standard extract-function refactors.
- **#17 HNSW defaults:** Add explicit `m=16, ef_construction=64` params (pgvector defaults).
- **#18 Admin jobs poll:** Comment documenting why 30s is intentional, or make configurable.
- **#19-20 Console.debug + API_BASE:** Cleanup.
- **#21 Raw status codes:** Use `status.HTTP_xxx` constants from `fastapi`.
- **#22 OAuth response_class:** Add `response_class=HTMLResponse` to redirect endpoints.
- **#23-25 Ingest one-liners/helpers:** Inline or annotate as intentional.

### `.lower().endswith()` x5 (P3 #25)

Already seen in code at line 833-839. Pattern:
```python
lower_path = file_path.lower()
assumes_4326 = (
    lower_path.endswith(".csv")
    or lower_path.endswith(".geojson")
    ...
)
```

Refactor to: `any(lower_path.endswith(ext) for ext in (".csv", ".geojson", ".json", ".xlsx", ".xls"))`

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `request.state` is the standard per-request cache pattern in FastAPI | Section 1 | Low — pattern is well-established, alternative is middleware-based context var |

## Sources

### Primary (HIGH confidence)
- Codebase grep/read — all call sites, exception patterns, schema definitions verified directly
- SQLAlchemy async docs — session concurrency constraints

### Secondary (MEDIUM confidence)
- FastAPI `request.state` pattern — standard practice, not re-verified against current docs this session
