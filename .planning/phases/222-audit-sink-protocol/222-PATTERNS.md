# Phase 222: audit-sink-protocol - Pattern Map

**Mapped:** 2026-04-30
**Files analyzed:** 8 new/modified target files (additive scaffolding + facade + dataclass + tests + Makefile) + 19 call-site files (mechanical rewrite — exemplar mapped)
**Analogs found:** 8 / 8 (all targets have exact or role-match analogs in-tree)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/app/platform/extensions/protocols.py` (APPEND `AuditSink`) | Protocol | structural-typing | `BrandingExtension`/`AuditExtension`/`AuthExtension` in **same file** + `IdentityExtension` in `app/core/identity.py:79-96` | exact |
| `backend/app/platform/extensions/defaults.py` (APPEND `DefaultAuditSink`) | default | delegation | `DefaultIdentityExtension` in **same file** (lines 27-43, async method shape) | exact |
| `backend/app/platform/extensions/__init__.py` (APPEND `get_audit_sinks()`) | accessor | registry-lookup | `get_audit_extension()` lines 95-100 (and 3 siblings) in **same file** | role-match (departure: list return, lazy default) |
| `backend/app/modules/audit/events.py` (NEW — `AuditEvent`) | event (frozen dataclass) | value-object | `log_action()` parameter list at `audit/service.py:49-57` (1:1 field mirror) | role-match (no exact frozen-dataclass analog in tree; pattern is canonical Python stdlib) |
| `backend/app/modules/audit/service.py` (APPEND `audit_emit()`) | facade | request-response (in-process fan-out) | `log_action()` lines 49-67 in **same file** (signature shape + `structlog` use at `extensions/__init__.py:30`) | role-match |
| `backend/tests/test_audit_sink.py` (NEW) | test | integration + unit | `backend/tests/test_audit.py:242-270` (`_enterprise_audit_ext`) + `backend/tests/conftest.py:454-484` (`saml_overlay_registered`) | exact |
| `backend/tests/test_layering.py` (APPEND `test_no_log_action_calls_outside_audit_service`) | architecture-guard | git-grep invariant | `test_no_imports_from_auth_visibility` at lines 159-185 + `test_no_auth_visibility_module_referenced` at lines 188-233 | exact |
| `Makefile` (APPEND `audit-sink-discipline` target — optional, Wave 6) | config | make-target wrapper | `openapi-check` line 42-43, `sdks-check`, `cli-check` targets | role-match |
| **65 call-site rewrites across 19 files** | call-site-rewrite | request-response | `backend/app/modules/admin/router.py:113-121` (exemplar — `user.create`) | exact (mechanical 1:1) |

## Pattern Assignments

### `backend/app/platform/extensions/protocols.py` (Protocol — APPEND `AuditSink`)

**Analog:** `backend/app/platform/extensions/protocols.py` (existing 3 Protocols in same file) + `backend/app/core/identity.py:79-96` (existing async-method Protocol with `AsyncSession` import)

**Imports pattern** (`protocols.py` lines 1-8 — current state):
```python
"""Protocol interfaces for GeoLens extension points.

Uses only stdlib types to avoid circular imports with domain models.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
```

**Existing Protocol shape** (`protocols.py` lines 11-29):
```python
@runtime_checkable
class BrandingExtension(Protocol):
    """Extension point for branding customization."""

    def get_branding_defaults(self) -> dict[str, object]: ...


@runtime_checkable
class AuditExtension(Protocol):
    """Extension point for audit export formats."""

    def get_export_formats(self) -> list[str]: ...


@runtime_checkable
class AuthExtension(Protocol):
    """Extension point for additional auth methods."""

    def get_auth_methods(self) -> list[str]: ...
```

**Async-method + AsyncSession import precedent** (`backend/app/core/identity.py:22-29, 79-96`):
```python
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol, Sequence, runtime_checkable

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

# ...

@runtime_checkable
class IdentityExtension(Protocol):
    """Enterprise overlay registration contract for alternate identity backends."""

    async def resolve_identity_from_token(
        self, token: str, request: Request, db: AsyncSession
    ) -> Identity | None: ...
```

**Pattern to copy:** `@runtime_checkable class X(Protocol): async def method(...) -> ...: ...`. Phase 222's `AuditSink` adds a 4th sibling protocol. The "stdlib only" docstring claim was already broken (precedent) by `core/identity.py` for the same reason — `AsyncSession` is infrastructure-level, not in `app.modules.*`, no cycle. **`AuditEvent` import must use `if TYPE_CHECKING:` forward-ref** to avoid `protocols.py → modules.audit.events` edge.

**Add (Phase 222):**
```python
from typing import Protocol, TYPE_CHECKING, runtime_checkable
from sqlalchemy.ext.asyncio import AsyncSession  # NEW (precedent: core/identity.py:29)

if TYPE_CHECKING:
    from app.modules.audit.events import AuditEvent

@runtime_checkable
class AuditSink(Protocol):
    """Write-side hook for audit event emission.

    Sibling to AuditExtension (read-side export-format gating). Enterprise
    overlays subscribe by appending instances to _extensions["audit_sinks"].
    """

    async def emit(self, session: AsyncSession, event: "AuditEvent") -> None: ...
```

---

### `backend/app/platform/extensions/defaults.py` (default — APPEND `DefaultAuditSink`)

**Analog:** `DefaultIdentityExtension` in same file (lines 27-43) — only async-default in the file today.

**Existing async-default shape** (`defaults.py:27-43`):
```python
class DefaultIdentityExtension:
    """Default identity: no alternate backend registered (Phase 214 D-14).

    Returning None from ``resolve_identity_from_token`` signals the auth
    dep chain (``get_optional_user`` / ``get_current_user``, retyped in
    Plan 02) to fall through to the existing JWT decode + DB lookup path.
    Community edition behavior is exactly today's behavior — one async
    method call returning None per request.

    The async signature is intentional (Pitfall 8). Enterprise auth
    overlays may perform DB lookups; the dep wire-in does
    ``await ext.resolve_identity_from_token(token, request, db)``, so
    all implementations — community and enterprise — MUST be async.
    """

    async def resolve_identity_from_token(self, token, request, db):  # type: ignore[no-untyped-def]
        return None
```

**Pattern to copy:** Plain class (no Protocol inheritance — PEP 544 structural subtyping), single async method, untyped params with `# type: ignore[no-untyped-def]` if needed, docstring explaining community-edition default behavior + rationale for async signature.

**Add (Phase 222):** `DefaultAuditSink.emit()` calls preserved `log_action()` via deferred import (matches Phase 214 discipline — `defaults.py` is platform-level, must not pull `modules.*` imports at module load):
```python
class DefaultAuditSink:
    """Community-edition default: writes one audit_logs row via log_action().

    log_action() is preserved as an internal helper (D-04 / AUDIT-02 option a).
    Application code does NOT call log_action() directly post-Phase-222; only
    this sink does.

    Does NOT swallow exceptions internally (D-07) — only the audit_emit()
    facade swallows. Internal swallowing would silently lose session.flush()
    constraint failures that today's tests expect to surface.
    """

    async def emit(self, session, event) -> None:  # type: ignore[no-untyped-def]
        # Deferred import: log_action lives in app.modules.audit.service.
        # extensions/ is platform-level and should not pull modules-level
        # imports at module load (matches Phase 214 deferred-import discipline).
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

---

### `backend/app/platform/extensions/__init__.py` (accessor — APPEND `get_audit_sinks()`)

**Analog:** `get_audit_extension()` at lines 95-100 (and 3 siblings: `get_branding_extension`, `get_auth_extension`, `get_identity_extension`).

**Existing single-instance accessor** (`__init__.py:95-100`):
```python
def get_audit_extension() -> AuditExtension:
    """Return the registered AuditExtension or the community default."""
    ext = _extensions.get("audit")
    if ext is None:
        return DefaultAuditExtension()
    return ext  # type: ignore[return-value]
```

**Imports block** (`__init__.py:13-30`):
```python
import structlog

from app.platform.extensions.defaults import (
    DefaultAuditExtension,
    DefaultAuthExtension,
    DefaultBrandingExtension,
    DefaultIdentityExtension,
)
from app.platform.extensions.protocols import (
    AuditExtension,
    AuthExtension,
    BrandingExtension,
)

if TYPE_CHECKING:
    from app.core.identity import IdentityExtension

logger = structlog.stdlib.get_logger(__name__)

_extensions: dict[str, object] = {}
_routers: list = []
_loaded: bool = False
```

**Pattern to copy:** Slot-lookup-or-default. Phase 222 adds **one departure** (D-09): list-typed return. The default is created fresh on each call when the slot is missing (D-11), matching existing accessors' shape.

**Add (Phase 222):**
```python
# Update existing imports block:
from app.platform.extensions.defaults import (
    DefaultAuditExtension,
    DefaultAuditSink,           # NEW
    DefaultAuthExtension,
    DefaultBrandingExtension,
    DefaultIdentityExtension,
)
from app.platform.extensions.protocols import (
    AuditExtension,
    AuditSink,                  # NEW
    AuthExtension,
    BrandingExtension,
)

# NEW accessor (after existing 4):
def get_audit_sinks() -> list[AuditSink]:
    """Return all registered AuditSinks, or [DefaultAuditSink()] when none.

    Departure from the four existing single-instance accessors: returns a
    list (D-09 — community always has 1 sink, enterprise can have N).
    Enterprise overlays append to _extensions["audit_sinks"] via
    ``setdefault + append`` in their register_extensions(registry) callback;
    do NOT reassign the slot or the community DefaultAuditSink disappears.
    """
    sinks = _extensions.get("audit_sinks")
    if sinks is None:
        return [DefaultAuditSink()]
    return list(sinks)  # type: ignore[arg-type]  # defensive copy
```

---

### `backend/app/modules/audit/events.py` (event dataclass — NEW FILE)

**Analog:** No exact frozen-dataclass analog in the codebase; `log_action()` parameter list at `audit/service.py:49-57` is the 1:1 field-mirror reference.

**`log_action()` signature mirror reference** (`audit/service.py:49-57`):
```python
async def log_action(
    session: AsyncSession,
    user_id: uuid.UUID,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
```

**Pattern to copy:** stdlib `@dataclass(frozen=True)` (PEP 557). Six fields exactly match `log_action()` parameter surface minus `session` (which is the carrier, not the payload). Frozen so sinks cannot mutate `event` between subscribers.

**Create (Phase 222):**
```python
"""Typed event payload for audit emission (Phase 222 D-02).

Sibling to log_action() parameter surface; mirrors fields 1:1.
Frozen so sinks cannot mutate the event between subscribers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class AuditEvent:
    """Immutable audit event passed to every registered AuditSink.

    user_id is required at emit-time (every emit names an actor), even though
    the AuditLog.user_id column is nullable to allow post-hoc user deletion to
    NULL-out the FK (ondelete=SET NULL — backend/app/modules/audit/models.py:22-24).
    The two are different concerns: emit-time actor naming vs row-storage
    nullability.

    Sink implementations MUST NOT mutate event.details (Pitfall F): frozen=True
    prevents attribute reassignment but NOT dict-content mutation; trust the
    contract.
    """

    user_id: uuid.UUID
    action: str
    resource_type: str
    resource_id: uuid.UUID | None = None
    details: dict | None = None
    ip_address: str | None = None
```

---

### `backend/app/modules/audit/service.py` (facade — APPEND `audit_emit()`)

**Analog:** `log_action()` in same file (lines 49-67) for signature shape; `structlog.stdlib.get_logger(__name__)` at `extensions/__init__.py:30` for logger pattern.

**Existing `log_action()` shape** (`audit/service.py:49-67` — preserved verbatim per D-04, D-05):
```python
async def log_action(
    session: AsyncSession,
    user_id: uuid.UUID,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Create an audit log entry. Does NOT commit -- caller's transaction handles it."""
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address,
    )
    session.add(entry)
```

**Existing structlog import precedent** (`extensions/__init__.py:13, 30`):
```python
import structlog
# ...
logger = structlog.stdlib.get_logger(__name__)
```

**Pattern to copy:** module-level free `async def`, takes `(session, event)`, iterates `get_audit_sinks()`, per-sink try/except per AUDIT-03 (D-06–D-08). The default sink does NOT swallow internally; only the facade does. Structured-log fields `sink`, `action`, `resource_type`, `resource_id`.

**Add (Phase 222) — at top of `audit/service.py`:**
```python
import structlog

# Existing imports stay:
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from app.modules.audit.models import AuditLog

# NEW:
from app.modules.audit.events import AuditEvent  # re-exported below
from app.platform.extensions import get_audit_sinks

logger = structlog.stdlib.get_logger(__name__)


async def audit_emit(session: AsyncSession, event: AuditEvent) -> None:
    """Dispatch event to every registered AuditSink with per-sink failure isolation.

    AUDIT-03: a sink that raises does NOT break the surrounding business op.
    Failures are logged via structlog.exception() but do not propagate.
    AUDIT-05: DefaultAuditSink runs first by virtue of the lazy-default list
    ordering — enterprise overlays append after via setdefault + append.
    """
    for sink in get_audit_sinks():
        try:
            await sink.emit(session, event)
        except Exception:  # broad: AUDIT-03 contract — never propagate sink failures
            logger.exception(
                "Audit sink raised; suppressed per AUDIT-03",
                sink=type(sink).__name__,
                action=event.action,
                resource_type=event.resource_type,
                resource_id=str(event.resource_id) if event.resource_id else None,
            )

# log_action() definition below remains UNCHANGED (D-04, D-05).
```

---

### Call-Site Rewrite — Exemplar (`backend/app/modules/admin/router.py:112-122`)

**Analog (and exemplar BEFORE/AFTER):** `admin/router.py:112-122` (`user.create` — highest-density file).

**Variant landscape verified across the 65 sites:**
- All-keyword (`session=db, user_id=..., ...`) ≈ 40 sites — admin/auth/settings/persistent_config/config_ops/sources/layers
- First-arg-positional (`db, user_id=..., ...`) ≈ 25 sites — maps/datasets/features/embed_tokens/processing/tasks_common
- Both transform identically: wrap kwargs in `AuditEvent(...)`, pass session as positional, drop `session=` keyword.

#### BEFORE (admin/router.py:112-122 — `user.create` exemplar):
```python
ip = get_client_ip(request)
await log_action(
    session=db,
    user_id=current_user.id,
    action="user.create",
    resource_type="user",
    resource_id=user.id,
    details={"username": body.username, "role": body.role},
    ip_address=ip,
)
await db.commit()
```

#### AFTER (Phase 222 D-15, D-16 — same args, wrapped in `AuditEvent`):
```python
ip = get_client_ip(request)
await audit_emit(
    db,
    AuditEvent(
        user_id=current_user.id,
        action="user.create",
        resource_type="user",
        resource_id=user.id,
        details={"username": body.username, "role": body.role},
        ip_address=ip,
    ),
)
await db.commit()
```

**Imports per file (BEFORE → AFTER):**
```python
# BEFORE (top-of-file, in 14 of 19 files)
from app.modules.audit.service import log_action

# AFTER
from app.modules.audit.events import AuditEvent
from app.modules.audit.service import audit_emit
# (or: `from app.modules.audit.service import audit_emit, AuditEvent` if D-02 re-exports;
#  see Open Question 2 in RESEARCH.md — recommended single-line re-export)
```

**LAZY-import sites — preserve idiom (5 total per Pitfall B):**

| File | Line(s) | Function | Why preserved |
|------|---------|----------|---------------|
| `backend/app/modules/auth/router.py` | 285, 318, 357 | 3 endpoints (`create_my_api_key`, `revoke_my_api_key`, `change_password`) | Lazy idiom inside function body — preserve as-is, just rename |
| `backend/app/processing/ingest/tasks_common.py` | 846 | `_apply_reupload_swap()` | Celery task module-import-time cycle (audit ↔ ingest) |
| `backend/app/platform/config_ops/service.py` | 283 | `apply_config()` | Lazy-import discipline (file imports `_registry`, `_is_env_only`, `log_action` all lazily) |

**Lazy-import rewrite pattern** (e.g., `auth/router.py:285`):
```python
# BEFORE (inside endpoint function body, NOT at module top)
from app.modules.audit.service import log_action

# AFTER
from app.modules.audit.events import AuditEvent
from app.modules.audit.service import audit_emit
```

**Per-file call counts (verified against grep — 65 total):**
- `backend/app/modules/admin/router.py` — 10 (lines 113, 213, 243, 298, 341, 371, 400, 488, 674, 779)
- `backend/app/modules/catalog/maps/router.py` — 9 (241, 433, 470, 510, 587, 628, 667, 823, 864)
- `backend/app/modules/catalog/sources/router.py` — 7 (56, 71, 202, 236, 321, 383, 430)
- `backend/app/modules/catalog/collections/router.py` — 5 (83, 201, 246, 280, 313)
- `backend/app/modules/catalog/features/router.py` — 4 (354, 443, 526, 592)
- `backend/app/modules/catalog/datasets/api/router.py` — 4 (159, 294, 333, 403)
- `backend/app/modules/catalog/layers/router.py` — 4 (125, 177, 237, 283)
- `backend/app/modules/catalog/sources/stac_router.py` — 3 (297, 310, 550)
- `backend/app/modules/auth/router.py` — 3 (291, 331, 375 — all LAZY-imported)
- `backend/app/modules/embed_tokens/router.py` — 3 (93, 155, 192)
- `backend/app/modules/settings/router.py` — 3 (455, 524, 582)
- `backend/app/core/persistent_config.py` — 2 (top-of-file import)
- `backend/app/modules/catalog/datasets/api/router_metadata.py` — 2 (172, 223)
- `backend/app/modules/catalog/datasets/api/router_export.py` — 1 (250)
- `backend/app/modules/embed_tokens/admin_router.py` — 1 (78)
- `backend/app/processing/export/router.py` — 1 (118)
- `backend/app/processing/ingest/tasks_common.py` — 1 (929 — LAZY at 846)
- `backend/app/platform/config_ops/service.py` — 1 (339 — LAZY at 283)

---

### `backend/tests/test_audit_sink.py` (NEW)

**Analog:** `backend/tests/test_audit.py:242-270` (`_enterprise_audit_ext` context manager) + `backend/tests/conftest.py:454-484` (`saml_overlay_registered` fixture).

**Existing `_enterprise_audit_ext` save/restore pattern** (`test_audit.py:242-270`):
```python
def _enterprise_audit_ext():
    """Context manager that registers an AuditExtension advertising csv+json."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        import app.platform.extensions as ext_mod
        from app.core.edition import init_edition
        from app.platform.extensions.defaults import DefaultAuditExtension

        prior_ext = ext_mod._extensions.get("audit")
        prior_info = __import__("app.core.edition", fromlist=["_info"])._info

        class _ExportingAudit(DefaultAuditExtension):
            def get_export_formats(self):
                return ["csv", "json"]

        ext_mod._extensions["audit"] = _ExportingAudit()
        init_edition(["audit"])
        try:
            yield
        finally:
            if prior_ext is None:
                ext_mod._extensions.pop("audit", None)
            else:
                ext_mod._extensions["audit"] = prior_ext
            __import__("app.core.edition", fromlist=["_info"])._info = prior_info

    return _ctx()
```

**Existing `saml_overlay_registered` snapshot/restore pattern** (`conftest.py:466-484`):
```python
from app.platform.extensions import _extensions, _routers

saved_ext = dict(_extensions)
saved_routers = list(_routers)
try:
    # Deferred import so collection does not require the enterprise package
    from geolens_enterprise.auth.saml import EnterpriseSamlExtension
    from geolens_enterprise.auth.saml.router import router as saml_router

    ext = EnterpriseSamlExtension()
    _extensions["auth"] = ext
    _extensions["identity"] = ext
    _routers.append(saml_router)
    yield ext
finally:
    _extensions.clear()
    _extensions.update(saved_ext)
    _routers.clear()
    _routers.extend(saved_routers)
```

**Pattern to copy:** save snapshot of `_extensions["audit_sinks"]`, set new state with `[DefaultAuditSink(), test_sink]` (Pitfall C — both must be present so AUDIT-05 default-row assertion passes), `try/yield/finally` restore. Use `caplog` (pytest stdlib) to assert structlog routed to stdlib log records — simpler than `structlog.testing.capture_logs`.

**Test surface (D-12, D-13):**
- `test_audit_sink_protocol_shape` — AUDIT-01 unit smoke (Protocol exists, `runtime_checkable`, `DefaultAuditSink` satisfies, `AuditEvent` has 6 expected fields)
- `test_fixture_sink_receives_events_alongside_default` — AUDIT-04 (FixtureSink + DefaultAuditSink both run; both record same event)
- `test_raising_sink_does_not_break_business_op` — AUDIT-03 (RaisingSink doesn't propagate; default still wrote; request 201; structlog logged)

**Trigger endpoint** for AUDIT-03/-04 integration: `POST /admin/users/` (`admin/router.py:113`'s `user.create` event — deterministic single-emit, FK to admin user).

---

### `backend/tests/test_layering.py` (APPEND `test_no_log_action_calls_outside_audit_service`)

**Analog:** `test_no_imports_from_auth_visibility` (lines 159-185) + `test_no_auth_visibility_module_referenced` (lines 188-233) — same file. The latter is the closer match (uses `:!` pathspec exclusion).

**Existing `_git_grep` helper** (`test_layering.py:80-87`):
```python
def _git_grep(pattern: str, path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "grep", "-n", "-E", pattern, "--", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
```

**Existing `_has_pathspec_magic` skip-guard precedent** (`test_layering.py:60-77, 199-205`):
```python
def _has_pathspec_magic() -> bool:
    """Return True if git supports `:!` pathspec exclusion (git >= 2.13)."""
    # ...
    match = re.search(r"git version 2\.(\d+)", result.stdout)
    return match is not None and int(match.group(1)) >= 13

# usage in test_no_auth_visibility_module_referenced:
if not _has_git_metadata():
    pytest.skip("git metadata unavailable; arch test only runs on full clones")
if not _has_pathspec_magic():
    pytest.skip(
        "git < 2.13 lacks `:!` pathspec exclusion; rely on the import-shaped "
        "guard above (test_no_imports_from_auth_visibility) instead"
    )
```

**Existing `:!` pathspec usage** (`test_layering.py:207-222`):
```python
result = subprocess.run(
    [
        "git", "grep", "-n", "-E",
        r"app\.modules\.auth\.visibility|auth\.visibility",
        "--",
        "backend/",
        ":!backend/tests/test_layering.py",
    ],
    cwd=REPO_ROOT,
    capture_output=True, text=True, check=False,
)

if result.returncode == 0:
    pytest.fail(
        "Regression: `auth.visibility` is referenced outside test_layering.py. "
        "Offending lines:\n" + result.stdout
    )
if result.returncode != 1:
    pytest.fail(
        f"git grep failed unexpectedly: rc={result.returncode}\n"
        f"stderr: {result.stderr}"
    )
```

**Pattern to copy:** `@pytest.mark.architecture` decorator, skip-guards (git metadata + pathspec magic), `git grep -n -E <pattern> -- <paths> :!<exclusions>`, assert `rc == 1` (no matches), specific failure message naming the offending lines.

**Add (Phase 222 — Wave 5):**
```python
@pytest.mark.architecture
def test_no_log_action_calls_outside_audit_service() -> None:
    """Phase 222 AUDIT-02: log_action() is called only by DefaultAuditSink.emit().

    All 65 historical call sites must route through audit_emit() instead.
    Excludes:
      - audit/service.py (defines log_action)
      - extensions/defaults.py (DefaultAuditSink.emit calls log_action — D-04)
      - tests/ (test seeds may call log_action directly — RESEARCH Open Q3 (b))
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")
    if not _has_pathspec_magic():
        pytest.skip("git < 2.13 lacks :! pathspec exclusion")

    result = subprocess.run(
        [
            "git", "grep", "-n", "-E",
            r"\bawait log_action\(",
            "--",
            "backend/app/",
            ":!backend/app/modules/audit/service.py",
            ":!backend/app/platform/extensions/defaults.py",
        ],
        cwd=REPO_ROOT,
        capture_output=True, text=True, check=False,
    )

    if result.returncode == 0:
        pytest.fail(
            "Phase 222 AUDIT-02 invariant violated: log_action() called "
            "outside the audit module. All 65 historical sites must use "
            "audit_emit() instead.\nOffending lines:\n" + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )
```

---

### `Makefile` (APPEND `audit-sink-discipline` — OPTIONAL Wave 6)

**Analog:** `openapi-check` line 42-43 (and `sdks-check`/`cli-check` siblings).

**Existing `openapi-check` pattern** (`Makefile:42-43`):
```makefile
openapi-check:
	cd backend && PYTHONPATH=. uv run python scripts/dump_openapi.py --check
```

**`.PHONY` declaration line** (`Makefile:1`):
```makefile
.PHONY: dev down reset-db migrate migration test test-cov e2e logs logs-db logs-api openapi openapi-check sdks sdks-check sdks-test publish-sdks-py publish-sdks-ts cli-build cli-test cli-check publish-cli
```

**Pattern to copy:** add target name to `.PHONY` declaration; target body uses `cd backend && PYTHONPATH=. uv run pytest <test-id>`; one-line comment above target documents the invariant.

**Add (Phase 222 — Wave 6, optional):**
```makefile
# Update .PHONY (append "audit-sink-discipline" to the list).

# Phase 222 invariant: log_action() is called only by DefaultAuditSink.emit().
# All 65 historical emit sites must route through audit_emit() instead.
audit-sink-discipline:
	cd backend && PYTHONPATH=. uv run pytest tests/test_layering.py::test_no_log_action_calls_outside_audit_service -v
```

---

## Shared Patterns

### Deferred (Lazy) Imports for Platform Layer
**Source:** `backend/app/platform/extensions/defaults.py` Phase 214 discipline, exemplified by Phase 222's `DefaultAuditSink.emit()`.
**Apply to:** `DefaultAuditSink.emit()` body (`from app.modules.audit.service import log_action` inside method, NOT at module top).
**Rationale:** `extensions/` is platform-level and must not pull `modules/*` imports at module load (would invert Phase 212/214 layering).

### Structlog Logger Pattern
**Source:** `backend/app/platform/extensions/__init__.py:13, 30`
```python
import structlog
logger = structlog.stdlib.get_logger(__name__)
```
**Apply to:** `audit_emit()` facade in `audit/service.py`. Use `logger.exception(...)` (NOT `logger.error(...)`) inside the per-sink `except Exception:` block — `.exception()` automatically includes traceback.

### Registry Save/Restore Test Fixture
**Source:** `backend/tests/conftest.py:454-484` (`saml_overlay_registered`)
**Apply to:** `test_audit_sink.py` fixture/inline-block for AUDIT-03 + AUDIT-04 tests.
```python
saved = _extensions.get("audit_sinks")
_extensions["audit_sinks"] = [DefaultAuditSink(), <test_sink>]
try:
    yield <test_sink>
finally:
    if saved is None:
        _extensions.pop("audit_sinks", None)
    else:
        _extensions["audit_sinks"] = saved
```
**Critical (Pitfall C):** seed slot to BOTH `DefaultAuditSink()` AND test sink — if only test sink, AUDIT-05 default-row assertion fails (default missing); if only-append-without-init, KeyError on missing slot.

### Architecture-Guard Test Pattern
**Source:** `backend/tests/test_layering.py:188-233` (`test_no_auth_visibility_module_referenced`)
**Apply to:** new `test_no_log_action_calls_outside_audit_service` (Wave 5).
- `@pytest.mark.architecture` decorator
- Skip-guards: `_has_git_metadata()` + `_has_pathspec_magic()`
- `git grep -n -E <pattern> -- backend/app/ :!<excluded files>`
- Assert `rc == 1` (no matches found = success), explicit `rc != 1` branch for unexpected git failures.

### Variant Argument Shapes Across Call Sites
**Source:** verified in RESEARCH.md and via direct read of `admin/router.py:113`, `auth/router.py:291`, `maps/router.py:241`.
**Apply to:** all 65 call-site rewrites.
- All-keyword (`session=db, user_id=...`) → `audit_emit(db, AuditEvent(user_id=..., ...))` — drop `session=` keyword, pass session positionally.
- First-arg-positional (`db, user_id=...`) → identical transform.
- Sites without `details` / `resource_id` / `ip_address` → `AuditEvent` defaults handle the omission (no special case needed).
**No outliers** beyond the 5 lazy-import preservation sites.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| (none) | — | — | Every Phase 222 file has at least one in-tree analog. The closest-to-novel piece is the `AuditEvent` frozen dataclass — no exact in-tree dataclass-event analog, but `log_action()`'s parameter list is the 1:1 field reference and `@dataclass(frozen=True)` is canonical Python stdlib (PEP 557). |

## Metadata

**Analog search scope:**
- `backend/app/platform/extensions/{protocols,defaults,__init__}.py`
- `backend/app/core/identity.py` (Phase 214 precedent for async-Protocol + AsyncSession import)
- `backend/app/modules/audit/{service,models,router}.py`
- `backend/tests/{test_audit,test_lifecycle,test_layering,conftest}.py`
- `Makefile`
- Sample call sites: `admin/router.py:113`, `auth/router.py:285,291,318,331,357,375`, `maps/router.py:241`, `tasks_common.py:846,929`

**Files scanned:** 14
**Pattern extraction date:** 2026-04-30
**Notes:**
- Phase 222 is the **5th instance** of the four-Protocol pattern (Branding/Audit/Auth/Identity). Every piece of scaffolding has 1-4 prior instances to copy from.
- The only **novel work** is (a) the list-typed accessor (one departure for one good reason — D-09) and (b) the per-sink try/except facade (narrow extension of `log_action()` with `for sink in get_audit_sinks()` wrapper).
- The 65-site rewrite is mechanical with **zero outliers** beyond the 5 lazy-import sites enumerated.
- Pitfall reconciliation: CONTEXT.md D-17 misattributes 4 lazy imports to `tasks_common.py`; reality is 5 lazy import sites split across 3 files (`auth/router.py:285,318,357` + `tasks_common.py:846` + `config_ops/service.py:283`). Planner uses RESEARCH.md's verified table (Pitfall B).
