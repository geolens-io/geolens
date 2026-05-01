# Phase 225: processing-port-protocol-cycle-inversion — Pattern Map

**Mapped:** 2026-05-01
**Files analyzed:** 13 (3 new, 2 modified scaffold, 8 caller migrations)
**Analogs found:** 13 / 13

---

## File Classification

| New / Modified File | Status | Role | Data Flow | Closest Analog | Match Quality |
|---------------------|--------|------|-----------|----------------|---------------|
| `backend/app/core/processing_port.py` | NEW | protocol-definition | structural-typing | `backend/app/core/identity.py` | exact |
| `backend/app/platform/extensions/defaults.py` | MODIFY (append) | default-impl | request-response | `defaults.py:46-76` (`DefaultAuditSink`) | exact |
| `backend/app/platform/extensions/__init__.py` | MODIFY (append) | accessor | request-response | `__init__.py:115-129` (`get_identity_extension`) | exact |
| `backend/tests/test_processing_port.py` | NEW | test-seam | unit | `backend/tests/test_embedding_backfill.py` | role-match |
| `backend/tests/test_layering.py` | MODIFY (append) | architecture-guard | static-analysis | `test_layering.py:421-489` + `333-418` | exact |
| `backend/app/processing/ai/service.py` | MODIFY | service | request-response | itself (post-D-15 annotation rewrite) | self |
| `backend/app/processing/ai/router.py` | MODIFY | route | request-response | itself | self |
| `backend/app/processing/ai/chat_service.py` | MODIFY | service | request-response | itself | self |
| `backend/app/processing/ai/metadata_service.py` | MODIFY | service | request-response | itself | self |
| `backend/app/processing/tiles/router.py` | MODIFY | route | request-response | itself | self |
| `backend/app/processing/export/router.py` | MODIFY | route | request-response | itself | self |
| `backend/app/processing/embeddings/backfill.py` | MODIFY | worker | batch | itself | self |
| `backend/app/processing/ingest/service.py` | MODIFY | service | batch | itself | self |

---

## Pattern Assignments

---

### 1. `backend/app/core/processing_port.py` (NEW — protocol-definition)

**Analog:** `backend/app/core/identity.py` (verbatim mirror)

**Module docstring + `from __future__ import annotations` header** (`identity.py:1-22`):
```python
"""Cross-domain catalog access contract.

Defines structural Protocols that processing/* uses to read and write
catalog data without importing the concrete SQLAlchemy ORM from
app.modules.catalog.*. Concrete ORM classes (Dataset, Record, Map,
DatasetGrant) satisfy the Protocols structurally (PEP 544); no
inheritance is required.

Uses only stdlib types (plus SQLAlchemy's AsyncSession for async method
signatures) to avoid the core -> modules.catalog import edge that
Phase 225 (PROCESS-01..05) is closing. AsyncSession is an
infrastructure type that does NOT live under app.modules.*.

An enterprise overlay (e.g. geolens-enterprise) may replace the default
implementation by registering a tier-aware or quota-enforcing port under
the 'processing_port' key via the geolens.extensions entry-point group;
get_processing_port() returns it on subsequent requests. Phase 226
(AIProviderExtension) is the next consumer of this boundary.
"""

from __future__ import annotations
```

**Imports + TYPE_CHECKING block** (`identity.py:22-30`, `protocols.py:11-19` for TYPE_CHECKING shape):
```python
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Protocol, Sequence, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.modules.catalog.search.service import SearchFilters
    from app.modules.catalog.datasets.domain.schemas import IngestionResult
```

**`@runtime_checkable` companion Protocol shape** (`identity.py:32-43` — `RoleProtocol` as model for slim companion Protocols):
```python
@runtime_checkable
class RoleProtocol(Protocol):
    """Slim role contract — ``name`` is the only attribute cross-domain code reads."""
    name: str
```
Use this shape for `KeywordProtocol`, `AttributeProtocol`, `DatasetGrantProtocol`.

**`@runtime_checkable` main Protocol with comprehensive surface** (`identity.py:46-68`):
```python
@runtime_checkable
class IdentityProtocol(Protocol):
    """Comprehensive identity surface read by ~42 cross-domain call sites.

    The 6-field surface (D-01) covers every read of the concrete ``User``
    ORM made outside the ``auth/`` and ``admin/`` modules: ...
    """

    id: uuid.UUID
    username: str
    email: str | None
    is_active: bool
    roles: Sequence[RoleProtocol]
    created_at: datetime
```
Mirror this shape for `DatasetProtocol`, `RecordProtocol`, `MapProtocol`.

**Type alias pattern** (`identity.py:71-76`):
```python
# Shorter alias for caller annotations (Phase 214 D-05).
# Both names are exported; ``Identity`` reads cleaner in parameter
# annotations and ``IdentityProtocol`` is preferred in conformance
# assertions / runtime ``isinstance`` checks.
Identity = IdentityProtocol
```
Use this pattern for `Dataset = DatasetProtocol`, `Record = RecordProtocol`, `Map = MapProtocol`, `DatasetGrant = DatasetGrantProtocol`.

**Extension Protocol shape** (`identity.py:79-96`):
```python
@runtime_checkable
class IdentityExtension(Protocol):
    """Enterprise overlay registration contract for alternate identity backends."""

    async def resolve_identity_from_token(
        self, token: str, request: Request, db: AsyncSession
    ) -> Identity | None: ...
```
Phase 225 does NOT add a `ProcessingPortExtension` nested Protocol (D-13). The Port itself is registered directly. Do not copy the extension Protocol shape.

**Notes:**
- `spatial_extent` on `RecordProtocol` must be typed `Any` (not geoalchemy2) to keep `core/` free of geoalchemy2 import.
- `apply_visibility_filter` is **synchronous** (not async) — mirrors `catalog/authorization.py:34`.
- `extract_bbox` is **synchronous** — mirrors `catalog/datasets/domain/utils.py:8`.
- `build_gdal_source` is **synchronous** — purely computational.
- No `TYPE_CHECKING` import of `IdentityExtension` needed; `ProcessingPort` is its own Protocol, not nested.

---

### 2. `backend/app/platform/extensions/defaults.py` — append `DefaultProcessingPort` (MODIFY)

**Analog:** `defaults.py:46-76` (`DefaultAuditSink`) — exact deferred-import forwarder shape.

**Deferred-import method body pattern** (`defaults.py:62-76`):
```python
class DefaultAuditSink:
    """Community-edition default: writes one audit_logs row via log_action().

    log_action() is preserved as an internal helper (Phase 222 D-04 / AUDIT-02
    option a). ...

    The async signature is intentional: enterprise overlays may perform non-blocking
    I/O (S3 PutObject, SIEM HTTP POST). All sinks — community and enterprise — are
    awaited by ``audit_emit()``.
    """

    async def emit(self, session, event) -> None:  # type: ignore[no-untyped-def]
        # Deferred import: log_action lives in app.modules.audit.service.
        # extensions/ is platform-level and should not pull modules-level
        # imports at module load (Phase 214 deferred-import discipline).
        from app.modules.audit.service import log_action

        await log_action(
            session,
            user_id=event.user_id,
            action=event.action,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            details=event.details,
            ip_address=event.ip_address,
        )
```

**`DefaultIdentityExtension` shape** (`defaults.py:27-43`) — simpler no-op variant as secondary reference:
```python
class DefaultIdentityExtension:
    """Default identity: no alternate backend registered (Phase 214 D-14).

    Returning None from ``resolve_identity_from_token`` signals the auth
    dep chain to fall through to the existing JWT decode + DB lookup path.
    ...
    """

    async def resolve_identity_from_token(self, token, request, db):  # type: ignore[no-untyped-def]
        return None
```

**Template for each `DefaultProcessingPort` method:**
```python
class DefaultProcessingPort:
    """Community-edition default: delegates every call to app.modules.catalog.*
    via deferred imports (Phase 225 D-09 / D-11 / PROCESS-01).

    Each method does a deferred import into app.modules.catalog.* inside the
    function body, keeping platform/extensions/ free of module-load-time
    modules.* edges (Phase 214 deferred-import discipline). Behavior is
    identical to the pre-Phase-225 baseline — the Port is the seam, not a
    re-implementation.

    DefaultProcessingPort.create_dataset, .get_dataset etc. delegate via the
    app.modules.catalog.datasets.domain.service FACADE (never the sub-modules
    directly — Phase 224 DECOUPLE-04).
    """

    async def get_dataset(self, session, dataset_id):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.service import get_dataset
        return await get_dataset(session, dataset_id)

    def apply_visibility_filter(self, stmt, user, user_roles, record_cls, grant_cls=None):  # type: ignore[no-untyped-def]
        from app.modules.catalog.authorization import apply_visibility_filter
        return apply_visibility_filter(stmt, user, user_roles, record_cls, grant_cls)
```

**Notes:**
- Every method uses `# type: ignore[no-untyped-def]` (same as `DefaultAuditSink.emit` and `DefaultIdentityExtension.resolve_identity_from_token`).
- Async methods: `get_dataset`, `get_record`, `search_datasets`, `check_dataset_access`, `get_user_roles`, `get_column_stats`, `get_distinct_values`, `create_dataset`, `create_map`, `update_map`.
- Sync methods: `apply_visibility_filter`, `extract_bbox`, `build_gdal_source`.
- Class docstring must cite Phase 225 D-09 / D-11 / PROCESS-01 and the Phase 224 façade discipline.
- Delegate `create_dataset`, `get_dataset`, `search_datasets` through `app.modules.catalog.datasets.domain.service` façade (NOT sub-modules).

---

### 3. `backend/app/platform/extensions/__init__.py` — append `get_processing_port()` (MODIFY)

**Analog:** `__init__.py:115-129` (`get_identity_extension`) — single-slot accessor pattern.

**Import additions to top of file** (mirrors existing pattern at `__init__.py:15-32`):
```python
from app.platform.extensions.defaults import (
    DefaultAuditExtension,
    DefaultAuditSink,          # NEW (Phase 222)
    DefaultAuthExtension,
    DefaultBillingExtension,   # NEW (Phase 223)
    DefaultBrandingExtension,
    DefaultIdentityExtension,
    DefaultProcessingPort,     # NEW (Phase 225)
)
```
And in the `TYPE_CHECKING` block:
```python
if TYPE_CHECKING:
    from app.core.identity import IdentityExtension
    from app.core.processing_port import ProcessingPort   # NEW (Phase 225)
```

**Single-slot accessor body** (`__init__.py:115-129`):
```python
def get_identity_extension() -> "IdentityExtension":
    """Return the registered IdentityExtension or the community default.

    Phase 214 / IDENT-03 — mirrors ``get_branding_extension()``,
    ``get_audit_extension()``, and ``get_auth_extension()`` exactly.
    Enterprise overlays register an implementation under the ``"identity"``
    key via the ``geolens.extensions`` entry-point group; community
    edition gets the no-op ``DefaultIdentityExtension`` whose
    ``resolve_identity_from_token`` returns ``None`` (existing JWT
    path runs unchanged).
    """
    ext = _extensions.get("identity")
    if ext is None:
        return DefaultIdentityExtension()
    return ext  # type: ignore[return-value]
```

**Template for `get_processing_port()`:**
```python
def get_processing_port() -> "ProcessingPort":
    """Return the registered ProcessingPort or the community default.

    Phase 225 / PROCESS-01 — single-slot shape (D-12), NOT list-shape
    like get_audit_sinks() / get_billing_extensions(). ProcessingPort is
    a singleton consumer surface; overlays REPLACE rather than append.

    Enterprise overlays register a tier-aware / quota-enforcing wrapper
    under the ``"processing_port"`` key via the ``geolens.extensions``
    entry-point group::

        registry["processing_port"] = TierAwareProcessingPort(quota_config)

    Community edition gets DefaultProcessingPort which forwards every
    call to the existing app.modules.catalog.* functions via deferred
    imports (D-09 / D-11 — behavior is byte-for-byte identical to
    pre-Phase-225).
    """
    ext = _extensions.get("processing_port")
    if ext is None:
        return DefaultProcessingPort()
    return ext  # type: ignore[return-value]
```

**Notes:**
- `"processing_port"` is the registry key (not `"processing"` — be precise).
- `get_processing_port()` returns the `DefaultProcessingPort()` directly if unregistered (no `or` short-circuit — mirrors `get_identity_extension`'s `if ext is None` shape, not `_extensions.get(...) or Default...()`).
- The `TYPE_CHECKING` guard means `ProcessingPort` is only imported when type-checking — no runtime import cost.

---

### 4. `backend/tests/test_processing_port.py` (NEW — test-seam unit test)

**Analog:** `backend/tests/test_embedding_backfill.py` — pure unit test with no DB, using `AsyncMock`/`MagicMock` stubs. `@pytest.mark.asyncio` marker.

**File header pattern** (`test_embedding_backfill.py:1-10`):
```python
"""Tests for embedding backfill: backfill_embeddings processes records without
embeddings, handles errors gracefully, and returns progress counts.

Unit tests using mocks -- no running database required.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
```

**Async test method marker** (`test_embedding_backfill.py:39`, `test_ai_metadata.py:111`):
```python
@pytest.mark.asyncio
async def test_processes_records_without_embeddings(self):
    ...
```
Note: Some test files use `@pytest.mark.anyio` (HTTP integration tests) and some use `@pytest.mark.asyncio` (pure unit tests without `AsyncClient`). For `test_processing_port.py`, use `@pytest.mark.asyncio` — it is a pure unit test with no HTTP client, matching `test_embedding_backfill.py`.

**`FakeProcessingPort` skeleton** (from RESEARCH.md §Test Seam Specification — the complete skeleton to copy verbatim):
```python
class FakeProcessingPort:
    """Minimal stub implementing the ProcessingPort surface with canned returns."""

    def __init__(self):
        _dataset_id = uuid.uuid4()
        self._dataset = MagicMock()
        self._dataset.id = _dataset_id
        self._dataset.table_name = "test_dataset_table"
        self._dataset.geometry_type = "Polygon"
        self._dataset.feature_count = 100
        self._dataset.srid = 4326
        self._dataset.column_info = [{"name": "area", "type": "float"}]
        self._dataset.sample_values = {"area": [1.0, 2.0]}
        self._dataset.record = MagicMock()
        self._dataset.record.title = "Test Dataset"
        self._dataset.record.summary = "A test dataset"
        self._dataset.record.keywords = []
        self._dataset.record.spatial_extent = None

        self._map = MagicMock()
        self._map.id = uuid.uuid4()
        self._map.name = "Test Map"
        self._dataset_id = str(_dataset_id)

    async def search_datasets(self, session, user, user_roles, filters):
        return ([self._dataset], 1)

    def apply_visibility_filter(self, stmt, user, user_roles, record_cls, grant_cls=None):
        return stmt  # No-op

    async def check_dataset_access(self, session, dataset, dataset_id, user, *, user_roles=None):
        return user_roles or set()

    async def get_user_roles(self, session, user):
        return {"viewer"}

    async def get_dataset(self, session, dataset_id):
        if str(dataset_id) == self._dataset_id:
            return self._dataset
        return None

    async def get_record(self, session, record_id):
        return self._dataset.record

    async def get_column_stats(self, session, table_name, column_name, **kwargs):
        return {"min": 0.0, "max": 100.0, "count": 100, "mean": 50.0, "quantiles": [25.0, 50.0, 75.0]}

    async def get_distinct_values(self, session, table_name, column_name, limit=100, **kwargs):
        return ["A", "B", "C"]

    def extract_bbox(self, dataset):
        return [-74.0, 40.7, -73.9, 40.8]

    async def create_dataset(self, session, table_name, title, created_by, **kwargs):
        return self._dataset

    async def create_map(self, session, name, description, created_by, notes=None):
        self._map.name = name
        return self._map

    async def update_map(self, session, map_id, **kwargs):
        return (self._map, [], None, None)

    def build_gdal_source(self, service_type, base_url, layer_name, **kwargs):
        return (f"{service_type}:{base_url}", layer_name)
```

**Notes:**
- `fake_session` and `fake_user` are fixtures that must either be defined locally or imported from `tests/conftest.py`. Check conftest for existing `AsyncMock()` session fixture before adding a new one.
- The test calls a D-15 service-layer function (e.g., `generate_map_from_prompt`) with `port=FakeProcessingPort()` explicitly — this is the seam proof.
- No DB required; pure in-process.

---

### 5. `backend/tests/test_layering.py` — append `test_no_processing_imports_catalog` (MODIFY)

**Analog A:** `test_layering.py:421-489` (`test_no_log_action_calls_outside_audit_service`) — simple subprocess.run shape with two pathspec exclusions.

**Analog B:** `test_layering.py:333-418` (`test_no_external_imports_of_dataset_domain_submodules`) — _git_grep helper shape with allowlist filtering.

**`test_no_log_action_calls_outside_audit_service` — full body to adapt** (`test_layering.py:421-489`):
```python
@pytest.mark.architecture
def test_no_log_action_calls_outside_audit_service() -> None:
    """Phase 222 AUDIT-02: ..."""
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")
    if not _has_pathspec_magic():
        pytest.skip(
            "git < 2.13 lacks `:!` pathspec exclusion; cannot enforce "
            "Phase 222 AUDIT-02 invariant via grep-based guard"
        )

    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-E",
            r"\bawait log_action\(",
            "--",
            "backend/app/",
            ":!backend/app/modules/audit/service.py",
            ":!backend/app/platform/extensions/defaults.py",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        pytest.fail(
            "Phase 222 AUDIT-02 invariant violated: log_action() is called "
            "outside ... Offending lines:\n{result.stdout}"
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )
```

**Adaptation for Phase 225 — concrete invocation from RESEARCH.md §Architecture Guard Specification:**
```python
@pytest.mark.architecture
def test_no_processing_imports_catalog() -> None:
    """Phase 225 PROCESS-02/04: backend/app/processing/ must not import from app.modules.catalog.*.

    All catalog access must go through ProcessingPort (app.core.processing_port).
    Strict zero-hit — no allowlist for processing/* (D-23).

    Excluded paths:
      - backend/tests/ — test fixtures construct catalog ORM objects directly,
        structurally satisfying the Protocols (D-23 pathspec exclusion).

    Maps to Phase 225 ROADMAP SC#2 / SC#3. Inlines former Phase 999.11
    (added in same phase as the inversion — guard before inversion fails CI).
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")
    if not _has_pathspec_magic():
        pytest.skip(
            "git < 2.13 lacks `:!` pathspec exclusion; cannot enforce "
            "Phase 225 PROCESS-04 invariant via grep-based guard"
        )

    result = subprocess.run(
        [
            "git", "grep", "-n", "-E",
            r"^\s*(from|import)\s+app\.modules\.catalog",
            "--",
            "backend/app/processing/",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        pytest.fail(
            "Phase 225 PROCESS-02/04 invariant violated: backend/app/processing/ "
            "contains direct imports from app.modules.catalog.*. All catalog access "
            "must go through ProcessingPort (app.core.processing_port). "
            f"Offending lines:\n{result.stdout}"
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )
```

**Module docstring update** — prepend Phase 225 to the existing docstring's Phase list. Current first lines (`test_layering.py:1-6`):
```python
"""Layering rules across Phases 212, 213, and 214.

Enforces open-core boundaries closed by:
- Phase 212 LAYER-01 - core/ must not depend on modules/settings/.
- Phase 213 LAYER-02 - modules/auth/visibility.py is gone; catalog authorization
  lives at app.modules.catalog.authorization.
- Phase 214 IDENT-01..03 - core/ broadened: must not depend on ANY app.modules.*.
```
Add Phase 225 entry:
```
- Phase 225 PROCESS-02/04 - processing/ must not import from app.modules.catalog.*;
  all catalog access goes through ProcessingPort (app.core.processing_port).
```

**Notes:**
- Phase 225's guard uses `subprocess.run(...)` directly (same as `test_no_log_action_calls_outside_audit_service`), NOT `_git_grep()` helper — because the scan target is `backend/app/processing/` with NO `:!` exclusions needed (tests/ is not under processing/). The `_has_pathspec_magic()` guard is still needed for future-proofing even without `:!` pathspecs (per the existing pattern).
- Strict zero-hit: NO allowlist loop (unlike `test_no_external_imports_of_dataset_domain_submodules`). Fail immediately if `returncode == 0`.

---

## Caller Migration Pattern (8 Files)

The 8 caller files share one mechanical swap pattern. The pattern mapper extracts the **before** and **after** import shapes:

### Before (representative — `processing/ai/service.py:31-39`):
```python
from app.core.identity import Identity
from app.core.config import settings
from app.modules.catalog.authorization import apply_visibility_filter
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record
from app.modules.catalog.datasets.domain.utils import extract_bbox
from app.modules.catalog.datasets.domain.column_stats import get_column_stats
from app.modules.catalog.maps.service import create_map, update_map
from app.processing.ai.token_usage import record_token_usage
from app.modules.catalog.search.service import SearchFilters, search_datasets
```

### After (D-15 + D-14 HTTP route shape):
```python
from app.core.identity import Identity
from app.core.config import settings
from app.core.processing_port import Dataset, DatasetGrant, Record
from app.platform.extensions import get_processing_port

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort
    from app.modules.catalog.search.service import SearchFilters
```
All `apply_visibility_filter(...)`, `extract_bbox(...)`, `get_column_stats(...)`, `create_map(...)`, `update_map(...)`, `search_datasets(...)` calls become `port.apply_visibility_filter(...)`, etc. Service-layer functions gain `port: ProcessingPort` as a keyword-only parameter with no default (D-15).

### Before (worker/deferred — representative, `ingest/tasks_vector.py:302`):
```python
# Inside function body:
from app.modules.catalog.sources.preview import build_gdal_source
...
url, layer = build_gdal_source(service_type, base_url, ...)
```

### After (D-14 worker shape — keep deferral, swap path):
```python
# Inside function body:
from app.platform.extensions import get_processing_port
port = get_processing_port()
url, layer = port.build_gdal_source(service_type, base_url, ...)
```

### HTTP route wire-in shape (D-14):
```python
# In router function signature:
async def some_route(
    ...
    db: AsyncSession = Depends(get_db),
    current_user: Identity = Depends(get_current_active_user),
    port: ProcessingPort = Depends(get_processing_port),
):
    ...
```

---

## Shared Patterns

### `from __future__ import annotations`
**Source:** `backend/app/core/identity.py:22`, `backend/app/platform/extensions/protocols.py:11`
**Apply to:** `core/processing_port.py`, `defaults.py` (already present)

### `@runtime_checkable` on every Protocol
**Source:** `backend/app/core/identity.py:32,46,79`
**Apply to:** All companion Protocols and `ProcessingPort` in `core/processing_port.py`

### `TYPE_CHECKING` forward-reference for catalog-domain types
**Source:** `backend/app/platform/extensions/protocols.py:18-19`
```python
if TYPE_CHECKING:
    from app.modules.audit.events import AuditEvent
```
**Apply to:** `core/processing_port.py` for `SearchFilters`, `IngestionResult`.
**Apply to:** `platform/extensions/__init__.py` for `ProcessingPort` itself.

### `# type: ignore[no-untyped-def]` on Default impl methods
**Source:** `backend/app/platform/extensions/defaults.py:42,62`
**Apply to:** Every method in `DefaultProcessingPort`

### Deferred import inside method bodies
**Source:** `backend/app/platform/extensions/defaults.py:63-66`
```python
async def emit(self, session, event) -> None:  # type: ignore[no-untyped-def]
    # Deferred import: log_action lives in app.modules.audit.service.
    # extensions/ is platform-level and should not pull modules-level
    # imports at module load (Phase 214 deferred-import discipline).
    from app.modules.audit.service import log_action
```
**Apply to:** Every method in `DefaultProcessingPort` — deferred import in the method body, not at module level.

### Phase 224 façade discipline
**Source:** CONTEXT.md §Canonical References ("Phase 224 façade discipline")
**Apply to:** `DefaultProcessingPort` — import from `app.modules.catalog.datasets.domain.service` (the façade), never from `service_create.py`, `service_query.py`, etc. directly.

---

## No Analog Found

No files lack a close analog. All patterns are drawn from existing code:

| Pattern Need | Resolution |
|---|---|
| `FakeProcessingPort` test-seam construction | RESEARCH.md §Test Seam Specification provides the complete skeleton |
| `test_no_processing_imports_catalog` exact invocation | RESEARCH.md §Architecture Guard Specification provides the exact `subprocess.run` call |

---

## Metadata

**Analog search scope:** `backend/app/core/`, `backend/app/platform/extensions/`, `backend/tests/`
**Files scanned:** 8 (identity.py, defaults.py, extensions/__init__.py, protocols.py, test_layering.py ×3 ranges, test_embedding_backfill.py)
**Pattern extraction date:** 2026-05-01
