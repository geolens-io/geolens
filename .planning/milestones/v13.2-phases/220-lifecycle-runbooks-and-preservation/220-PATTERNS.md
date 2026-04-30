# Phase 220: lifecycle-runbooks-and-preservation - Pattern Map

**Mapped:** 2026-04-29
**Files analyzed:** 8 (3 NEW, 5 MODIFIED)
**Analogs found:** 7 / 8 (one net-new pattern with external reference for cross-repo CI checkout)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `docs/edition-deactivation.md` | docs (operator runbook) | request-response (human-read) | `docs/saml.md` (full doc) | partial — only substantive doc in repo |
| `docs/edition-reactivation.md` | docs (operator runbook) | request-response (human-read) | `docs/saml.md` Installation §32-58 | partial — same scope guidance |
| `backend/tests/test_lifecycle.py` | test (integration / lifecycle) | event-driven (registry mutation) | `backend/tests/test_saml_overlay.py` | exact — same pattern, inverse purpose |
| `docs/saml.md` (Installation §) | docs edit (targeted line replace) | — | self (lines 43-58) | exact — surgical retarget of one bullet + new subsection |
| `backend/pyproject.toml` (markers list) | config (pytest registration) | — | self (lines 71-75) | exact — one-line addition next to existing markers |
| `.github/workflows/ci.yml` (backend-test) | CI workflow (private-repo checkout + install) | batch (CI step sequence) | self (`backend-test` job lines 219-312) | role-match — net-new pattern for cross-repo private checkout |
| `.planning/REQUIREMENTS.md` (LIFECYCLE-04) | docs edit (text-precision fix) | — | self (line 24) | exact — single-line wording fix |
| `.planning/ROADMAP.md` (Phase 220 SC#4) | docs edit (text-precision fix) | — | self (line 80) | exact — mirrors REQUIREMENTS fix |

## Pattern Assignments

### `docs/edition-deactivation.md` (NEW — operator runbook)

**Analog:** `docs/saml.md` (the only substantive operator doc in this repo per RESEARCH §Pitfall 1; all other `docs/*.md` are stub redirects to docs.getgeolens.com)

**Tone & front-matter pattern** (saml.md:1-14):
```markdown
# SAML SSO

> **SAML SSO requires the `geolens-enterprise` overlay (commercial license).** See the [Enterprise Edition install guide](install-guide.md) for setup. Community edition does not include SAML.

GeoLens Enterprise adds SP-initiated SAML 2.0 single sign-on to any community deployment by loading an enterprise overlay package alongside the core API. Once installed, the admin UI gains a **SAML SSO** tab where you register one or more identity providers (IdPs)...

| | Value |
|---|---|
| Package | `geolens-enterprise` (commercial; not on PyPI) |
| License | Commercial — contact sales |
```
Operator-facing doc opens with a `>` blockquote callout naming the audience/scope, a one-paragraph explainer, then a key/value at-a-glance table.

**Section structure pattern** (saml.md:31-58 Installation):
- ATX `## Section` headers
- Code-block-heavy: bash blocks for commands, no inline code-only narration
- Pre/Post-step callouts inline (`> **Pitfall:**` / `> **Always request ...**`)

**Pitfall callout pattern** (saml.md:65-70, 113):
```markdown
> **Always request `NAMEID_FORMAT_PERSISTENT` from your IdP.** Email-format NameIDs (`NAMEID_FORMAT_EMAILADDRESS`) break user identity continuity if the IdP later changes a user's email — GeoLens uses NameID as the unique subject, so an email change becomes a new account. Persistent IDs are stable across email changes.
```
Use blockquote-with-bold-lead for "must read this before doing X" warnings. Phase 220 runbook applies this for the destructive-path callout and the "GEOLENS_EDITION alone is incomplete" callout.

**Table-for-matrix pattern** (saml.md:140-150, hardening defaults):
```markdown
| Setting | Value | Reason |
|---|---|---|
| `want_assertions_signed` | `True` | The IdP MUST sign assertions. Unsigned assertions are rejected. |
```
Phase 220's data-fate matrix (per CONTEXT.md Claude's Discretion: "near the top of `docs/edition-deactivation.md`") uses this exact table shape: data class × scenario, terse cells, code-formatted column names where applicable.

**Cross-link pattern** (saml.md:217-223):
```markdown
## References
- [`docs/admin-guide.md`](admin-guide.md) — operating GeoLens in production (audit log, user management, RBAC).
- [`docs/install-guide.md`](install-guide.md) — running a GeoLens instance, including the enterprise overlay.
```
Backtick-wrap doc paths in link text, narrative explanation after em-dash. Phase 220 runbook references `edition-reactivation.md` and `saml.md` this way.

**Cross-link target file paths to use** (verified):
- `[edition-reactivation.md](edition-reactivation.md)` — sibling runbook
- `[saml.md](saml.md)` — for IdP-side cleanup pointer
- Optionally: `[install-guide.md](install-guide.md)` and `[admin-guide.md](admin-guide.md)` (both stubs but the redirect chain reaches operator docs)

---

### `docs/edition-reactivation.md` (NEW — operator runbook, thin)

**Analog:** `docs/saml.md` Installation section (saml.md:32-57)

**Reactivation walkthrough mirrors the existing activation walkthrough**:
```markdown
## Installation

The enterprise overlay ships as a separate Python package (`geolens-enterprise`) plus an enterprise Docker compose file:

\`\`\`bash
# Stop community-only stack if it is running
docker compose down

# Start the enterprise stack (loads the overlay + runs the e002 migration)
docker compose -f docker-compose.yml -f docker-compose.enterprise.yml up -d --build
\`\`\`

Loading the overlay triggers the `e002_add_saml_columns` Alembic migration, which:

1. Adds four nullable columns to `catalog.oauth_providers` (`idp_entity_id`, `idp_sso_url`, `idp_certificate`, `sp_entity_id`).
2. Relaxes the `chk_oauth_providers_type` CHECK constraint to include `'saml'`.

...

Verify the overlay loaded:

\`\`\`bash
# Should show the SAML routes mounted
curl -fsS http://localhost:8000/openapi.json | jq '.paths | keys[] | select(test("/auth/saml/"))'
\`\`\`

If the SAML routes are missing, confirm `geolens-enterprise` is installed (`uv pip list | grep enterprise`) and that the API logs include `loaded extension: identity` at startup.
```
Per CONTEXT.md D-07 + RESEARCH.md A3: reactivation runbook is **thin** (½ page). Re-uses this verify-block almost verbatim, then adds a post-reactivation checklist (SAML columns physically present, providers re-appear in admin UI, IdP login round-trips).

---

### `backend/tests/test_lifecycle.py` (NEW — integration test, registry-clear simulation)

**Analog:** `backend/tests/test_saml_overlay.py` (Phase 217 carry-over)

**Module docstring pattern** (test_saml_overlay.py:1-18):
```python
"""Integration tests for the SAML enterprise overlay (Phase 217 Plan 02).

Covers the 8 SAML test scenarios specified in 217-02-PLAN.md task 03:

- Registration: extension dual-registers under ``identity`` and ``_routers``
- Metadata: GET /auth/saml/{slug}/metadata returns valid samlmetadata+xml
...

All tests use the ``saml_overlay_registered`` conftest fixture which
programmatically installs ``EnterpriseSamlExtension`` for the test's
lifetime. The SAML router is also dynamically mounted into the FastAPI
app for the test's duration, then unmounted on teardown so other tests
that assume the community community/no-SAML default are unaffected.
"""
```
New test file opens with a docstring naming the requirement (LIFECYCLE-04), the simulation strategy (registry clear in single pytest session), and the inherited fixture (`saml_overlay_registered`).

**Imports pattern** (test_saml_overlay.py:20-33):
```python
from __future__ import annotations

import base64
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.auth.oauth.encryption import encrypt_secret
from app.modules.auth.oauth.models import OAuthProvider
```
- `from __future__ import annotations` first
- stdlib imports, then `pytest`, then SQLAlchemy
- App imports last, ordered by depth
- Phase 220 lifecycle test adds: `from sqlalchemy.orm import undefer_group`, `from app.modules.auth.oauth.models import OAuthAccount`, and `import app.core.edition as edition_mod`

**SAML provider seeding helper pattern — copy verbatim or import** (test_saml_overlay.py:96-137):
```python
async def _seed_saml_provider(
    db: AsyncSession,
    *,
    slug: str = FIXTURE_SLUG,
    display_name: str = "Fixture IdP",
    idp_entity_id: str = FIXTURE_IDP_ENTITY_ID,
    idp_sso_url: str = "https://fixture-idp.geolens.test/sso",
    idp_certificate: str = FIXTURE_CERT_PEM,
    sp_entity_id: str = FIXTURE_SP_ENTITY_ID,
    group_claim: str | None = "groups",
    group_role_mapping: dict | None = None,
    default_role: str = "viewer",
    enabled: bool = True,
) -> OAuthProvider:
    """Seed a SAML OAuthProvider row.

    NOTE: ``client_id`` and ``client_secret_encrypted`` are NOT-NULL on the
    ORM (backend/app/modules/auth/oauth/models.py:40-41). Plan 03 makes them
    Optional in Pydantic but does NOT relax the DB columns. Seed with
    placeholder strings to satisfy the constraint.
    """
    if group_role_mapping is None:
        group_role_mapping = {"editors": "editor"}
    provider = OAuthProvider(
        slug=slug,
        display_name=display_name,
        provider_type="saml",
        client_id="unused",                                # placeholder for NOT-NULL
        client_secret_encrypted=encrypt_secret("unused"),  # placeholder for NOT-NULL
        idp_entity_id=idp_entity_id,
        idp_sso_url=idp_sso_url,
        idp_certificate=encrypt_secret(idp_certificate),   # Fernet-encrypted at rest
        sp_entity_id=sp_entity_id,
        group_claim=group_claim,
        group_role_mapping=group_role_mapping,
        default_role=default_role,
        enabled=enabled,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider
```
Phase 220 lifecycle test must seed the provider with real values (not the FIXTURE_CERT_PEM keys) AND seed an `OAuthAccount` linkage row + a `User` with `auth_provider='oauth'`. **Recommended:** import the helper rather than redefining (keeps the seed contract DRY), and add a small `_seed_saml_user_and_account()` helper next to it.

**Edition state save/restore pattern** (test_saml_overlay.py:233-239 + 270):
```python
import app.core.edition as edition_mod
...
saved_info = edition_mod._info
edition_mod.init_edition(["enterprise"])
...
# Teardown:
edition_mod._info = saved_info
```
Save `_info` before flipping; restore in `finally`. The lifecycle test follows this same shape but flips twice (enterprise → community within a single test) and restores at teardown.

**Marker + async signature pattern** (test_saml_overlay.py:285-298):
```python
async def test_saml_overlay_registers_under_identity_and_routers(
    saml_overlay_registered,
):
    """SAML-09: extension dual-registered under 'identity' AND _routers."""
    from app.platform.extensions import _extensions, _routers
    from geolens_enterprise.auth.saml import EnterpriseSamlExtension

    assert isinstance(_extensions["identity"], EnterpriseSamlExtension)
    ...
```
Phase 220 lifecycle test: prefix with `@pytest.mark.lifecycle` (NEW marker), uses `async def` (anyio_mode=auto in pyproject), takes `client`, `test_db_session`, `saml_overlay_registered` fixtures. Imports inside the test body when they reference `geolens_enterprise` (deferred — same rationale as conftest).

**Inherited fixture (registry save/restore pattern — DO NOT REIMPLEMENT)** — `backend/tests/conftest.py:454-484`:
```python
@pytest.fixture
def saml_overlay_registered():
    """Programmatically register EnterpriseSamlExtension into the live extension
    registry for the duration of a single test. Restores prior state on
    teardown so other tests that expect community edition still see their
    default.
    ...
    """
    from app.platform.extensions import _extensions, _routers

    saved_ext = dict(_extensions)
    saved_routers = list(_routers)
    try:
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
**Critical:** the lifecycle test's mid-test `_extensions.clear()` + `_routers.clear()` runs BEFORE this fixture's `finally` block, which means the fixture's restore-from-saved happens after the test body. No new fixture needed; just request `saml_overlay_registered` and clear the registry inside the test body.

**Deferred-column query pattern** (RESEARCH §Code Examples; production echo at `~/Code/geolens-enterprise/geolens_enterprise/auth/saml/router.py:55-61`):
```python
from sqlalchemy import select
from sqlalchemy.orm import undefer_group
from app.modules.auth.oauth.models import OAuthProvider

stmt = (
    select(OAuthProvider)
    .where(OAuthProvider.id == seeded_id)
    .options(undefer_group("saml"))
)
result = await test_db_session.execute(stmt)
provider = result.scalar_one()
assert provider.idp_entity_id == "https://idp.test/entity"
```
Use `undefer_group("saml")` — the same option the production SAML router uses. Raw SQL fallback is acceptable if ORM-state weirdness post-clear surfaces (see RESEARCH §Code Examples, alternative block).

**Cleanup pattern** (test_saml_overlay.py:185-219, `_cleanup_saml_providers` fixture):
```python
@pytest.fixture
async def _cleanup_saml_providers(test_db_session):
    """Best-effort cleanup of any SAML provider rows AND any users JIT-provisioned
    from SAML callbacks after each test.
    ...
    """
    yield
    try:
        await test_db_session.execute(
            text("DELETE FROM catalog.users WHERE email = :email"),
            {"email": FIXTURE_NAMEID},
        )
        await test_db_session.execute(
            text(
                "DELETE FROM catalog.oauth_accounts WHERE provider_id IN "
                "(SELECT id FROM catalog.oauth_providers WHERE provider_type='saml')"
            )
        )
        await test_db_session.execute(
            text("DELETE FROM catalog.oauth_providers WHERE provider_type='saml'")
        )
        await test_db_session.commit()
    except Exception:
        await test_db_session.rollback()
```
Phase 220 lifecycle test takes the same `_cleanup_saml_providers` fixture so seeded SAML rows don't pollute other tests. (Or define a new test-local fixture with the same shape if planner wants to keep imports flat — both work.)

---

### `docs/saml.md` (MODIFIED — targeted Installation section edit)

**Analog:** self, lines 43-58 (the Installation section)

**Existing line to retarget** (saml.md:48):
```markdown
The migration is reversible (`alembic downgrade -1` removes the columns and re-tightens the CHECK), but downgrading destroys any SAML provider rows. Back up first.
```

**Replacement pattern (per CONTEXT.md D-03 + RESEARCH §Pattern 2)** — drop in place of the existing line, near saml.md:48, immediately after the migration-effects list at saml.md:43-47:
```markdown
> **To deactivate SAML, see [docs/edition-deactivation.md](edition-deactivation.md).**
> The canonical path leaves the schema alone — your SAML provider rows and the
> 4 deferred SAML columns persist through deactivation, ready for reactivation.
>
> The `alembic downgrade -1` path is destructive: it deletes
> `oauth_accounts` SAML rows, deletes `oauth_providers` SAML rows, and drops
> the 4 SAML columns. Use only for permanent decommissioning. Mandatory pre-step:
> `pg_dump --table catalog.oauth_providers --table catalog.oauth_accounts --table catalog.users`.
> Without this dump, the deletion is unrecoverable.
```

**New "Deactivating SAML" subsection** — short paragraph, added immediately after the existing "Verify the overlay loaded" block (after saml.md:57). Use this exact heading depth (`###`) since it nests under `## Installation`:
```markdown
### Deactivating SAML

To turn SAML off, follow the canonical path in [docs/edition-deactivation.md](edition-deactivation.md). The TL;DR: stop loading the `geolens-enterprise` overlay (drop `docker-compose.enterprise.yml` from your compose stack or `pip uninstall geolens-enterprise`) and restart. Your SAML provider rows survive; your users' identities survive; reactivation is a clean re-mount.
```

**No other edits.** Per D-03 + Anti-Pattern 5: only the existing "reversible" bullet + this short subsection. IdP configurations, hardening defaults, troubleshooting, audit, security posture all stay byte-identical.

---

### `backend/pyproject.toml` (MODIFIED — markers list)

**Analog:** self, lines 71-75

**Existing pattern** (pyproject.toml:71-75):
```toml
markers = [
    "perf: performance regression tests (deselected by default)",
    "requires_ogr2ogr: tests that invoke ogr2ogr and need build_pg_conn_str redirected to the test database (K2-PRE; fixture lives in tests/conftest.py)",
    "architecture: layering and boundary tests; opt-out locally with `-m 'not architecture'` (Phase 212 LAYER-01 guard)",
]
```

**Append pattern (one-line addition)** — Phase 220 adds a single entry immediately after `architecture`:
```toml
markers = [
    "perf: performance regression tests (deselected by default)",
    "requires_ogr2ogr: tests that invoke ogr2ogr and need build_pg_conn_str redirected to the test database (K2-PRE; fixture lives in tests/conftest.py)",
    "architecture: layering and boundary tests; opt-out locally with `-m 'not architecture'` (Phase 212 LAYER-01 guard)",
    "lifecycle: edition deactivation/reactivation tests requiring enterprise overlay (Phase 220 LIFECYCLE-04)",
]
```

**DO NOT touch `addopts`** (pyproject.toml:70 — `addopts = "-m 'not perf'"`). Per RESEARCH §Pitfall 7: lifecycle is intended to run by default, only `perf` is heavy enough to need opt-out. Adding `not lifecycle` to addopts would silently uncoverage the test.

---

### `.github/workflows/ci.yml` (MODIFIED — backend-test job)

**Analog:** self, `backend-test` job at ci.yml:219-312 (existing job structure)

**Existing job step pattern** (ci.yml:219-279, abridged):
```yaml
backend-test:
  name: Backend Tests
  needs: changes
  if: needs.changes.outputs.backend == 'true' || github.event_name == 'push'
  runs-on: ubuntu-latest
  defaults:
    run:
      working-directory: backend
  env:
    POSTGRES_USER: geolens
    POSTGRES_PASSWORD: geolens_test
    ...
    PYTHONPATH: .
  steps:
    - uses: actions/checkout@v4

    - name: Start PostgreSQL with PostGIS + pgvector
      working-directory: .
      run: |
        docker build -t geolens-test-db -f - . <<'DOCKERFILE'
        ...

    - uses: astral-sh/setup-uv@v6
      with:
        version: "0.10.2"
        ...

    - uses: actions/setup-python@v5
      with:
        python-version: "3.13"

    - name: Install system dependencies
      run: sudo apt-get update && sudo apt-get install -y gdal-bin

    - name: Install Python dependencies
      run: uv sync --locked --dev
```
Step ordering: checkout → DB setup → uv setup → python setup → system deps → python deps → DB schema setup → migrations → tests.

**Net-new pattern (no in-repo precedent — cited from `actions/checkout@v4` README)** — Phase 220 inserts a second `actions/checkout` step + an enterprise-install step BEFORE the `Install Python dependencies` step, AFTER the existing `actions/checkout@v4` at ci.yml:239:

```yaml
    - uses: actions/checkout@v4
      with:
        path: geolens   # NB: changes default checkout path; existing steps may need working-directory updates

    - name: Checkout geolens-enterprise (skip on fork PRs without secret)
      if: ${{ env.GEOLENS_ENTERPRISE_TOKEN != '' }}
      uses: actions/checkout@v4
      with:
        repository: ishiland/geolens-enterprise
        token: ${{ secrets.GEOLENS_ENTERPRISE_TOKEN }}
        path: geolens-enterprise
      env:
        GEOLENS_ENTERPRISE_TOKEN: ${{ secrets.GEOLENS_ENTERPRISE_TOKEN }}

    - name: Install enterprise overlay (if available)
      working-directory: backend
      run: |
        if [ -d "../../geolens-enterprise" ] && [ -f "../../geolens-enterprise/pyproject.toml" ]; then
          uv add --editable ../../geolens-enterprise
          echo "OVERLAY_INSTALLED=1" >> $GITHUB_ENV
        else
          echo "geolens-enterprise not available (fork PR or missing secret) — lifecycle marker deselected"
          echo "OVERLAY_INSTALLED=0" >> $GITHUB_ENV
        fi

    - name: Run tests with coverage
      run: |
        if [ "${OVERLAY_INSTALLED:-0}" = "1" ]; then
          uv run pytest -v --tb=short -m 'not perf' --cov=app --cov-report=term-missing --cov-report=html:htmlcov --cov-report=xml:coverage.xml --cov-fail-under=58.5
        else
          uv run pytest -v --tb=short -m 'not perf and not lifecycle' --cov=app --cov-report=term-missing --cov-report=html:htmlcov --cov-report=xml:coverage.xml --cov-fail-under=58.5
        fi
```

**Existing step to replace (ci.yml:303-304)**:
```yaml
    - name: Run tests with coverage
      run: uv run pytest -v --tb=short -m 'not perf' --cov=app --cov-report=term-missing --cov-report=html:htmlcov --cov-report=xml:coverage.xml --cov-fail-under=58.5
```
Replace with the conditional version above.

**Citations (no in-repo precedent for cross-repo private checkout):**
- `actions/checkout@v4` `repository:` + `token:` + `path:` parameters: documented at github.com/actions/checkout README.
- Fork-PR secret unavailability behavior: github.com docs/actions/security-guides/encrypted-secrets — `secrets.X` returns empty string in fork-PR runs; `if: env.X != ''` evaluates falsy and skips the step cleanly.
- Recommended secret name: `GEOLENS_ENTERPRISE_TOKEN` (RESEARCH §A1 — naming bikeshed; planner can pick another).

**Path-restructure caveat:** the second-checkout pattern requires the first checkout to use `path: geolens` (so the two repos sit side-by-side). This may force `working-directory:` updates throughout the job. Alternative: use `path: geolens-enterprise` for the SECOND checkout and leave the first checkout as default (current path = `$GITHUB_WORKSPACE`); reference enterprise as `../geolens-enterprise` from `backend/`. Planner picks final shape — second alternative is the smaller diff.

---

### `.planning/REQUIREMENTS.md` (MODIFIED — text-precision fix LIFECYCLE-04)

**Analog:** self, line 24

**Existing line:**
```markdown
- [ ] **LIFECYCLE-04**: Disabling the enterprise edition (without running `alembic downgrade`) preserves `oauth_providers` rows with `provider_type='saml'` and the 4 `deferred=True` SAML columns on `User` — verified by an integration test that exercises the deactivate path.
```

**Replacement (one-word fix per CONTEXT.md Claude's Discretion):**
```markdown
- [ ] **LIFECYCLE-04**: Disabling the enterprise edition (without running `alembic downgrade`) preserves `oauth_providers` rows with `provider_type='saml'` and the 4 `deferred=True` SAML columns on `oauth_providers` — verified by an integration test that exercises the deactivate path.
```
Diff: `on \`User\`` → `on \`oauth_providers\``. (RESEARCH §Pitfall 5 confirms all 4 SAML columns are physically on `catalog.oauth_providers`, not `users`.)

---

### `.planning/ROADMAP.md` (MODIFIED — text-precision fix Phase 220 SC#4)

**Analog:** self, line 80

**Existing line (ROADMAP.md:80):**
```markdown
  4. An integration test runs in CI (`pytest -m lifecycle`) that exercises the deactivate path and asserts `oauth_providers` rows with `provider_type='saml'` and the 4 `deferred=True` User columns are intact after edition flag is toggled off
```

**Replacement (mirror REQUIREMENTS.md fix):**
```markdown
  4. An integration test runs in CI (`pytest -m lifecycle`) that exercises the deactivate path and asserts `oauth_providers` rows with `provider_type='saml'` and the 4 `deferred=True` `oauth_providers` columns are intact after edition flag is toggled off
```
Diff: `User columns` → `\`oauth_providers\` columns`.

---

## Shared Patterns

### Three Module-Level State Surfaces (lifecycle test critical)

**Source:** `backend/app/platform/extensions/__init__.py` (registry) + `backend/app/core/edition.py` (cached info)

**Apply to:** `backend/tests/test_lifecycle.py` exclusively (not the runbooks)

The test's "simulate overlay-not-loaded" must reset exactly THREE module-level surfaces (RESEARCH §Pitfall 2):
```python
# Source: pattern derived from test_saml_overlay.py:233 (init_edition usage) +
# conftest.py:481-484 (registry clear)
from app.platform.extensions import _extensions, _routers
import app.core.edition as edition_mod

_extensions.clear()
_routers.clear()
edition_mod.init_edition([])    # third reset — flips is_enterprise() to False
```
Skip any of the three and the test fails for the wrong reason. Do NOT touch `_loaded` (benign sentinel) or SAML's internal caches `_outstanding_requests`, `replay_cache._seen` (RESEARCH §Pitfall 3 — out of scope for the lifecycle assertion).

### Operator-Doc Tone (runbooks only)

**Source:** `docs/saml.md` Hardening Defaults + Troubleshooting + Limitations sections

**Apply to:** Both new runbooks (`edition-deactivation.md`, `edition-reactivation.md`)

- ATX `## Section` / `### Subsection` heading levels
- Code blocks with shell prompts: ```bash blocks for commands; ```sql for SQL snippets
- `>` blockquote callouts with bold lead for warnings
- Tables for matrix-shaped content (data class × scenario, not bullet lists)
- Cross-link via `[`docs/foo.md`](foo.md)` — backtick-wrap path in link text
- No emojis (per project CLAUDE.md)
- No "AI assisted" / "Bot" markers in commit messages or doc body (per CLAUDE.md)

### Edition-Mode Quote Block (runbooks)

**Source:** `docs/saml.md:3` (header callout pattern)

**Apply to:** Both new runbooks — open with a `>` blockquote naming the audience and prerequisites, similar to:
```markdown
> **This runbook is for operators of an enterprise GeoLens deployment.** Community deployments do not have SAML installed and do not need this procedure.
```

### Verification-by-grep Discipline (runbooks)

**Source:** RESEARCH §Validation Architecture / Concrete Measurement Points (220-RESEARCH.md:683-715)

**Apply to:** Both runbooks — VALIDATION.md will grep for these literal strings, so the runbooks must contain them verbatim:
- `pre-flight` (deactivation runbook)
- `pg_dump` (deactivation runbook, destructive section)
- `oauth_providers` (deactivation runbook)
- `docker compose down` (deactivation runbook)
- `GEOLENS_EDITION` (deactivation runbook)
- `defense-in-depth` or `defense in depth` (deactivation runbook)
- `verify` or `verification` (reactivation runbook)
- `/auth/saml` (reactivation runbook)
- `destructive` (deactivation runbook AND saml.md edit)
- `mandatory` or `required` (deactivation runbook)
- `edition-deactivation.md` (saml.md edit, reactivation runbook)
- `edition-reactivation.md` (deactivation runbook)

The negative grep on saml.md:
- `! grep -E 'migration is reversible.*alembic downgrade' docs/saml.md` — the existing line at saml.md:48 must be gone post-edit.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `.github/workflows/ci.yml` cross-repo private checkout step | CI workflow | batch | No existing step in this repo checks out a private sibling repo. The pattern is documented in `actions/checkout@v4` README + GitHub's secrets-in-fork-PR docs. Treat as net-new pattern with external citations (RESEARCH §Pattern 3). |

The runbooks themselves have a **partial-match analog** (`docs/saml.md`) for tone and structure but are net-new operator content (no edition-lifecycle doc has shipped before in this repo). The substantive operator docs were relocated to the `getgeolens.com` repo on 2026-04-26 (RESEARCH §Pitfall 1); the only remaining substantive in-repo doc is `docs/saml.md`. New runbooks ship in this repo only for v13.2 (cross-repo docs-site sync is RESEARCH §Open Question 1, deferred).

## Metadata

**Analog search scope:** `docs/`, `backend/tests/`, `backend/pyproject.toml`, `.github/workflows/`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`
**Files scanned:** 7 (saml.md, test_saml_overlay.py, conftest.py:454-484, pyproject.toml:60-89, ci.yml full, REQUIREMENTS.md:1-50, ROADMAP.md:60-100)
**Pattern extraction date:** 2026-04-29
**Upstream context:** 220-CONTEXT.md (D-01..D-07 locked), 220-RESEARCH.md (Patterns 1-3, Pitfalls 1-8, A1-A8 assumptions)
