# Phase 210: Enterprise Overlay Repo - Research

**Researched:** 2026-03-26
**Domain:** Python packaging, entry_points plugin architecture, Alembic multi-branch migrations, Docker Compose overlays
**Confidence:** HIGH

## Summary

Phase 210 creates a sibling `geolens-enterprise` repo that installs as a pip package and proves the overlay pattern works end-to-end. The core extension system (Phase 206) already provides `load_extensions()` with `importlib.metadata.entry_points(group="geolens.extensions")`, `init_edition()` auto-detection, Protocol interfaces, and `require_enterprise()` guards. The enterprise package simply needs to register implementations via pyproject.toml entry_points.

The three enterprise features to extract are: (1) SAML SSO (`backend/app/auth/saml/`), (2) audit log export endpoints (`backend/app/audit/router.py` export endpoints), and (3) branding toggle write endpoint (`backend/app/settings/router.py` PUT branding). Core retains the read-only branding endpoint (public), the audit list endpoint (not enterprise-gated), and all Protocol/guard/edition infrastructure. Enterprise Alembic migrations use `branch_labels=['enterprise']` with a separate versions directory discovered via `config.set_main_option("version_locations", ...)` in `env.py`.

**Primary recommendation:** Structure the enterprise package as a single pip-installable package with entry_points registration, keeping the loader callable pattern already established in `extensions/__init__.py`. Use `config.set_main_option` in `alembic/env.py` to dynamically append enterprise migration paths discovered via entry_points.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Enterprise Alembic migrations use a separate `branch_labels=['enterprise']` and a versions directory inside the enterprise package. Core runs `alembic upgrade head` (core branch only), enterprise deployment runs `alembic upgrade head` (both branches merge).
- **D-02:** Enterprise migration versions directory lives in the `geolens-enterprise` package. Core `alembic/env.py` is updated to discover enterprise migration paths via `importlib.metadata.entry_points`.
- **D-03:** Extract all enterprise feature code from core into the private enterprise repo. Core keeps only Protocol interfaces, default implementations, guards, and edition detection. SAML router, branding config, and audit export implementations move to `geolens-enterprise`.
- **D-04:** All three enterprise features (branding toggle, SAML SSO, audit log export) are extracted in this phase -- not just one proof-of-concept.
- **D-05:** After extraction, core `require_enterprise()` guards remain but the guarded code behind them is removed. The enterprise package re-registers the routes/config when installed.
- **D-06:** `docker-compose.enterprise.yml` volume-mounts the enterprise package into the API container and runs `pip install -e` at startup. No private registry needed for development.
- **D-07:** Enterprise repo lives as a sibling directory (`../geolens-enterprise/`). The overlay compose file uses relative path volume mounts.
- **D-08:** Enterprise package uses `pyproject.toml` with `[project.entry-points."geolens.extensions"]` to register Protocol implementations for auth, audit, and branding.
- **D-09:** When `pip install geolens-enterprise`, `load_extensions()` discovers the entry_points, `init_edition()` auto-detects enterprise, guards unlock, features activate.

### Claude's Discretion
- Enterprise package internal directory structure
- How core `alembic/env.py` discovers enterprise migration paths (entry_point group or config)
- Startup ordering for enterprise `pip install -e` in Docker entrypoint
- Test strategy for enterprise package (in-repo tests vs integration tests against core)
- How enterprise routes re-register after extraction (FastAPI `include_router` from entry_point loader)

### Deferred Ideas (OUT OF SCOPE)
- Private PyPI registry for production enterprise distribution
- Git submodule coupling between core and enterprise
- Full white-label features (custom logo, colors, OEM)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REPO-01 | A `geolens-enterprise` repo scaffold exists with `pyproject.toml` defining entry_points that register with the core extension system | pyproject.toml entry_points pattern documented; loader callable pattern matches existing `load_extensions()` |
| REPO-02 | Enterprise repo installs as an editable pip package into the existing Docker Compose setup via a compose override file | docker-compose.enterprise.yml overlay with volume mount + entrypoint pip install -e |
| REPO-03 | Enterprise Alembic migrations use a separate branch label and do not conflict with core migrations | Alembic `branch_labels` + `version_locations` multi-directory support researched |
| REPO-04 | At least one enterprise feature lives in the enterprise repo, proving the overlay pattern end-to-end | All three features (SAML, audit export, branding write) extracted per D-04 |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- Never indicate AI or Bot activity in commit messages
- Prefer simple, readable code over clever abstractions
- Follow existing project conventions when editing files
- Be direct and concise

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| importlib.metadata | stdlib | Entry point discovery | Already used by `load_extensions()` in core |
| alembic | 1.18.x (bundled) | Multi-branch migrations | Already in backend dependencies |
| setuptools | latest | Build backend for entry_points | Standard Python packaging |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pysaml2 | >=7.5.4 | SAML SSO (moved to enterprise) | Enterprise package dependency |
| defusedxml | >=0.7.1 | XML parsing for SAML metadata | Enterprise package dependency |

**Enterprise package pyproject.toml:**
```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "geolens-enterprise"
version = "0.1.0"
description = "GeoLens Enterprise extensions"
requires-python = ">=3.13"
dependencies = [
    "pysaml2>=7.5.4",
    "defusedxml>=0.7.1",
]

[project.entry-points."geolens.extensions"]
enterprise = "geolens_enterprise:register_extensions"

[project.entry-points."geolens.migrations"]
enterprise = "geolens_enterprise:get_migration_paths"
```

## Architecture Patterns

### Recommended Enterprise Package Structure
```
geolens-enterprise/
├── pyproject.toml
├── geolens_enterprise/
│   ├── __init__.py          # register_extensions() + get_migration_paths()
│   ├── auth/
│   │   └── saml/
│   │       ├── __init__.py
│   │       ├── router.py    # SAML login/ACS endpoints
│   │       ├── config.py    # pysaml2 client builder
│   │       ├── metadata.py  # IdP metadata parser
│   │       └── replay.py    # Assertion replay cache
│   ├── audit/
│   │   ├── __init__.py
│   │   └── export.py        # CSV/JSON streaming export endpoints
│   ├── branding/
│   │   ├── __init__.py
│   │   └── router.py        # PUT /settings/branding/ endpoint
│   └── migrations/
│       └── versions/        # Enterprise-only Alembic migrations
│           └── .gitkeep
└── tests/
    ├── conftest.py
    └── test_registration.py
```

### Pattern 1: Extension Registration Callable
**What:** The enterprise package exports a `register_extensions(registry: dict)` function that populates the core extension registry with enterprise implementations and registers FastAPI routers.
**When to use:** Always -- this is how `load_extensions()` discovers enterprise features.
**Example:**
```python
# geolens_enterprise/__init__.py
from __future__ import annotations


def register_extensions(registry: dict) -> None:
    """Register all enterprise extensions with the core registry.

    Called by core load_extensions() via entry_points discovery.
    Populates registry dict AND registers FastAPI routers with the app.
    """
    from geolens_enterprise.auth.saml.router import router as saml_router
    from geolens_enterprise.audit.export import router as audit_export_router
    from geolens_enterprise.branding.router import router as branding_router

    # Register protocol implementations
    registry["auth"] = EnterpriseAuthExtension()
    registry["audit"] = EnterpriseAuditExtension()
    registry["branding"] = EnterpriseBrandingExtension()

    # Store routers for later inclusion
    registry["_routers"] = [saml_router, audit_export_router, branding_router]


def get_migration_paths() -> list[str]:
    """Return paths to enterprise Alembic migration directories."""
    import importlib.resources
    return [str(importlib.resources.files("geolens_enterprise") / "migrations" / "versions")]
```

### Pattern 2: Core Extension Loader Update (Router Registration)
**What:** Update `load_extensions()` in core to also register any FastAPI routers provided by extensions.
**When to use:** The current loader only populates `_extensions` dict. It needs to also handle router registration.
**Example:**
```python
# Updated extensions/__init__.py
from __future__ import annotations

from importlib.metadata import entry_points
import structlog

logger = structlog.stdlib.get_logger(__name__)

_extensions: dict[str, object] = {}
_routers: list = []
_loaded: bool = False


def load_extensions() -> None:
    """Discover and load all extensions from the geolens.extensions group."""
    global _loaded

    eps = entry_points(group="geolens.extensions")
    for ep in eps:
        try:
            loader = ep.load()
            if callable(loader):
                loader(_extensions)
                logger.info("Loaded extension", name=ep.name)
        except Exception:
            logger.warning("Failed to load extension", name=ep.name, exc_info=True)

    # Extract routers if registered
    routers = _extensions.pop("_routers", [])
    _routers.extend(routers)
    _loaded = True


def get_extension_routers() -> list:
    """Return FastAPI routers registered by extensions."""
    return list(_routers)
```

### Pattern 3: Alembic Multi-Directory Discovery
**What:** Core `alembic/env.py` discovers enterprise migration paths via entry_points and adds them to `version_locations`.
**When to use:** Always at migration time -- both `alembic upgrade head` and `alembic revision`.
**Example:**
```python
# In alembic/env.py, before do_run_migrations:
from importlib.metadata import entry_points as iter_entry_points
import pathlib

def _discover_migration_paths() -> list[str]:
    """Discover additional migration version directories from plugins."""
    paths = []
    for ep in iter_entry_points(group="geolens.migrations"):
        try:
            fn = ep.load()
            if callable(fn):
                for p in fn():
                    if pathlib.Path(p).is_dir():
                        paths.append(p)
        except Exception:
            pass  # Non-fatal: core migrations still run
    return paths

# Append enterprise migration paths to version_locations
extra_paths = _discover_migration_paths()
if extra_paths:
    base_versions = config.get_main_option("version_locations") or "alembic/versions"
    all_paths = base_versions + " " + " ".join(extra_paths)
    config.set_main_option("version_locations", all_paths)
```

### Pattern 4: Docker Compose Override
**What:** Enterprise overlay compose file that volume-mounts the enterprise package and installs it at startup.
**Example:**
```yaml
# docker-compose.enterprise.yml
services:
  api:
    volumes:
      - ../geolens-enterprise:/enterprise:ro
    environment:
      GEOLENS_ENTERPRISE_PATH: /enterprise

  worker:
    volumes:
      - ../geolens-enterprise:/enterprise:ro
    environment:
      GEOLENS_ENTERPRISE_PATH: /enterprise

  migrate:
    volumes:
      - ../geolens-enterprise:/enterprise:ro
    environment:
      GEOLENS_ENTERPRISE_PATH: /enterprise
```

### Pattern 5: Entrypoint Enterprise Install
**What:** The api-entrypoint.sh checks for enterprise package and installs it before starting.
**Example:**
```bash
# Added to api-entrypoint.sh before migrations
if [ -d "/enterprise" ] && [ -f "/enterprise/pyproject.toml" ]; then
    echo "Installing enterprise extensions..."
    uv pip install -e /enterprise 2>&1 || {
        echo "WARNING: Enterprise package install failed" >&2
    }
fi
```

### Anti-Patterns to Avoid
- **Importing enterprise code from core:** Core must never `import geolens_enterprise`. All discovery goes through entry_points.
- **Hardcoding enterprise routers in main.py:** Routers must be registered dynamically via the extension loader, not via `from geolens_enterprise import ...` in core.
- **Sharing Alembic versions directory:** Enterprise migrations must live in the enterprise package, not in `backend/alembic/versions/`.
- **Making core depend on enterprise package:** Core's `pyproject.toml` must not list `geolens-enterprise` as a dependency. The relationship is one-directional: enterprise depends on core.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Entry point discovery | Custom module scanning | `importlib.metadata.entry_points()` | Already implemented in core `load_extensions()` |
| Multi-directory migrations | Custom migration runner | Alembic `version_locations` + `branch_labels` | Battle-tested, handles dependency ordering |
| Package installation in Docker | Custom script to copy/symlink | `pip install -e` / `uv pip install -e` | Proper metadata registration for entry_points |
| YAML merging for compose | Custom merge scripts | `docker compose -f ... -f ...` | Native Docker Compose feature |

**Key insight:** The entire overlay pattern relies on standard Python packaging primitives (entry_points, pip install) and standard Docker Compose override files. No custom discovery or plugin framework needed.

## Common Pitfalls

### Pitfall 1: Entry Points Not Discoverable After pip install -e
**What goes wrong:** `importlib.metadata.entry_points(group="geolens.extensions")` returns empty after `pip install -e`.
**Why it happens:** Editable installs with modern build backends require proper `[build-system]` configuration. If setuptools is not declared as build backend, entry_points metadata may not be generated.
**How to avoid:** Always include `[build-system]` section in enterprise `pyproject.toml` with `requires = ["setuptools>=68.0"]` and `build-backend = "setuptools.build_meta"`.
**Warning signs:** `load_extensions()` logs no entries on startup despite package being installed.

### Pitfall 2: Alembic version_locations Memoization
**What goes wrong:** Setting `version_locations` in `env.py` after ScriptDirectory is already created has no effect.
**Why it happens:** Alembic's ScriptDirectory caches `version_locations` via memoized properties (GitHub issue #570).
**How to avoid:** Set `config.set_main_option("version_locations", ...)` BEFORE `context.configure()` is called, ideally at the top of `env.py` after config is obtained but before any migration operations.
**Warning signs:** Enterprise migrations not found despite correct paths.

### Pitfall 3: Circular Import Between Enterprise and Core
**What goes wrong:** Enterprise package imports core models/services that import enterprise code.
**Why it happens:** Moving SAML router to enterprise -- it imports from `app.auth.oauth.service`, `app.auth.service`, `app.dependencies`, etc.
**How to avoid:** Enterprise package imports from core are fine (one-directional). Core must never import from `geolens_enterprise`. Enterprise code references core modules via their full `app.*` paths since both packages are installed in the same environment.
**Warning signs:** `ImportError` on startup.

### Pitfall 4: Migration Branch Ordering on Fresh Database
**What goes wrong:** Enterprise migrations try to run before core migrations they depend on.
**Why it happens:** Alembic `upgrade head` with multiple heads and no explicit dependency chain.
**How to avoid:** Enterprise migration initial revision must declare `depends_on` pointing to the latest core migration revision (e.g., `depends_on = ('0010_add_saml_provider_columns',)`). This creates a merge point.
**Warning signs:** SQL errors about missing tables/columns on fresh deploy.

### Pitfall 5: Core SAML Router Import Fails After Extraction
**What goes wrong:** Core `main.py` imports `from app.auth.saml.router import router as saml_router` but SAML code has been moved to enterprise.
**Why it happens:** Direct imports in `main.py` remain after code extraction.
**How to avoid:** Replace the hardcoded SAML router import in `main.py` with dynamic router registration from the extension system. The SAML router line must be removed from core and re-registered by the enterprise extension loader.
**Warning signs:** `ImportError` on community-only deployment.

### Pitfall 6: Docker Volume Mount Permissions
**What goes wrong:** `pip install -e /enterprise` fails because the volume is mounted read-only but pip needs to write `.egg-info`.
**Why it happens:** Enterprise volume mounted with `:ro` flag prevents `pip install -e` from writing package metadata.
**How to avoid:** Mount the enterprise volume without `:ro` OR use `uv pip install --no-build-isolation /enterprise` which handles metadata differently. Alternatively, the entrypoint can copy to a writable temp directory first.
**Warning signs:** Permission denied errors during startup.

## Code Examples

### Core main.py -- Dynamic Router Registration
```python
# In lifespan(), after load_extensions() and init_edition():
from app.extensions import get_extension_routers

load_extensions()
init_edition(list_extensions())

# Register enterprise routers dynamically
for router in get_extension_routers():
    app.include_router(router)
```

**Problem:** FastAPI routers must be included before the app starts serving (during lifespan), but `app.include_router()` works at any point before the first request is served.

**Solution:** The lifespan function runs before the ASGI server accepts connections, so including routers there is safe. However, routes added in `main.py` module scope (the 20+ `app.include_router` calls) run at import time. Enterprise routers added during lifespan will also work because Starlette/FastAPI supports late router addition.

### Enterprise SAML Router (Extracted)
```python
# geolens_enterprise/auth/saml/router.py
# Same code as current app/auth/saml/router.py but imports remain
# pointing to core: from app.auth.oauth.service import ...
# The only change: this file lives in the enterprise package.
```

### Core Audit Router After Extraction
```python
# backend/app/audit/router.py -- export endpoints REMOVED
# Only list_audit_logs remains (not enterprise-gated)
router = APIRouter(prefix="/admin", tags=["Admin"])

@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_audit_logs(...):
    """Query audit logs with optional filters (admin only)."""
    ...
# CSV/JSON export endpoints moved to enterprise package
```

### Core Settings Router After Extraction
```python
# backend/app/settings/router.py -- PUT branding endpoint REMOVED
# GET /branding/ stays (public, no enterprise gate)
@router.get("/branding/")
async def get_branding(...):
    """Return branding configuration (public, no auth required)."""
    ...
# PUT /branding/ moved to enterprise package
```

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | `backend/pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `cd backend && uv run pytest tests/ -x -q` |
| Full suite command | `cd backend && uv run pytest tests/ -q` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REPO-01 | Enterprise pyproject.toml has valid entry_points; pip install -e succeeds | integration | Manual: `cd ../geolens-enterprise && pip install -e .` | Wave 0 |
| REPO-02 | Docker compose override starts app with enterprise active | integration | `docker compose -f docker-compose.yml -f docker-compose.enterprise.yml up -d` | Wave 0 |
| REPO-03 | Enterprise migrations use branch label, don't conflict with core | unit | `cd backend && uv run pytest tests/test_enterprise_migrations.py -x` | Wave 0 |
| REPO-04 | Enterprise features activate when package installed | unit | `cd backend && uv run pytest tests/test_extension_loading.py -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `cd /Users/ishiland/Code/geolens/backend && uv run pytest tests/ -x -q`
- **Per wave merge:** `cd /Users/ishiland/Code/geolens/backend && uv run pytest tests/ -q`
- **Phase gate:** Full suite green + manual docker compose enterprise overlay verification

### Wave 0 Gaps
- [ ] `geolens-enterprise/` directory scaffold with pyproject.toml
- [ ] `geolens-enterprise/tests/test_registration.py` -- verifies entry_points callable works
- [ ] Enterprise package internal test that `register_extensions()` populates registry dict
- [ ] Core test that `load_extensions()` discovers mock entry_points

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| setup.py entry_points | pyproject.toml entry_points | PEP 621 (2021) | Use `[project.entry-points]` not `setup.py` |
| `pkg_resources.iter_entry_points` | `importlib.metadata.entry_points` | Python 3.9+ | Already using correct API in core |
| `alembic.ini` static paths | `config.set_main_option` in env.py | Alembic 1.x | Dynamic path discovery possible |

## Open Questions

1. **Router Registration Timing**
   - What we know: `app.include_router()` works during lifespan. Enterprise routers need to be registered before first request.
   - What's unclear: Whether routes added during lifespan are properly reflected in OpenAPI docs.
   - Recommendation: Test that `/docs` shows enterprise routes. If not, move router registration to module scope with conditional import (try/except).

2. **Alembic autogenerate with Enterprise Models**
   - What we know: Enterprise may add new models/tables. `alembic revision --autogenerate` needs to see enterprise models.
   - What's unclear: How `target_metadata` in env.py discovers enterprise models without importing them.
   - Recommendation: Enterprise models should use the same `Base` from `app.database`. When enterprise is installed, its models are imported via the extension loader, making them visible to autogenerate.

3. **Core SAML Import Chain After Extraction**
   - What we know: Core `main.py` line 45 does `from app.auth.saml.router import router as saml_router`. This must be removed.
   - What's unclear: Whether other core code imports from `app.auth.saml.*`.
   - Recommendation: Grep for all `app.auth.saml` imports in core. Remove all of them. Enterprise package provides SAML via extension router registration.

## Sources

### Primary (HIGH confidence)
- Core extension system: `backend/app/extensions/__init__.py` -- existing loader pattern
- Core edition detection: `backend/app/edition.py` -- auto-detect from loaded extensions
- Core Alembic env.py: `backend/alembic/env.py` -- current single-branch configuration
- Alembic branches docs: https://alembic.sqlalchemy.org/en/latest/branches.html
- Alembic config API: https://alembic.sqlalchemy.org/en/latest/api/config.html

### Secondary (MEDIUM confidence)
- Alembic version_locations memoization issue: https://github.com/sqlalchemy/alembic/issues/570 -- confirms `set_main_option` before script access works
- setuptools entry_points docs: https://setuptools.pypa.io/en/latest/userguide/entry_point.html
- Python packaging guide: https://packaging.python.org/en/latest/guides/writing-pyproject-toml/

### Tertiary (LOW confidence)
- None -- all findings verified against official docs or existing codebase

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- using existing patterns from core codebase
- Architecture: HIGH -- entry_points pattern already implemented and proven in Phase 206
- Pitfalls: HIGH -- verified against Alembic issue tracker and codebase analysis
- Migration multi-directory: MEDIUM -- `set_main_option` approach needs testing due to memoization concerns (issue #570)

**Research date:** 2026-03-26
**Valid until:** 2026-04-26 (stable domain, no fast-moving dependencies)
