# Phase 1157: Backend Export Access + Route Hygiene — Pattern Map

**Mapped:** 2026-05-30
**Files analyzed:** 3 (1 modified + 1 modified + 1 new)
**Analogs found:** 3 / 3

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/app/processing/export/router.py` | controller | request-response | `backend/app/modules/catalog/datasets/api/router_export.py` | exact (same anon-branch split pattern) |
| `backend/app/standards/ogc/router.py` | controller | request-response | `backend/app/modules/auth/router.py` | exact (stacked-decorator dual-shape alias) |
| `backend/tests/test_export_access.py` | test | request-response | `backend/tests/test_vector_tile_auth.py` + `backend/tests/test_export_hardening.py` | exact |

---

## Pattern Assignments

### `backend/app/processing/export/router.py` (EXP-01)

**Analog:** `backend/app/modules/catalog/datasets/api/router_export.py`

**Current offender — imports block (lines 1-21):**
```python
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.modules.audit.service import AuditEvent, audit_emit
from app.core.identity import Identity
from app.modules.auth.dependencies import require_permission   # <-- must change
from app.core.dependencies import get_db
from app.platform.extensions import get_processing_port
from app.processing.export.ogr import ExportError
from app.processing.export.schemas import ExportFormat
from app.processing.export.service import export_dataset
```

**Required import additions** (from `router_export.py` lines 7-32):
```python
# Add these to the import block:
from app.modules.auth.dependencies import get_optional_user   # replaces require_permission in sig
from app.modules.catalog.authorization import (
    check_dataset_access,
    check_dataset_access_or_anonymous,
)
from app.modules.auth.permissions import get_effective_permissions
from app.modules.catalog.authorization import get_user_roles
```

GOTCHA: `check_dataset_access_or_anonymous` is NOT a method on the processing port.
A prior `port.check_dataset_access_or_anonymous(...)` call was silently non-functional
(AttributeError at runtime). Import directly from `app.modules.catalog.authorization`.

**Current handler signature — the bug (lines 31-49):**
```python
@router.get("/{dataset_id}/export", response_class=FileResponse)
async def export_dataset_endpoint(
    dataset_id: uuid.UUID,
    request: Request,
    format: ExportFormat = Query(ExportFormat.gpkg, description="Export format"),
    target_crs: str | None = Query(None, description="Target CRS, e.g. EPSG:3857"),
    bbox: str | None = Query(
        None, description="Bounding box: minx,miny,maxx,maxy (WGS84)"
    ),
    where: str | None = Query(
        None, description="Attribute filter expression, e.g. pop > 1000"
    ),
    # BUG: require_permission forces authentication BEFORE any visibility check.
    # Anonymous export of public+published data 401s here before it can be allowed.
    user: Identity = Depends(require_permission("export")),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
```

**Reference analog — `download_cog` handler signature** (`router_export.py` lines 353-358):
```python
@router.get("/{dataset_id}/download/cog", response_class=Response)
async def download_cog(
    dataset_id: uuid.UUID,
    request: Request,
    user: Identity | None = Depends(_resolve_download_user),   # None = anonymous
    db: AsyncSession = Depends(get_db),
) -> Response:
```

For `export_dataset_endpoint`, no download-token JWT complexity is needed — use
`get_optional_user` directly (simpler than `_resolve_download_user`):
```python
@router.get("/{dataset_id}/export", response_class=FileResponse)
async def export_dataset_endpoint(
    dataset_id: uuid.UUID,
    request: Request,
    format: ExportFormat = Query(...),
    target_crs: str | None = Query(None, ...),
    bbox: str | None = Query(None, ...),
    where: str | None = Query(None, ...),
    user: Identity | None = Depends(get_optional_user),   # None = anonymous
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
```

**Reference analog — anon vs authenticated branch pattern** (`router_export.py` lines 384-407):
```python
    # 2. Visibility + permission check (branches on authenticated vs anonymous).
    if user is None:
        # Anonymous download via mint-issued no-sub token. The mint endpoint at
        # POST /auth/download-token/{id} already enforced
        # check_dataset_access_or_anonymous(); the token's typ/scope/exp checks
        # in _resolve_download_user are the auth gate. Still require public
        # visibility here as defense-in-depth (a tampered/replayed token
        # cannot grant access to a private dataset).
        await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)
        if dataset.record.visibility != "public":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anonymous download requires public dataset",
            )
    else:
        # Authenticated path: full RBAC visibility check + export permission.
        await check_dataset_access(db, dataset, dataset_id, user)
        user_roles = await get_user_roles(db, user)
        matrix = await get_effective_permissions(db)
        if not any(matrix.get(role, {}).get("export", False) for role in user_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing permission: export",
            )
```

**Access contract (from `backend/app/platform/extensions/defaults.py` lines 109-110):**
`can_access_dataset()` for anonymous (`user is None`) = `visibility == 'public' AND record_status == 'published'`.
`check_dataset_access_or_anonymous` enforces this and raises **404** (not 403) for anonymous denials — hides dataset existence. EXP-02 denied-path assertions should accept `{401, 403, 404}`.

**Current authenticated-only visibility check (lines 64-65) — to be replaced by the branch above:**
```python
    # 2. Visibility check
    await port.check_dataset_access(db, dataset, dataset_id, user)
```

---

### `backend/app/standards/ogc/router.py` (API-01)

**Analog:** `backend/app/modules/auth/router.py`

**Current `get_collection_items` decorator (lines 244-256) — no trailing-slash alias:**
```python
@ogc_features_router.get(
    "/collections/{dataset_id}/items",
    response_class=JSONResponse,
    responses={
        200: {
            "content": {
                "application/geo+json": {
                    "schema": OGCFeatureItemsResponse.model_json_schema()
                }
            }
        },
        **ERROR_RESPONSES_PUBLIC,
    },
)
async def get_collection_items(
    request: Request,
    dataset_id: uuid.UUID,
    ...
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
```

**Reference stacked-decorator pattern** (`backend/app/modules/auth/router.py` lines 69-70):
```python
@router.post("/login/", response_model=TokenResponse, include_in_schema=False)
@router.post("/login", response_model=TokenResponse)
@limiter.limit(_login_rate_limit)
async def login(...):
```

Convention: trailing-slash alias decorator comes FIRST (outermost), is hidden with
`include_in_schema=False`. The no-slash canonical decorator comes SECOND. All
other decorators (e.g. `@limiter.limit`) come after both route decorators.

**Fix shape for `get_collection_items`:**
```python
@ogc_features_router.get(
    "/collections/{dataset_id}/items/",
    response_class=JSONResponse,
    responses={...},
    include_in_schema=False,   # trailing-slash alias, hidden from OpenAPI
)
@ogc_features_router.get(
    "/collections/{dataset_id}/items",
    response_class=JSONResponse,
    responses={...},
)
async def get_collection_items(...):
```

**`redirect_slashes=False` confirmation** (`backend/app/api/main.py` lines 462-484):
```python
    # ROUTE-01 (Phase 1092): redirect_slashes=False at the app level.
    #
    # All trailing-slash-only routes register a no-slash alias via
    # stacked decorators (see backend/app/modules/auth/router.py,
    # settings/router.py, admin/router.py, etc.). The canonical
    # decorator stays in OpenAPI; the alias is hidden via
    # ``include_in_schema=False``.
    redirect_slashes=False,
```

Note: `ogc_features_router` is defined at line 37 of `router.py`:
```python
ogc_features_router = APIRouter(tags=["OGC Features"])
```
The stacked decorators use `@ogc_features_router.get(...)`, not `@router.get(...)`.

---

### `backend/tests/test_export_access.py` (EXP-02)

**Primary analog:** `backend/tests/test_vector_tile_auth.py`
**Secondary analog:** `backend/tests/test_export_hardening.py`

**Dataset factory — use `tests.factories.create_dataset`** (`backend/tests/factories.py` lines 32-85):
```python
async def create_dataset(
    session: AsyncSession,
    *,
    created_by: uuid.UUID,
    name: str = "Test Dataset",
    table_name: str | None = None,
    visibility: str = "public",
    srid: int = 4326,
    geometry_type: str = "MultiPolygon",
    feature_count: int = 42,
    description: str | None = "A test dataset",
    source_format: str = "geojson",
    source_filename: str = "test.geojson",
    record_status: str = "published",   # <-- set to "draft"/"internal"/"ready" for unpublished
    theme_category: list[str] | None = None,
    column_info: list[dict] | None = None,
) -> Dataset:
    ...
    await session.commit()
    await session.refresh(dataset)
    return dataset
```

Alternative: `_create_vector_dataset` in `test_vector_tile_auth.py` (lines 47-98) creates
Record + Dataset directly (no geometry by default). The `create_dataset` factory from
`tests.factories` is the canonical, project-wide form — prefer it.

**Mock export service pattern** (`test_export_hardening.py` lines 181-220):
```python
@pytest.fixture
def mock_export_service_for_known05(monkeypatch):
    temp_dir = tempfile.mkdtemp(prefix="test_export_hardening_known05_")

    async def _fake_export(table_name, dataset_name, format_key, *, ...):
        fmt = FORMAT_MAP[format_key]
        ext = fmt["ext"]
        media = fmt["media"]
        filename = f"{dataset_name}{ext}"
        file_path = os.path.join(temp_dir, filename)
        with open(file_path, "wb") as f:
            f.write(b"mock export data")
        return file_path, filename, media

    monkeypatch.setattr("app.processing.export.router.export_dataset", _fake_export)
    yield _fake_export
    if os.path.isdir(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
```

**Anon denial assertion shape** (`test_vector_tile_auth.py` lines 176-196):
```python
async def test_anon_single_token_denied_for_public_unpublished(
    self, client: AsyncClient, test_db_session
):
    admin_id = await _get_admin_id(test_db_session)
    _record, dataset = await _create_vector_dataset(
        test_db_session,
        created_by=admin_id,
        visibility="public",
        record_status="internal",       # unpublished
    )

    resp = await client.get(f"/tiles/token/{dataset.id}/")

    assert resp.status_code in (401, 404), (
        f"Expected 401 or 404 for anon on public+unpublished, got {resp.status_code}: {resp.text}"
    )
```

EXP-02 denied assertions accept `{401, 403, 404}` (not just 404):
- anonymous + public-unpublished → 404 (check_dataset_access_or_anonymous hides existence)
- anonymous + private/restricted → 404 (same)
- non-owner authenticated + private → 404 (check_dataset_access raises 404)
- viewer with export revoked → 403

**Positive over-gating guard shape** (`test_vector_tile_auth.py` lines 296-321):
```python
async def test_anon_single_token_allowed_for_public_published(
    self, client: AsyncClient, test_db_session
):
    admin_id = await _get_admin_id(test_db_session)
    _record, dataset = await _create_vector_dataset(
        test_db_session,
        created_by=admin_id,
        visibility="public",
        record_status="published",      # published = allowed for anon
    )
    resp = await client.get(f"/tiles/token/{dataset.id}/")
    assert resp.status_code == 200, (
        f"Expected 200 for anon on public+published, got {resp.status_code}: {resp.text}"
    )
```

**Auth helper shape** (`test_vector_tile_auth.py` lines 137-142):
```python
async def _get_auth_header(client: AsyncClient, username: str, password: str) -> dict:
    resp = await client.post(
        "/auth/login", data={"username": username, "password": password}
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
```

Alternatively, rely on the `admin_auth_header` and `viewer_auth_header` fixtures
provided by conftest (pattern from `test_export_hardening.py` lines 277-279).

**Test file header / run recipe** (from `test_vector_tile_auth.py` lines 14-18):
```
Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
  - Run with: set -a && source ../.env.test && set +a
               uv run pytest tests/test_export_access.py -v
```

**Standard imports for a new integration test file:**
```python
import os
import shutil
import tempfile
import uuid

import pytest
from httpx import AsyncClient

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.processing.export.ogr import FORMAT_MAP

from tests.factories import create_dataset, get_user_id
```

---

## Shared Patterns

### Anonymous access contract
**Source:** `backend/app/platform/extensions/defaults.py` (anon branch at lines 109-110)
**Apply to:** EXP-01 handler body + EXP-02 test assertions

`can_access_dataset(user=None, dataset)` returns `True` only when
`visibility == 'public' AND record_status == 'published'`.
`check_dataset_access_or_anonymous` enforces this and raises HTTP 404 (not 403)
to avoid leaking dataset existence to anonymous callers.

### Import path for authorization helpers
**Source:** `backend/app/modules/catalog/datasets/api/router_export.py` lines 27-32
**Apply to:** `backend/app/processing/export/router.py`

```python
from app.modules.catalog.authorization import (
    check_dataset_access,
    check_dataset_access_or_anonymous,
    get_user_roles,
)
from app.modules.auth.permissions import get_effective_permissions
from app.modules.auth.dependencies import get_optional_user
```

### Stacked-decorator convention
**Source:** `backend/app/modules/auth/router.py` lines 69-70
**Apply to:** `backend/app/standards/ogc/router.py` `get_collection_items`

Trailing-slash alias is the OUTER (first) decorator with `include_in_schema=False`.
Canonical no-slash form is the INNER (second) decorator, remains in OpenAPI schema.

### Mock export service fixture
**Source:** `backend/tests/test_export_hardening.py` lines 181-220
**Apply to:** `backend/tests/test_export_access.py`

Patch `app.processing.export.router.export_dataset` with a monkeypatch that writes
`b"mock export data"` to a temp file and returns `(file_path, filename, media_type)`.
Use `monkeypatch` fixture (not `unittest.mock`) for consistency with the existing pattern.

---

## No Analog Found

None — all three files have close analogs in the codebase.

---

## Metadata

**Analog search scope:** `backend/app/processing/export/`, `backend/app/modules/catalog/datasets/api/`, `backend/app/standards/ogc/`, `backend/app/modules/auth/`, `backend/app/api/`, `backend/tests/`
**Files scanned:** 8 source files + 3 test files
**Pattern extraction date:** 2026-05-30
