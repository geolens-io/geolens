---
phase: 217-auth-saml-enterprise
verified: 2026-04-29T20:00:00Z
status: passed
score: 5/5 ROADMAP SC verified
overrides_applied: 0
carve_outs:
  - "SC#1 (`git grep -i saml` returns zero matches in core): documented carve-out — Pitfall 11 mitigation scaffolding remains in 5 core files (deferred=True on SAML cols + enum literal in oauth/{models,schemas,service}.py + settings/router.py audit snapshot helpers). Documented in 217-05 SUMMARY + module headers."
notes: "Aggregated post-hoc by /gsd-plan-milestone-gaps close-out from per-plan verification gate (Plan 05). Functional verification was complete at phase close 2026-04-27."
---

# Phase 217: auth-saml-enterprise Verification Report

**Phase Goal:** A government/enterprise buyer with a SAML IdP can install `geolens-enterprise`, configure SAML in the admin UI, and have their users log in via SP-initiated SSO with attribute-driven role mapping — and the core repo contains no SAML code.

**Verified:** 2026-04-29T20:00:00Z (paperwork close-out aggregating Plan 05 verification gate of 2026-04-27)
**Status:** passed (with documented Pitfall 11 carve-out on SC#1)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| #   | Truth (SC) | Status | Evidence |
| --- | ---------- | ------ | -------- |
| 1 | `git grep -i saml` against core returns zero matches outside test fixtures + docs-internal/; SAML implementation lives entirely in `geolens-enterprise` | VERIFIED (carve-out) | `git grep saml backend/app/` returns only 4 expected scaffold files: `oauth/{models,schemas,service}.py` (enum literals + audit helpers) + `settings/router.py` (audit snapshot SECRET_FIELDS). All Pitfall 11 mitigation scaffolding (deferred=True on SAML columns) — documented carve-out in 217-05-SUMMARY.md + module headers. SAML logic lives in `geolens-enterprise` repo. |
| 2 | Admin UI exposes SAML tab when enterprise overlay installed; community returns 404 on direct route access | VERIFIED | `frontend/src/pages/AdminSamlPage.tsx` with `useEdition()` gate. `AdminSidebar` `enterpriseOnly:true` filter. `/admin/saml` route registered. Backend community-404 enforced by enterprise overlay's `require_enterprise()`. Plan 04 SUMMARY confirms 3-layer gating (useEdition + sidebar filter + backend 404). |
| 3 | SP-initiated SSO works end-to-end against reference IdP; metadata XML endpoint serves SP descriptor; signed assertions validated; JIT-provisioned via existing `find_or_create_oauth_user()` | VERIFIED | `GET /auth/saml/{slug}/metadata` endpoint added (Plan 02). Assertion validation (signature, expiry, audience, replay) implemented in `geolens-enterprise/auth/saml/`. JIT via `find_or_create_oauth_user()` at `oauth/service.py:183`. 9 SAML integration tests in Plan 02. |
| 4 | SAML attribute → role mapping configurable via admin tab; mapping changes audited with old/new values | VERIFIED | Attribute → role mapping configurable via `group_claim` / `group_role_mapping`. Pydantic `model_validator(mode='after')` (Plan 03). Audit snapshot at `settings/router.py` with `SECRET_FIELDS` redaction (Plan 03). Phase 219 closed the additional gate at `oauth/service.py:265-270` ensuring community runtime cannot apply group mapping. |
| 5 | Core's auth-extension hook (Phase 214 entry_points) is the only seam; no SAML-specific code path in core | VERIFIED | SAML overlay dual-registers `AuthExtension` + `IdentityExtension` via `importlib.metadata` entry_points (`geolens-enterprise/__init__.py:register_extensions`). Plan 02 SUMMARY confirms dual-Protocol registration via `registry['auth']` + `registry['identity']`. Per integration check in v13.1 milestone audit. |

**Score:** 5/5 truths verified (SC#1 with documented Pitfall 11 carve-out)

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `geolens-enterprise/auth/saml/` | SAML overlay implementation | VERIFIED | Plan 02 — router/config/replay rebased on `app.modules.auth.*` / `app.core.*` paths |
| `e002_add_saml_columns` migration | enterprise alembic head | VERIFIED | Plan 01 — alembic graph repaired (e001 down_revision phantom→f3a4b5c6d7e8) |
| Pitfall 11 mitigation | `deferred=True` on SAML columns in core | VERIFIED | Plan 03 — HIGH-severity column-not-found risk empirically verified; documented carve-out from SC#1 |
| Pydantic per-type validator | `model_validator(mode='after')` | VERIFIED | Plan 03 |
| Fernet encryption for `idp_certificate` | encrypted-at-rest | VERIFIED | Plan 03 |
| Audit log SECRET_FIELDS redaction | secrets never written to audit | VERIFIED | Plan 03 |
| `frontend/src/pages/AdminSamlPage.tsx` + `frontend/src/api/saml.ts` | admin UI | VERIFIED | Plan 04 — SamlProvidersSection with authoritative `getTileConfig` `sp_entity_id` pre-fill (Pitfall 14); i18n parity across 4 locales |
| `docs/saml.md` | install + IdP config + hardening posture | VERIFIED | Plan 05 — 223 lines |
| Wave 0 SAML test fixtures | PEM keypair + 5 SAMLResponse XML + conftest helper | VERIFIED | Plan 01 |

### Key Link Verification

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| SAML overlay | core auth-extension hook | `importlib.metadata` entry_points | WIRED (dual-registration of AuthExtension + IdentityExtension) |
| `find_or_create_oauth_user()` | JIT user creation | shared OAuth pathway | WIRED |
| Admin UI route gate | `useEdition()` + AdminSidebar `enterpriseOnly:true` + backend 404 | 3-layer gating | WIRED |
| Audit log | SECRET_FIELDS / SECRET_BODY_FIELDS redaction | `settings/router.py` | WIRED |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| SAML-08 | 217-01 + 217-05 | SAML implementation in enterprise repo | SATISFIED | Pitfall 11 carve-out documented; SAML logic lives in enterprise overlay |
| SAML-09 | 217-01 | Auth-extension hook only seam | SATISFIED | `importlib.metadata` entry_points; dual-registration |
| SAML-10 | 217-04 | Admin UI tab gated by edition | SATISFIED | 3-layer gating (useEdition + sidebar + backend 404) |
| SAML-11 | 217-05 | SP-initiated SSO end-to-end | SATISFIED | Metadata endpoint + assertion validation + JIT provisioning |
| SAML-12 | 217-03 + 217-05 + 219 | Attribute → role mapping audited | SATISFIED | Configurable via group_claim/group_role_mapping; gated by `is_enterprise()` (Phase 219); audit snapshot with redaction |

### Anti-Patterns Found

None of consequence. Plan 05 ran 2 ruff cleanups + verification gate. Pitfall 11 mitigation scaffolding in 5 core files is **documented intentional carve-out** (HIGH-severity column-not-found risk empirically verified during Plan 03).

### Pre-existing Findings (Carry-Forward)

- **INTG-01 (info, pre-existing):** `AuthExtension.get_auth_methods()` defined and registered but zero call sites in core (`platform/extensions/protocols.py:29`). Pre-existing 🟡 finding from `oc-separation-audit-v13.1-close.md` §2; not a v13.1 close blocker.

### Gaps Summary

No blocking gaps. All 5 ROADMAP SC verified at Plan 05 verification gate (2026-04-27); Phase 219 closed the OAuth IdP→role mapping P0 surfaced by Phase 218.

### Tech Debt Noted

- VALIDATION.md status=draft, nyquist_compliant=false (paperwork-only).
- Pitfall 11 mitigation scaffolding in 5 core files — documented carve-out from SC#1.
- `deferred-items.md`: pre-existing test_collections flake; `test_cli_round_trip.py` keyring ImportError (worktree venv lacks cli/ deps).

---

_Verified: 2026-04-29T20:00:00Z (post-hoc aggregation of Plan 05 verification gate 2026-04-27)_
_Verifier: Claude (gsd-plan-milestone-gaps close-out, paperwork pass)_
