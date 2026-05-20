# Requirements: GeoLens — v1014 Security Audit Remediation

**Defined:** 2026-05-20
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Source of truth:** `docs-internal/audits/sec-audit-20260519.md` (561 lines, 41KB). Each REQ-ID maps to a Finding ID (S01–S16) in §"Finding details" / §"Medium severity" or to a follow-up (SEC-FOLLOWUP-01..10) in §"Not blocking — follow-up tickets". Regression tests pre-drafted in `e2e/sec-audit.spec.ts` (18 tests pinning S01–S13).

## v1014 Requirements

Requirements for milestone v1014. Each maps to exactly one phase in `ROADMAP.md`. Public tag: **v1.4.0** (minor — substantial security hardening + new SSRF safeguards + AGENTS.md/SECURITY.md guardrails).

### HIGH severity remediation (Phase 1061)

- [x] **SEC-S01** *(HIGH, CVSS 7.5)*: User browsing the STAC catalog (`/stac/...`) sees only Records the visibility filter would allow on the same Records via the OGC API peer router. Fix: thread `user` / `user_roles` params + apply `apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)` to the underlying queries in `backend/app/standards/stac/router.py:54-822`. Acceptance: e2e/sec-audit.spec.ts S01 tests (private + anonymous) pass.
- [x] **SEC-S02** *(HIGH, CVSS 8.1)*: User cannot mutate dataset metadata (3 handlers in `backend/app/modules/catalog/datasets/api/router.py:263-426`) on Records they do not own / have not been granted access to. Fix: add `check_dataset_access(dataset, user, user_roles, action="write")` after `get_dataset()` in each handler; ownership + grant checks before any UPDATE. Acceptance: e2e/sec-audit.spec.ts S02 test (Editor B forbidden from mutating Editor A's private dataset metadata) passes.
- [x] **SEC-S03** *(HIGH, CVSS 8.1)*: User cannot perform column DDL operations (4 handlers in `backend/app/modules/catalog/layers/router.py:94-301`) on layers belonging to Records they do not own / have not been granted access to. Fix: same `check_dataset_access` pattern as SEC-S02. Acceptance: e2e/sec-audit.spec.ts S03 test passes (Editor B forbidden from adding/dropping columns on Editor A's layer).
- [x] **SEC-S04** *(HIGH, CVSS 8.5)*: User-supplied Service URLs cannot follow HTTP redirects to internal/private network addresses (SSRF). Fix: `make_safe_client()` factory in `backend/app/modules/catalog/sources/router.py:120-124` (+ all adapters) that uses an httpx `event_hooks={"response": [_revalidate_redirect]}` hook to revalidate every redirect target against the SSRF allowlist; set `GDAL_HTTP_FOLLOWLOCATION=NO` for ogr2ogr subprocess calls. Acceptance: e2e/sec-audit.spec.ts S04 test passes (302 redirect to `169.254.169.254` rejected with 400/403).
- [x] **SEC-S05** *(HIGH, CVSS 7.5)*: User querying `/datasets/{id}/related/` sees only related Records the visibility filter would allow. Fix: add `check_dataset_access_or_anonymous(dataset, user, user_roles)` before `get_related_datasets()` call in `backend/app/modules/catalog/datasets/api/router_data.py:56-65`; also apply `apply_visibility_filter` to the related-records query itself. Acceptance: e2e/sec-audit.spec.ts S05 test passes.
- [x] **SEC-S06** *(HIGH, CVSS 7.5)*: Demo deployment cannot start with the literal committed `.env.demo` credentials. Fix: rename `.env.demo` → `.env.demo.example` (no real defaults); add `scripts/init-demo-env.sh` that generates per-deploy random credentials; extend `validate_demo_credentials_guard` (backend startup) to refuse literal committed `JWT_SECRET_KEY=demo-only-do-not-use-in-production-change-me` etc. Acceptance: backend refuses to start with the literal committed values; demo deployment succeeds with `init-demo-env.sh`-generated credentials.
- [x] **SEC-S07** *(HIGH, CVSS 7.0)*: MinIO cannot start with default `minioadmin/minioadmin` credentials. Fix: drop `:-minioadmin` defaults in `docker-compose.yml:507-508,536`; change to `${MINIO_ROOT_USER:?MINIO_ROOT_USER is required}` fail-closed shell expansion. Acceptance: `docker compose up minio` fails fast with clear error when env vars are unset.
- [x] **SEC-GUARD-01** *(Architectural)*: AGENTS.md updated with headline-pattern rule pinning the visibility-filter coverage contract: "Any new handler that fetches a `Record`/`Dataset`/`Map`/`RecordEmbedding` by ID must either call `check_dataset_access_or_anonymous` (read) or `check_dataset_access` + ownership check (write/destructive), OR apply `apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)` to the underlying query." Pre-commit grep guardrail proposal from `docs-internal/audits/security-lessons.md` evaluated; ship the highest-confidence variant. Acceptance: AGENTS.md updated, guardrail committed, optional pre-commit hook lives in `.pre-commit-config.yaml` or documented as a manual review checklist line.

### MEDIUM severity remediation (Phase 1062)

- [x] **SEC-S08** *(MEDIUM, CVSS 5.3)*: Embed token framing CSP gap closed. Fix per audit §S08. Acceptance: e2e/sec-audit.spec.ts S08 test passes (embed iframe enforces `frame-ancestors` directive matching configured allowlist).
- [x] **SEC-S09** *(MEDIUM, CVSS 5.0)*: ogr2ogr `-where` clause user input validated by a sqlglot-based SQL validator before being passed to subprocess. Whitelist of safe SQL constructs (filter expressions only — no DDL, no UNION, no semicolon-terminated multi-statements). Acceptance: e2e/sec-audit.spec.ts S09 test passes (malicious `-where` payload rejected at API boundary).
- [x] **SEC-S10** *(MEDIUM, CVSS 5.3)*: Basemap `api_key` query-param exposure documented (public-facing — not a secret; rotation guidance in admin docs) + per-route rate limit on `/basemap-proxy` to cap abuse. Acceptance: docstring + admin doc page exists; rate limit covered by e2e/sec-audit.spec.ts S10 test.
- [x] **SEC-S11** *(MEDIUM, CVSS 5.3)*: Per-route rate limit applied to `/search/datasets/` + `/datasets/{id}/related/` to cap OpenAI embedding cost from a runaway client / bot. Default: configurable per-IP and per-token rate caps. Acceptance: e2e/sec-audit.spec.ts S11 test passes (429 returned after threshold).
- [ ] **SEC-S12** *(MEDIUM, CVSS 5.0)*: `simple`-regconfig GIN index added for non-English full-text search input that breaks the English-stem tokenization. Migration adds index; query path picks the right regconfig based on locale signal. Acceptance: French/Spanish/German FTS query against a French/Spanish/German dataset returns matches that previously returned 0.
- [ ] **SEC-S13** *(MEDIUM, CVSS 4.3)*: `max_length=1000` added to `/search/facets/?q=` query param. Acceptance: e2e/sec-audit.spec.ts S13 test passes (1001-char payload rejected with 422).
- [ ] **SEC-S14** *(MEDIUM, CVSS 5.4)*: ESLint guard added preventing `localStorage.setItem('*token*', ...)` patterns. Medium-term httpOnly-cookie migration plan documented in `docs-internal/audits/security-lessons.md` (or new ADR). Acceptance: ESLint rule fails on intentional regression test; migration plan documented.
- [x] **SEC-S15** *(MEDIUM, CVSS 4.3)*: JWT tokens include `jti` (random unique ID) + `token_version` claim. Revocation surface: bump `token_version` on the User row → all prior JWTs become invalid on next request. Acceptance: revocation flow integration test passes (token issued, version bumped, subsequent request 401s).
- [x] **SEC-S16** *(MEDIUM, CVSS 4.3)*: Password complexity validator added at registration + change-password endpoints. Minimum: 12 chars, mix of letter classes (configurable via `.env`). Acceptance: weak password rejected with 422; configuration override tested.

### LOW follow-up tickets (Phase 1063)

- [ ] **SEC-FU-01**: HTTP 5xx-mutation test fixtures added for STAC visibility regression — pinned by S01 spec. Acceptance: fixture supports paths that return 5xx from underlying query so e2e/sec-audit.spec.ts can assert no information disclosure on error.
- [ ] **SEC-FU-02**: `validate_demo_credentials_guard` extended to refuse `JWT_SECRET_KEY=demo-only-do-not-use-in-production-change-me` literal at startup (defense-in-depth on top of SEC-S06).
- [ ] **SEC-FU-03**: ESLint rule `react/no-danger` enabled in `frontend/eslint.config.js` to lock the popup-template ban that v13.12 introduced.
- [ ] **SEC-FU-04**: GDAL `Authorization` header pinned to base64url charset to close CRLF-smuggling defense-in-depth gap (Subagent A notes).
- [ ] **SEC-FU-05**: `max_length` added to `intersects` query parameter on STAC search router (Subagent I M-1).
- [ ] **SEC-FU-06**: `math.isfinite()` guard added in `parse_bbox` to reject NaN/Inf coordinates (Subagent I M-2).
- [ ] **SEC-FU-07**: ILIKE escape `.replace("%", r"\%").replace("_", r"\_")` added in `maps/service_crud.py:140-147` and `service_collections.py:29-35` (Subagent J LOW-3, LOW-4).
- [ ] **SEC-FU-08**: `pg_audit` or per-table change log added for column DDL so dataset owners are notified when an editor mutates their schema (post-fix complement to SEC-S03).
- [ ] **SEC-FU-09**: `nginx server_tokens off;` moved into the prod server block (currently default config).
- [ ] **SEC-FU-10**: Role-scoping recommendations documented for cloud Postgres in `.env.example` `DATABASE_URL_OVERRIDE` section (least-privilege guidance for application DB user).

### Close gate (Phase 1064)

- [ ] **SEC-CTRL-01**: Milestone close requires:
  - `e2e/sec-audit.spec.ts` full suite runs green (18 tests pinning S01–S13) — env-var fixtures provisioned (`SEC_AUDIT_PRIVATE_RECORD_ID`, `SEC_AUDIT_PRIVATE_DATASET_ID`, `SEC_AUDIT_EDITOR_B_TOKEN`, `SEC_AUDIT_SSRF_TEST_REDIRECTOR`)
  - All standard smoke gates green: backend pytest, frontend typecheck + vitest, e2e:smoke, i18n parity
  - Code-review pass with inline fixes applied per `feedback_review_findings_inline.md`
  - Re-run `/sec-audit` against `localhost:8080` and confirm merge gate flips from BLOCK → PASS
  - CHANGELOG `[Unreleased]` → `[1.4.0]` block populated with security-headline framing
  - Local tag `v1014` created
  - Public tag `v1.4.0` created (minor bump from v1.3.0)

## Coverage

- **v1014 requirements:** 28 (8 in Phase 1061, 9 in Phase 1062, 10 in Phase 1063, 1 in Phase 1064)
- **HIGH:** 7 / 7 (100%) mapped to Phase 1061
- **MEDIUM:** 9 / 9 (100%) mapped to Phase 1062
- **LOW follow-ups:** 10 / 10 (100%) mapped to Phase 1063
- **Architectural guardrail:** 1 / 1 (SEC-GUARD-01) mapped to Phase 1061
- **Close gate:** 1 / 1 (SEC-CTRL-01) mapped to Phase 1064
- **Unmapped:** 0
- **Duplicates:** 0

## Traceability (filled by roadmap)

| REQ-ID         | Severity | Phase | Verified |
|----------------|----------|-------|----------|
| SEC-S01        | HIGH     | 1061  | —        |
| SEC-S02        | HIGH     | 1061  | —        |
| SEC-S03        | HIGH     | 1061  | —        |
| SEC-S04        | HIGH     | 1061  | —        |
| SEC-S05        | HIGH     | 1061  | —        |
| SEC-S06        | HIGH     | 1061  | —        |
| SEC-S07        | HIGH     | 1061  | —        |
| SEC-GUARD-01   | Arch     | 1061  | —        |
| SEC-S08        | MEDIUM   | 1062  | 1062-05  |
| SEC-S09        | MEDIUM   | 1062  | —        |
| SEC-S10        | MEDIUM   | 1062  | —        |
| SEC-S11        | MEDIUM   | 1062  | —        |
| SEC-S12        | MEDIUM   | 1062  | —        |
| SEC-S13        | MEDIUM   | 1062  | —        |
| SEC-S14        | MEDIUM   | 1062  | —        |
| SEC-S15        | MEDIUM   | 1062  | —        |
| SEC-S16        | MEDIUM   | 1062  | —        |
| SEC-FU-01      | LOW      | 1063  | —        |
| SEC-FU-02      | LOW      | 1063  | —        |
| SEC-FU-03      | LOW      | 1063  | —        |
| SEC-FU-04      | LOW      | 1063  | —        |
| SEC-FU-05      | LOW      | 1063  | —        |
| SEC-FU-06      | LOW      | 1063  | —        |
| SEC-FU-07      | LOW      | 1063  | —        |
| SEC-FU-08      | LOW      | 1063  | —        |
| SEC-FU-09      | LOW      | 1063  | —        |
| SEC-FU-10      | LOW      | 1063  | —        |
| SEC-CTRL-01    | Gate     | 1064  | —        |

## Future Requirements (deferred — not in v1014 scope)

Carried forward from prior milestone deferred items.

### Marketplace & Distribution

- [ ] **v1.7 Marketplace & Distribution unpause** — phases 36-42 paused at Phase 40 (AWS AMI Build).

### Cloud / Enterprise architecture

- [ ] **999.6**: Tenant scoping infrastructure for multi-tenant isolation (Cloud prerequisite, deferred SaaS).
- [ ] **999.13**: Persistent connector registry (Enterprise feature, P2).
- [ ] **999.14**: Helm chart + AMI Packer pipeline (P2).
- [ ] **999.15**: SBOM + signed image distribution (P2).
- [ ] **999.16**: Extract `geolens-schemas` PyPI package (P2).

### Hygiene

- [ ] **Recreate public repo before launch** — pending todo from 2026-05-05 (`.planning/todos/pending/2026-05-05-recreate-public-repo-before-launch.md`).

## Out of Scope

Items the audit explicitly notes as out of scope for this remediation pass:

- **Penetration testing of running services** — `/sec-audit` is static + config audit, not dynamic pen-testing.
- **Network architecture** — firewalls, WAF, CDN config sit outside the repo and are operator concerns.
- **IaC (Terraform/Pulumi)** — repo contains Helm chart only; full IaC not in tree.
- **Frontend bundle CVE scan post-build** — `npm audit` covers source deps; bundle-level CVE scanning deferred.
- **Compliance frameworks** — SOC2/HIPAA/GDPR are not in scope per `/sec-audit` command spec.
