---
phase: 212
slug: core-settings-decouple
status: verified
threats_open: 0
asvs_level: 1
created: 2026-04-27
---

# Phase 212 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| `core/` → `modules/settings/` (BEFORE) | Pre-existing layering inversion that this phase removed | n/a (boundary now closed) |
| `core/` → `core/db/` (AFTER) | All AppSetting consumers depend on a peer file inside `core/`; same trust level | ORM metadata only |
| Developer ↔ CI architecture guard | `architecture` pytest marker is opt-out; CI default invocation includes the guard | n/a (test surface) |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-212-01 | Tampering | All 9 caller files + `backend/alembic/env.py` (stale-import / runtime ImportError) | mitigate | `git grep` gates verify ZERO matches on old path AND exactly 11 matches on new path; `alembic check` runs clean for `app_settings`; full pytest 1999/1999 PASS proves runtime imports resolve | closed |
| T-212-02 | Elevation of Privilege | Architecture guard bypass | mitigate | `architecture` marker is opt-out (CI runs `-m 'not perf'`, includes architecture by default); regex anchored to `^\s*(from\|import)` catches all reasonable re-introductions; negative-test discipline in Plan 03 Step 4 confirmed guard fires; `_has_git_metadata()` skip is documented safety-belt, not primary control | closed |
| T-212-03 | Informational | New `core/db/models.py` module + relocation overall | accept | No new external attack surface — table schema (`__tablename__`/`__table_args__`), API endpoints, auth flows all byte-identical pre/post relocation. SQLAlchemy identifies tables by metadata, not module path. | closed |
| T-212-03 (Plan 03 instance) | Informational | `_has_git_metadata()` skip in `test_layering.py` | accept | If CI runner lacks `.git/`, test skips rather than fails. Acceptable because (a) GitHub Actions `actions/checkout@v4` always provides `.git/`, (b) Phase 218 audit re-run is the ultimate proof, (c) `.dockerignore` absent so docker-compose-based tests see `.git/`. | closed |
| T-212-01 (Plan 04 carryover) | Tampering | Verification gate itself (false-pass risk) | mitigate | Each verification command is independently re-runnable against the live tree (`alembic check`, full pytest, ruff, `git grep`); 212-04 SUMMARY records exit codes and stdout excerpts; Phase 218 audit re-run provides final proof | closed |
| T-212-02 (Plan 04 carryover) | Elevation | Phase exit without running verification gate | accept | `/gsd-verify-work` catches missing SUMMARY artifact; Phase 218 audit re-run catches re-introduced finding; controls are layered, not single-point. | closed |
| T-212-03 (Plan 04 instance) | Informational | Plan 04 modifies no production files | accept | Verification-only plan; no runtime change. | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-212-01 | T-212-03 (Plan 01/02) | Pure import-path relocation; SQLAlchemy table identity preserved by `__tablename__`+`__table_args__`; no new external surface | author (via PLAN.md) | 2026-04-27 |
| AR-212-02 | T-212-03 (Plan 03) | `_has_git_metadata()` skip is safety-belt; CI runners (GitHub Actions, docker-compose) all provide `.git/` | author (via PLAN.md) | 2026-04-27 |
| AR-212-03 | T-212-02 (Plan 04) | Layered controls: missing-SUMMARY guard + Phase 218 audit re-run catch any phase-exit bypass | author (via PLAN.md) | 2026-04-27 |
| AR-212-04 | T-212-03 (Plan 04) | Verification-only plan modifies no production files | author (via PLAN.md) | 2026-04-27 |

*Accepted risks do not resurface in future audit runs.*

---

## Mitigation Verification (for `mitigate` disposition threats)

| Threat | Control | Evidence |
|--------|---------|----------|
| T-212-01 (Plans 01/02) | Test suite + alembic check + git grep gates | 212-VERIFICATION.md SC #1–#5 all PASS; 1999/1999 tests green; `git grep "from app\.modules\.settings"` against `backend/app/core/` returns zero matches |
| T-212-02 (Plan 03) | Architecture guard test + opt-out marker | `backend/tests/test_layering.py:test_core_does_not_import_from_settings_module` exists, runs in CI default invocation, passes; `pyproject.toml` line 74 registers `architecture` marker; `addopts = "-m 'not perf'"` line 70 does NOT exclude `architecture` |
| T-212-01 (Plan 04 carryover) | Verification gate evidence file | `212-04-SUMMARY.md` records exit codes and command stdout for the 4 gate checks (alembic check, pytest, ruff, ROADMAP SC verification) |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-04-27 | 7 | 7 | 0 | Claude (gsd-secure-phase, State B) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-04-27
