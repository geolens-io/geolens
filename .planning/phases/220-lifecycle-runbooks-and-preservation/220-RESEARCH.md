# Phase 220: lifecycle-runbooks-and-preservation - Research

**Researched:** 2026-04-29
**Domain:** Operator runbook authoring + edition-overlay deactivation behavior + pytest-marker-driven CI integration
**Confidence:** HIGH (locked decisions cover all major axes; remaining uncertainty is style/depth, not technical)

## Summary

Phase 220 closes LIFECYCLE-01..05 with three concrete artifacts: two new top-level runbooks (`docs/edition-deactivation.md`, `docs/edition-reactivation.md`), a targeted edit to `docs/saml.md` Installation section retargeting the existing "reversible (`alembic downgrade -1`)" framing, and a registry-level integration test (`backend/tests/test_lifecycle.py`) under a new `lifecycle` pytest marker. CI is amended to install `geolens-enterprise` before the backend test job so `e002_add_saml_columns` is in the test DB and the lifecycle test can seed real SAML data.

The architectural mechanism the test simulates — `_extensions.clear()` + `_routers.clear()` + `init_edition([])` — is verified against the actual code: there are exactly **three** module-level caches that need re-initialization for a faithful "community-after-enterprise-was-loaded" simulation: `app.platform.extensions._extensions`, `app.platform.extensions._routers`, and `app.core.edition._info`. The existing `saml_overlay_registered` fixture (`backend/tests/conftest.py:454-484`) already implements the registry save/restore pattern; the lifecycle test inverts it (start with overlay registered, clear, assert).

**Primary recommendation:** Author runbooks in the substantive style of `docs/saml.md` (the only non-redirect doc in `docs/`), test design follows the existing `saml_overlay_registered` fixture pattern, and CI gates the lifecycle job behind `secrets.GEOLENS_ENTERPRISE_TOKEN != ''` so fork PRs see "skipped" not "failed."

## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01: Stop loading the overlay is canonical; `GEOLENS_EDITION=community` is documented as defense-in-depth.** Runbook prescribes the 6-step sequence (snapshot → inventory → stop overlay → optional env var → verify → confirm DB state). Architectural rationale: `init_edition()` honors `GEOLENS_EDITION=community` BUT typed accessors (`get_audit_extension()` / `get_branding_extension()`) do NOT consult `is_enterprise()` — they return whatever's registered. So the env var alone leaves audit-export and branding overlays silently active.

**D-02: Document the destructive `alembic downgrade -1` path with a mandatory pre-export step. Do NOT add `e003_drop_saml_safe`.** The safe deactivation path leaves the schema alone. The runbook quotes the destructive nature and prescribes mandatory `pg_dump --table catalog.oauth_providers --table catalog.oauth_accounts --table catalog.users` before the alembic command.

**D-03: `docs/saml.md` Installation section's existing "reversible (`alembic downgrade -1`)" framing gets retargeted.** Targeted edit (NOT full rewrite). Adds a "Deactivating SAML" subsection linking the runbook. Other sections of saml.md stay untouched.

**D-04: Registry-level simulation in a single pytest session.** Marker `@pytest.mark.lifecycle`. Test seeds SAML data → clears `_extensions` / `_routers` → re-calls `init_edition([])` → asserts SQL persistence + accessor defaults + `is_enterprise()` False.

**D-05: Test lives in `backend/tests/test_lifecycle.py`** (or extends an existing file at plan time). NOT in `geolens-enterprise/tests/`.

**D-06: CI workflow amended to install `geolens-enterprise` before the backend test job.** Checkout + `uv add --editable ./geolens-enterprise` + `alembic upgrade heads`.

**D-07: Top-level `docs/edition-deactivation.md` + `docs/edition-reactivation.md`.** No `docs/lifecycle/` subdir.

### Claude's Discretion

- **CI fork-PR gating** — recommend option (a): `if: secrets.GEOLENS_ENTERPRISE_TOKEN != ''` skips fork PRs cleanly.
- **Pre-flight checklist depth** — wording, command examples, SQL snippets are planner choice. Style reference: `docs/saml.md` (only substantive doc; `docs/upgrade-guide.md`, `docs/install-guide.md`, `docs/admin-guide.md`, `docs/cloud-deployment.md`, `docs/configuration-reference.md` are all stub-redirects to docs.getgeolens.com — see Pitfall 1 below).
- **Data-fate matrix shape** — markdown table near the top of `docs/edition-deactivation.md`.
- **Reactivation runbook depth** — recommend thin (½ page); links to existing activation steps in saml.md, focuses on post-reactivation verification.
- **TestClient strategy for `/auth/saml/*` 404 assertion** — recommend SQL-only assertions (sufficient for LIFECYCLE-04 literal text); route-404 is belt-and-braces.
- **REQUIREMENTS.md / ROADMAP.md text-precision fix** — recommend silent fix as part of Phase 220's docs work. LIFECYCLE-04 says "4 `deferred=True` User columns" — should read "on `catalog.oauth_providers`."
- **`GEOLENS_EDITION` configuration-reference entry** — N/A: `docs/configuration-reference.md` is a 3-line redirect to docs.getgeolens.com. The env-var doc lives in the marketing/docs site repo (`getgeolens.com`), not this repo. Phase 220 does NOT need to amend it here. (Caveat language about "env-var-alone-is-incomplete" goes in `docs/edition-deactivation.md` instead.)

### Deferred Ideas (OUT OF SCOPE)

- User-continuity re-onboarding procedure (Phase 221, LIFECYCLE-06)
- Round-trip symmetry test (Phase 221, LIFECYCLE-07)
- Non-destructive `e003` alembic downgrade (D-02 resolves LIFECYCLE-05 the other way)
- Generic edition lifecycle for non-SAML enterprise overlays
- `is_enterprise()` checks on registry accessors (architecturally distinct backlog item)
- Audit-log entry on edition transitions
- `pre-flight check` CLI command
- `docs/lifecycle/` subdirectory
- Docker-compose stack swap test (truer fidelity, future hardening)
- Doc-test for SC#3 (manual PR review is the v13.2 control)

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| LIFECYCLE-01 | Operator can read deactivation runbook walking enterprise→community downgrade | Operator-sequence research §1; data-fate matrix §3; existing `saml.md` style reference §6 |
| LIFECYCLE-02 | Operator can read reactivation runbook confirming `deferred=True` SAML columns + `oauth_providers` rows survive | Architectural mechanism §1 — `deferred=True` group keeps columns physically present even with the overlay absent |
| LIFECYCLE-03 | `docs/saml.md` no longer recommends destructive `alembic downgrade -1` as the only path; cross-links to runbook | Existing `saml.md` Installation section §5 — exact line + section identified |
| LIFECYCLE-04 | Disabling the enterprise edition (without `alembic downgrade`) preserves `oauth_providers` SAML rows + 4 deferred columns — verified by integration test | Test design §2 — registry-clear simulation + `undefer_group("saml")` assertion pattern; reusable `saml_overlay_registered` fixture |
| LIFECYCLE-05 | Either non-destructive alembic path exists OR runbook documents destructive path with mandatory data-export step | D-02 resolves toward "documented destructive"; `e002.downgrade()` analysis §3 confirms the destructive surface |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Operator-facing runbooks | Documentation (top-level `docs/`) | — | `docs/edition-{deactivation,reactivation}.md` consumed by humans, not code |
| Edition deactivation simulation | Backend test (`backend/tests/`) | — | Registry-clear is in-process Python state; lives in pytest session |
| Pytest marker registration | Backend config (`backend/pyproject.toml`) | — | Markers list is project-level metadata |
| Enterprise overlay install in CI | CI workflow (`.github/workflows/ci.yml`) | Backend dependency layer | Workflow checkout + `uv add --editable` |
| SAML deferred-column persistence | Database (catalog.oauth_providers) | ORM (SQLAlchemy `deferred=True`) | Physical columns survive without overlay; ORM masks them on default queries |
| Cross-doc linking | Documentation (`docs/saml.md` ↔ `docs/edition-*.md`) | — | Markdown reference links — no runtime |

## Standard Stack

### Core (already in repo — no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | >=9.0.3 | Test runner | [VERIFIED: backend/pyproject.toml:49] Already the test framework; markers list at lines 71-75 |
| SQLAlchemy | >=2.0.25 | ORM with `deferred=True, deferred_group="saml"` semantics | [VERIFIED: backend/app/modules/auth/oauth/models.py:67-78] The pattern this phase tests |
| alembic | >=1.13.0 | Schema migration runner (referenced by destructive-path doc) | [VERIFIED: backend/pyproject.toml:12] Existing migration tool |
| structlog | >=25.4.0 | Logger used by `init_edition()` | [VERIFIED: backend/app/core/edition.py:14] No change |
| FastAPI TestClient (httpx ASGITransport) | — | Integration test transport | [VERIFIED: backend/tests/conftest.py:6,261] Existing pattern |

### Supporting (CI-only)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `actions/checkout@v4` | v4 | Multi-repo checkout in CI | [CITED: github.com/actions/checkout] Use `repository:`, `token:`, `path:` to pull `geolens-enterprise` alongside `geolens` |
| `astral-sh/setup-uv@v6` | v6 | uv-based dep install | [VERIFIED: .github/workflows/ci.yml:60] Already the project's pattern |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Registry-clear in pytest session | Docker-compose stack swap | Deferred per CONTEXT.md — heavier CI cost, truer fidelity. v13.2 ships fast registry test |
| `secrets.GEOLENS_ENTERPRISE_TOKEN` PAT | SSH deploy key (`ssh-key:` param of checkout) | PAT is simpler for cross-repo same-account access; deploy keys are typically used for org-vs-fork. Both work; PAT recommended for solo-account simplicity |

**Installation:** No new dependencies. Phase 220 adds:
- 1 pytest marker line in `backend/pyproject.toml`
- 1 new test file `backend/tests/test_lifecycle.py`
- 2 new docs `docs/edition-{deactivation,reactivation}.md`
- 1 targeted edit to `docs/saml.md`
- 1 amended workflow `.github/workflows/ci.yml`

**Version verification:** Not applicable — no new external dependencies added.

## Architecture Patterns

### System Architecture Diagram

```
                   ┌──────────────────────────────────────────────┐
                   │  Operator (enterprise GeoLens deployment)    │
                   └─────────────────────┬────────────────────────┘
                                         │ reads
                                         ▼
              ┌──────────────────────────────────────────────────────┐
              │  docs/edition-deactivation.md (NEW)                  │
              │   ├── Pre-flight checklist (snapshot, inventory)     │
              │   ├── Sequence: stop overlay → restart → verify      │
              │   ├── Data-fate matrix (safe vs. destructive)        │
              │   └── Cross-link → docs/saml.md (IdP-side cleanup)   │
              └──────────────────────────────────────────────────────┘
                                         │ links to
                                         ▼
              ┌──────────────────────────────────────────────────────┐
              │  docs/saml.md Installation (TARGETED EDIT)           │
              │   ├── "Deactivating SAML" subsection (NEW)           │
              │   └── Retargeted "reversible alembic" line           │
              │       → links docs/edition-deactivation.md           │
              └──────────────────────────────────────────────────────┘
                                         │ links to
                                         ▼
              ┌──────────────────────────────────────────────────────┐
              │  docs/edition-reactivation.md (NEW)                  │
              │   ├── Re-mount overlay → restart → verify            │
              │   └── Confirms SAML columns + rows intact            │
              └──────────────────────────────────────────────────────┘

    ─────────── Code surface (data-preservation guarantee) ───────────

  ┌────────────────────────┐    ┌────────────────────────────────────┐
  │ pytest -m lifecycle    │───▶│ backend/tests/test_lifecycle.py    │
  │ (CI gate)              │    │  ├─ Seeds SAML provider+account    │
  └────────────────────────┘    │  ├─ Clears _extensions, _routers   │
              ▲                 │  ├─ Re-calls init_edition([])      │
              │                 │  └─ Asserts SQL + accessor defaults│
              │                 └────────────────────────────────────┘
              │                              │ requires
              │                              ▼
  ┌──────────────────────────┐   ┌────────────────────────────────────┐
  │.github/workflows/ci.yml  │──▶│ Checkout geolens-enterprise        │
  │ backend-test job         │   │ → uv add --editable ../enterprise  │
  │ (AMENDED)                │   │ → alembic upgrade heads            │
  └──────────────────────────┘   │ → e002_add_saml_columns applied    │
              ▲                  └────────────────────────────────────┘
              │ skipped on fork PRs                  │ enables
              │ (secrets.GEOLENS_ENTERPRISE_TOKEN)   ▼
              │                  ┌────────────────────────────────────┐
              │                  │ Test DB schema:                     │
              │                  │  catalog.oauth_providers            │
              │                  │   + idp_entity_id, idp_sso_url,     │
              │                  │   idp_certificate, sp_entity_id     │
              │                  │   (deferred=True, deferred_group)   │
              │                  └────────────────────────────────────┘
              │
  External fork PRs ──▶ skipped (no secret) ──▶ no failure for OSS contributors
```

### Component Responsibilities

| File | Responsibility | Action |
|------|----------------|--------|
| `docs/edition-deactivation.md` | Authoritative enterprise→community downgrade runbook | NEW |
| `docs/edition-reactivation.md` | Authoritative community→enterprise re-upgrade runbook | NEW |
| `docs/saml.md` | SAML setup + IdP config + targeted edit linking deactivation runbook | EDITED (Installation section only) |
| `backend/pyproject.toml` | Pytest marker registration | EDITED (`markers` list, +1 line) |
| `backend/tests/test_lifecycle.py` | Registry-level deactivation integration test | NEW |
| `.github/workflows/ci.yml` | Backend test job amended to install `geolens-enterprise` overlay | EDITED (backend-test job) |
| `backend/app/core/edition.py` | `_info` singleton (read by test) | UNCHANGED — read-only reference |
| `backend/app/platform/extensions/__init__.py` | `_extensions`, `_routers`, `_loaded` module state (cleared by test) | UNCHANGED — read-only reference |
| `backend/tests/conftest.py` | `saml_overlay_registered` fixture (pattern reference for new test) | UNCHANGED — pattern source |
| `~/Code/geolens-enterprise/geolens_enterprise/migrations/versions/e002_add_saml_columns.py` | Provides 4 SAML columns + relaxes CHECK on upgrade; destructive on downgrade | UNCHANGED — referenced from runbook |

### Recommended Project Structure

```
docs/
├── edition-deactivation.md       # NEW — top-level runbook
├── edition-reactivation.md       # NEW — top-level runbook
├── saml.md                       # EDITED Installation §
├── admin-guide.md                # untouched (already a redirect stub)
├── install-guide.md              # untouched (already a redirect stub)
└── upgrade-guide.md              # untouched (already a redirect stub)

backend/
├── pyproject.toml                # EDITED markers list
└── tests/
    ├── conftest.py               # untouched (provides saml_overlay_registered)
    ├── test_saml_overlay.py      # untouched (Phase 217 — pattern reference)
    └── test_lifecycle.py         # NEW

.github/workflows/
└── ci.yml                        # EDITED backend-test job
```

### Pattern 1: Registry-Level Deactivation Simulation (D-04)

**What:** Within a single pytest session, after seeding SAML data with the overlay registered, clear the in-process extension registry and re-init edition as community. Asserts the deactivation contract: SQL data persists, ORM accessors return defaults, `is_enterprise()` flips to False.

**When to use:** Any test that needs to verify "what does the runtime look like after the overlay is gone." Phase 221's symmetry test inherits this pattern and adds a re-register phase.

**Example (sketch — final code in plan phase):**
```python
# Source: pattern derived from backend/tests/conftest.py:454-484 (saml_overlay_registered)
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import undefer_group

from app.modules.auth.oauth.models import OAuthProvider, OAuthAccount
from app.modules.auth.models import User
from app.platform.extensions import _extensions, _routers
import app.core.edition as edition_mod
from app.platform.extensions import (
    get_audit_extension, get_branding_extension,
    get_auth_extension, get_identity_extension,
)
from app.platform.extensions.defaults import (
    DefaultAuditExtension, DefaultBrandingExtension,
    DefaultAuthExtension, DefaultIdentityExtension,
)


@pytest.mark.lifecycle
async def test_overlay_removal_preserves_saml_data(
    client, test_db_session, saml_overlay_registered,
):
    """LIFECYCLE-04: clearing the extension registry does not destroy SAML data."""
    # 1. Seed (overlay is registered via saml_overlay_registered fixture)
    edition_mod.init_edition(["enterprise"])
    provider = OAuthProvider(
        slug="lifecycle-test",
        display_name="Lifecycle Test IdP",
        provider_type="saml",
        client_id="unused",
        client_secret_encrypted="unused",
        idp_entity_id="https://idp.test/entity",
        idp_sso_url="https://idp.test/sso",
        idp_certificate="encrypted-pem",
        sp_entity_id="https://geolens.test/auth/saml/lifecycle-test",
    )
    test_db_session.add(provider)
    await test_db_session.commit()
    await test_db_session.refresh(provider)
    seeded_id = provider.id

    # ... seed OAuthAccount + User similarly ...

    # 2. Simulate overlay-not-loaded
    _extensions.clear()
    _routers.clear()
    edition_mod.init_edition([])    # flips is_enterprise() to False

    # 3. Assertions
    # SQL: SAML columns physically present + values preserved
    stmt = (
        select(OAuthProvider)
        .where(OAuthProvider.id == seeded_id)
        .options(undefer_group("saml"))
    )
    result = await test_db_session.execute(stmt)
    survivor = result.scalar_one()
    assert survivor.idp_entity_id == "https://idp.test/entity"
    assert survivor.idp_sso_url == "https://idp.test/sso"
    assert survivor.idp_certificate == "encrypted-pem"
    assert survivor.sp_entity_id == "https://geolens.test/auth/saml/lifecycle-test"

    # OAuthAccount + User rows still present
    # ...

    # Edition state
    from app.core.edition import is_enterprise
    assert is_enterprise() is False

    # Registry accessors return community defaults
    assert isinstance(get_audit_extension(), DefaultAuditExtension)
    assert isinstance(get_branding_extension(), DefaultBrandingExtension)
    assert isinstance(get_auth_extension(), DefaultAuthExtension)
    assert isinstance(get_identity_extension(), DefaultIdentityExtension)
```

[VERIFIED: backend/tests/conftest.py:466-484] The `saml_overlay_registered` fixture already saves/restores `_extensions` and `_routers`, so the test inherits clean teardown. The lifecycle test's clear-and-re-init happens AFTER seeding but BEFORE the fixture's finally block runs.

### Pattern 2: Targeted Doc Edit (D-03)

**What:** Replace the existing line in `docs/saml.md:48` ("The migration is reversible (`alembic downgrade -1` removes the columns and re-tightens the CHECK), but downgrading destroys any SAML provider rows. Back up first.") with a labeled-destructive framing + link.

**Why:** Surgical scope keeps PR review minimal. saml.md's other 14 sections stay byte-identical.

**Pattern:**
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

### Pattern 3: CI Cross-Repo Checkout with Fork-PR Skip (Claude's Discretion)

**What:** Amend the `backend-test` job in `.github/workflows/ci.yml` to checkout `geolens-enterprise` and install it before pytest runs.

**When to use:** Backend test job needs the enterprise overlay (and its `e002_add_saml_columns` migration) for the lifecycle test to seed real SAML data.

**Example (sketch — final yaml in plan phase):**
```yaml
# Source: pattern from actions/checkout README (private repos require token)
backend-test:
  # ... existing setup ...
  steps:
    - uses: actions/checkout@v4
      with:
        path: geolens

    - name: Checkout geolens-enterprise (skip on fork PRs)
      if: ${{ github.event.pull_request.head.repo.fork == false || github.event_name == 'push' }}
      uses: actions/checkout@v4
      with:
        repository: ishiland/geolens-enterprise
        token: ${{ secrets.GEOLENS_ENTERPRISE_TOKEN }}
        path: geolens-enterprise

    - name: Install enterprise overlay (if available)
      working-directory: geolens/backend
      run: |
        if [ -d "../../geolens-enterprise" ]; then
          uv add --editable ../../geolens-enterprise
        else
          echo "geolens-enterprise not available (fork PR or missing secret) — skipping lifecycle marker"
          echo "LIFECYCLE_SKIP=1" >> $GITHUB_ENV
        fi

    - name: Run tests with coverage
      working-directory: geolens/backend
      run: |
        if [ "${LIFECYCLE_SKIP:-0}" = "1" ]; then
          uv run pytest -v --tb=short -m 'not perf and not lifecycle' --cov=app ...
        else
          uv run pytest -v --tb=short -m 'not perf' --cov=app ...
        fi
```

[CITED: github.com/actions/checkout — private repo checkout requires PAT or deploy key; fork PRs do not have access to repository secrets by default.] The `if:` gate on the second checkout prevents the job from failing on fork PRs while still running on `main` and on PRs from project members where secrets are available.

### Anti-Patterns to Avoid

- **Anti-pattern 1: env-var-only deactivation.** Setting `GEOLENS_EDITION=community` does NOT clear `_extensions['audit']` or `_extensions['branding']`. The runbook MUST prescribe overlay-removal first; env var is defense-in-depth only.
- **Anti-pattern 2: docker-compose stack swap mid-test.** D-04 explicitly excludes this for v13.2 — single pytest session, registry-level simulation. Attempting compose swap inside pytest spawns subprocess complexity that's not justified for the LIFECYCLE-04 contract.
- **Anti-pattern 3: applying `alembic downgrade` mid-test.** The lifecycle test must NOT run `e002.downgrade()` — that would defeat the test (the assertion is "schema persists when overlay is gone"). The 4 SAML columns remain physically present in the test DB after teardown; that's correct.
- **Anti-pattern 4: hand-rolled column-drop SQL in test.** Don't write `ALTER TABLE DROP COLUMN` in the test setup — the conftest's existing SAML-bridge logic + `alembic upgrade heads` is the source of truth.
- **Anti-pattern 5: rewriting saml.md beyond the targeted edit.** D-03 + D-07 are explicit: only the existing "reversible" line + a small "Deactivating SAML" subsection. Other sections (IdP configs, hardening defaults, troubleshooting, audit) stay byte-identical.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cross-repo checkout in GH Actions | Custom `git clone` shell command | `actions/checkout@v4` with `repository:` + `token:` | Handles auth, ref tracking, depth, submodules |
| Pytest fixture for "overlay registered" | New fixture from scratch | Existing `saml_overlay_registered` (`backend/tests/conftest.py:454-484`) | Already implements save/restore semantics correctly |
| ORM access to deferred columns | Raw SQL bypassing the ORM | `select(OAuthProvider).options(undefer_group("saml"))` (existing pattern) | [VERIFIED: geolens-enterprise/geolens_enterprise/auth/saml/router.py:14,58] Same pattern the SAML router uses |
| Edition state mutation in test | Direct `_info` assignment | `init_edition([])` / `init_edition(["enterprise"])` | Public API, used by `test_saml_overlay.py:239` already |
| Multi-head alembic discovery | Custom `version_locations` mutation | Existing `geolens.migrations` entry-point group + conftest discovery | [VERIFIED: backend/tests/conftest.py:113-139] Already wired |
| SAML provider seeding in tests | Hand-built ORM object | Existing `_seed_saml_provider()` helper from `test_saml_overlay.py:96-137` | Includes encrypt_secret() for cert, slug placeholder, sane defaults — copy or import |

**Key insight:** Phase 220 is almost entirely doc + 1 test + 1 CI tweak — the test reuses every existing fixture and pattern. The risk is over-engineering the test or the CI; the planner should default to "smallest possible diff" for both.

## Runtime State Inventory

> Phase 220 is partially a refactor of mental model (saml.md framing) plus new test infrastructure. The "rename" lens applies to documentation framing, not code identifiers.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — Phase 220 does NOT migrate or rename any DB rows. The lifecycle test seeds throwaway SAML data and relies on conftest teardown. | None |
| Live service config | None — no n8n / Datadog / Tailscale / Cloudflare touchpoints. CI is the only "live service config" affected, and the change is in `.github/workflows/ci.yml` (in git). | Amend `.github/workflows/ci.yml` |
| OS-registered state | None — no OS-level registrations involve the SAML lifecycle. | None |
| Secrets/env vars | New CI secret `GEOLENS_ENTERPRISE_TOKEN` (PAT for private-repo checkout). Code does NOT read this — only the workflow does. | Add secret in GitHub repo settings; document in runbook how operator-side `GEOLENS_ENTERPRISE_PATH` env var relates (read-only ref to existing var, no rename) |
| Build artifacts / installed packages | None — no pip egg-info / Docker image tag / npm global install touched. The CI install of `geolens-enterprise` is fresh per job, no caching considered for v13.2. | None |

**The canonical question:** *After every file in the repo is updated, what runtime systems still have the old framing cached?* Answer: docs.getgeolens.com (the marketing/docs site) — see Pitfall 1 below.

## Common Pitfalls

### Pitfall 1: Most `docs/*.md` files are stub redirects to docs.getgeolens.com

**What goes wrong:** Planner picks `docs/upgrade-guide.md` or `docs/install-guide.md` as a "style reference" and discovers it's a 3-line redirect with no operator content.

**Why it happens:** [VERIFIED: read of `docs/upgrade-guide.md`, `docs/install-guide.md`, `docs/admin-guide.md`, `docs/cloud-deployment.md`, `docs/configuration-reference.md`] On 2026-04-26, substantive operator docs were relocated to the `getgeolens.com` repo's docs site. The local `docs/*.md` stubs remain as compatibility breadcrumbs only. The ONLY substantive doc still in this repo's `docs/` is `docs/saml.md` (Phase 217 carry-over) and `docs/DESIGN-GUIDE.md`.

**How to avoid:** Use `docs/saml.md` as the style reference for the new runbooks. Tone: operator-direct, code-block-heavy, occasional `> **Pitfall:**` callouts, tables for matrix-shaped content.

**Warning signs:** Planner cites `docs/upgrade-guide.md` for tone — flag this. The new runbooks `docs/edition-deactivation.md` and `docs/edition-reactivation.md` will be substantive, not stubs (since they're net-new operator content not yet on the docs site).

**Open question for planner:** Should Phase 220 simultaneously add corresponding pages to the `getgeolens.com` docs site? This is a cross-repo concern. CONTEXT.md does not address it. Recommend deferring to a follow-up cross-repo task; Phase 220 ships in this repo only.

### Pitfall 2: `_extensions.clear()` does NOT clear `app.core.edition._info`

**What goes wrong:** Test clears `_extensions` and `_routers` but doesn't re-call `init_edition()`. `is_enterprise()` keeps returning True from the cached `EditionInfo(edition='enterprise', features=...)` set during seed. Test fails with confusing assertion mismatch.

**Why it happens:** [VERIFIED: backend/app/core/edition.py:16,27,43-47] `_info` is a separate module-level singleton. `init_edition()` writes to it; `get_edition()` reads it; nothing else mutates it. Clearing the extensions registry does NOT touch `_info`.

**How to avoid:** The test MUST call `init_edition([])` AFTER clearing `_extensions` / `_routers`. Three module-level state surfaces, three explicit resets:

```python
_extensions.clear()
_routers.clear()
edition_mod.init_edition([])    # <-- DON'T forget this
```

**Warning signs:** `is_enterprise()` returns True after the clear — that's the symptom.

### Pitfall 3: SAML router has its own module-level state that the test doesn't need to clear

**What goes wrong:** Planner over-clears, attempts to reset `saml_router_mod._outstanding_requests` and `replay_cache._seen` (as `test_saml_overlay.py:239-248` does for SAML flow tests), gets confused when the lifecycle test doesn't need them.

**Why it happens:** [VERIFIED: backend/tests/test_saml_overlay.py:239-248] Those resets are needed for SAML ACS replay tests (the flow tests). The lifecycle test does NOT exercise SAML auth flow — it just verifies data preservation after registry clear. Those caches don't affect the assertion.

**How to avoid:** Keep the lifecycle test focused on the 3 module-level surfaces named in Pitfall 2. SAML's internal caches are out of scope.

### Pitfall 4: `e002.downgrade()` deletes `oauth_accounts` SAML rows BEFORE dropping columns

**What goes wrong:** Operator runs `alembic downgrade -1` thinking only the columns get dropped, doesn't realize the SQL `DELETE FROM catalog.oauth_accounts WHERE provider_id IN (...saml...)` runs first.

**Why it happens:** [VERIFIED: ~/Code/geolens-enterprise/geolens_enterprise/migrations/versions/e002_add_saml_columns.py:60-84] `downgrade()` body, in order:
1. `DELETE FROM catalog.oauth_accounts WHERE provider_id IN (SELECT id FROM catalog.oauth_providers WHERE provider_type = 'saml')`
2. `DELETE FROM catalog.oauth_providers WHERE provider_type = 'saml'`
3. `op.drop_constraint("chk_oauth_providers_type", ...)` — drops the relaxed CHECK
4. `op.create_check_constraint("chk_oauth_providers_type", ..., "provider_type IN ('oidc', 'google', 'microsoft')")` — re-tightens
5. `op.drop_column("oauth_providers", "sp_entity_id", ...)` (and 3 more)

**How to avoid:** The runbook's destructive-path section MUST enumerate ALL data deleted, not just the columns. Mandatory `pg_dump` step covers all three tables touched: `oauth_providers`, `oauth_accounts`, `users`.

**Warning signs:** Runbook says "drops the columns" without mentioning the row deletes — incomplete description.

### Pitfall 5: `users` table is NOT touched by `e002.downgrade()`, despite REQUIREMENTS.md claiming SAML columns are on `User`

**What goes wrong:** Test or doc author tries to assert SAML data on `users` rows, finds nothing, gets confused about LIFECYCLE-04 wording.

**Why it happens:** [VERIFIED: ~/Code/geolens-enterprise/geolens_enterprise/migrations/versions/e002_add_saml_columns.py + backend/app/modules/auth/oauth/models.py:67-78] All 4 SAML columns are on `catalog.oauth_providers`, NOT on `users`. SAML users get `auth_provider='oauth'` (Phase 217 D-04) and link via `oauth_accounts`. The User table has no SAML-specific columns. REQUIREMENTS.md LIFECYCLE-04 wording ("4 `deferred=True` User columns") is imprecise — flagged in CONTEXT.md Claude's Discretion.

**How to avoid:** Test asserts on `oauth_providers` (4 deferred columns + provider row) + `oauth_accounts` (linkage row) + `users` (auth_provider='oauth', no SAML-specific columns). REQUIREMENTS.md amendment fixes the wording in passing.

**Warning signs:** Test comment or assertion mentions "SAML columns on users table" — that's the symptom.

### Pitfall 6: Fork PRs cannot access `secrets.GEOLENS_ENTERPRISE_TOKEN`

**What goes wrong:** External contributor opens a PR; lifecycle test job fails because checkout of `geolens-enterprise` returns 404 (no token).

**Why it happens:** [CITED: docs.github.com Actions secrets policy] By default, secrets are not available to workflow runs triggered from a fork. The PAT cannot be read; checkout of the private repo fails authentication.

**How to avoid:** Gate the second checkout step with `if: ${{ secrets.GEOLENS_ENTERPRISE_TOKEN != '' }}` (the secret is missing in the runner-side env when not provided, so the conditional evaluates falsy). Combine with conditional pytest invocation that adds `-m 'not lifecycle'` when the overlay isn't installed.

**Warning signs:** Fork PR shows "Backend Tests: failed" with HTTP 404 in checkout step — that's the symptom. Solution: skip cleanly with a "lifecycle test skipped on fork PRs" log line so OSS contributors aren't confused.

### Pitfall 7: Adding `lifecycle` to `addopts = "-m 'not perf'"` deselect list

**What goes wrong:** Planner over-symmetrizes with `perf` marker pattern, adds `not lifecycle` to the deselect list. Lifecycle test stops running in normal `pytest` invocation; CI passes but lifecycle is silently uncovered.

**Why it happens:** [VERIFIED: backend/pyproject.toml:70] `addopts = "-m 'not perf'"` excludes `perf`-marked tests by default. Lifecycle is intended to run by default (CONTEXT.md "Established Patterns"); only `perf` is heavy enough to need opt-out.

**How to avoid:** Lifecycle marker registration in `markers` list ONLY. Do NOT touch `addopts`. Pytest invocation in CI runs `-m 'not perf'` which still includes lifecycle.

**Warning signs:** PR diff shows `addopts = "-m 'not perf and not lifecycle'"` — that's the bug.

### Pitfall 8: Test assertion on `app.routes` is fragile

**What goes wrong:** Planner picks `assert no_route_matches('/auth/saml')` as the post-clear assertion; FastAPI's app instance is process-wide and Phase 217 `saml_router_mounted` fixture's teardown leaves residue.

**Why it happens:** [VERIFIED: backend/tests/test_saml_overlay.py:177-182] `_unmount_saml_router()` rewrites `app.router.routes` in place. Test order matters; if a SAML test runs before the lifecycle test, the route may already be absent before any clearing. Inverting that — if a SAML test runs after — also creates ordering coupling.

**How to avoid:** Per CONTEXT.md "Claude's Discretion" recommendation: SQL-only assertions are sufficient for LIFECYCLE-04. The route-404 assertion is belt-and-braces; if included, use a fresh TestClient instance OR explicitly assert `app.router.routes` does not contain `/auth/saml/{slug}/login` after the clear. Don't rely on test-order side effects.

**Warning signs:** Test passes when run alone but fails when run after `test_saml_overlay.py` — that's the symptom.

## Code Examples

### Test Setup — Seeding SAML Data with Overlay Registered

```python
# Source: pattern from backend/tests/test_saml_overlay.py:96-137 (_seed_saml_provider)
from app.modules.auth.oauth.encryption import encrypt_secret
from app.modules.auth.oauth.models import OAuthProvider, OAuthAccount
from app.modules.auth.models import User

provider = OAuthProvider(
    slug="lifecycle-test",
    display_name="Lifecycle Test IdP",
    provider_type="saml",
    client_id="unused",                                # NOT-NULL placeholder
    client_secret_encrypted=encrypt_secret("unused"),  # NOT-NULL placeholder
    idp_entity_id="https://idp.test/entity",
    idp_sso_url="https://idp.test/sso",
    idp_certificate=encrypt_secret("-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----"),
    sp_entity_id="https://geolens.test/auth/saml/lifecycle-test",
    enabled=True,
)
test_db_session.add(provider)
await test_db_session.commit()
await test_db_session.refresh(provider)
```

### Querying Deferred SAML Columns Post-Deactivation

```python
# Source: geolens-enterprise/geolens_enterprise/auth/saml/router.py:55-61
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

Alternative (raw SQL — useful if ORM-state weirdness post-clear surfaces):
```python
from sqlalchemy import text

result = await test_db_session.execute(
    text(
        "SELECT idp_entity_id, idp_sso_url, idp_certificate, sp_entity_id "
        "FROM catalog.oauth_providers WHERE id = :id"
    ),
    {"id": seeded_id},
)
row = result.one()
assert row.idp_entity_id == "https://idp.test/entity"
```

### Pytest Marker Registration

```toml
# backend/pyproject.toml — extend the markers list
markers = [
    "perf: performance regression tests (deselected by default)",
    "requires_ogr2ogr: tests that invoke ogr2ogr and need build_pg_conn_str redirected to the test database (K2-PRE; fixture lives in tests/conftest.py)",
    "architecture: layering and boundary tests; opt-out locally with `-m 'not architecture'` (Phase 212 LAYER-01 guard)",
    "lifecycle: edition deactivation/reactivation tests requiring enterprise overlay (Phase 220 LIFECYCLE-04)",
]
```

### Edition Re-Initialization

```python
# Source: backend/tests/test_saml_overlay.py:239 (existing pattern)
import app.core.edition as edition_mod

# Save before flipping (allows test teardown to restore other tests' assumptions)
saved_info = edition_mod._info

# Flip to enterprise for seed phase
edition_mod.init_edition(["enterprise"])
# ... seed SAML data ...

# Flip to community for assertion phase
edition_mod.init_edition([])    # empty list → auto-detect community

# Teardown
edition_mod._info = saved_info
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `docs/saml.md` framing: "alembic downgrade -1 is reversible, back up first" | Targeted retargeting: "alembic downgrade -1 is destructive; primary deactivation is overlay-removal — see edition-deactivation.md" | Phase 220 (this phase) | Operators no longer pointed at the destructive path as primary |
| Edition deactivation = mental model only (no test) | Pytest marker `lifecycle` + integration test verifying data persistence | Phase 220 (this phase) | Behavioral guarantee, not just docs |
| `geolens-enterprise` not in CI test path | CI installs overlay via `uv add --editable` before backend test job | Phase 220 (this phase) | Existing `test_saml_overlay.py` and enterprise repo's tests gain CI coverage as a side benefit |
| Most `docs/*.md` are substantive operator docs | Most `docs/*.md` are 3-line stubs redirecting to docs.getgeolens.com | 2026-04-26 (cross-repo split) | Style references must use `docs/saml.md`; new docs ship in this repo only |

**Deprecated/outdated:**
- The `2026_04_08_0001-strip_dead_saml_code.py` migration deleted SAML support before Phase 217 added it back via the enterprise overlay. References to "SAML never worked" in commit history pre-Phase-217 are correct historically but obsoleted by `e002_add_saml_columns`.

## Assumptions Log

> Claims tagged `[ASSUMED]` in this research that need user/planner confirmation before becoming locked.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Recommended GitHub Actions secret name `GEOLENS_ENTERPRISE_TOKEN` (PAT) | Pattern 3 | Low — naming bikeshed; planner can pick another. Functionally identical |
| A2 | The PAT-vs-deploy-key tradeoff favors PAT for solo-account simplicity | Standard Stack: Alternatives | Low — both work; deploy key is structurally cleaner if user prefers it |
| A3 | Reactivation runbook should be thin (½ page) referencing existing activation docs | Claude's Discretion | Low — planner's call; user feedback can adjust |
| A4 | The data-fate matrix lives near the top of `docs/edition-deactivation.md` | Claude's Discretion | Low — placement is style |
| A5 | REQUIREMENTS.md / ROADMAP.md text-precision fix ("User columns" → "oauth_providers columns") happens silently as part of Phase 220's docs work | Claude's Discretion | Medium — if user prefers explicit doc-only commit, that's just a sequencing choice for the planner |
| A6 | No corresponding update to `getgeolens.com` docs site is required in Phase 220 | Pitfall 1 — Open question | Medium — if user wants cross-repo sync, it's a follow-up task; Phase 220 in `geolens` repo stands alone |
| A7 | `secrets.X != ''` semantics (empty string when secret unavailable on fork PR) is correct | Pitfall 6 | Medium — alternative is `github.event.pull_request.head.repo.fork == false`; both work, latter is more explicit |
| A8 | Lifecycle marker is included in default pytest run (NOT added to `addopts` deselect list) | Pitfall 7 | Low — CONTEXT.md Established Patterns is explicit; this is verification not a new assumption |

## Open Questions

1. **Cross-repo docs.getgeolens.com sync — does Phase 220 update the marketing/docs site?**
   - What we know: `docs/*.md` in this repo are mostly redirect stubs; substantive operator docs live in `getgeolens.com` repo (cross-repo split 2026-04-26).
   - What's unclear: Whether the new runbooks should also be authored on docs.getgeolens.com simultaneously.
   - Recommendation: defer to a follow-up cross-repo task. Phase 220 ships authoritative content in this repo's `docs/` (operator can consume it directly); marketing-site sync is a planner decision but probably out of v13.2 scope.

2. **PAT scope and rotation policy for `GEOLENS_ENTERPRISE_TOKEN`** — what permissions, what expiry?
   - What we know: PAT must have read access to `geolens-enterprise` repo.
   - What's unclear: Fine-grained PAT vs. classic; lifetime; rotation cadence.
   - Recommendation: fine-grained PAT scoped to `geolens-enterprise` content:read, 1-year expiry, document the rotation procedure inline in `.github/workflows/ci.yml` as a comment. Planner picks final shape.

3. **Should the runbook mention worker-entrypoint deactivation symmetry?**
   - What we know: [VERIFIED: backend/scripts/worker-entrypoint.sh:42-55] Worker entrypoint mirrors api-entrypoint's enterprise install logic. CONTEXT.md notes "both must be deactivated symmetrically."
   - What's unclear: Whether to surface this as a separate runbook step or fold it into the docker-compose-down step.
   - Recommendation: brief mention in the runbook ("worker container also receives the overlay; `docker compose down` removes both"); detailed enumeration is over-engineering since the compose file is the single source of truth.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| pytest | Test suite | ✓ | >=9.0.3 | — |
| pytest-asyncio | Async test runner | ✓ | (dev dep) | — |
| SQLAlchemy `deferred_group` semantic | OAuthProvider model | ✓ | 2.0.25+ | — |
| `geolens-enterprise` (sibling repo) | Lifecycle test seed phase + CI install | ✓ | 0.1.0 (filesystem at `~/Code/geolens-enterprise`) | None — required |
| `actions/checkout@v4` | CI cross-repo checkout | ✓ | v4 | — |
| GitHub PAT for private repo | CI checkout of `geolens-enterprise` | ✗ (must be added to repo secrets) | — | Skip lifecycle test on PRs without secret |
| `pg_dump` (CLI) | Operator pre-step on destructive path | ✓ in standard postgres install | — | None — operator concern, not CI |

**Missing dependencies with no fallback:**
- `secrets.GEOLENS_ENTERPRISE_TOKEN` — must be added to GitHub repo settings for `main` branch / project-member PR runs

**Missing dependencies with fallback:**
- Fork PRs without the secret — gracefully skip lifecycle test via `if:` gate

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3+ with anyio_mode=auto, asyncio_mode=strict |
| Config file | `backend/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `cd backend && uv run pytest tests/test_lifecycle.py -v` |
| Full suite command | `cd backend && uv run pytest -v -m 'not perf' --cov=app --cov-fail-under=58.5` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LIFECYCLE-01 | docs/edition-deactivation.md exists with required sections | grep / doc-content check (manual or scripted) | `test -f docs/edition-deactivation.md && grep -q 'pre-flight' docs/edition-deactivation.md` | ❌ Wave 0 (doc) |
| LIFECYCLE-02 | docs/edition-reactivation.md exists with verification checklist | grep / doc-content check | `test -f docs/edition-reactivation.md && grep -q 'verify' docs/edition-reactivation.md` | ❌ Wave 0 (doc) |
| LIFECYCLE-03 | docs/saml.md no longer presents `alembic downgrade -1` as primary | grep negative check | `! grep -E 'reversible.*alembic downgrade' docs/saml.md && grep -q 'edition-deactivation.md' docs/saml.md` | ❌ Wave 0 (doc edit) |
| LIFECYCLE-04 | Disabling overlay preserves SAML data | unit/integration test | `pytest tests/test_lifecycle.py::test_overlay_removal_preserves_saml_data -x -m lifecycle` | ❌ Wave 0 (test) |
| LIFECYCLE-05 | docs/edition-deactivation.md documents destructive path with mandatory pg_dump | grep check | `grep -q 'pg_dump' docs/edition-deactivation.md && grep -q -i 'destructive' docs/edition-deactivation.md` | ❌ Wave 0 (doc) |

### Sampling Rate
- **Per task commit:** `pytest tests/test_lifecycle.py -v` (single test file, ~1-2s)
- **Per wave merge:** `pytest -v -m 'not perf'` (full backend suite; lifecycle marker included since it's not deselected)
- **Phase gate:** Full suite green + grep-verifiable doc assertions all pass before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `backend/tests/test_lifecycle.py` — covers LIFECYCLE-04
- [ ] `backend/pyproject.toml` `markers` list — adds `lifecycle` marker (1-line edit, technically a code change but trivial)
- [ ] `docs/edition-deactivation.md` — covers LIFECYCLE-01, LIFECYCLE-05
- [ ] `docs/edition-reactivation.md` — covers LIFECYCLE-02
- [ ] `docs/saml.md` Installation section — covers LIFECYCLE-03 (targeted edit)
- [ ] `.github/workflows/ci.yml` — overlay install + fork-PR gating (enables LIFECYCLE-04 in CI)
- [ ] No framework install needed — all dependencies present

### Concrete Measurement Points (for VALIDATION.md synthesis)

**Doc-content greps (LIFECYCLE-01, 02, 03, 05 — verifiable assertions):**
```bash
# LIFECYCLE-01: deactivation runbook covers pre-flight, snapshot, sequence, env-var defense-in-depth
test -f docs/edition-deactivation.md
grep -q -i 'pre-flight' docs/edition-deactivation.md
grep -q -i 'pg_dump' docs/edition-deactivation.md
grep -q -i 'oauth_providers' docs/edition-deactivation.md
grep -q -i 'docker compose down' docs/edition-deactivation.md
grep -q 'GEOLENS_EDITION' docs/edition-deactivation.md
grep -q -i 'defense.in.depth\|defense-in-depth' docs/edition-deactivation.md

# LIFECYCLE-02: reactivation runbook exists + post-reactivation verify section
test -f docs/edition-reactivation.md
grep -q -i 'verify\|verification' docs/edition-reactivation.md
grep -q '/auth/saml' docs/edition-reactivation.md

# LIFECYCLE-03: saml.md retargeted (negative + positive checks)
# Negative: legacy "reversible alembic downgrade" framing GONE
! grep -E 'migration is reversible.*alembic downgrade' docs/saml.md
# Positive: cross-link to edition-deactivation present
grep -q 'edition-deactivation.md' docs/saml.md
# Positive: destructive labeling present
grep -q -i 'destructive' docs/saml.md

# LIFECYCLE-05: destructive path explicitly documented + mandatory pg_dump
grep -q -i 'destructive' docs/edition-deactivation.md
grep -q 'pg_dump' docs/edition-deactivation.md
grep -q -i 'mandatory\|required' docs/edition-deactivation.md

# Cross-link symmetry
grep -q 'edition-reactivation' docs/edition-deactivation.md
grep -q 'edition-deactivation' docs/edition-reactivation.md
grep -q 'edition-deactivation' docs/saml.md
```

**Test execution checks (LIFECYCLE-04 — behavioral assertions):**
```bash
# Marker registered
grep -q '"lifecycle:' backend/pyproject.toml

# Test file exists, runs cleanly
cd backend && uv run pytest tests/test_lifecycle.py -v -m lifecycle
# Expected output: "test_overlay_removal_preserves_saml_data PASSED"

# Test asserts all 5 schema-state preconditions:
#   1. oauth_providers row with provider_type='saml' present
#   2. All 4 deferred columns (idp_entity_id, idp_sso_url, idp_certificate, sp_entity_id) populated
#   3. oauth_accounts row linking provider→user present
#   4. users row with auth_provider='oauth' present
#   5. is_enterprise() returns False; default extension classes returned
```

**CI integration check:**
```bash
# Workflow amended
grep -q 'geolens-enterprise' .github/workflows/ci.yml
grep -q 'GEOLENS_ENTERPRISE_TOKEN\|secrets.GEOLENS' .github/workflows/ci.yml
grep -q 'fork == false\|secrets.*!= .' .github/workflows/ci.yml
```

**Schema-state checks (after lifecycle test runs in CI):**
- 4 SAML columns physically present in test DB schema (verifiable via `\d catalog.oauth_providers` in psql, automated via `information_schema.columns` query)
- Provider row, account row, user row all retain integrity post-clear

**Negative checks (LIFECYCLE-03 must-not-have):**
- `docs/saml.md` no longer matches the regex `reversible.*alembic downgrade` (the legacy line)
- `docs/saml.md` no longer presents alembic as "the" deactivation path (link to runbook required)

## Project Constraints (from CLAUDE.md)

- **Version control:** Never indicate AI/Bot activity in commit messages.
- **Code style:** Prefer simple, readable code over clever abstractions; follow existing project conventions.
- **Communication:** Be direct and concise; skip preamble.
- **Project context (from MEMORY.md):** Backend FastAPI + PostGIS; v13.2 in progress (Phase 220-221); v13.1 SAML implementation is ground truth.
- **No emojis in committed files** (per global communication rule).
- **Project-specific:** [VERIFIED: feedback_no_blanket_add_planning.md] Don't `git add -fA .planning/<dir>/`; add files individually.
- **Project-specific:** [VERIFIED: feedback_ci_local_first.md] Run lint/typecheck/tests locally before pushing — relevant when developing the lifecycle test.

## Sources

### Primary (HIGH confidence)
- [VERIFIED: backend/app/core/edition.py] — `_info` singleton, `init_edition()`, `get_edition()`, `is_enterprise()`
- [VERIFIED: backend/app/platform/extensions/__init__.py] — `_extensions`, `_routers`, `_loaded` module state; typed accessors do NOT consult `is_enterprise()`
- [VERIFIED: backend/app/platform/extensions/defaults.py] — `DefaultAuditExtension`, `DefaultBrandingExtension`, `DefaultAuthExtension`, `DefaultIdentityExtension`
- [VERIFIED: backend/app/platform/extensions/guards.py] — `require_enterprise()` raises 404 (not 403)
- [VERIFIED: backend/app/api/main.py:122-135] — startup chain (load_extensions → init_edition → mount routers)
- [VERIFIED: backend/app/modules/auth/oauth/models.py:67-78] — 4 SAML columns with `deferred=True, deferred_group="saml"`
- [VERIFIED: backend/pyproject.toml:71-75] — pytest markers list pattern
- [VERIFIED: backend/tests/conftest.py:454-484] — `saml_overlay_registered` fixture (registry save/restore pattern)
- [VERIFIED: backend/tests/conftest.py:113-176] — multi-head alembic discovery + SAML column bridge for community-only test runs
- [VERIFIED: backend/tests/test_saml_overlay.py:96-137] — `_seed_saml_provider()` helper
- [VERIFIED: backend/tests/test_saml_overlay.py:239] — `init_edition(["enterprise"])` precedent
- [VERIFIED: ~/Code/geolens-enterprise/geolens_enterprise/__init__.py] — `register_extensions()` populates registry under `auth`, `identity`, `audit`, `branding`, `_routers`
- [VERIFIED: ~/Code/geolens-enterprise/geolens_enterprise/migrations/versions/e002_add_saml_columns.py] — exact upgrade/downgrade behavior including row deletes
- [VERIFIED: ~/Code/geolens-enterprise/geolens_enterprise/auth/saml/router.py:14,55-61] — `undefer_group("saml")` pattern in production code
- [VERIFIED: docs/saml.md:32-58] — Installation section structure + the exact "reversible" line to retarget
- [VERIFIED: docker-compose.enterprise.yml] — overlay activation contract
- [VERIFIED: backend/scripts/api-entrypoint.sh:46-58] — runtime overlay install conditional
- [VERIFIED: backend/scripts/worker-entrypoint.sh:42-55] — worker mirror of api-entrypoint
- [VERIFIED: .github/workflows/ci.yml] — current backend-test job structure (lines 219-312)
- [VERIFIED: .planning/phases/220-lifecycle-runbooks-and-preservation/220-CONTEXT.md] — locked decisions D-01..D-07
- [VERIFIED: .planning/REQUIREMENTS.md] — LIFECYCLE-01..05 text + traceability
- [VERIFIED: .planning/ROADMAP.md] — Phase 220 5 success criteria

### Secondary (MEDIUM confidence)
- [CITED: github.com/actions/checkout README] — private-repo checkout requires PAT; fork-PR secret unavailability is documented behavior
- [CITED: docs.github.com Actions secrets policy] — fork PRs cannot access repo secrets by default

### Tertiary (LOW confidence — none)
- No tertiary sources required; all claims trace to verified code or official documentation.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps; all referenced versions verified in pyproject.toml
- Architecture: HIGH — registry-clear simulation mechanism is verified by reading the 4 module-level state surfaces (`_extensions`, `_routers`, `_loaded`, `_info`) and confirming only 3 need explicit reset (`_loaded` is benign post-clear since it's just a "load was attempted" sentinel)
- Pitfalls: HIGH — every pitfall is grounded in verified code paths or explicit CONTEXT.md decisions; Pitfall 1 (docs stub redirects) is a verified surprise that the planner must not miss
- Documentation patterns: MEDIUM — only `docs/saml.md` available as substantive style reference; new runbooks are net-new content with no exact precedent
- CI gating strategy: MEDIUM — recommended approach (`secrets.X != ''` conditional) is widely-used GH Actions idiom but no in-repo precedent for cross-repo private-repo checkout exists

**Research date:** 2026-04-29
**Valid until:** 2026-05-29 (30 days — stable surface; no fast-moving dependencies. Re-verify if `geolens-enterprise` ships breaking changes to `e002` or registry shape.)
