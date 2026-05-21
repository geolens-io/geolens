# Requirements: GeoLens v1016 Hardening Sweep

**Defined:** 2026-05-21
**Archived:** 2026-05-21
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

## v1016 Requirements

Requirements for the v1016 Hardening Sweep milestone. All 26/26 satisfied.

### Known Items — v1015 Tech-Debt

Carried-forward items from v1015 milestone close. All 7 noted in PROJECT.md "Recent Shipped Milestone: v1015" tech-debt followups section.

- [x] **KNOWN-01**: `_resolve_download_user` consumes JWT `sub` claim correctly for anonymous download tokens (Phase 1065 carryover; not a v1015 regression, but downstream token-consumption gap)
- [x] **KNOWN-02**: `alembic upgrade head` against a clean DB is exercised in close-gate (test-DB-bound; was verified via `down_revision` linkage only in v1015)
- [x] **KNOWN-03**: `CPL_VSIL_CURL_ALLOWED_EXTENSIONS` clamp applied to all GDAL subprocesses (raster ingest, COG conversion), not only `_build_vrt`
- [x] **KNOWN-04**: VRT VSI allow-list (7 prefixes) consolidated to a single source of truth — validator + env overlay no longer require dual-edit when adding a new scheme
- [x] **KNOWN-05**: Export endpoint returns 403 for revoked-export-on-viewer (full parity with v1014 SEC-S04; v1015 only verified anonymous 401)
- [x] **KNOWN-06**: `e2e:smoke:builder` + `npm run typecheck` enforced in close-gate (was per-plan verification only in v1015)
- [x] **KNOWN-07**: Full backend pytest enforced in close-gate (was touched-area + new-files scoped in v1015)

### Known Items — v1014 INFO Closures

5 v1014 INFO findings deferred from v1062/v1063 reviews. Each had a pending todo file at `.planning/todos/pending/`.

- [x] **KNOWN-08**: `.env.example` documents `PASSWORD_MIN_LENGTH` and `PASSWORD_REQUIRE_CLASSES` near existing auth settings (v1062 IN-01)
- [x] **KNOWN-09**: `validate_password_complexity` decides whether whitespace counts as the symbol class — either treat as symbol with docstring, or exclude with docstring (v1062 IN-02)
- [x] **KNOWN-10**: `where_validator.py` adds an `exp.Dot` AST bypass-path test (v1062 IN-03)
- [x] **KNOWN-11**: `_sanitize_authorization_token` 8-char minimum documented inline (v1063 IN-01)
- [x] **KNOWN-12**: `StacSearchBody.limit` and `offset` carry Pydantic `ge`/`le` constraints (v1063 IN-02)

### Known Items — Dependabot

- [x] **KNOWN-13**: `idna` bumped to ≥ 3.15 in `backend/uv.lock` to close Dependabot #40 (CVE-2026-45409 / GHSA-65pc-fj4g-8rjx — DoS via `idna.encode()` with crafted inputs)

### Audit Sweep

Fresh re-audit runs against the v1015 ship state. Last baselines: `/sec-audit` 2026-05-19 (27 findings closed in v1014), `/ingest-audit` 2026-05-19 (9 findings closed in v1015).

- [x] **AUDIT-01**: `/sec-audit` re-run produces `SECURITY-AUDIT-2026-05-21.md` at `.planning/audits/`
- [x] **AUDIT-02**: `/ingest-audit` re-run produces `INGEST-AUDIT-2026-05-21.md` at `.planning/audits/`
- [x] **AUDIT-03**: Triage classification doc maps each finding to severity (HIGH/MEDIUM/LOW/INFO) and assigns it to Phase 1073 or 1074

### Audit Remediation (Expanded from Phase 1072 triage 2026-05-21)

Both fresh audits returned PASS at HIGH/MEDIUM. v1014/v1015/Phase 1071 closed all prior HIGH/MEDIUM/P0/P1 findings. Triage at `.planning/audits/TRIAGE-2026-05-21.md` classified remaining open items: 4 P2 findings worth closing in v1016, 8 deferred to v1017.

- [x] **REMED-01**: TanStack mutations for re-upload commit + VRT creation invalidate `jobStatusByDataset` so dataset-detail page no longer shows stale warnings (ingest-audit P2-06)
- [x] **REMED-02**: `JobStatusResponse` schema carries `progress` / `current_step` / `rows_processed` fields populated by ingest worker writes so 10-min raster ingests show progress in UI (ingest-audit P2-07)
- [x] **REMED-03**: Ingest task chunk-loop logic deduplicated into a shared helper testable in isolation (ingest-audit P2-05)
- [x] **REMED-04**: COG URL construction consolidated into a single storage helper consumed by raster/cog.py + stac_router.py + presigned helpers; SEC-OBSV-01 + SEC-OBSV-02 docstring contracts pinned at the same time (ingest-audit P2-01 + sec-audit SEC-OBSV-01/02)

### Close Gate

- [x] **GATE-01**: `CHANGELOG.md` carries a `[1.5.1] - 2026-05-21` entry listing all closed items
- [x] **GATE-02**: Full backend pytest passes (`uv run pytest` in `backend/`; not touched-area scoped)
- [x] **GATE-03**: Frontend vitest passes (`npm run test` in `frontend/`)
- [x] **GATE-04**: `e2e:smoke:builder` + `npm run typecheck` pass in `frontend/`
- [x] **GATE-05**: Live Playwright MCP smoke on `localhost:8080` against rebuilt containers — 5/5 surfaces PASS (catalog, dataset detail, builder, viewer, AI/embed status)
- [x] **GATE-06**: Local `v1016` tag + public `v1.5.1` tag cut at the close-gate commit; pushed to `origin`

## Out of Scope

| Feature | Reason |
|---------|--------|
| Recreate public repo from scratch | Moot — `1.0.0` already shipped publicly from existing repo; PyPI/npm/GHCR can't be re-published. Stale 2026-05-05 todo moved to `resolved/` |
| Resume v1.7 Marketplace & Distribution | Paused at Phase 40 (AWS AMI Build); not a hardening surface |
| New features or refactors beyond audit findings | Patch tag `v1.5.1` means backward-compatible only; feature work waits for next minor (`v1.6.0` or later) |
| Open-core boundary expansion | v13.1-derived boundaries are stable at A grade; not a v1016 surface |
| Frontend audit / UI review | This milestone is backend-heavy (security/ingest); UI surfaces are stable post-v1011 |

## Outcomes

### Phase 1071: Known Items Closure
All 11 KNOWN reqs (KNOWN-01..05, KNOWN-08..13) closed in Phase 1071. Status: Complete.
KNOWN-06 and KNOWN-07 were remapped to Phase 1074 (close-gate process items, not code-change items).

### Phase 1072: Re-audit & Triage
All 3 AUDIT reqs (AUDIT-01..03) closed in Phase 1072. Status: Complete. Both audits PASS.

### Phase 1073: Audit Remediation
All 4 REMED reqs (REMED-01..04) closed in Phase 1073. Status: Complete.

### Phase 1074: Close Gate
All 8 GATE reqs (incl. KNOWN-06/07 and GATE-01..06) closed in Phase 1074. Status: Complete.

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| KNOWN-01 | Phase 1071 | Complete |
| KNOWN-02 | Phase 1071 (live smoke in 1074) | Complete |
| KNOWN-03 | Phase 1071 | Complete |
| KNOWN-04 | Phase 1071 | Complete |
| KNOWN-05 | Phase 1071 | Complete |
| KNOWN-06 | Phase 1074 | Complete |
| KNOWN-07 | Phase 1074 | Complete |
| KNOWN-08 | Phase 1071 | Complete |
| KNOWN-09 | Phase 1071 | Complete |
| KNOWN-10 | Phase 1071 | Complete |
| KNOWN-11 | Phase 1071 | Complete |
| KNOWN-12 | Phase 1071 | Complete |
| KNOWN-13 | Phase 1071 | Complete |
| AUDIT-01 | Phase 1072 | Complete |
| AUDIT-02 | Phase 1072 | Complete |
| AUDIT-03 | Phase 1072 | Complete |
| REMED-01 | Phase 1073 | Complete |
| REMED-02 | Phase 1073 | Complete |
| REMED-03 | Phase 1073 | Complete |
| REMED-04 | Phase 1073 | Complete |
| GATE-01 | Phase 1074 | Complete |
| GATE-02 | Phase 1074 | Complete |
| GATE-03 | Phase 1074 | Complete |
| GATE-04 | Phase 1074 | Complete |
| GATE-05 | Phase 1074 | Complete |
| GATE-06 | Phase 1074 | Complete |

**Coverage:**
- v1016 requirements: 26 total (24 upfront + REMED expanded from 2 → 4 after Phase 1072 triage)
- Mapped to phases: 26
- Satisfied: 26 ✓
- Unsatisfied: 0 ✓

---
*Requirements defined: 2026-05-21*
*Archived: 2026-05-21 at milestone close*
