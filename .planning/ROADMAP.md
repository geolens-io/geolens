# Roadmap: GeoLens v13.1 Open-Core Separation P1

**Milestone:** v13.1 Open-Core Separation P1
**Source spec:** `docs-internal/audits/oc-separation-deferred-items-20260426.md` (P1 bucket)
**Granularity:** standard
**Phase range:** 212–218 (continuing from v13.0 which ended at Phase 211)
**Coverage:** 21/21 v13.1 requirements mapped

## Milestone Goal

Close the six P1 boundary/seam debts surfaced in the open-core audit so the open-core architecture is demonstrably ship-ready before the first paid customer. Target audit grades: Boundary B → A−, Seam Quality C → B, OSS Surface D → C.

## Phases

- [x] **Phase 212: core-settings-decouple** — Break `core ↔ settings` layering inversion (`AppSetting` import in `core/persistent_config.py` + `core/public_urls.py`) (completed 2026-04-27)
- [x] **Phase 213: catalog-authz-relocate** — Move `auth/visibility.py` → `catalog/authorization.py`; migrate 23 inbound callers with no behavior change (completed 2026-04-27)
- [x] **Phase 214: identity-protocol-extract** — Define `IdentityProtocol` in `core/identity.py`; migrate 51 cross-domain `User` import sites; expose extension hook for custom identity backends (completed 2026-04-27)
- [x] **Phase 215: sdks-from-openapi** — Auto-generate Python + TypeScript SDKs from `backend/openapi.json` snapshot; publish to PyPI/npm; add `make sdks-check` CI drift gate (completed 2026-04-27)
- [ ] **Phase 216: geolens-cli-mvp** — Apache-2.0 `geolens` CLI on PyPI with `login`, `scan`, `publish`, `export stac` commands consuming the generated Python SDK
- [ ] **Phase 217: auth-saml-enterprise** — Reintroduce SAML cleanly as `geolens-enterprise` overlay using core's auth-extension hook; SP-initiated SSO with assertion validation, JIT provisioning, attribute → role mapping
- [ ] **Phase 218: oc-audit-close-v13.1** — Re-run `/oc-audit`; commit closing audit at `docs-internal/audits/oc-separation-audit-v13.1-close.md` showing Boundary ≥ A−, Seam Quality ≥ B, OSS Surface ≥ C

## Phase Details

### Phase 212: core-settings-decouple
**Goal**: `core/` no longer imports from `modules/settings/` — the layering inversion that violated the open-core boundary is gone, and downstream consumers (PersistentConfig, public URL builder) keep their existing behavior
**Depends on**: Nothing (mechanical refactor; can run in parallel with 213/214)
**Requirements**: LAYER-01
**Success Criteria** (what must be TRUE):
  1. `grep -rn "from app.modules.settings" backend/app/core/` returns zero `AppSetting` imports (and zero settings-module references generally)
  2. `PersistentConfig` continues to read/write DB-backed values; admin Settings UI loads and saves all 16 config instances correctly
  3. `core/public_urls.py` continues to resolve the public base URL with the same precedence (request → DB override → env var)
  4. The 1965-test backend baseline stays green; no test required AppSetting-import shimming
  5. The audit's "Layering" finding for `core/persistent_config.py:30` and `core/public_urls.py:14` no longer reproduces
**Plans:** 4/4 plans complete (verified 2026-04-26 + UAT 2026-04-27)

Plans:
- [x] 212-01-introduce-core-db-models-PLAN.md — Create new core/db/models.py with relocated AppSetting class (verbatim copy + docstring)
- [x] 212-02-migrate-callers-and-delete-old-PLAN.md — Migrate all 9 callers to app.core.db.models, update alembic/env.py, delete modules/settings/models.py
- [x] 212-03-architecture-guard-PLAN.md — Add backend/tests/test_layering.py guard + register architecture pytest marker
- [x] 212-04-phase-verification-gate-PLAN.md — Run alembic check + full pytest + ruff + ROADMAP SC verification gate

### Phase 213: catalog-authz-relocate
**Goal**: Dataset visibility / authorization logic lives under `catalog/authorization.py` where it belongs; `auth/` no longer owns catalog-domain knowledge
**Depends on**: Nothing (mechanical relocation; independent of 212)
**Requirements**: LAYER-02
**Success Criteria** (what must be TRUE):
  1. `backend/app/modules/auth/visibility.py` is deleted; all 15 direct visibility imports and 8 deferred-import call sites resolve to `catalog/authorization.py`
  2. RBAC-filtered search, tile, feature, STAC, and OGC Records endpoints return identical results for the same user/role pairs as before the relocation
  3. The 1965-test backend baseline stays green, including the visibility/authorization unit tests
  4. `git grep "auth.visibility\|from app.modules.auth.visibility"` returns zero matches across the whole repo
**Plans:** 4/4 plans complete

Plans:
- [x] 213-01-introduce-catalog-authorization-PLAN.md — Create new catalog/authorization.py (verbatim copy of auth/visibility.py with module docstring + DatasetGrant import promoted to module level)
- [x] 213-02-migrate-callers-and-delete-old-PLAN.md — Migrate all 26 import lines across 23 files to app.modules.catalog.authorization, delete auth/visibility.py, run full pytest for RBAC parity
- [x] 213-03-architecture-guard-PLAN.md — Extend backend/tests/test_layering.py with two new architecture guard tests + update module docstring (Phase 212 marker reused)
- [x] 213-04-phase-verification-gate-PLAN.md — Run alembic check + full pytest + ruff + ROADMAP SC#1-#4 verification gate

### Phase 214: identity-protocol-extract
**Goal**: Cross-domain code depends on an `IdentityProtocol` abstraction rather than the concrete `User` SQLAlchemy model, and the extension system can register alternate identity backends — unblocking enterprise auth overlays without modifying core
**Depends on**: Nothing (touches all 11 domains but is self-contained; prerequisite for Phase 217)
**Requirements**: IDENT-01, IDENT-02, IDENT-03
**Success Criteria** (what must be TRUE):
  1. `backend/app/core/identity.py` defines `IdentityProtocol` capturing the surface 51 cross-domain call sites depend on (id, email, role, tenant context, etc.); the concrete `User` ORM model satisfies it
  2. All 51 cross-domain `User` import sites across the 11 domains type against `IdentityProtocol` (or an alias of it), not the concrete SQLAlchemy class
  3. The extension system exposes a registration hook (typed accessor + entry_point seam, mirroring `get_branding_extension()` / `get_audit_extension()`) so an enterprise overlay can supply an alternate identity backend without core changes
  4. Existing JWT, OAuth/OIDC, API key, and refresh-token flows operate unchanged against the concrete model; the 1965-test backend baseline stays green
  5. `pyright`/`mypy` (per project convention) reports no new typing regressions introduced by the Protocol migration
**Plans:** 4/4 plans complete (2026-04-27 — all 5 ROADMAP SC verified PASS)

Plans:
- [x] 214-01-introduce-core-identity-PLAN.md — Create core/identity.py (IdentityProtocol, RoleProtocol, IdentityExtension, Identity alias) + DefaultIdentityExtension + get_identity_extension() typed accessor
- [x] 214-02-retype-deps-and-wire-extension-PLAN.md — Retype get_optional_user/get_current_user/get_current_active_user to return Identity; wire extension between API-key and JWT paths in both deps (Pitfall 9 duplication preserves expired-token UX)
- [x] 214-03-migrate-cross-domain-callers-PLAN.md — Migrate ~33 cross-domain caller files: swap User import for Identity; rewrite parameter annotations; 7 Pitfall-1 SQL-attribute files keep concrete User and join allowlist
- [x] 214-04-architecture-guard-and-verification-gate-PLAN.md — Extended test_layering.py with broadened core/ guard + cross-domain User-import allowlist test (13 :! pathspec exclusions); replaced narrow Phase 212-03 test; phase verification gate confirmed alembic clean (pre-existing drift only) + 2001 passing tests in container + ruff clean + 5 SC PASS

### Phase 215: sdks-from-openapi
**Goal**: External integrators (and the v13.1 CLI) consume GeoLens through auto-generated, version-pinned Python and TypeScript SDKs; SDK drift against the OpenAPI snapshot is impossible to merge accidentally
**Depends on**: Nothing (the OpenAPI snapshot at `backend/openapi.json` already exists; `make openapi-check` is the precedent pattern)
**Requirements**: OCSDK-01, OCSDK-02, OCSDK-03, OCSDK-04
**Success Criteria** (what must be TRUE):
  1. `pip install geolens-sdk` (PyPI, Apache-2.0) yields a typed Python client with Bearer-token and API-key auth helpers; round-trip against a running instance succeeds for `/search/datasets`, `/datasets/{id}`, and `POST /ingest`
  2. `npm install @geolens/sdk` (Apache-2.0) yields a typed TypeScript client with the same auth helpers and request/response models; round-trip against a running instance succeeds for the same three endpoints
  3. `make sdks` regenerates both SDKs from `backend/openapi.json` in a single shot; `make sdks-check` fails CI when generated code drifts from the committed sources (mirrors `make openapi-check`)
  4. Each SDK package version pins to the OpenAPI snapshot version it was generated from; `docs/sdks.md` documents the chosen generators (Python + TS) with rationale and the publish/release process
**Plans:** 5/5 plans complete

Plans:
- [x] 215-01-PLAN.md — Scaffold sdks/python/ + sdks/typescript/ directories with hand-maintained tooling, license, and gitignores (no generated code yet)
- [x] 215-02-PLAN.md — Wire Makefile targets (sdks/sdks-check/sdks-test/publish-sdks-py/publish-sdks-ts), scripts/sync_sdk_versions.py, scripts/flatten_openapi_defs.py preprocessor (research-extension finding), and run first regeneration to commit baseline generated code
- [x] 215-03-PLAN.md — Add hand-written auth wrappers (Python GeolensClient + TypeScript createGeolensClient) with bearer + api-key + anonymous + ValueError-on-both behaviors
- [x] 215-04-PLAN.md — Add round-trip integration test (12 tests), wire sdks-check job into ci.yml, and create publish-sdks.yml workflow scaffold (manual-trigger only)
- [x] 215-05-PLAN.md — Wrote docs/sdks.md (305 lines), closed __init__.py cp-stash gap from Plan 04, added module-level skip for SDK round-trip when sdks/ absent in container, ran phase verification gate (alembic clean / 2001 passed / sdks-check 0 / 12 round-trip pass / actionlint clean for Phase 215 workflows / both SDKs build) — all 4 ROADMAP SC PASS

### Phase 216: geolens-cli-mvp
**Goal**: An end user can install the Apache-2.0 `geolens` CLI from PyPI, log into any GeoLens instance, scan a directory of spatial data, publish a dataset, and export STAC metadata — without writing a line of HTTP code or touching the GeoLens UI
**Depends on**: Phase 215 (CLI consumes the generated Python SDK; no hand-rolled HTTP client)
**Requirements**: OCCLI-01, OCCLI-02, OCCLI-03, OCCLI-04, OCCLI-05, OCCLI-06
**Success Criteria** (what must be TRUE):
  1. `pip install geolens` from PyPI installs an Apache-2.0 standalone package; `geolens --version` prints a version compatible with both community and enterprise instances
  2. `geolens login <instance-url>` authenticates and stores the token in the OS keyring (or equivalent); a `--no-keyring` fallback writes to a config file for headless/CI use
  3. `geolens scan <dir>` walks the directory, detects vector and raster files, and prints a dry-run report (file path, detected format, would-ingest yes/no) without uploading anything
  4. `geolens publish <file>` uploads a vector or raster file to the configured instance via the generated Python SDK and prints the resulting dataset URL on success
  5. `geolens export stac <dataset-id>` writes valid STAC 1.1 JSON for a raster dataset to stdout (or a file via `-o`)
  6. The CLI source contains zero direct HTTP/`httpx`/`requests` imports for catalog operations — every API call goes through the generated Python SDK from Phase 215
**Plans:** 4/6 plans executed

Plans:
- [x] 216-01-scaffold-cli-package-PLAN.md — Apache-2.0 cli/ package + Typer scaffold + Wave 0 tests + Makefile recipes
- [x] 216-02-auth-and-config-PLAN.md — XDG config + keyring with file fallback + login/logout/whoami + AppState.sdk()
- [x] 216-03-scan-command-PLAN.md — directory walk + extension classification + shapefile sibling-grouping
- [x] 216-04-publish-command-PLAN.md — 3-step ingest with multipart workaround + progress UI + dataset URL
- [ ] 216-05-export-stac-command-PLAN.md — STAC 1.1 pass-through with vector guard + atomic file write
- [ ] 216-06-roundtrip-ci-docs-PLAN.md — round-trip integration test + sync_sdk_versions ext + CI cli-test job + publish-cli.yml + docs/cli.md + verification gate

### Phase 217: auth-saml-enterprise
**Goal**: A government/enterprise buyer with a SAML IdP can install `geolens-enterprise`, configure SAML in the admin UI, and have their users log in via SP-initiated SSO with attribute-driven role mapping — and the core repo contains no SAML code
**Depends on**: Phase 214 (overlay registers via the IdentityProtocol extension hook)
**Requirements**: SAML-08, SAML-09, SAML-10, SAML-11, SAML-12
**Success Criteria** (what must be TRUE):
  1. `git grep -i saml` against the core repo returns zero matches outside test fixtures and `docs-internal/` documentation; the SAML implementation lives entirely in `geolens-enterprise`
  2. With the enterprise overlay installed, the admin UI exposes a "SAML" configuration tab; in community mode the same tab is absent and direct route access returns 404 (matching the existing enterprise-gated pattern from v13.0)
  3. SP-initiated SSO works end-to-end against a reference IdP: metadata XML endpoint serves the SP descriptor; signed assertions are validated for signature, expiry, audience, and replay; new users are JIT-provisioned through the existing `find_or_create_oauth_user()` pathway
  4. SAML attribute → role mapping (e.g., `groups` → admin/editor/viewer) is configurable through the same admin tab; mapping changes are recorded in the existing audit log with old/new values
  5. Core's auth-extension hook (added in Phase 214 via `importlib.metadata` entry_points) is the only seam the SAML overlay registers into — there is no SAML-specific code path in core
**Plans**: TBD

### Phase 218: oc-audit-close-v13.1
**Goal**: The milestone's audit-grade promise is independently verified — re-running the open-core audit produces grades that meet or exceed the v13.1 targets, and the result is committed for traceability
**Depends on**: Phases 212, 213, 214, 215, 216, 217 (all P1 work must be merged)
**Requirements**: AUDIT-V1
**Success Criteria** (what must be TRUE):
  1. Running `/oc-audit` against the post-217 state produces grades meeting or exceeding: Boundary ≥ A−, Seam Quality ≥ B, OSS Surface ≥ C
  2. The audit output is committed at `docs-internal/audits/oc-separation-audit-v13.1-close.md` with the same structure as the 2026-04-26 source audit (findings table, grades, deferred items)
  3. Any P1-tagged residual findings in the closing audit are explicitly triaged: either fixed in a follow-up phase, demoted to P2 with rationale, or accepted as out-of-scope for v13.1
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 212 → 213 → 214 → 215 → 216 → 217 → 218

(212 and 213 are independent and may run in parallel; 214 is a prerequisite for 217; 215 is a hard prerequisite for 216; 218 gates milestone close.)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 212. core-settings-decouple | 4/4 | Complete    | 2026-04-27 |
| 213. catalog-authz-relocate | 4/4 | Complete    | 2026-04-27 |
| 214. identity-protocol-extract | 4/4 | Complete    | 2026-04-27 |
| 215. sdks-from-openapi | 5/5 | Complete   | 2026-04-27 |
| 216. geolens-cli-mvp | 4/6 | In Progress|  |
| 217. auth-saml-enterprise | 0/TBD | Not started | - |
| 218. oc-audit-close-v13.1 | 0/TBD | Not started | - |

## Backlog

### Phase 999.5: Helm chart for Kubernetes deployment (BACKLOG)

**Goal:** [Captured for future planning]
**Requirements:** TBD
**Plans:** 0 plans
**Source:** `docs-internal/audits/oc-separation-audit-20260426-b.md` §7 P3
**Estimated effort:** ~1 week

Compose-only deployment today; enterprise prospects in regulated/government markets typically demand K8s. Helm chart enables enterprise adoption at scale and unblocks K8s-first prospects.

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Phase 999.6: Tenant scoping infrastructure for multi-tenant isolation (BACKLOG)

**Goal:** [Captured for future planning]
**Requirements:** TBD
**Plans:** 0 plans
**Source:** `docs-internal/audits/oc-separation-audit-20260426-b.md` §2 (Seam #8) / §7 P3
**Estimated effort:** 1–2 weeks+ (architectural prerequisite)

No tenant-scoping infrastructure exists today — `User` has no tenant column, all catalog tables sit in single `catalog` schema, no request-context middleware. Required before the Enterprise tier's "multi-org / tenant isolation" feature can ship. Touches identity, catalog, audit, and embed-token domains; needs migration plan + query-injection callback registry + tenant-context propagation.

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)
