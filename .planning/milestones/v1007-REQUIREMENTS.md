# Requirements: v1007 Release Hygiene

**Defined:** 2026-05-12
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

## Milestone Goal

Close release hygiene after v1006 by proving the repository is scanner-clean, generated artifacts are current, the local stack is healthy, Playwright smoke is robust without hidden seed assumptions, and temporary UAT data no longer pollutes browser verification.

## Constraints

- Do not add product capability scope beyond release hygiene.
- Do not change persisted product schemas.
- Keep generated OpenAPI/SDK artifacts aligned with current backend routes.
- Treat temporary local data cleanup as environment hygiene, not user data migration.
- Keep E2E fixes deterministic and self-contained.

## v1007 Requirements

### Dependency And Security Hygiene

- [x] **REL-01**: Verify open Dependabot alerts against manifests, lockfiles, and local dependency scanners.
- [x] **REL-02**: Backend security, lint, format, and full coverage gates pass.
- [x] **REL-03**: Frontend i18n, changed-namespace, lint, typecheck, and coverage gates pass.

### Generated Artifact Hygiene

- [x] **REL-04**: OpenAPI snapshot reflects current backend routes.
- [x] **REL-05**: Python and TypeScript SDK generated artifacts reflect current OpenAPI output.

### Runtime And Browser Hygiene

- [x] **REL-06**: Docker Compose stack reaches a healthy `up --wait` state.
- [x] **REL-07**: Root Playwright smoke passes across core, builder, and fixture flows.
- [x] **REL-08**: Playwright MCP live browser sanity passes with a clean current-page console.
- [x] **REL-09**: Known temporary UAT/smoke datasets are removed from authenticated local catalog results.

### Closeout

- [x] **REL-10**: Milestone artifacts document evidence, fixes, caveats, and follow-up expectations.

## Traceability

| Requirement | Phase | Status |
|---|---|---|
| REL-01 | Phase 1032 | Complete |
| REL-02 | Phase 1032 | Complete |
| REL-03 | Phase 1032 | Complete |
| REL-04 | Phase 1032 | Complete |
| REL-05 | Phase 1032 | Complete |
| REL-06 | Phase 1032 | Complete |
| REL-07 | Phase 1032 | Complete |
| REL-08 | Phase 1032 | Complete |
| REL-09 | Phase 1032 | Complete |
| REL-10 | Phase 1032 | Complete |

**Coverage:**
- v1007 requirements: 10 total
- Complete: 10
- Pending: 0
- Mapped to phases: 10
- Unmapped: 0

---
*Requirements defined: 2026-05-12*
*Last updated: 2026-05-12 after Phase 1032 completion*
