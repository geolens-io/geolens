# Requirements: GeoLens v1016 Hardening Sweep

**Defined:** 2026-05-21
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

## v1016 Requirements

Requirements for the v1016 Hardening Sweep milestone. Each maps to a phase in ROADMAP.md.

### Known Items — v1015 Tech-Debt

Carried-forward items from v1015 milestone close. All 7 noted in PROJECT.md "Recent Shipped Milestone: v1015" tech-debt followups section.

- [ ] **KNOWN-01**: `_resolve_download_user` consumes JWT `sub` claim correctly for anonymous download tokens (Phase 1065 carryover; not a v1015 regression, but downstream token-consumption gap)
- [ ] **KNOWN-02**: `alembic upgrade head` against a clean DB is exercised in close-gate (test-DB-bound; was verified via `down_revision` linkage only in v1015)
- [ ] **KNOWN-03**: `CPL_VSIL_CURL_ALLOWED_EXTENSIONS` clamp applied to all GDAL subprocesses (raster ingest, COG conversion), not only `_build_vrt`
- [ ] **KNOWN-04**: VRT VSI allow-list (7 prefixes) consolidated to a single source of truth — validator + env overlay no longer require dual-edit when adding a new scheme
- [ ] **KNOWN-05**: Export endpoint returns 403 for revoked-export-on-viewer (full parity with v1014 SEC-S04; v1015 only verified anonymous 401)
- [ ] **KNOWN-06**: `e2e:smoke:builder` + `npm run typecheck` enforced in close-gate (was per-plan verification only in v1015)
- [ ] **KNOWN-07**: Full backend pytest enforced in close-gate (was touched-area + new-files scoped in v1015)

### Known Items — v1014 INFO Closures

5 v1014 INFO findings deferred from v1062/v1063 reviews. Each has a pending todo file at `.planning/todos/pending/`.

- [ ] **KNOWN-08**: `.env.example` documents `PASSWORD_MIN_LENGTH` and `PASSWORD_REQUIRE_CLASSES` near existing auth settings (v1062 IN-01)
- [ ] **KNOWN-09**: `validate_password_complexity` decides whether whitespace counts as the symbol class — either treat as symbol with docstring, or exclude with docstring (v1062 IN-02)
- [ ] **KNOWN-10**: `where_validator.py` adds an `exp.Dot` AST bypass-path test (v1062 IN-03)
- [ ] **KNOWN-11**: `_sanitize_authorization_token` 8-char minimum documented inline (v1063 IN-01)
- [ ] **KNOWN-12**: `StacSearchBody.limit` and `offset` carry Pydantic `ge`/`le` constraints (v1063 IN-02)

### Known Items — Dependabot

- [ ] **KNOWN-13**: `idna` bumped to ≥ 3.15 in `backend/uv.lock` to close Dependabot #40 (CVE-2026-45409 / GHSA-65pc-fj4g-8rjx — DoS via `idna.encode()` with crafted inputs)

### Audit Sweep

Fresh re-audit runs against the v1015 ship state. Last baselines: `/sec-audit` 2026-05-19 (27 findings closed in v1014), `/ingest-audit` 2026-05-19 (9 findings closed in v1015).

- [ ] **AUDIT-01**: `/sec-audit` re-run produces `SECURITY-AUDIT-2026-05-21.md` at `.planning/audits/`
- [ ] **AUDIT-02**: `/ingest-audit` re-run produces `INGEST-AUDIT-2026-05-21.md` at `.planning/audits/`
- [ ] **AUDIT-03**: Triage classification doc maps each finding to severity (HIGH/MEDIUM/LOW/INFO) and assigns it to Phase 1073 or 1074

### Audit Remediation (Expands Mid-Milestone)

Meta-requirements that expand into concrete `REMED-XX` IDs after Phase 1072 triage lands. `/gsd-autonomous` handles via mid-milestone `/gsd-phase` insertion if finding count warrants splitting Phase 1073.

- [ ] **REMED-01**: All HIGH and MEDIUM severity findings from AUDIT-03 triage are closed in code + tests
- [ ] **REMED-02**: All LOW and INFO severity findings from AUDIT-03 triage are closed in code + docs (INFO may close as pending todo files if scope warrants deferral)

### Close Gate

- [ ] **GATE-01**: `CHANGELOG.md` carries a `[1.5.1] - 2026-05-2X` entry listing all closed items
- [ ] **GATE-02**: Full backend pytest passes (`uv run pytest` in `backend/`; not touched-area scoped)
- [ ] **GATE-03**: Frontend vitest passes (`npm run test` in `frontend/`)
- [ ] **GATE-04**: `e2e:smoke:builder` + `npm run typecheck` pass in `frontend/`
- [ ] **GATE-05**: Live Playwright MCP smoke on `localhost:8080` against rebuilt containers — 5/5 surfaces PASS (catalog, dataset detail, builder, viewer, AI/embed status)
- [ ] **GATE-06**: Local `v1016` tag + public `v1.5.1` tag cut at the close-gate commit; pushed to `origin`

## Out of Scope

| Feature | Reason |
|---------|--------|
| Recreate public repo from scratch | Moot — `1.0.0` already shipped publicly from existing repo; PyPI/npm/GHCR can't be re-published. Stale 2026-05-05 todo moved to `resolved/` |
| Resume v1.7 Marketplace & Distribution | Paused at Phase 40 (AWS AMI Build); not a hardening surface |
| New features or refactors beyond audit findings | Patch tag `v1.5.1` means backward-compatible only; feature work waits for next minor (`v1.6.0` or later) |
| Open-core boundary expansion | v13.1-derived boundaries are stable at A grade; not a v1016 surface |
| Frontend audit / UI review | This milestone is backend-heavy (security/ingest); UI surfaces are stable post-v1011 |

## Traceability

Will be populated by `gsd-roadmapper` during roadmap creation. Final count: 24 upfront reqs + N from REMED expansion after Phase 1072.

| Requirement | Phase | Status |
|-------------|-------|--------|
| KNOWN-01 | Phase 1071 | Pending |
| KNOWN-02 | Phase 1071 | Pending |
| KNOWN-03 | Phase 1071 | Pending |
| KNOWN-04 | Phase 1071 | Pending |
| KNOWN-05 | Phase 1071 | Pending |
| KNOWN-06 | Phase 1074 | Pending |
| KNOWN-07 | Phase 1074 | Pending |
| KNOWN-08 | Phase 1071 | Pending |
| KNOWN-09 | Phase 1071 | Pending |
| KNOWN-10 | Phase 1071 | Pending |
| KNOWN-11 | Phase 1071 | Pending |
| KNOWN-12 | Phase 1071 | Pending |
| KNOWN-13 | Phase 1071 | Pending |
| AUDIT-01 | Phase 1072 | Pending |
| AUDIT-02 | Phase 1072 | Pending |
| AUDIT-03 | Phase 1072 | Pending |
| REMED-01 | Phase 1073 | Pending |
| REMED-02 | Phase 1073 | Pending |
| GATE-01 | Phase 1074 | Pending |
| GATE-02 | Phase 1074 | Pending |
| GATE-03 | Phase 1074 | Pending |
| GATE-04 | Phase 1074 | Pending |
| GATE-05 | Phase 1074 | Pending |
| GATE-06 | Phase 1074 | Pending |

**Coverage:**
- v1016 requirements: 24 total (upfront)
- Mapped to phases: 24
- Unmapped: 0 ✓
- Note: REMED-01..02 expand into concrete `REMED-XX` IDs mid-milestone via `/gsd-phase` after Phase 1072 ships

---
*Requirements defined: 2026-05-21*
*Last updated: 2026-05-21 after initial definition*
