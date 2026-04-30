# Phase 223: marketplace-billing-extraction - Research

**Researched:** 2026-04-30
**Domain:** FastAPI extension protocol, AWS Marketplace boto3 metering, cross-repo overlay pattern
**Confidence:** HIGH — all critical claims verified against live codebase

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01**: BILLING-03 and SC#1 are amended — boto3 stays in core for S3; goal is "AWS Marketplace API not invoked from core"
- **D-02**: `core/marketplace.py` deleted (not relocated in core); body moves verbatim to enterprise overlay
- **D-03**: `aws_marketplace_product_code` and `aws_marketplace_public_key_version` removed from core `Settings`
- **D-04**: Overlay reads AWS Marketplace env vars via `os.environ.get(...)` or its own `BillingSettings`
- **D-05**: `.env.example` AWS Marketplace section restructured with "Enterprise overlay only" header
- **D-06**: `BillingExtension` is list-shape `_extensions["billing_extensions"]`, accessor `get_billing_extensions() -> list[BillingExtension]`, lazy default `[DefaultBillingExtension()]`
- **D-07**: `DefaultBillingExtension.on_startup()` is a literal no-op (`async def on_startup(self, app): return`)
- **D-08**: `BillingExtension.on_startup` is async-only
- **D-09**: Hook signature `async def on_startup(self, app: FastAPI) -> None`; fall back to `app: object` if cycle detected
- **D-10**: Core dispatch wraps each extension with `asyncio.wait_for(..., timeout=10.0)` + per-extension try/except (TimeoutError + Exception)
- **D-11**: 10-second timeout hardcoded, not configurable
- **D-12**: Failure scope is per-extension, per-startup; no circuit-breaking
- **D-13**: Conditional gate (`if AWS_MARKETPLACE_PRODUCT_CODE`) lives in overlay's `on_startup`, not in core dispatch
- **D-14**: Cross-repo phase — both `geolens` (core) and `geolens-enterprise` (overlay) receive changes
- **D-15**: Fixture-based extension test in `backend/tests/test_billing_extension.py` (new file)
- **D-16**: Architecture-guard test in `backend/tests/test_layering.py` + Makefile target
- **D-17**: BILLING-06 verified by running `/oc-audit` after both Phase 222 and Phase 223 ship

### Claude's Discretion

- `MarketplaceBillingExtension` internal organization (overlay-side) — single class or helper module
- `BillingSettings` Pydantic vs `os.environ.get` in overlay (D-04 recommends `os.environ.get`)
- Test file location — `test_billing_extension.py` (new file, recommended)
- Makefile target name — `make billing-extraction-discipline` recommended
- Single PR vs multi-PR — two coordinated PRs (one per repo) recommended
- Whether `_init_default_billing()` step needed — lazy-default accessor recommended (no init step)
- Dispatch loop extra context fields — `extension`, `timeout_seconds`/`error` per D-10 pseudocode

### Deferred Ideas (OUT OF SCOPE)

- Replacing boto3 with aiobotocore/minio-py in core S3 storage
- boto3 as `[project.optional-dependencies]` extra
- Stripe/per-deployment/per-seat billing (Cloud-tier)
- Multi-tenant billing isolation
- Configurable `BILLING_STARTUP_TIMEOUT_SECONDS`
- Per-extension timeout overrides
- Circuit-breaking / extension-quarantine
- `BillingExtension.on_shutdown(app)` hook
- Unified registry-shape abstraction
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BILLING-01 | `BillingExtension` Protocol in `backend/app/platform/extensions/protocols.py` with `on_startup(app)` hook; community default is no-op | Protocol scaffolding verified in live codebase; `AuditSink` is the direct template |
| BILLING-02 | `backend/app/core/marketplace.py` removed from core; impl moves to enterprise overlay | File verified at `backend/app/core/marketplace.py` (30 lines); single import at `api/main.py:20` confirmed |
| BILLING-03 | **AMENDED per D-01**: no module under `backend/app/` calls `boto3.client('meteringmarketplace').register_usage(...)`; AWS Marketplace billing API invoked exclusively from enterprise overlay | All boto3 sites inventoried; only marketplace.py uses meteringmarketplace |
| BILLING-04 | Lifespan `api/main.py:184-203` replaced with `for ext in get_billing_extensions(): ext.on_startup(app)`; community deploys perform zero AWS API calls | Block verified live at lines 184-203; exact dispatch pattern researched |
| BILLING-05 | `aws_marketplace_product_code` / `aws_marketplace_public_key_version` removed from core `Settings` (D-03 chose overlay-only option) | Both fields verified at `config.py:87-88`; field_validator entry at line 108 also confirmed |
| BILLING-06 | Audit re-run after both Phase 222 and Phase 223 ship reports zero 🟡 boundary risks in §1; Boundary Integrity grade A+ | Audit doc §1 verified; three 🟡 loci confirmed; Phase 222 already shipped |
</phase_requirements>

---

## Summary

Phase 223 is a surgical code relocation. The AWS Marketplace `register_marketplace_usage` call currently lives at `backend/app/api/main.py:184-203`, imports from `backend/app/core/marketplace.py:20`, and reads two fields from `backend/app/core/config.py:Settings`. All three loci are confirmed 🟡 risks in the 2026-04-30 audit §1. The fix is to move the behavior to the enterprise overlay via a new `BillingExtension` Protocol — the same Protocol extraction pattern that Phase 222 used for `AuditSink`.

The Phase 222 pattern is the ground truth for this phase. `AuditSink` (list-shape, async, `get_audit_sinks()` accessor, lazy default, per-sink try/except facade, fixture-based test, architecture-guard in `test_layering.py`) is replicated almost exactly for `BillingExtension`. The primary differences are: (1) the dispatch is in the lifespan startup of `api/main.py`, not in a service facade; (2) `asyncio.wait_for(..., timeout=10.0)` wraps each extension (already present in today's marketplace block at line 189-192 — the pattern is preserved, not invented); (3) this is a cross-repo phase requiring matching commits in `geolens-enterprise`.

The import cycle concern for `from fastapi import FastAPI` in `protocols.py` is resolved: **FastAPI imports zero `app.*` modules** (verified via uv run import trace). `from fastapi import FastAPI` is safe to add to `protocols.py` alongside the existing `from sqlalchemy.ext.asyncio import AsyncSession`.

**Primary recommendation:** Follow Phase 222's 5-plan structure verbatim with the additions specific to this phase: Protocol scaffolding → enterprise overlay class → core lifespan dispatch + deletions → tests + Makefile → audit re-run + doc amendments.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| BillingExtension Protocol definition | API / Backend (core) | — | Protocols live in `platform/extensions/` — the lowest shared layer |
| DefaultBillingExtension (no-op) | API / Backend (core) | — | Defaults live in `platform/extensions/defaults.py` alongside four existing defaults |
| get_billing_extensions() accessor | API / Backend (core) | — | Registry accessor, mirrors `get_audit_sinks()` exactly |
| Lifespan dispatch loop | API / Backend (core `api/main.py`) | — | The `lifespan` async context manager is the only execution site |
| MarketplaceBillingExtension class | Enterprise overlay (`geolens-enterprise`) | — | Business logic (boto3 + AWS API call) belongs entirely in the overlay |
| AWS Marketplace env var ownership | Enterprise overlay | — | Core no longer reads `AWS_MARKETPLACE_PRODUCT_CODE` post-phase |
| Architecture-guard test | API / Backend (test layer) | — | `test_layering.py` + Makefile target enforce the boundary statically |
| Fixture-based dispatch test | API / Backend (test layer) | — | `test_billing_extension.py` mirrors `test_audit_sink.py` |

---

## Standard Stack

### Core (no new libraries — all already present)

| Library | Version in use | Purpose | Why standard |
|---------|----------------|---------|--------------|
| `fastapi` | already in `pyproject.toml` | `FastAPI` type for Protocol signature | Application framework |
| `asyncio` | stdlib | `asyncio.wait_for` for dispatch timeout | Already used at `api/main.py:189` for this exact purpose |
| `structlog` | already in `pyproject.toml` | Warning logging in dispatch loop | Codebase-wide log facade; used in all existing extension patterns |
| `boto3` | already in `pyproject.toml` (stays) | S3 storage + S3 health check in core (unrelated to marketplace) | Stays in core for S3; added to enterprise overlay for marketplace |

[VERIFIED: live codebase grep + `backend/app/core/marketplace.py` inspection]

### Enterprise overlay additions

| Library | Version | Purpose | Action |
|---------|---------|---------|--------|
| `boto3` | `>=1.35.0` | `meteringmarketplace` client in overlay | Add to `geolens-enterprise/pyproject.toml` dependencies |

[VERIFIED: `geolens-enterprise/pyproject.toml` currently has only `pysaml2` and `defusedxml`; boto3 not declared]

**No installation steps required for core repo.** The enterprise overlay requires:

```bash
# In geolens-enterprise/pyproject.toml [project.dependencies]:
"boto3>=1.35.0",
```

---

## Architecture Patterns

### System Architecture Diagram

```
api/main.py (lifespan startup)
   │
   ├── load_extensions()                  ← registers overlay's billing_extensions slot
   │       └── geolens_enterprise:register_extensions(registry)
   │               └── registry.setdefault("billing_extensions", [DefaultBillingExtension()])
   │                         .append(MarketplaceBillingExtension())
   │
   ├── [S3 health check — untouched]
   │
   ├── for ext in get_billing_extensions():    ← NEW dispatch loop (replaces lines 184-203)
   │       await asyncio.wait_for(ext.on_startup(app), timeout=10.0)
   │       except TimeoutError → structlog.warning + continue
   │       except Exception   → structlog.warning + continue
   │
   │   Community path: DefaultBillingExtension.on_startup() → return (no-op)
   │   Enterprise path: MarketplaceBillingExtension.on_startup()
   │                       → if not os.environ.get("AWS_MARKETPLACE_PRODUCT_CODE"): return
   │                       → asyncio.to_thread(boto3_call, ...)
   │
   └── init_cache() / init_tile_cache() / ...   ← unchanged; run AFTER dispatch
```

### Recommended Project Structure (new files only)

```
backend/app/platform/extensions/
├── protocols.py          # ADD: BillingExtension Protocol (5th Protocol)
├── defaults.py           # ADD: DefaultBillingExtension (6th default)
└── __init__.py           # ADD: get_billing_extensions() accessor

geolens-enterprise/geolens_enterprise/
├── __init__.py           # AMEND: register billing_extensions slot
└── billing/
    └── __init__.py       # NEW: MarketplaceBillingExtension class

backend/tests/
├── test_billing_extension.py   # NEW: BILLING-04 dispatch tests
└── test_layering.py            # AMEND: add BILLING-02 architecture guard
```

### Pattern 1: BillingExtension Protocol (mirrors AuditSink exactly)

```python
# backend/app/platform/extensions/protocols.py
# Source: Phase 222 AuditSink pattern (verified live at protocols.py:43-58)
# + D-09: FastAPI import is safe (no cycle — verified via uv run import trace)

from fastapi import FastAPI   # Safe: FastAPI imports zero app.* modules [VERIFIED]

@runtime_checkable
class BillingExtension(Protocol):
    """Startup billing hook (Phase 223 D-06/D-08/D-09).

    Enterprise overlays subscribe by appending instances to
    ``_extensions["billing_extensions"]`` via ``setdefault + append``.
    Core dispatch wraps each call with asyncio.wait_for(timeout=10.0).
    """

    async def on_startup(self, app: FastAPI) -> None: ...
```

[VERIFIED: import safety confirmed via `uv run python3` in `/Users/ishiland/Code/geolens/backend`]

### Pattern 2: DefaultBillingExtension (mirrors DefaultAuditSink shape)

```python
# backend/app/platform/extensions/defaults.py
# Source: existing DefaultAuditSink at defaults.py:46-76 (verified live)

class DefaultBillingExtension:
    """Community default — no-op startup hook (Phase 223 D-07 / BILLING-01)."""

    async def on_startup(self, app) -> None:  # type: ignore[no-untyped-def]
        return
```

Note: `app` typed loosely on the default (same as `DefaultAuditSink`'s `session, event` are loosely typed at `defaults.py:62`) to avoid a potential forward-ref issue. The Protocol itself uses `FastAPI` for the type-checked contract; the default class doesn't need it.

### Pattern 3: get_billing_extensions() accessor (mirrors get_audit_sinks() exactly)

```python
# backend/app/platform/extensions/__init__.py
# Source: get_audit_sinks() at __init__.py:130-156 (verified live)

def get_billing_extensions() -> list[BillingExtension]:
    """Return all registered BillingExtensions, or [DefaultBillingExtension()] when slot missing.

    Phase 223 D-06/D-10/D-11 — mirrors get_audit_sinks() shape verbatim.
    """
    exts = _extensions.get("billing_extensions")
    if exts is None:
        return [DefaultBillingExtension()]
    return list(exts)  # type: ignore[arg-type]
```

### Pattern 4: Core lifespan dispatch loop (replaces lines 184-203)

```python
# backend/app/api/main.py — replaces lines 184-203
# Source: D-10 pseudocode + existing asyncio.wait_for at api/main.py:189-192 (verified live)
# Import: from app.platform.extensions import get_billing_extensions  (add to existing import block)

from app.platform.extensions import (
    get_billing_extensions,   # NEW
    get_extension_routers,
    list_extensions,
    load_extensions,
)

# In lifespan(), replacing the if settings.aws_marketplace_product_code: block:
for ext in get_billing_extensions():
    try:
        await asyncio.wait_for(ext.on_startup(app), timeout=10.0)
    except asyncio.TimeoutError:
        logger.warning(
            "BillingExtension.on_startup timed out -- continuing without billing",
            extension=type(ext).__name__,
            timeout_seconds=10.0,
        )
    except Exception as exc:
        logger.warning(
            "BillingExtension.on_startup failed -- continuing without billing",
            extension=type(ext).__name__,
            error=str(exc),
        )
```

### Pattern 5: Enterprise overlay registration (additive to existing register_extensions)

```python
# geolens-enterprise/geolens_enterprise/__init__.py
# Source: existing register_extensions pattern (verified live)

def register_extensions(registry: dict) -> None:
    # ... existing saml/audit/branding registrations unchanged ...

    # Phase 223: billing_extensions slot (list-shape, D-06)
    billing_extensions = registry.setdefault(
        "billing_extensions", [DefaultBillingExtension()]
    )
    billing_extensions.append(_get_billing_extension())

def _get_billing_extension():
    from geolens_enterprise.billing import MarketplaceBillingExtension
    return MarketplaceBillingExtension()
```

Note: `DefaultBillingExtension` must be imported from `app.platform.extensions.defaults`:

```python
from app.platform.extensions.defaults import DefaultBillingExtension
```

### Pattern 6: MarketplaceBillingExtension (enterprise overlay — new module)

```python
# geolens-enterprise/geolens_enterprise/billing/__init__.py — NEW FILE
# register_marketplace_usage body moves VERBATIM from core/marketplace.py:6-30

import os
import uuid


class MarketplaceBillingExtension:
    """Enterprise billing: calls RegisterUsage on AWS Marketplace at startup."""

    async def on_startup(self, app) -> None:
        """Fire AWS Marketplace RegisterUsage (D-13: gate lives here, not in core)."""
        product_code = os.environ.get("AWS_MARKETPLACE_PRODUCT_CODE")
        if not product_code:
            return  # Community deployments / unconfigured enterprise: skip silently

        public_key_version = int(os.environ.get("AWS_MARKETPLACE_PUBLIC_KEY_VERSION", "1"))

        import asyncio
        await asyncio.to_thread(
            self._register_usage, product_code, public_key_version
        )

    def _register_usage(self, product_code: str, public_key_version: int) -> None:
        import boto3
        import structlog

        logger = structlog.stdlib.get_logger(__name__)
        client = boto3.client("meteringmarketplace")
        resp = client.register_usage(
            ProductCode=product_code,
            PublicKeyVersion=public_key_version,
            Nonce=str(uuid.uuid4()),
        )
        logger.info(
            "AWS Marketplace metering registered",
            product_code=product_code,
            signature=resp.get("Signature", "")[:32] + "...",
        )
```

Key differences from today's `register_marketplace_usage`:
- `settings` is NOT passed (core Settings no longer has these fields)
- `logger` is NOT passed (overlay constructs its own)
- Uses `asyncio.to_thread` (same as today's call at `api/main.py:190`) since boto3 is sync
- `product_code` and `public_key_version` read from `os.environ` directly (D-04 / D-13)

### Pattern 7: Architecture-guard test (mirrors Phase 222 AUDIT-02 guard)

```python
# backend/tests/test_layering.py — new test function
# Source: existing test_no_log_action_calls_outside_audit_service at test_layering.py:332-400

@pytest.mark.architecture
def test_no_core_marketplace_import() -> None:
    """Phase 223 BILLING-02: app.core.marketplace must not exist after this phase.

    Asserts that (a) the module is absent from the filesystem and
    (b) importing it raises ImportError — ensuring no accidental resurrection.
    """
    import importlib
    import sys

    # (a) Attempting import must fail
    try:
        importlib.import_module("app.core.marketplace")
        pytest.fail(
            "app.core.marketplace was importable — it must be deleted from the "
            "core repo (Phase 223 BILLING-02). "
            "Remove backend/app/core/marketplace.py and delete the import at "
            "backend/app/api/main.py:20."
        )
    except ImportError:
        pass  # Expected: module was deleted

    # (b) No surviving import of app.core.marketplace in backend/app/
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")

    result = _git_grep(
        r"from app\.core\.marketplace",
        "backend/app/",
    )
    if result.returncode == 0:
        pytest.fail(
            "Phase 223 BILLING-02 invariant violated: backend/app/ still contains "
            "an import from app.core.marketplace. Offending lines:\n"
            + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )
```

### Anti-Patterns to Avoid

- **Don't call `get_billing_extensions()` before `load_extensions()`**: extensions register during `load_extensions()`; calling the accessor before that returns only the default. The existing lifespan ordering (`load_extensions()` at line 125 → S3 health check → marketplace block at 184) is correct and must be preserved.
- **Don't pass `settings` to the overlay**: after D-03, core Settings no longer has the marketplace fields; the overlay must read `os.environ` directly.
- **Don't overwrite the registry slot in `register_extensions`**: use `setdefault + append`, not `registry["billing_extensions"] = [MarketplaceBillingExtension()]`. Overwrite would lose `DefaultBillingExtension` from the iteration.
- **Don't relocate `core/marketplace.py` within core**: D-02 is a hard delete, not a rename. Any surviving `from app.core.marketplace` reference in `backend/app/` will be caught by the architecture guard.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Startup timeout for hanging extension | Manual `asyncio.shield` + cancel | `asyncio.wait_for(coro, timeout=10.0)` | Already used at `api/main.py:189` for the same purpose; stdlib; handles CancelledError correctly |
| AWS API call in async context | Naive `await boto3_call(...)` | `await asyncio.to_thread(sync_boto3_call, ...)` | boto3 is sync; already used today at `api/main.py:190`; `to_thread` is the correct bridge |
| Module existence check | `os.path.exists(...)` on `.py` file | `importlib.import_module(...)` in a try/except | The architecture guard tests import behavior, not filesystem presence |

---

## Runtime State Inventory

This phase is NOT a rename/rebrand/migration phase — it is a code relocation. No stored runtime state embeds `core/marketplace` as a key, and no database records reference these settings. The env vars (`AWS_MARKETPLACE_PRODUCT_CODE`, `AWS_MARKETPLACE_PUBLIC_KEY_VERSION`) are read from the environment at runtime; they are not stored in the database.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — marketplace settings are environment variables, not DB records | None |
| Live service config | None — no n8n workflows or external service configs reference marketplace module paths | None |
| OS-registered state | None | None |
| Secrets/env vars | `AWS_MARKETPLACE_PRODUCT_CODE`, `AWS_MARKETPLACE_PUBLIC_KEY_VERSION` — env var names UNCHANGED; only which code reads them changes | No migration; operators' existing `.env` files continue to work (vars are now read by overlay, same behavior) |
| Build artifacts | `backend/app/core/marketplace.py` — deleted from filesystem; Python `__pycache__` will be stale | Docker rebuild clears this; local `uv run` environments may need `find . -name '__pycache__' -exec rm -rf {} +` if import errors appear |

---

## Codebase Verification Findings

### Finding 1: Confirmed boto3 sites [VERIFIED: live grep]

Exactly four boto3 import sites exist in `backend/app/`:

| File | Line | Usage | Action |
|------|------|-------|--------|
| `backend/app/core/marketplace.py` | 18 | `import boto3` (inline, inside function) | **DELETE FILE** |
| `backend/app/platform/storage/s3.py` | 28 | `import boto3` (top-level) | Untouched — S3 storage |
| `backend/app/api/main.py` | 161 | `import boto3 as _boto3` (inline, inside S3 health check block) | Untouched — S3 health check |
| `backend/app/platform/jobs/worker.py` | 184 | `import boto3 as _boto3` (lazy inline) | Untouched — worker S3 credential probe |

Only `core/marketplace.py:18` is marketplace-related. The audit doc's scoping of 🟡 risks to the three marketplace loci is confirmed correct.

### Finding 2: Live lifespan ordering [VERIFIED: api/main.py read]

The actual lifespan ordering in `backend/app/api/main.py`:

```
Line 122: seed_roles()
Line 123: seed_initial_admin()
Line 125: load_extensions()        ← extensions register here
Line 126: init_edition(...)
Line 134: get_extension_routers()
Line 153: init_storage()
Line 155-182: S3 health check     ← boto3 used here (untouched)
Line 184-203: AWS Marketplace block  ← THIS IS REPLACED by BillingExtension dispatch
Line 205: init_cache()
Line 206: init_tile_cache()
Line 207: init_tile_pool()
Line 208: task_app.open_async()
```

Post-phase ordering: `load_extensions()` → S3 health check → `for ext in get_billing_extensions(): ...` → `init_cache()`. **This is correct and matches CONTEXT.md's specification.**

### Finding 3: FastAPI import cycle — NO CYCLE [VERIFIED: uv run import trace]

`from fastapi import FastAPI` imports zero `app.*` modules. The import trace was run inside the backend virtualenv:

```
FastAPI imports app.* modules: []
Safe to add FastAPI import to protocols.py: True
```

**D-09 recommendation stands: use `app: FastAPI` in the Protocol signature.** No fallback to `app: object` needed.

### Finding 4: `core/marketplace.py` body — exact 30 lines [VERIFIED: file read]

The file contains one function `register_marketplace_usage(settings, logger)` with an inline `import boto3`. The function body moves verbatim to `MarketplaceBillingExtension._register_usage` (or inlined in `on_startup`). The two parameters (`settings`, `logger`) are NOT passed from the dispatch loop — the overlay constructs its own logger and reads env vars directly.

### Finding 5: `config.py` fields and validator location [VERIFIED: file read]

- `aws_marketplace_product_code: str | None = None` at **line 87**
- `aws_marketplace_public_key_version: int = 1` at **line 88**
- `aws_marketplace_product_code` entry in `@field_validator(...)` whitelist at approximately **line 108** (within the `empty_str_to_none` validator's argument list, lines 90-110)

All three must be deleted. The validator argument list contains 13 entries; removing `aws_marketplace_product_code` from the tuple is the surgical edit.

### Finding 6: Enterprise overlay current state [VERIFIED: file reads]

`geolens-enterprise/geolens_enterprise/__init__.py` currently registers:
- `registry["auth"]` = SAML extension (dual-registered as `registry["identity"]`)
- `registry["audit"]` = audit extension
- `registry["branding"]` = branding extension
- `registry["_routers"]` = list of extension routers

No `billing_extensions` slot exists. Adding it via `setdefault + append` is purely additive. The `_get_billing_extension()` lazy-import helper follows the established `_get_saml_extension()` / `_get_audit_extension()` / `_get_branding_extension()` pattern exactly.

`geolens-enterprise/pyproject.toml` has only `pysaml2>=7.5.4` and `defusedxml>=0.7.1` in dependencies. `boto3>=1.35.0` must be added.

### Finding 7: `.env.example` AWS Marketplace section [VERIFIED: file read]

Current content at lines 347-356:

```
# --- AWS Marketplace (BYOL/AMI billing) ---
# Only set when running the GeoLens AWS Marketplace AMI listing.
# [OPTIONAL] AWS Marketplace product code (enables hourly metering)
# Type: string | No default
# AWS_MARKETPLACE_PRODUCT_CODE=

# [OPTIONAL] Public key version for RegisterUsage signature verification
# Only relevant when AWS_MARKETPLACE_PRODUCT_CODE is set.
# Type: integer | Default: 1
# AWS_MARKETPLACE_PUBLIC_KEY_VERSION=1
```

Proposed replacement per D-05:

```
# --- AWS Marketplace (Enterprise overlay only) ---
# WARNING: These variables are read by the geolens-enterprise overlay's
# MarketplaceBillingExtension. They have NO EFFECT on community (open-core)
# deployments — setting them without the enterprise overlay installed is a no-op.
# Only configure these when running the GeoLens AWS Marketplace AMI listing
# with the enterprise overlay installed.
#
# [OPTIONAL] AWS Marketplace product code (enables hourly metering via overlay)
# Type: string | No default
# AWS_MARKETPLACE_PRODUCT_CODE=
#
# [OPTIONAL] Public key version for RegisterUsage signature verification
# Only relevant when AWS_MARKETPLACE_PRODUCT_CODE is set.
# Type: integer | Default: 1
# AWS_MARKETPLACE_PUBLIC_KEY_VERSION=1
```

### Finding 8: Phase 222 architecture-guard Makefile target [VERIFIED: Makefile read]

The `audit-sink-discipline` target at line 143-144:

```makefile
audit-sink-discipline: ## Verify no `await log_action(` calls exist outside audit/service.py + extensions/defaults.py (Phase 222 AUDIT-02)
	cd backend && PYTHONPATH=. uv run pytest tests/test_layering.py::test_no_log_action_calls_outside_audit_service -v
```

Phase 223's parallel target should follow this exact shape:

```makefile
billing-extraction-discipline: ## Verify app.core.marketplace is absent from core (Phase 223 BILLING-02)
	cd backend && PYTHONPATH=. uv run pytest tests/test_layering.py::test_no_core_marketplace_import -v
```

The `billing-extraction-discipline` name should be added to `.PHONY`. Current `.PHONY` line includes `audit-sink-discipline` at the end — append `billing-extraction-discipline`.

---

## BILLING-03 / SC#1 Amended Wording

Per D-01, the plan phase must include explicit edits to the following two files.

**`.planning/REQUIREMENTS.md` BILLING-03 replacement text:**

```
- [ ] **BILLING-03**: No module under `backend/app/` calls `boto3.client("meteringmarketplace").register_usage(...)`. The AWS Marketplace billing API is invoked exclusively from the enterprise overlay's `BillingExtension.on_startup()`. `boto3` remains in `backend/pyproject.toml` because the core S3 storage provider (`app.platform.storage.s3`) and the lifespan S3 health check use it — that is an unrelated boundary concern out of scope for v13.3.
```

**`.planning/ROADMAP.md` Phase 223 SC#1 replacement text:**

```
  1. `backend/app/core/marketplace.py` is deleted from core; no module under `backend/app/` calls `boto3.client("meteringmarketplace").register_usage(...)`. `boto3` remains a core dependency because the core S3 storage provider and S3 health check use it — that is an unrelated boundary concern. The AWS Marketplace billing API is invoked exclusively from the enterprise overlay.
```

---

## Common Pitfalls

### Pitfall 1: Calling the dispatch loop before `load_extensions()`
**What goes wrong:** `get_billing_extensions()` returns only `[DefaultBillingExtension()]` — the overlay's `MarketplaceBillingExtension` was never registered because `load_extensions()` hadn't run yet. Enterprise deployments silently fail to meter.
**Why it happens:** Someone inserts the dispatch loop call early in the lifespan for "early validation" purposes.
**How to avoid:** Dispatch loop must appear AFTER `load_extensions()` at line 125. The existing placement of the marketplace block at line 184 (after line 125) is the correct model.
**Warning signs:** `MarketplaceBillingExtension` not called in integration test; only `DefaultBillingExtension` runs.

### Pitfall 2: Passing `settings` to MarketplaceBillingExtension
**What goes wrong:** `AttributeError: 'Settings' object has no attribute 'aws_marketplace_product_code'` at runtime after D-03 removes those fields.
**Why it happens:** Forgetting to update the overlay when core settings are removed; copying today's `register_marketplace_usage(settings, logger)` signature verbatim.
**How to avoid:** The overlay's `on_startup` receives only `app: FastAPI`; it reads `os.environ.get("AWS_MARKETPLACE_PRODUCT_CODE")` directly.

### Pitfall 3: Test registry fixture not restoring `_extensions["billing_extensions"]`
**What goes wrong:** One test's fixture mutations bleed into subsequent tests; `get_billing_extensions()` returns unexpected extensions in later tests.
**Why it happens:** Missing `finally` block in the fixture cleanup.
**How to avoid:** Mirror the exact `try/finally` pattern from `test_audit_sink.py:79-125` (lines 79-81 save snapshot, lines 121-125 restore). The key: save `saved = _extensions.get("billing_extensions")` before the test; restore with `_extensions["billing_extensions"] = saved` or `_extensions.pop("billing_extensions", None)` if `saved is None`.

### Pitfall 4: `DefaultBillingExtension` import in overlay uses wrong path
**What goes wrong:** `ImportError: cannot import name 'DefaultBillingExtension' from 'app.platform.extensions.defaults'` — because the new class wasn't added to `defaults.py` before the overlay code was merged.
**Why it happens:** Cross-repo coordination drift — overlay merged before core's Protocol scaffolding.
**How to avoid:** D-14 ordering: enterprise repo's `billing/__init__.py` module can be written first, but the `register_extensions` amendment that imports `DefaultBillingExtension` from core must wait until core's `defaults.py` change is shipped. Plan task ordering must enforce this.

### Pitfall 5: `asyncio.wait_for` wrapping an already-async call that uses `asyncio.to_thread`
**What goes wrong:** `RuntimeError: asyncio.run() cannot be called when another event loop is running` or nested loop issues.
**Why it happens:** Confusion about `asyncio.to_thread` vs `asyncio.wait_for`. Today's code at `api/main.py:189-192` does `asyncio.wait_for(asyncio.to_thread(...), timeout=10.0)` — the `wait_for` wraps the thread coroutine, not the sync function. This is correct.
**How to avoid:** The overlay's `on_startup` is `async def`, awaitable. The dispatch loop does `await asyncio.wait_for(ext.on_startup(app), timeout=10.0)`. Inside `on_startup`, `asyncio.to_thread(sync_boto3_call, ...)` is the correct wrapper for the sync boto3 call. These nest correctly.

### Pitfall 6: `from app.core.marketplace import register_marketplace_usage` left in api/main.py
**What goes wrong:** `ModuleNotFoundError: No module named 'app.core.marketplace'` at every startup after the file is deleted.
**Why it happens:** Only deleting `core/marketplace.py` without also removing the import at `api/main.py:20`.
**How to avoid:** Both edits are part of the same plan task: (1) delete `core/marketplace.py`, (2) delete the import at `api/main.py:20`. The architecture-guard test catches this immediately.

### Pitfall 7: Cross-repo ordering inverted
**What goes wrong:** Core merges first (deleting `core/marketplace.py` and removing Settings fields), enterprise overlay hasn't been updated yet — enterprise deployments boot without marketplace billing (behavioral regression for paying customers).
**Why it happens:** Core is easier to plan as standalone; enterprise overlay coordination is an afterthought.
**How to avoid:** D-14 specifies the ordering. The safest plan-level ordering: enterprise overlay's `MarketplaceBillingExtension` class ships first (it can reference the new Protocol type before it exists, because Python duck-typing; or keep the Protocol name as a comment until core ships). Core's delete of `core/marketplace.py` and dispatch loop replacement ship second. Both should be in PRs that can be merged in the correct order.

---

## Phase 222 Test Patterns to Mirror

### Registry fixture restore pattern (from `test_audit_sink.py:79-125`)

```python
# REQUIRED pattern for all test_billing_extension.py tests
saved = _extensions.get("billing_extensions")
_extensions["billing_extensions"] = [DefaultBillingExtension(), fixture_ext]
try:
    # ... test body ...
finally:
    if saved is None:
        _extensions.pop("billing_extensions", None)
    else:
        _extensions["billing_extensions"] = saved
```

### FixtureBillingExtension class shape

```python
class FixtureBillingExtension:
    def __init__(self) -> None:
        self.received: list = []  # list of app instances passed to on_startup

    async def on_startup(self, app) -> None:
        self.received.append(app)
```

### RaisingBillingExtension class shape

```python
class RaisingBillingExtension:
    async def on_startup(self, app) -> None:
        raise RuntimeError("simulated billing extension failure for BILLING-04")
```

### HangingBillingExtension class shape (for timeout test)

```python
class HangingBillingExtension:
    async def on_startup(self, app) -> None:
        await asyncio.sleep(15.0)  # exceeds 10.0s timeout
```

---

## Lifespan Testing — Recommended Approach

**Problem:** How to test D-10's dispatch contract (10s timeout + per-extension try/except) end-to-end in isolation?

**Option A: Call dispatch loop code directly** (recommended)
Extract the dispatch loop into a helper function `_dispatch_billing_extensions(app, extensions, timeout)` in `api/main.py` (or test-only helper). Call it directly in tests without spinning up the full app lifespan.

**Option B: TestClient startup**
`async with AsyncClient(app=app)` triggers the lifespan; assertions check side effects. But: slow, requires DB, hard to inject fixture extensions cleanly.

**Option C: Direct `_extensions` manipulation + partial lifespan**
Mirror Phase 222's pattern exactly: manipulate `_extensions["billing_extensions"]` directly, call `audit_emit`-equivalent dispatch code. For billing, there's no equivalent to `audit_emit` — the dispatch is inline in `lifespan`. 

**Recommended:** Use Option A. Extract a `_dispatch_billing_extensions(app, exts, timeout)` helper inline in `api/main.py` and call it in tests. This is the simplest path that proves D-10's contract without requiring DB access. For the happy-path and raising tests, the app argument can be a `MagicMock()`. For the timeout test, use `pytest-anyio` with a real async `asyncio.sleep(15.0)`.

Alternatively, the dispatch code can be tested entirely by directly calling the for-loop logic, since `asyncio.wait_for` and `asyncio.TimeoutError` are stdlib and easy to exercise with `anyio`:

```python
@pytest.mark.anyio
async def test_hanging_billing_extension_times_out(caplog):
    """D-10: timeout survival test."""
    from app.platform.extensions import _extensions
    from app.platform.extensions.defaults import DefaultBillingExtension

    class HangingExt:
        async def on_startup(self, app):
            await asyncio.sleep(15.0)

    class TrackingExt:
        ran = False
        async def on_startup(self, app):
            TrackingExt.ran = True

    saved = _extensions.get("billing_extensions")
    _extensions["billing_extensions"] = [HangingExt(), TrackingExt()]
    try:
        import time
        mock_app = object()
        start = time.monotonic()
        # Call the extracted helper or inline-replicate the dispatch loop
        # with a short timeout for the test
        for ext in [HangingExt(), TrackingExt()]:
            try:
                await asyncio.wait_for(ext.on_startup(mock_app), timeout=10.0)
            except asyncio.TimeoutError:
                pass
            except Exception:
                pass
        elapsed = time.monotonic() - start
        assert elapsed < 11.0  # 10s timeout + epsilon
        assert TrackingExt.ran  # subsequent extension still ran
    finally:
        if saved is None:
            _extensions.pop("billing_extensions", None)
        else:
            _extensions["billing_extensions"] = saved
```

**Trade-off note:** Testing the dispatch loop directly (without going through the full lifespan) does not exercise the exact call path in production. For Phase 223's scope, this is acceptable — the `asyncio.wait_for` contract is stdlib and fully predictable; what matters is verifying the overlay-dispatch semantics, not re-testing stdlib.

---

## Cross-Repo Coordination — Phase 217 Precedent

Phase 217 (SAML overlay, `auth-saml-enterprise`) established the two-repo pattern:

1. Core repo delivered the `AuthExtension` Protocol + `DefaultAuthExtension` + `get_auth_extension()` accessor first.
2. Enterprise repo added `EnterpriseSamlExtension` implementing `AuthExtension` and registered it in `register_extensions`.
3. Both PRs were coordinated before merge — enterprise PR was opened against a core branch, reviewed together, merged in order (core first → enterprise second).

Phase 223 follows the same ordering. The `feedback_audit_sibling_repos_at_milestone_close.md` carve-out is directly applicable: Phase 223 close must verify `geolens-enterprise` has the `billing/` module committed before declaring the phase complete.

**Verification steps at phase close:**
1. `cd ~/Code/geolens-enterprise && git log --oneline -5` — confirm `billing/__init__.py` commit is present
2. `cd ~/Code/geolens && git log --oneline -5` — confirm `core/marketplace.py` deletion commit is present
3. Run `make billing-extraction-discipline` from geolens root — confirms architecture guard passes
4. Run `/oc-audit` — produces new audit doc; verifies BILLING-06 (zero 🟡 in §1)

---

## Environment Availability

Step 2.6: No new external dependencies required for the core repo. The enterprise overlay adds boto3 to its own `pyproject.toml`, but boto3 is already installed in the core virtualenv (and in CI).

| Dependency | Required By | Available | Notes |
|------------|------------|-----------|-------|
| `boto3` | `MarketplaceBillingExtension` (overlay) | ✓ (in core venv) | Already installed transitively; overlay declares it explicitly post-phase |
| `asyncio` | dispatch loop | ✓ (stdlib) | No installation needed |
| `uv` | test runner | ✓ | Standard project toolchain |
| `geolens-enterprise` overlay | Integration test | ✓ (installed in CI per Phase 220 D-06) | Tests that need the overlay work in CI |

---

## Validation Architecture

`workflow.nyquist_validation` is absent from `.planning/config.json` — treated as enabled.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-anyio |
| Config file | `backend/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `cd backend && uv run pytest tests/test_billing_extension.py tests/test_layering.py::test_no_core_marketplace_import -v` |
| Full suite command | `cd backend && uv run pytest --timeout=60` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BILLING-01 | BillingExtension Protocol exists; DefaultBillingExtension is no-op | unit | `pytest tests/test_billing_extension.py::test_billing_extension_protocol_shape -v` | ❌ Wave 0 |
| BILLING-02 | `app.core.marketplace` raises ImportError | architecture | `pytest tests/test_layering.py::test_no_core_marketplace_import -v` | ❌ Wave 0 (new test function in existing file) |
| BILLING-03 | No `register_usage` call in `backend/app/` | architecture (grep) | `make billing-extraction-discipline` | ❌ Wave 0 (Makefile target) |
| BILLING-04 | Dispatch loop: happy path + raising extension + timeout | unit (anyio) | `pytest tests/test_billing_extension.py -v` | ❌ Wave 0 |
| BILLING-05 | `aws_marketplace_product_code` removed from Settings | unit | `pytest tests/test_billing_extension.py::test_settings_has_no_marketplace_fields -v` | ❌ Wave 0 |
| BILLING-06 | Audit re-run reports ✅ Closed for 3 loci | manual (`/oc-audit`) | N/A — manual verification step | N/A |

### Sampling Rate

- **Per task commit:** `cd backend && uv run pytest tests/test_billing_extension.py tests/test_layering.py::test_no_core_marketplace_import -v`
- **Per wave merge:** `cd backend && uv run pytest --timeout=60`
- **Phase gate:** Full suite green + `make billing-extraction-discipline` + `/oc-audit` grade A+ before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `backend/tests/test_billing_extension.py` — NEW FILE; covers BILLING-01, BILLING-04, BILLING-05
- [ ] `backend/tests/test_layering.py::test_no_core_marketplace_import` — NEW TEST in existing file; covers BILLING-02
- [ ] `Makefile` target `billing-extraction-discipline` — covers BILLING-03 (static grep)
- [ ] `geolens-enterprise/geolens_enterprise/billing/__init__.py` — NEW FILE in enterprise repo

---

## Security Domain

`security_enforcement` key is absent from `.planning/config.json` — treated as enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | This phase does not touch auth |
| V3 Session Management | no | No session changes |
| V4 Access Control | no | No access control changes |
| V5 Input Validation | marginal | `os.environ.get("AWS_MARKETPLACE_PRODUCT_CODE")` is read-only; not user-controlled input |
| V6 Cryptography | no | boto3 handles TLS to AWS; no hand-rolled crypto |
| V9 Communication Security | marginal | boto3 `meteringmarketplace` client uses HTTPS by default; no config change needed |

### Known Threat Patterns for this Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| boto3 `meteringmarketplace` error leakage | Information Disclosure | Already in scope: `logger.warning` at dispatch level uses `str(exc)`, not full traceback; acceptable for startup logs |
| Env var injection via `AWS_MARKETPLACE_PRODUCT_CODE` | Tampering | Env vars are operator-controlled; no sanitization needed for a product code string |
| Overlay code bypassing startup isolation | Elevation of Privilege | `asyncio.wait_for` timeout cap prevents runaway overlay from blocking startup indefinitely (D-10 / D-11) |

No new security concerns beyond what Phase 223's design already addresses.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `boto3>=1.35.0` is the correct minimum version for `geolens-enterprise/pyproject.toml` | Standard Stack | If core uses a later API, the overlay may hit compatibility issues. Check core's `backend/pyproject.toml` boto3 pin during planning. | 

[ASSUMED: specific boto3 version number for the enterprise overlay — verified that boto3 is absent from enterprise `pyproject.toml` but did not look up core's exact pin]

All other major claims in this research are VERIFIED against the live codebase.

---

## Open Questions

1. **What is core's exact boto3 version pin?**
   - What we know: boto3 is in `backend/pyproject.toml`; enterprise overlay needs to add it
   - What's unclear: minimum version to specify (e.g., `>=1.35.0` vs `>=1.26.0`)
   - Recommendation: planner reads `backend/pyproject.toml` and mirrors the same pin in `geolens-enterprise/pyproject.toml`

2. **Should BILLING-05 have a Settings-level test?**
   - What we know: deleting the two fields from `Settings` will cause Pydantic validation errors if any `.env` file still sets them... but Pydantic BaseSettings silently ignores extra env vars by default (`extra = "ignore"`)
   - What's unclear: whether core's `Settings` has `model_config = SettingsConfigDict(extra='ignore')` or strict extra handling
   - Recommendation: planner checks `config.py` SettingsConfigDict; if `extra='ignore'`, the test just asserts the field doesn't exist on `Settings`; if strict, existing `.env` files with the field set will cause startup failures (document in CHANGELOG)

3. **What CHANGELOG entry format is expected for v13.3?**
   - What we know: CONTEXT.md mentions a CHANGELOG entry for operator visibility; v13.2 had an entry
   - What's unclear: whether this is one entry per phase or per milestone
   - Recommendation: one CHANGELOG entry at the v13.3 close covers both Phase 222 and Phase 223 together; Phase 223's specific entry covers the env-var documentation change in `.env.example`

---

## Sources

### Primary (HIGH confidence — VERIFIED against live codebase)

- `/Users/ishiland/Code/geolens/backend/app/api/main.py` — verified lifespan ordering, marketplace block lines 184-203, S3 health check lines 155-182, boto3 import at line 161, existing `from app.core.marketplace import register_marketplace_usage` at line 20
- `/Users/ishiland/Code/geolens/backend/app/core/marketplace.py` — verified 30-line function body, `import boto3` at line 18
- `/Users/ishiland/Code/geolens/backend/app/core/config.py` — verified `aws_marketplace_product_code` at line 87, `aws_marketplace_public_key_version` at line 88, `field_validator` whitelist entry
- `/Users/ishiland/Code/geolens/backend/app/platform/extensions/protocols.py` — verified current Protocol shape + `AsyncSession` import precedent + `TYPE_CHECKING` pattern
- `/Users/ishiland/Code/geolens/backend/app/platform/extensions/defaults.py` — verified DefaultAuditSink shape + loose typing pattern on defaults
- `/Users/ishiland/Code/geolens/backend/app/platform/extensions/__init__.py` — verified `get_audit_sinks()` implementation shape (exact template for `get_billing_extensions()`)
- `/Users/ishiland/Code/geolens/backend/tests/test_audit_sink.py` — verified fixture-based test pattern, registry save/restore idiom, `FixtureSink` / `RaisingSink` shapes
- `/Users/ishiland/Code/geolens/backend/tests/test_layering.py` — verified architecture-guard test pattern, git grep shape, `@pytest.mark.architecture` marker
- `/Users/ishiland/Code/geolens/Makefile` — verified `audit-sink-discipline` target format (lines 143-144); confirmed `.PHONY` spelling
- `/Users/ishiland/Code/geolens-enterprise/geolens_enterprise/__init__.py` — verified `register_extensions` shape, `_get_*` lazy-import helpers, existing slots
- `/Users/ishiland/Code/geolens-enterprise/pyproject.toml` — verified current dependencies (pysaml2, defusedxml only); confirmed boto3 is absent
- `/Users/ishiland/Code/geolens/.env.example` lines 347-356 — verified current AWS Marketplace section text
- FastAPI import cycle check: `uv run python3` trace confirmed `from fastapi import FastAPI` imports zero `app.*` modules

### Secondary (HIGH confidence — from CONTEXT.md and audit doc)

- `.planning/phases/223-marketplace-billing-extraction/223-CONTEXT.md` — all 17 decisions and canonical refs
- `.planning/phases/222-audit-sink-protocol/222-CONTEXT.md` — Phase 222 canonical pattern (D-09/D-10/D-11/D-12/D-13)
- `docs-internal/audits/oc-separation-audit-20260430.md` §1 — three 🟡 loci confirmed

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new libraries; all existing patterns verified live
- Architecture: HIGH — lifespan ordering, import graph, and Protocol shape all verified via live code reads and uv run traces
- Pitfalls: HIGH — drawn from Phase 222 experience + live code verification
- Enterprise overlay: HIGH — `__init__.py` and `pyproject.toml` read directly

**Research date:** 2026-04-30
**Valid until:** 2026-05-30 (stable codebase; no third-party API changes expected)
