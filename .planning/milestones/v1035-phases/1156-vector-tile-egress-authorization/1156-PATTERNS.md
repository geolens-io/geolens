# Phase 1156: Vector-Tile Egress Authorization - Pattern Map

**Mapped:** 2026-05-30
**Files analyzed:** 2 (tiles/router.py — 5 entry points; new regression test file)
**Analogs found:** 2 / 2

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/app/processing/tiles/router.py` | middleware / request-handler | request-response (auth gate) | same file — `_resolve_raster_access` (lines 354–481) | exact (same file, mirror branch) |
| `backend/tests/test_vector_tile_auth.py` (new) | test | request-response | `backend/tests/test_raster_tiles.py` | exact (same test class shape, same fixtures) |

---

## Pattern Assignments

### `backend/app/processing/tiles/router.py` — five vector entry points

**Analog:** `_resolve_raster_access` in the same file (lines 354–481) — the already-correct raster path that gates on `record_status == "published"` for anonymous callers.

---

#### 1. `_DatasetMeta` NamedTuple (lines 78–91) — ADD `record_status` and `created_by`

Current (missing both fields; `_authorize_vector_tile_request` has no way to enforce status):

```python
# backend/app/processing/tiles/router.py:78-91
class _DatasetMeta(NamedTuple):
    """Plain data extracted from Dataset+Record for tile serving."""

    dataset_id: uuid.UUID
    record_id: uuid.UUID
    table_name: str
    visibility: str
    record_type: str
    geometry_type: str | None
    column_info: list
    tile_cache_ttl: int | None
    # Phase 269 H-23: tile column allowlist (None / [] / list[str]).
    tile_columns: list[str] | None
```

Fields to add (mirror the raster path which reads `record_status` and `created_by` at lines 409–410):

```python
# raster analog — router.py:408-410
visibility = row["visibility"]
record_status = row["record_status"]
created_by = row["created_by"]
```

---

#### 2. `_resolve_dataset_meta` (lines 991–1028) — populate `record_status` and `created_by`

Current build block (lines 1015–1025) — **`record_status` and `created_by` are not carried**:

```python
# backend/app/processing/tiles/router.py:1015-1025
    meta = _DatasetMeta(
        dataset_id=dataset.id,
        record_id=dataset.record_id,
        table_name=dataset.table_name,
        visibility=dataset.record.visibility,
        record_type=dataset.record.record_type,
        geometry_type=dataset.geometry_type,
        column_info=dataset.column_info or [],
        tile_cache_ttl=dataset.tile_cache_ttl,
        tile_columns=dataset.tile_columns,
    )
```

After fix, add two lines mirroring how the raster path passes `record_status` and `created_by` from the ORM row to the auth helper:

```python
        record_status=dataset.record.record_status,
        created_by=dataset.record.created_by,
```

Note: `_dataset_cache` caches `_DatasetMeta` by `table_name`. Adding fields to the NamedTuple invalidates all in-flight cached entries at startup — not a runtime issue (the cache has a 60s TTL and is process-local).

---

#### 3. `_authorize_vector_tile_request` (lines 1031–1069) — ADD status guard in the `public` branch

Current code — **no `record_status` check in the `else` (public) branch**:

```python
# backend/app/processing/tiles/router.py:1031-1069
async def _authorize_vector_tile_request(
    request: Request,
    meta: _DatasetMeta,
    db: AsyncSession,
    *,
    sig: str | None,
    exp: int | None,
    scope: str | None,
) -> str:
    """Authorize direct vector-tile access and return cache scope."""
    embed_token_header = request.headers.get("X-Embed-Token")
    if embed_token_header:
        is_valid = await validate_embed_token_access(
            embed_token_header, meta.dataset_id, db, request
        )
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or expired embed token, or dataset not in scope",
            )
        return "private"

    if meta.visibility != "public":
        if not sig or not exp or not scope:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Signature required for non-public tiles",
            )
        if scope != meta.table_name:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Scope mismatch"
            )
        if not verify_tile_signature(scope, exp, sig):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or expired signature",
            )

    return "public"
```

Raster analog to copy for the `public` branch (lines 465–479):

```python
# backend/app/processing/tiles/router.py:465-479  (RASTER — the model)
    else:
        # Public dataset: still block non-published for unauthenticated users
        if record_status != "published":
            # Unauthenticated users cannot see unpublished public datasets
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
                )
            # Authenticated non-owners cannot see unpublished
            port = get_processing_port()
            user_roles = await port.get_user_roles(db, user)
            if "admin" not in user_roles and created_by != user.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
                )
```

Because `_authorize_vector_tile_request` does not currently receive a `user` parameter, two implementation choices are available:

**Option A (minimal diff):** add `user: Identity | None` parameter (already available at all three call sites — `get_tile_token`, `get_tile_tokens_batch`, and `cluster_tile_endpoint` all resolve `user` via `Depends(get_optional_user)`).

**Option B (cleaner):** in the `public` branch, call `check_dataset_access_or_anonymous(db, dataset_obj, dataset_id, user)` — the wrapper already raises 404 for anon+non-published. The `_DatasetMeta` path does not carry the full ORM object, so this requires either fetching it or switching back to the ORM object. Only viable if `_resolve_dataset_meta` is refactored to return the full ORM object or a `user` context is threaded through.

The CONTEXT.md decision says: "Use whichever keeps the diff smallest and consistent with the raster path." **Option A** (add `user` param) is smallest. The call sites already have `user` in scope:

- `cluster_tile_endpoint` (line 1105): has `user: Identity | None` via Depends — but currently missing from signature; needs to be added.
- The main vector tile endpoint (line 1269): same pattern.

---

#### 4. `get_tile_token` (lines 835–882) — replace visibility-only gate

Current authorization block (lines 865–873) — **`record_status` never consulted**:

```python
# backend/app/processing/tiles/router.py:865-873
    # Non-public datasets require authentication and RBAC
    if dataset.record.visibility != "public":
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        await port.check_dataset_access(db, dataset, dataset_id, user)
```

Canonical fix — replace with `check_dataset_access_or_anonymous()` which already enforces `visibility == "public" AND record_status == "published"` for `user is None` (see `defaults.py:109-110`):

```python
# Drop-in replacement (one call covers all three branches):
    await port.check_dataset_access_or_anonymous(db, dataset, dataset_id, user)
```

This is the "cleanest fix" noted in the audit (`qa-260530-egress-gating.md:113`) — `get_tile_token` already holds the full ORM `dataset` object and the `user` dependency.

---

#### 5. `get_tile_tokens_batch` (lines 887–954) — replace per-dataset visibility-only gate

Current per-dataset auth block (lines 939–947) — **same `visibility != "public"` gap**:

```python
# backend/app/processing/tiles/router.py:939-947
        # Per-dataset auth check
        if dataset.record.visibility != "public":
            if user is None:
                tokens[key] = {"error": "Authentication required"}
                continue
            try:
                await port.check_dataset_access(db, dataset, dataset_id, user)
            except HTTPException as exc:
                tokens[key] = {"error": exc.detail}
                continue
```

Replacement — mirror the single-token fix but preserve the batch error-capture pattern (do not raise; accumulate error per key):

```python
        # Per-dataset auth check (status-aware)
        try:
            await port.check_dataset_access_or_anonymous(db, dataset, dataset_id, user)
        except HTTPException as exc:
            tokens[key] = {"error": exc.detail}
            continue
```

The `port.check_dataset_access_or_anonymous` signature is defined in `backend/app/modules/catalog/authorization.py:75` and already handles `user is None` → 404 for non-public-published datasets.

---

#### 6. `cluster_tile_endpoint` (lines 1105–1137) — inherited fix

`cluster_tile_endpoint` calls `_authorize_vector_tile_request` at line 1130. Once `_authorize_vector_tile_request` is fixed (entry point 3 above) and the `user` parameter is threaded through, `cluster_tile_endpoint` inherits the fix automatically. The only change needed in this function is:

1. Add `user: Identity | None = Depends(get_optional_user)` to its parameter list.
2. Pass `user=user` to `_authorize_vector_tile_request`.

Current call site (lines 1128–1137):

```python
# backend/app/processing/tiles/router.py:1128-1137
    meta = await _resolve_dataset_meta(table_name, db)
    _ensure_clusterable_dataset(meta)
    cache_scope = await _authorize_vector_tile_request(
        request,
        meta,
        db,
        sig=sig,
        exp=exp,
        scope=scope,
    )
```

---

## Shared Patterns

### Canonical anonymous-access contract
**Source:** `backend/app/platform/extensions/defaults.py:61-65` (query filter) and `:109-110` (`can_access_dataset`)

```python
# defaults.py:61-65  — filter_visible, anonymous branch
        if user is None:
            return stmt.where(
                record_cls.visibility == "public",
                record_cls.record_status == "published",
            )

# defaults.py:109-110  — can_access_dataset, anonymous branch
        if user is None:
            return record.visibility == "public" and record.record_status == "published"
```

### `check_dataset_access_or_anonymous` wrapper
**Source:** `backend/app/modules/catalog/authorization.py:75-97`

```python
# authorization.py:75-97
async def check_dataset_access_or_anonymous(
    db: AsyncSession, dataset: Any, dataset_id: uuid.UUID, user: Identity | None
) -> set[str]:
    """Enforce visibility for both authenticated and anonymous users.

    Returns the resolved user_roles set (empty for anonymous).
    Anonymous users may only access public + published datasets.
    Authenticated users follow the full RBAC rules via check_dataset_access().
    """
    if user is None:
        allowed = await get_permission_extension().can_access_dataset(
            db,
            dataset,
            dataset_id,
            None,
            user_roles=set(),
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
            )
        return set()
    return await check_dataset_access(db, dataset, dataset_id, user)
```

**Apply to:** `get_tile_token` (lines 865–873) and each iteration of `get_tile_tokens_batch` (lines 939–947) — these two entry points already hold the full ORM `dataset` object, making this a one-call replacement.

### Raster public-branch status guard (inline version)
**Source:** `backend/app/processing/tiles/router.py:465-479`

```python
    else:
        # Public dataset: still block non-published for unauthenticated users
        if record_status != "published":
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
                )
            port = get_processing_port()
            user_roles = await port.get_user_roles(db, user)
            if "admin" not in user_roles and created_by != user.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
                )
```

**Apply to:** `_authorize_vector_tile_request` public branch — replicate this structure after adding `user` and `meta.record_status` / `meta.created_by` to the function. This is Option A and keeps the diff within the single function.

---

## Test Pattern

### `backend/tests/test_vector_tile_auth.py` (new file)

**Analog:** `backend/tests/test_raster_tiles.py`

**Fixtures used** (all from `conftest.py`):
- `client: AsyncClient` — test HTTP client (line 1274)
- `test_db_session` — async DB session that shares the same transaction as the client (line 1503)
- `admin_auth_header: dict` — JWT header for admin user (line 1475)

**Dataset factory pattern** (copy from `test_raster_tiles.py:87-117`):

```python
# test_raster_tiles.py:87-117
async def _create_vector_dataset(
    session,
    *,
    created_by: uuid.UUID,
    visibility: str = "public",
    record_status: str = "published",
) -> tuple[Record, Dataset]:
    """Create a vector Record + Dataset for contrast tests."""
    record = Record(
        title=f"Vector Tile Test {uuid.uuid4().hex[:6]}",
        summary="Dataset for vector tile contrast tests",
        theme_category=["test"],
        visibility=visibility,
        record_status=record_status,
        record_type="vector_dataset",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=f"vector_tile_test_{uuid.uuid4().hex[:8]}",
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.flush()
    await session.commit()
    await session.refresh(dataset)
    return record, dataset
```

Note: the `table_name` used in tile-token tests is `dataset_id`-based (token endpoint takes UUID). The `.pbf` path takes `table_name` in the URL. The regression test for the token endpoints only needs `dataset.id`; the `.pbf` regression test needs `dataset.table_name` — but since no real PostGIS data is seeded, the `.pbf` route will 500/404 on the ST_AsMVT query. The regression for the data leak is best covered via the **token endpoint** (SEC-01 primary surface) plus asserting the `_authorize_vector_tile_request` unit path via the raster-auth-check analog. The token endpoint tests follow this shape:

**Denial test — public+unpublished, anonymous** (copy shape from `test_raster_tiles.py:288-317`):

```python
# test_raster_tiles.py:288-317 — blocks_unpublished_for_non_owner pattern
    async def test_auth_check_blocks_unpublished_for_non_owner(
        self, client: AsyncClient, test_db_session, admin_auth_header: dict
    ):
        admin_id = await _get_admin_id(test_db_session)
        record, dataset, asset = await _create_raster_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            record_status="draft",
        )
        # create viewer user ...
        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
            headers=viewer_header,
        )
        assert resp.status_code == 404
```

Translate to the vector token endpoint: anonymous caller (no headers), `record_status="internal"`, expect 401 or 404.

**Positive case — public+published, anonymous** (copy shape from `test_raster_tiles.py:374-394`):

```python
# test_raster_tiles.py:374-394 — positive case (over-gating guard)
    async def test_public_dataset_accessible_by_both_paths(
        self, client: AsyncClient, test_db_session
    ):
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset, _asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        # Path B: token endpoint (no auth)
        token_resp = await client.get(f"/tiles/token/{dataset.id}/")
        assert token_resp.status_code == 200
```

**Test run recipe:**

```bash
# From backend/ directory:
set -a && source ../.env.test && set +a
uv run pytest backend/tests/test_vector_tile_auth.py -v
```

---

## No Analog Found

None. All five entry points have a direct analog in `_resolve_raster_access` (same file). The test file has a direct analog in `test_raster_tiles.py`.

---

## Metadata

**Analog search scope:** `backend/app/processing/tiles/router.py`, `backend/app/platform/extensions/defaults.py`, `backend/app/modules/catalog/authorization.py`, `backend/tests/test_raster_tiles.py`, `backend/tests/conftest.py`
**Files scanned:** 5
**Pattern extraction date:** 2026-05-30
