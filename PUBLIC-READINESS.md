# GeoLens — Public Release Readiness Assessment

**Date:** 2026-05-07
**Milestone:** v13.12 Pre-Public Security & Audit Hardening
**Codebase commit:** `edfa13b6`

## TL;DR

The v13.12 milestone executed 17 audit dimensions covering security, infrastructure, API contracts, documentation, code structure, performance, internationalization, and open-core boundaries. The sweep produced 193 findings; all 39 Critical and High severity items have been remediated and verified by closing-commit and spot-check. 154 Medium and Low findings have been routed to backlog with rationale and target follow-up cycles. Composite grade across the 17 dimensions is **A-**. **Recommendation: CONDITIONAL-GO** for public release announcement, with three deployment-side conditions adopters must be made aware of (detailed below).

## Audit Sweep Coverage

17 audit dimensions executed during v13.12 (Phases 263-266):

| # | Dimension | Audit Skill | Pre-Sweep Findings (C/H/M/L) | Post-Sweep Status |
|---|-----------|-------------|-------------------------------|-------------------|
| 1 | Security (general) | /sec-audit | 0/2/5/4 | All H closed; 5 M + 4 L deferred |
| 2 | Dependency CVEs | /dep-audit | 0/0/2/4 | Already clean; 2 M + 4 L deferred |
| 3 | Diff security | /security-review | 0/4/5/4 | All H closed; 5 M + 4 L deferred |
| 4 | Env vars | /env-audit | 0/1/5/4 | All H closed; 5 M + 4 L deferred |
| 5 | Open-core boundary | /oc-audit | 0/0/2/4 | A+ pre-sweep; 2 M + 4 L deferred |
| 6 | Docker | /docker-audit | 0/3/9/11 | All H closed; 9 M + 11 L deferred |
| 7 | PostgreSQL | /db-audit | 0/5/7/4 | All H closed; 7 M + 4 L deferred |
| 8 | Migrations | /migration-audit | 0/1/4/4 | All H closed; 4 M + 4 L deferred |
| 9 | API contract | /api-contract | 0/3/4/2 | All H closed; 4 M + 2 L deferred |
| 10 | Documentation | /doc-audit | 0/7/6/3 | All H closed; 6 M + 3 L deferred |
| 11 | Admin / governance | /admin-audit | 0/1/4/5 | All H closed; 4 M + 5 L deferred |
| 12 | Demo readiness | /demo-ready | 1/0/4/3 | C closed; 4 M + 3 L deferred |
| 13 | Performance | /perf-profile | 1/5/8/4 | C + all H closed; 8 M + 4 L deferred |
| 14 | i18n | /i18n-audit | 0/1/4/2 | All H closed; 4 M + 2 L deferred |
| 15 | Backend structure | /backend-audit | 0/1/3/4 | All H closed; 3 M + 4 L deferred |
| 16 | Frontend structure | /frontend-audit | 0/0/4/5 | Already clean; 4 M + 5 L deferred |
| 17 | Test health | /test-audit | 0/4/7/4 | All H closed; 7 M + 4 L deferred |
| | **Total** | | **2 / 37 / 83 / 71** | **All C+H closed; 154 M+L deferred** |

H-37 (perf-profile docker-resource-limits cross-listing) was deduped to H-26 (docker-audit memory caps) at triage; counts above reflect the post-dedupe allocation.

## Per-Audit Grades

| Audit Dimension | Grade | Rationale |
|-----------------|-------|-----------|
| Security (general) | A | 2 H closed (OAuth redirect_uri injection + JWT-secret-default rejection); 5 M deferred are defense-in-depth (logging redaction, SVG CSP, X-Forwarded-Host allowlist). Auth/crypto primitives sound pre-sweep. |
| Dependency CVEs | A | Zero CVE-exploitable deps shipped. python-multipart and mako bumped pre-milestone. 2 M + 4 L are bump-cadence and license-check polish. |
| Diff security (security-review) | A | All 4 H closed (manifest path traversal, OAuth email_verified, embed-token Origin bypass, Helm SECRET_KEY rename). The path-traversal fix uses three-layer defense. 5 M deferred are post-launch hardening. |
| Env vars | A | H-19 (.env.demo boot guard) closed cleanly. 5 M deferred are minor — mostly Settings-model alignment items. |
| Open-core boundary | A+ | Boundary integrity A+/A+/A/A pre-sweep; nothing to remediate. Strongest dimension in the sweep. |
| Docker | A- | All 3 H closed (duplicate Dockerfile deleted, 2GB VPS memory caps, tile pool privilege drop). 9 M + 11 L are the heaviest deferred load — `no-new-privileges`, capability drops, multi-stage refactor — all scheduled for v13.13+ infra milestone. |
| PostgreSQL | A | All 5 H closed via 4 new Alembic revisions (audit_logs, pg_trgm, refresh_tokens, HNSW). `alembic check` clean post-sweep. 7 M deferred are tuning + connection-budget polish. |
| Migrations | A | H-21 (alembic check noise) closed, plus migration-audit Mediums absorbed by H-08 closure (HNSW now in Alembic). 4 M + 4 L deferred are docs + tracked-design items. |
| API contract | A | All 3 H closed (PUT thumbnail breaking documented, layers-route slash collision fixed, /maps/icons shadowing fixed). SDK regenerated, openapi-check + sdks-check both green. |
| Documentation | A- | All 7 H closed — the largest doc remediation in the sweep (README first-dataset section, Manhattan Skyline, CONTRIBUTING tree, frontend widgets path, PyPI/npm metadata sweep). 6 M + 3 L deferred are next-polish items. The volume of doc Highs reflects pre-sweep public-launch-readiness gap, all addressed. |
| Admin / governance | A | H-01 (operator runbook stubs) closed. Admin surface is healthy; 4 M + 5 L deferred are convention/event polish. |
| Demo readiness | A | C-01 (README seed-bug) closed via dual fix (script extension + 4-locale README update). 4 M + 3 L deferred are next-docs polish. |
| Performance | A- | C-02 (tile SQL LIMIT + per-zoom simplification) and 5 H closed (embedding LRU, tile column allowlist, OGC/STAC limit cap, perf-marker coverage extension). New Alembic revision 0012; 14 perf tests (was 5). 8 M + 4 L deferred are tuning + parallelization opportunities. |
| i18n | A | H-20 (StyleJsonDialog wrap) closed in 4 locales with i18next plural conventions. 4 M + 2 L deferred — most are project-accepted English-fallback patterns from prior milestones. |
| Backend structure | A | H-05 (size-budget guard extension) closed. 3 M + 4 L deferred are LOC-threshold polish on routers/orchestrators. |
| Frontend structure | A | Type safety A pre-sweep; all 1183 tests passing pre-sweep; no Highs. 4 M + 5 L deferred are store-location and bundle-trimming polish. |
| Test health | A | All 4 H closed (E2E skips documented/removed, audit-spec script added, CI rationale documented, admin pages tested). 7 M + 4 L deferred are quality-sweep items. |

**Composite grade: A-** — weighted across 17 dimensions, with no dimension scoring below A-, no Critical or High remaining open, and meaningful deferred load (154 M+L) routed to documented follow-ups.

## Remediation Highlights

The most user-and-operator-impactful closures shipped this milestone:

- **Manifest local-path traversal closed (H-29)** — eliminated a server-side file-read primitive available to any user with `upload` permission. Three-layer defense: regex tightening, field validator, runtime `is_relative_to(upload_staging_dir)` check.
- **OAuth redirect_uri host-header injection closed (H-27)** — `_request_origin` no longer trusts attacker-controllable headers (`X-Forwarded-Host`, `Origin`, `Referer`) for OAuth flows. Explicit `PUBLIC_APP_URL` env var now required.
- **JWT secret default rejection (H-28)** — boot-time validator rejects the literal `dev-only-change-me-in-production` value (which exactly matched the 32-char length validator pre-fix); `.env.example` ships with empty `JWT_SECRET_KEY=`.
- **`.env.demo` boot guard (H-19)** — app refuses to boot with hardcoded demo credentials unless `GEOLENS_DEMO_MODE=true` is explicitly set.
- **OAuth email auto-link gated on `email_verified` (H-30)** — OIDC providers that don't verify emails can no longer be used to take over arbitrary local accounts.
- **README seed-natural-earth bug closed (C-01)** — public adopters can now run `seed-natural-earth.py --username admin --password admin` end-to-end. Single-command UX preserved across 4 README locales.
- **Tile SQL perf regression closed (C-02)** — `LIMIT 50000` + per-zoom simplification (extended from z<6 to z<10); perf coverage now spans z=0/2/4/8 against 500-polygon grid.
- **5 missing DB indexes added (H-06..H-10)** — audit_logs hot paths, pg_trgm GIN trigram on search columns, HNSW vector index in Alembic (was lazy-created in app code), refresh_tokens cleanup index, tile pool privilege-drop to `geolens_reader`.
- **Helm chart env reconciliation (H-32)** — Helm `secret.yaml` env var renamed `SECRET_KEY` → `JWT_SECRET_KEY` to match what the app actually reads; reconciliation test added to catch future drift.
- **Documentation gap closure (H-01, H-11..H-17)** — public operator runbook stubs landed, README has a working path between login and seeing data via `geolens init/validate/apply`, CONTRIBUTING.md project tree synced, all `geolens.io` references in PyPI/npm metadata replaced with owned `getgeolens.com`.
- **API contract cleanup (H-02..H-04)** — PUT `/maps/{id}/thumbnail/` body shape change documented in CHANGELOG as breaking; `/maps/{id}/layers` and `/maps/icons` route shadowing/slash collisions fixed; SDK regenerated; openapi-check and sdks-check both green.
- **Performance gates extended (H-22..H-25)** — embedding LRU cache (TTL 300s), per-dataset tile column allowlist (Alembic 0012), OGC/STAC limit capped to 200 with keyset cursor, perf-marker coverage now 14 endpoints (was 5).

## Outstanding Risks (Conditions)

Adopters and operators should be aware of the following before deploying or evaluating:

- **H-28 deployment requirement.** Local `.env` files using the rejected `JWT_SECRET_KEY=dev-only-change-me-in-production` value will fail boot post-H-28. Operators must regenerate via `openssl rand -hex 32`. This is a deployment configuration consideration, not a code-quality concern.
- **154 M+L findings deferred to post-launch.** Cross-audit duplicates noted in `.planning/audits/v13.12/DEFERRED-FINDINGS.md`; net "real" follow-up backlog after dedupes is roughly 100-110 unique items. Heaviest deferred surfaces are docker-audit (20 items — `no-new-privileges`, capability drops, multi-stage refactor) and perf-profile (12 items — tuning + parallelization). All routed to a v13.13+ hardening milestone.
- **Distribution gap is OUT OF SCOPE for v13.12.** Helm chart polish, SBOM, signed container images, and AMI publishing pipeline are NOT addressed by this milestone. See DIST-01..04 in `.planning/REQUIREMENTS.md` v2 section. Recommend a follow-up "v13.13 Distribution & Packaging" milestone for procurement-driven adopters.
- **Public repo recreation (OSS-01) is OUT OF SCOPE.** Tracked separately at `.planning/todos/pending/2026-05-05-recreate-public-repo-before-launch.md`. Must complete before public-release announcement.
- **CHANGELOG `[Unreleased]` is empty (M-06)** despite 10 added routes and the C-01/H-02 changes since v1.0.2. This is paperwork that should be filled in before tagging the next public release (v1.1.0 recommended given the H-02 breaking-change documentation).
- **E2E suite is local-only by design (H-35).** CI `e2e-test` job intentionally `if: false`; rationale documented in CONTRIBUTING.md. Operators evaluating the public-test surface should expect to run `npm run e2e:smoke:audit` locally to exercise the catch-all gate.

## Recommendation

**CONDITIONAL-GO: ship the public release announcement once the distribution-side prerequisites are complete; the codebase itself is audit-clean.**

All 39 Critical and High audit findings have been closed and verified by commit-hash and spot-check. Composite grade across 17 audit dimensions is A-, with no dimension scoring below A- and the strongest dimensions (open-core boundary, dependency posture, type safety) sitting at A+/A. Net-new C+H regression scan is clean: zero reverts, zero `BREAKING:` introductions, zero security-disabling commits in the v13.12 remediation range. The deferred load is well-characterized and routed to follow-up milestones with rationale.

The conditional qualifier reflects out-of-scope deployment prerequisites that are blockers for the public announcement (not for the codebase itself):

1. **Public repo must be recreated** per the existing `.planning/todos/pending/2026-05-05-recreate-public-repo-before-launch.md` plan. The current public repo holds pre-1.0.0 history that should not be the launch artifact.
2. **CHANGELOG `[Unreleased]` must be populated** with the v13.12 closures and tagged as v1.1.0 (the H-02 PUT thumbnail body breaking change forces minor-version bump).
3. **Adopter-facing release-notes blurb must surface H-28** (regenerate `JWT_SECRET_KEY` if your `.env` uses the example default — boot will fail otherwise).

These three items are documentation, packaging, and communication work — not code. The audit-and-remediation portion of the public-readiness gate is **GREEN**.

## Appendix: References

- Master Findings: [`.planning/audits/v13.12/FINDINGS-MASTER.md`](.planning/audits/v13.12/FINDINGS-MASTER.md)
- Re-Audit Verification: [`.planning/audits/v13.12/RE-AUDIT.md`](.planning/audits/v13.12/RE-AUDIT.md)
- Deferred Findings: [`.planning/audits/v13.12/DEFERRED-FINDINGS.md`](.planning/audits/v13.12/DEFERRED-FINDINGS.md)
- Phase 268 Summary: [`.planning/phases/268-security-and-infra-remediation/268-SUMMARY.md`](.planning/phases/268-security-and-infra-remediation/268-SUMMARY.md)
- Phase 269 Summary: [`.planning/phases/269-api-docs-code-perf-i18n-remediation/269-SUMMARY.md`](.planning/phases/269-api-docs-code-perf-i18n-remediation/269-SUMMARY.md)
- Original audit reports: `.planning/audits/v13.12/<skill>.md` (17 files)
