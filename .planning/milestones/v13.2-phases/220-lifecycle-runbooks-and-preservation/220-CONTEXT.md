# Phase 220: lifecycle-runbooks-and-preservation - Context

**Gathered:** 2026-04-29
**Status:** Ready for planning

<domain>
## Phase Boundary

An operator running an enterprise GeoLens deployment can find authoritative runbooks in `docs/` that walk them through enterprise→community deactivation and back through community→enterprise reactivation, and a CI integration test (`pytest -m lifecycle`) proves the safe deactivation path preserves SAML provider rows + the 4 deferred SAML columns on `catalog.oauth_providers`. `docs/saml.md` no longer presents `alembic downgrade -1` as the primary deactivation path — it points at the runbook and labels the alembic path as destructive/opt-in.

Concretely after this phase:

- `docs/edition-deactivation.md` exists and walks the canonical path: stop loading the `geolens-enterprise` overlay (drop `docker-compose.enterprise.yml` from the compose stack OR `pip uninstall geolens-enterprise`) → restart → optionally set `GEOLENS_EDITION=community` as defense-in-depth. Includes a pre-flight checklist (audit SAML provider inventory, communicate to SAML users, snapshot of `catalog.oauth_providers` + `catalog.oauth_accounts` SAML rows) and a data-fate matrix (what survives the safe path vs. what `alembic downgrade -1` destroys, with the destructive path's mandatory data-export step).
- `docs/edition-reactivation.md` exists and walks the inverse path: re-mount/re-install the overlay → restart → confirm SAML routes mount and `oauth_providers` SAML rows are intact and usable.
- `docs/saml.md` Installation section gets a targeted edit: the existing "reversible (`alembic downgrade -1`)" line is rewritten to label that path as destructive/opt-in with a mandatory pre-export step, and points at `docs/edition-deactivation.md` as the primary path. A short "Deactivating SAML" subsection links the runbook from saml.md.
- A new pytest marker `lifecycle` is registered in `backend/pyproject.toml` (`markers` list). One backend integration test under `pytest -m lifecycle` exercises the registry-level deactivation simulation and asserts the safe path is non-destructive (`oauth_providers` SAML row + 4 deferred columns + `oauth_accounts` row all intact).
- The CI workflow (`.github/workflows/ci.yml`) installs the `geolens-enterprise` overlay before the backend test job so `e002_add_saml_columns` runs and the lifecycle test can seed real SAML data.

**In scope:** `docs/edition-deactivation.md`; `docs/edition-reactivation.md`; targeted edit to `docs/saml.md` Installation section; new `lifecycle` pytest marker registered in `backend/pyproject.toml`; one registry-level integration test under `backend/tests/` marked `@pytest.mark.lifecycle` that seeds SAML data → simulates overlay-not-loaded by clearing the extension registry → re-inits edition as community → asserts data persistence; CI amendment to install `geolens-enterprise` so `e002_add_saml_columns` is in the test DB; cross-link from `docs/saml.md` Installation section to the new runbook.

**Out of scope:** User-continuity re-onboarding procedure (Phase 221, LIFECYCLE-06); deactivate→reactivate round-trip symmetry test (Phase 221, LIFECYCLE-07); a non-destructive `e003` alembic downgrade (LIFECYCLE-05 resolved by documenting the destructive path with a mandatory export, not by adding a safe alembic path); generic edition lifecycle for non-SAML enterprise overlays (excluded per REQUIREMENTS.md OUT OF SCOPE table); `is_enterprise()` checks on the registry accessors (`get_audit_extension()` / `get_branding_extension()` — see Risk Surfaces below; tracked as a deferred backlog item, not Phase 220 work).

</domain>

<decisions>
## Implementation Decisions

### Deactivation operator sequence (LIFECYCLE-01)
- **D-01: Stop loading the overlay is the canonical deactivation lever; `GEOLENS_EDITION=community` is documented as defense-in-depth, not the primary switch.** The runbook prescribes:
  1. Snapshot the SAML state (SQL dump of `catalog.oauth_providers WHERE provider_type='saml'` + matching `catalog.oauth_accounts` rows + relevant `catalog.users` rows). This is the safety net before any change.
  2. Inventory live SAML usage (admin UI SAML SSO tab) and communicate the impending deactivation to SAML-authenticated users (re-onboarding procedure for those users is Phase 221's deliverable; runbook just says "see Phase 221 doc when shipped" with a TODO marker until then).
  3. Stop the enterprise stack: `docker compose down`, then restart without `-f docker-compose.enterprise.yml` (or `pip uninstall geolens-enterprise` for non-Docker deployments).
  4. Optional defense-in-depth: set `GEOLENS_EDITION=community` in the deployment env to make `is_enterprise()` always return False even if a stale overlay accidentally loads.
  5. Verify: `/auth/saml/*` routes return 404; admin UI no longer shows SAML SSO tab; backend logs show `edition=community` and an empty `features` list.
  6. Database state at this point: 4 SAML columns on `oauth_providers` are physically present (deferred=True keeps them off default queries), `oauth_providers` SAML rows are intact, `oauth_accounts` SAML rows are intact, SAML users' `auth_provider='oauth'` rows in `users` are intact. Reactivation is a clean re-mount.

  Rationale: `init_edition()` honors `GEOLENS_EDITION=community` even when extensions are loaded, BUT `register_extensions()` still runs and pollutes `registry['audit']` / `registry['branding']` with enterprise instances. `get_audit_extension()` and `get_branding_extension()` do NOT consult `is_enterprise()` — they return whatever's registered. So `GEOLENS_EDITION=community` alone leaves the audit-export and branding overlays silently active. Stopping the overlay at the entry-point discovery layer is the only complete deactivation. This is a real architectural finding from this discussion — see Risk Surfaces / D-08 for the deferred fix.

### LIFECYCLE-05 alembic decision
- **D-02: Document the destructive `alembic downgrade -1` path with a mandatory pre-export step. Do NOT add a non-destructive alembic path (no `e003_drop_saml_safe`).** Rationale: the safe deactivation path leaves the schema alone — `e002.downgrade()` is only needed for hard-license-expiry cleanup or a clean-DB audit requirement, which is rare. Carrying a second alembic path forever for a rare ops scenario isn't justified. The runbook makes the trade-off visible:
  > **Destructive path (`alembic downgrade -1`):** drops the 4 SAML columns on `oauth_providers`, re-tightens `chk_oauth_providers_type`, AND `DELETE`s `oauth_accounts` SAML rows + `oauth_providers` SAML rows (per `e002.downgrade()`). Use only when you need a clean schema (e.g., enterprise license has been permanently revoked AND your audit team requires no SAML data residue). **Mandatory pre-step:** `pg_dump --table catalog.oauth_providers --table catalog.oauth_accounts --table catalog.users` before running the alembic command. Without this dump, the deletion is unrecoverable.
- **D-03: `docs/saml.md` Installation section's current "reversible (`alembic downgrade -1`)" framing gets retargeted.** The existing line is rewritten to label `alembic downgrade -1` as destructive/opt-in, link to `docs/edition-deactivation.md` as the primary deactivation path, and surface the mandatory data-export prerequisite. saml.md gains a brief "Deactivating SAML" paragraph in the Installation section pointing at the runbook. No other rewrites to saml.md (other sections — IdP configuration, hardening defaults, troubleshooting — stay untouched).

### Integration test design (LIFECYCLE-04)
- **D-04: Registry-level simulation in a single pytest session.** The lifecycle test:
  1. Marker: `@pytest.mark.lifecycle`. New marker registered in `backend/pyproject.toml` (`markers` list — pattern matches existing `perf`, `requires_ogr2ogr`, `architecture` markers).
  2. Test runs against a DB that has `e002_add_saml_columns` applied (CI installs the enterprise overlay — D-06).
  3. Setup: seed an `OAuthProvider` row with `provider_type='saml'`, all 4 SAML columns populated; seed a matching `OAuthAccount` linkage row; seed a `User` with `auth_provider='oauth'` linked via `oauth_accounts`.
  4. Simulate overlay-not-loaded: clear the in-process extension registry — `_extensions.clear()`, `_routers.clear()`, `_loaded = True` (stays in the "load was performed but found nothing" state, which mirrors what happens when `entry_points(group="geolens.extensions")` returns an empty iterator). Re-call `init_edition([])` to flip the cached edition info to community.
  5. Assertions:
     - SQL: `SELECT idp_entity_id, idp_sso_url, idp_certificate, sp_entity_id FROM catalog.oauth_providers WHERE id = :seeded_id` returns the values set in step 3 (use `undefer_group("saml")` or raw text SQL since deferred=True keeps them off default queries).
     - SQL: the `oauth_accounts` row from step 3 is still present.
     - SQL: the `users` row is still present.
     - HTTP: `GET /auth/saml/{slug}/login` returns 404 (route not mounted because `_routers` is empty AND new app instance won't include it — easiest path: assert via TestClient that the route is absent from `app.routes` post-simulation, OR start a fresh TestClient app instance after the registry clear and exercise it).
     - Registry accessors: `get_audit_extension()` returns `DefaultAuditExtension`, `get_branding_extension()` returns `DefaultBrandingExtension`, `get_identity_extension()` returns `DefaultIdentityExtension`, `get_auth_extension()` returns `DefaultAuthExtension`.
     - `is_enterprise()` returns `False`.
  6. Teardown: standard pytest DB rollback. The test does NOT mutate alembic state (no upgrade/downgrade run mid-test). The 4 SAML columns remain physically present in the test DB after teardown — that's correct.
- **D-05: The lifecycle test lives in `backend/tests/test_lifecycle.py` (or extends an existing test file if a clean home exists at plan time).** It is part of the core repo's backend test suite — NOT in `geolens-enterprise/tests/`. Rationale: the test asserts behavior of the CORE deactivation path; the enterprise package merely provides the migration that puts the columns there. Phase 221's round-trip test (LIFECYCLE-07) likely lives next to it.
- **D-06: CI workflow (`.github/workflows/ci.yml`) is amended to install the `geolens-enterprise` overlay before the backend test job runs.** This means: (a) checkout `geolens-enterprise` alongside `geolens` (private repo — requires deploy key OR PAT secret in the GH Actions config), (b) `uv add --editable ./geolens-enterprise` in the backend job's setup step, (c) `alembic upgrade head` runs both the core and enterprise migration heads. Side benefit: the enterprise overlay's existing tests (`backend/tests/test_saml_overlay.py`, `~/Code/geolens-enterprise/tests/test_registration.py`) gain CI coverage too.

### Documentation structure (LIFECYCLE-01, LIFECYCLE-02, LIFECYCLE-03)
- **D-07: New runbooks ship as top-level `docs/edition-deactivation.md` + `docs/edition-reactivation.md`.** Consistent with existing top-level docs (`docs/upgrade-guide.md`, `docs/cloud-deployment.md`, `docs/saml.md`). No new `docs/lifecycle/` subdirectory. saml.md's edit is targeted (not a full rewrite of the Installation section); other sections of saml.md stay untouched. Cross-links: `docs/saml.md` Installation section → `docs/edition-deactivation.md` (mandatory per LIFECYCLE-03); `docs/edition-deactivation.md` → `docs/saml.md` (for IdP-side cleanup, e.g., disable the SAML app at the IdP after GeoLens-side deactivation); `docs/edition-deactivation.md` ↔ `docs/edition-reactivation.md`. Optional cross-links from `docs/admin-guide.md` and `docs/install-guide.md` if those docs already mention edition mode — Claude's discretion at plan time.

### Claude's Discretion
- **CI fork-PR access** — `geolens-enterprise` is a private repo. PRs from external forks can't access deploy keys or PAT secrets in GH Actions by default. Planner decides whether to: (a) gate the lifecycle test job behind a `secrets.GEOLENS_ENTERPRISE_TOKEN` availability check (`if: secrets.X != ''`), skipping for forks; (b) split the lifecycle test into a separate workflow that only runs on `pull_request_target` for trusted authors; (c) accept that lifecycle tests don't run on fork PRs and rely on push-to-main verification. Recommendation: option (a) — fork PRs see a "skipped" status, not a failure, and the lifecycle test is gated on `main` and on PRs from project members (where secrets are available).
- **Pre-flight checklist depth** — D-01 names the categories (snapshot, inventory, communicate, stop, verify). Planner picks exact wording, command examples, and SQL snippets. Use `docs/upgrade-guide.md` style as the reference for tone/format if it exists.
- **Where the data-fate matrix lives in the runbook** — likely a markdown table near the top of `docs/edition-deactivation.md`. Columns: data class (SAML provider rows, oauth_account links, user identities, audit log entries) × scenario (safe path / destructive path). Planner picks final shape.
- **Reactivation runbook depth** — LIFECYCLE-02 only requires walkthrough + confirmation that columns + rows survive. Could be short (½ page) since the operator already has the activation walkthrough in `docs/saml.md` and `docs/install-guide.md`. Planner decides whether `docs/edition-reactivation.md` is a thin "see install-guide.md, then verify checklist" doc, or a full re-walkthrough. Recommendation: thin — link to existing activation docs, focus on the post-reactivation verification checklist (SAML routes mount? audit-log shows e002 schema unchanged? existing SAML providers re-appear in admin UI? test login from the IdP succeeds?).
- **TestClient strategy for asserting `/auth/saml/*` returns 404 post-simulation** — planner picks: (a) start a second TestClient with a fresh FastAPI app after registry clear, (b) directly assert on `app.routes` membership, (c) other. Pure SQL assertions are sufficient to satisfy LIFECYCLE-04's literal text ("`oauth_providers` rows ... and the 4 `deferred=True` ... columns are intact"); the route-404 assertion is a belt-and-braces extra.
- **Requirements text precision** — REQUIREMENTS.md LIFECYCLE-04 + ROADMAP.md Phase 220 SC#4 say "the 4 `deferred=True` User columns" — they're actually on `OAuthProvider`, not `User`. (User table doesn't have SAML-specific columns; SAML users get `auth_provider='oauth'` and link via `oauth_accounts`.) Planner decides whether to silently fix the wording in REQUIREMENTS.md / ROADMAP.md as part of Phase 220's documentation work, or note in CONTEXT.md and leave the requirements text as-is. Recommendation: fix in REQUIREMENTS.md as a docs-only amendment (one commit, no scope expansion); CONTEXT.md and the runbook use the precise location ("`catalog.oauth_providers`").

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements / roadmap (the source of truth)
- `.planning/REQUIREMENTS.md` §LIFECYCLE-01..05 — the five requirements this phase closes. **Note text-precision issue:** LIFECYCLE-04 says "4 `deferred=True` User columns" — should read "on `catalog.oauth_providers`". See Claude's Discretion above.
- `.planning/ROADMAP.md` §Phase 220 — goal statement + 5 success criteria. Each SC is binding; SC#3 is what dictates the saml.md edit; SC#4 is the integration test contract; SC#5 is the LIFECYCLE-05 either/or that D-02 resolves toward "documented destructive."
- `.planning/STATE.md` — confirms milestone state, Phase 220 next; v13.1 close-gate verified.
- `.planning/PROJECT.md` — milestone overview.

### Project / state
- `.planning/milestones/v13.1-phases/217-auth-saml-enterprise/217-CONTEXT.md` — **most important upstream context.** Phase 217 is the implementation Phase 220 documents. D-01 (oauth_providers reuse), D-02 (e002 migration), D-04 (oauth_accounts linkage + auth_provider='oauth'), D-13 (single-class dual-Protocol), D-15 (hardening defaults) are all ground truth that Phase 220's runbook describes from the operator's view. Read in full before writing the runbook.
- `.planning/milestones/v13.1-ROADMAP.md` — for the v13.1 close-gate context that surfaced the lifecycle gap as backlog 999.7 (now promoted to v13.2).

### Code (what the runbook describes)
- `backend/app/core/edition.py` — `init_edition()`, `get_edition()`, `is_enterprise()`. The runbook describes the env-var override (`GEOLENS_EDITION=community`) at the level of "what this flag does and what it does NOT do." Note that `init_edition` is called once at startup with `loaded_extensions` from `list_extensions()`; the env-var override is consulted only at startup.
- `backend/app/platform/extensions/__init__.py` — `load_extensions()` discovers entry points; `_extensions` and `_routers` registries; typed accessors (`get_branding_extension()`, `get_audit_extension()`, `get_auth_extension()`, `get_identity_extension()`). **Critical:** typed accessors do NOT check `is_enterprise()`. They return whatever was registered. This is the architectural reason `GEOLENS_EDITION=community` alone is incomplete deactivation. The lifecycle test asserts these accessors return the defaults after registry clear.
- `backend/app/platform/extensions/guards.py` — `require_enterprise()` raises 404 when `is_enterprise()` is False. Applied to SAML router endpoints; correctly 404s SAML routes when env override is set, but doesn't gate the registry accessors.
- `backend/app/platform/extensions/defaults.py` — `DefaultAuditExtension`, `DefaultAuthExtension`, `DefaultBrandingExtension`, `DefaultIdentityExtension`. The lifecycle test asserts these are returned post-deactivation.
- `backend/app/api/main.py:125-135` — startup chain: `load_extensions()` → `init_edition(list_extensions())` → mount routers from `get_extension_routers()`. The runbook describes this chain in plain language for the operator's "what happens at startup" section.
- `backend/app/modules/auth/oauth/models.py:40-78` — `OAuthProvider` ORM. The 4 SAML columns at lines 67-78 with `deferred=True, deferred_group="saml"`. The runbook references the deferred behavior to explain why community deployments without `e002` applied still work, and why post-deactivation queries work without the columns being explicitly hidden.
- `backend/alembic/versions/2026_04_08_0001-strip_dead_saml_code.py` — community migration that DROPPED the 4 SAML columns on its way to community-clean schema. The runbook references this for context: "this migration represents what a clean-community schema looks like."

### Code (enterprise overlay — outside repo)
- `~/Code/geolens-enterprise/geolens_enterprise/__init__.py` — `register_extensions()` populates `registry['auth']`, `registry['identity']`, `registry['audit']`, `registry['branding']`, `registry['_routers']`. Runbook describes this in operator language.
- `~/Code/geolens-enterprise/geolens_enterprise/migrations/versions/e002_add_saml_columns.py` — adds the 4 SAML columns + relaxes `chk_oauth_providers_type`. Its `downgrade()` is destructive (DELETEs SAML rows + drops columns + tightens CHECK). The runbook quotes the destructive nature explicitly. Lifecycle test seeds against the schema this migration produces.
- `~/Code/geolens-enterprise/geolens_enterprise/migrations/versions/e001_enterprise_initial.py` — enterprise branch initial migration; `down_revision='0010_add_saml_provider_columns'`. Runbook references it briefly for the "enterprise alembic branch" mental model.
- `~/Code/geolens-enterprise/pyproject.toml` — `geolens.extensions` entry point declaration. Runbook quotes: "removing this package removes the entry point, which is what `load_extensions()` discovers; deactivation is structurally the inverse of activation."

### Code (compose / entrypoint — what the runbook prescribes)
- `docker-compose.enterprise.yml` — volume-mounts `../geolens-enterprise:/enterprise` and sets `GEOLENS_ENTERPRISE_PATH`. Runbook prescribes "drop this overlay file from your `docker compose` invocation to deactivate."
- `docker-compose.yml` — community baseline. Runbook describes "community = run with this file alone."
- `backend/scripts/api-entrypoint.sh:46-58` — checks `GEOLENS_ENTERPRISE_PATH` and runs `uv add --editable` if the directory exists with a `pyproject.toml`. This is the runtime install of the overlay. Runbook quotes the conditional so operators understand "no GEOLENS_ENTERPRISE_PATH = no overlay install = no entry point = community mode."
- `backend/scripts/worker-entrypoint.sh:45-...` — mirror of api-entrypoint for the worker process; runbook notes both must be deactivated symmetrically.

### Code (test scaffolding for the lifecycle test)
- `backend/pyproject.toml:71-75` — `[tool.pytest.ini_options]` `markers` list. Phase 220 adds `lifecycle: edition deactivation/reactivation tests requiring enterprise overlay (Phase 220 LIFECYCLE-04)` here.
- `backend/tests/conftest.py` — global pytest fixtures (DB session, app TestClient). Lifecycle test reuses the existing `db` fixture for seeding; needs to verify whether the existing fixtures pass the right kwargs to undefer the SAML group, or if the test needs a one-off `undefer_group("saml")` query helper.
- `backend/tests/test_saml_overlay.py` — existing tests of the SAML overlay (Phase 217 carry-over). Reference for how SAML provider rows are seeded in tests; the lifecycle test mirrors that pattern.
- `backend/tests/fixtures/saml/` — SAML test fixtures (XML responses, certs). Not directly used by the lifecycle test (no IdP roundtrip), but reference for seeding shape.

### CI
- `.github/workflows/ci.yml` — current CI workflow. Phase 220 amends the backend job to: (a) checkout `geolens-enterprise` (`actions/checkout@v4` with `repository:`, `token:`, `path:`), (b) `uv add --editable` the overlay before pytest. Planner picks the secret name (`GEOLENS_ENTERPRISE_TOKEN`?) and the fork-PR gating strategy.
- `.github/workflows/publish.yml`, `publish-cli.yml`, `publish-sdks.yml`, `release.yml` — adjacent workflows. Phase 220 does NOT touch these; lifecycle is a backend test concern.

### Existing docs (cross-link targets / style references)
- `docs/saml.md` — file the targeted edit lands in. Section to amend: "Installation" (lines 32-58 currently). Pattern to amend: the bullet that says "The migration is reversible (`alembic downgrade -1` removes the columns and re-tightens the CHECK), but downgrading destroys any SAML provider rows. Back up first." Replace with a labeled-destructive framing + a link to `docs/edition-deactivation.md`.
- `docs/install-guide.md` — referenced by saml.md for enterprise overlay setup. Phase 220 doesn't edit this file directly but the runbook may cross-link to it for the activation half of the lifecycle.
- `docs/admin-guide.md` — referenced by saml.md for audit log + RBAC. Phase 220 may add a brief cross-link from admin-guide if it discusses edition state — Claude's discretion.
- `docs/upgrade-guide.md` — style reference for the runbook tone (existing operator-facing doc).
- `docs/cloud-deployment.md` — style reference for ops-oriented procedural docs.
- `docs/configuration-reference.md` — `GEOLENS_EDITION` env var likely referenced here. Phase 220 verifies the entry exists; if not, considers adding it (or planner punts to Claude's discretion).

### CLAUDE.md operational notes
- `CLAUDE.md` (project-local + user-global) — confirms milestone status (v13.2 in progress, 2 phases, 220-221) and the v13.1 SAML implementation is "ground truth for v13.2." User memory has a sibling-repo audit feedback note (`feedback_audit_sibling_repos_at_milestone_close`) — relevant when Phase 220 ships, especially for the geolens-enterprise repo's lock-step with `e002`.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Pytest marker registration in `backend/pyproject.toml`** — existing markers (`perf`, `requires_ogr2ogr`, `architecture`) follow a clear pattern: name + colon + one-line description. `lifecycle` marker drops in alongside.
- **`OAuthProvider` ORM with `deferred=True, deferred_group="saml"`** — already designed for the Pitfall 11 case (community deployments lacking the columns physically). The lifecycle test exploits this design: the model class doesn't break post-deactivation; only explicit `provider.idp_entity_id` access (via `undefer_group` or attribute load) hits the column.
- **`is_enterprise()` + `init_edition()` + `_info` cached singleton in `backend/app/core/edition.py`** — easy to re-init within a test (`init_edition([])` flips the cache). No new abstraction needed.
- **`_extensions`, `_routers`, `_loaded` module-level state in `backend/app/platform/extensions/__init__.py`** — the extension registry is a flat module-level dict + list. Clearing it in a test is straightforward: `_extensions.clear(); _routers.clear()`. No new test hook needed.
- **`docker-compose.enterprise.yml` overlay pattern** — clean activation/deactivation contract: drop the overlay file, restart, no extension load. The runbook describes this from the operator's view; no code change to the compose surface.
- **`backend/scripts/api-entrypoint.sh` conditional install** — `if [ -d "${ENTERPRISE_PATH}" ] && [ -f "${ENTERPRISE_PATH}/pyproject.toml" ]; then uv add --editable ...`. Self-documenting deactivation contract: no path → no install → no entry point → no extension. Runbook quotes the conditional.
- **Existing pytest fixtures in `backend/tests/conftest.py`** — DB session, TestClient, async fixtures. Lifecycle test reuses them.
- **Phase 217 SAML test fixtures (`backend/tests/fixtures/saml/`)** — reference for how SAML provider rows + user rows are seeded in existing tests.
- **Existing `backend/tests/test_saml_overlay.py`** — Phase 217 carry-over. Pattern reference for the seed phase of the lifecycle test.

### Established Patterns
- **Top-level `docs/*.md`** — flat docs structure (no nesting beyond `docs/audits/` and `docs/images/`). New runbooks follow this convention.
- **Pytest marker + opt-out** — `addopts = "-m 'not perf'"` in `backend/pyproject.toml`. Existing pattern: heavy markers are deselected by default and explicitly selected with `-m`. Lifecycle test should NOT be deselected by default — it's a regular CI gate; just expose the marker for selective `-m lifecycle` runs.
- **Enterprise overlay = entry-point + volume mount** — Phase 217's whole architecture. Runbook describes this plainly so operators understand the lifecycle is mechanical (entry-point present/absent), not configurational.
- **Edition env-var override + auto-detect** — `init_edition()` honors explicit override, falls back to extension presence. Runbook describes both behaviors.

### Integration Points
- **`backend/app/api/main.py` startup chain** — `load_extensions()` → `init_edition()` → mount routers. The lifecycle test simulates "no extensions discovered" by clearing the registry between requests in-process; in production the operator achieves the same state by removing the package from the Python env.
- **CI workflow `.github/workflows/ci.yml`** — Phase 220 amends this to clone + install `geolens-enterprise`. New job step (or new job) before the existing pytest invocation. Planner decides job structure.
- **Audit log** — Phase 220 itself doesn't write to the audit log (docs + a test). But the runbook should mention "deactivation is not currently audit-logged at the platform level — operator-side change tickets are the audit trail" so operators don't expect a `lifecycle.deactivated` audit entry. Future deferred backlog: emit an audit-log entry on `init_edition()` transitions if the cached edition changes between starts.

### Risk surfaces
- **`get_audit_extension()` / `get_branding_extension()` / `get_auth_extension()` registry-accessor leak** — typed accessors return whatever's registered without consulting `is_enterprise()`. Implication: setting `GEOLENS_EDITION=community` alone (without removing the package) leaves the audit and branding overlays silently active. This is the architectural reason D-01 prescribes overlay-removal as canonical. **Not Phase 220's fix to make** — gating accessors by edition is a separate v13.2+ task. Runbook acknowledges this constraint as a documented limitation; Phase 220 also adds a deferred-idea entry below to track the structural fix.
- **Stale entrypoint state in container restart-without-rebuild** — the entrypoint runs `uv add --editable /enterprise` to register the overlay. If a container is restarted (not rebuilt) after the operator removes the volume mount, the previous container's writable layer may still hold the entry-point. Mitigation: runbook prescribes `docker compose down` (full container removal), not `docker compose restart`.
- **Fork-PR access to `geolens-enterprise`** — private repo; secrets aren't available in fork PR runs by default. Lifecycle test will need either a "skip if secrets unavailable" gate or a separate workflow trigger. Acceptable consequence: external contributor PRs don't run the lifecycle test; main-branch and trusted-author PRs do. Document the gating decision in CI workflow comments so OSS contributors aren't confused by skipped jobs.
- **Enterprise migration drift between this phase and v13.1's `e002`** — if `e002` changes after Phase 220 ships (new columns, schema tweaks), the lifecycle test's seed phase needs to keep up. Mitigation: lifecycle test uses ORM model fields (`OAuthProvider.idp_entity_id` etc.) for seed values, not raw column lists. Schema drift surfaces as a test failure on the next CI run, not a silent skip.
- **Reactivation runbook completeness vs. Phase 221 dependence** — Phase 220 ships the reactivation runbook (LIFECYCLE-02); Phase 221 ships the user re-onboarding procedure (LIFECYCLE-06) referenced from the deactivation runbook. Risk: deactivation runbook references a Phase 221 doc that doesn't exist yet. Mitigation: Phase 220 runbook includes a TODO marker pointing at "see `docs/edition-deactivation.md` Handling existing SAML users section (Phase 221)" with explicit "Phase 221 will land this section" annotation. When Phase 221 ships, that TODO turns into a real link.
- **`docs/saml.md` SC#3 strict literal compliance** — SC#3 says saml.md "no longer presents `alembic downgrade -1` as the primary deactivation path." Risk: a future doc edit re-introduces the framing. Mitigation: Phase 220 doesn't add a test for this (no doc-test infrastructure yet); rely on PR review + the cross-link from edition-deactivation.md as the structural reminder.
- **CI runtime cost** — installing `geolens-enterprise` adds ~30-60s to the backend test job (one-time `uv add --editable`). Acceptable cost for the lifecycle coverage; no caching considered for Phase 220 (planner can revisit if cost matters).

</code_context>

<specifics>
## Specific Ideas

- **Overlay-removal canonical, env var defense-in-depth** — D-01: the runbook does NOT recommend `GEOLENS_EDITION=community` alone. Stop loading the overlay first; set the env var only as a redundant safety. Rationale traced to the architectural finding that registry accessors don't gate by edition.
- **Document destructive, do NOT add a safe alembic path** — D-02: the safe deactivation IS "leave the schema alone." `alembic downgrade -1` exists; don't add `e003`. Runbook makes the destructive nature explicit + mandatory data export.
- **Targeted saml.md edit, not a rewrite** — D-03 + D-07: only the existing "reversible" framing in the Installation section gets retargeted; everything else in saml.md stays.
- **Top-level `docs/edition-*.md`** — D-07: no `docs/lifecycle/` subdir; consistency with existing top-level operator docs.
- **Registry-level test in single pytest session** — D-04: clear `_extensions` / `_routers` in-process to simulate overlay-not-loaded; assert SQL persistence + accessor defaults. Don't run docker-compose swap or apply alembic mid-test.
- **Enterprise overlay always installed in CI** — D-06: amend `.github/workflows/ci.yml` to install `geolens-enterprise` for the backend job. Side benefit: existing enterprise tests gain CI coverage too. Fork-PR gating is a planner subdecision (Claude's discretion).
- **Requirements text says "User columns" but they're on `oauth_providers`** — Claude's Discretion: planner amends REQUIREMENTS.md / ROADMAP.md text precision as part of Phase 220's docs work; CONTEXT.md and runbook use the precise location.

</specifics>

<deferred>
## Deferred Ideas

- **Gate registry accessors by edition** — `get_audit_extension()`, `get_branding_extension()`, `get_auth_extension()`, `get_identity_extension()` should check `is_enterprise()` and return the community default if False. This would make `GEOLENS_EDITION=community` a complete deactivation lever, not just a label. Out of Phase 220 scope (architecturally distinct from runbook + test work). Should land as a separate backlog phase before v13.2 closes if user prioritizes; otherwise file as v14+ backlog.
- **Audit-log entry on edition transitions** — emit an audit-log row when `init_edition()` detects the edition has changed since the last persisted state. Operationally useful (audit trail of activation/deactivation events). Out of Phase 220 scope — the runbook explicitly notes this absence as a current limitation.
- **`pre-flight check` CLI command** — `geolens admin lifecycle pre-deactivate` that runs the snapshot + inventory steps automatically (counts SAML providers, exports SAML rows, generates the operator's confirmation prompt). Out of Phase 220 scope — runbook is sufficient for v13.2; CLI tooling is a v14+ enhancement.
- **`docs/lifecycle/` directory** — if v14+ adds more lifecycle topics (tenant-scoping deactivation, SCIM provisioning lifecycle, etc.), revisit grouping these under `docs/lifecycle/`. Out of Phase 220 scope — single SAML lifecycle doesn't justify a subdirectory.
- **`pytest -m lifecycle` integration with docker-compose stack swap (truer fidelity)** — registry-level simulation in D-04 is the v13.2 deliverable; a docker-compose-level test that brings down the enterprise stack and brings up community against the same DB is a future hardening enhancement. Hybrid (registry-test in PR CI + nightly compose-test) is the natural progression.
- **Doc-test for SC#3** — automated check that `docs/saml.md` doesn't reintroduce "alembic downgrade -1 is reversible" framing. Out of Phase 220 scope — manual PR review is the v13.2 control.
- **Phase 221's deactivation→reactivation symmetry test placement** — likely co-located with Phase 220's lifecycle test (`backend/tests/test_lifecycle.py`). Phase 221 inherits the marker + the CI overlay install; just adds the reactivate phase + symmetry assertions on top of Phase 220's seed-and-deactivate path.

</deferred>

---

*Phase: 220-lifecycle-runbooks-and-preservation*
*Context gathered: 2026-04-29*
