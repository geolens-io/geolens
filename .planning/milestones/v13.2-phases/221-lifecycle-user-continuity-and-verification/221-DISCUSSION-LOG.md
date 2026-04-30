# Phase 221: lifecycle-user-continuity-and-verification - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-30
**Phase:** 221-lifecycle-user-continuity-and-verification
**Areas discussed:** Re-onboarding mechanism, Conversion targets, oauth_accounts cleanup, Round-trip test design

**Mode:** User selected all four gray areas, then asked Claude to "choose reasonable best-practice defaults." Treated as `--auto`-style follow-through: Claude picked the recommended option for each area and recorded the rationale in CONTEXT.md.

---

## Re-onboarding mechanism (LIFECYCLE-06)

| Option | Description | Selected |
|--------|-------------|----------|
| Extend admin PATCH endpoint | Add `password` + `auth_provider` fields to existing `UserUpdate` schema. Smallest surface change but conflates a domain-critical conversion with field-level edits; broadens generic-update audit-log surface; security-negative (password in a generic PATCH body). | |
| Dedicated convert-auth endpoint | `POST /admin/users/{id}/convert-saml-to-local` — single-purpose, atomic transaction (validate → set password → flip auth_provider → delete oauth_accounts → write audit_log), single audit action `auth.convert_saml_to_local`, clean curl example for the runbook. | ✓ |
| CLI command only | Add `geolens admin user convert-saml-to-local` to the v13.1 CLI. No precedent for admin maintenance commands in that CLI; deferred. | |
| Runbook + SQL recipe | No new code; document a transactional SQL recipe. Brittle for a critical lifecycle path; no audit-log integration without manual SQL inserts. | |

**Selected:** Dedicated convert-auth endpoint.
**Rationale:** Single-purpose, atomic, narrow surface. Keeps password handling out of the generic-update audit-log surface (security positive). Gives the runbook a clean copy-paste curl example. SC#1's "documented procedure (runbook or CLI command)" is satisfied by runbook + curl.

---

## Conversion targets (LIFECYCLE-06)

| Option | Description | Selected |
|--------|-------------|----------|
| Local-password only | One canonical conversion target. Always available regardless of OIDC config state. OIDC mentioned in runbook as manual procedure (deferred for tooling). | ✓ |
| Both local and OIDC | Endpoint takes a `target` discriminator with two arms; tests cover both paths. Triples test surface. Requires picking target `oauth_provider_id` for OIDC, validating provider is configured. | |
| Local primary, OIDC documented | Same delivery as local-only; just frames OIDC as "alternative if you have one" in runbook. Functionally identical to local-only for v13.2 tooling. | |

**Selected:** Local-password only.
**Rationale:** Universally available; one tested path; satisfies LIFECYCLE-06's "local-password OR OIDC" inclusive disjunction. OIDC re-link is documented in the runbook appendix as a manual SQL+OAuth-flow procedure for operators with an existing OIDC provider; automating it is in deferred ideas.

---

## oauth_accounts cleanup on conversion (LIFECYCLE-06)

| Option | Description | Selected |
|--------|-------------|----------|
| Delete the linkage row | Clean break — user is purely local after conversion. The `oauth_providers` SAML row stays (other users may still link to it). Audit log preserves the historical fact of the conversion. | ✓ |
| Preserve for re-link | Leave the `oauth_accounts` row alive; admin re-flips on reactivation. Creates ambiguous state: `auth_provider='local'` + live `oauth_accounts` is a contradiction the system has no policy for. | |
| Soft-delete | Add a `disabled_at` column or similar marker. Schema change for a v13.2 deliverable; overkill. | |

**Selected:** Delete the linkage row (clean break).
**Rationale:** Avoids ambiguous post-conversion state. Reverse conversion (local → SAML) is an explicit deferred backlog item, not an automatic re-link on reactivation. The audit_log entry preserves the historical fact; we don't need the join-table row as a tombstone.

---

## Round-trip test design (LIFECYCLE-07)

| Option | Description | Selected |
|--------|-------------|----------|
| Extend test_lifecycle.py with second test fn | Per Phase 220's deferred recommendation. Three test functions total: deactivate-only (Phase 220), conversion (Phase 221 LIFECYCLE-06), round-trip (Phase 221 LIFECYCLE-07). Shared fixtures; clear intent per function. | ✓ |
| New file | `test_lifecycle_roundtrip.py`. Splits closely-related concerns; loses fixture sharing convenience. | |
| Parametrize existing test | Parametrize `test_overlay_removal_preserves_saml_data` over deactivate-only and round-trip. Obscures that round-trip has different setup (re-registration) and different post-conditions. | |

**Selected:** Extend test_lifecycle.py with a second test function (and a third for the conversion test). Audit-trail assertion uses a SEEDED `audit_log` row (not just FK reflection).
**Rationale:** Phase 220 CONTEXT.md explicitly recommends co-location. Three discrete test functions keep each contract crystal clear. A seeded `audit_log` row gives real end-to-end coverage of LIFECYCLE-07's "audit trail intact" requirement; without it the assertion is vacuous.

---

## Claude's Discretion

User explicitly delegated default-picking ("Choose reasonable, best-practice defaults for all your questions"). Beyond the four gray areas above, the following were resolved at Claude's discretion and recorded in CONTEXT.md `Claude's Discretion`:

- Frontend admin UI affordance shape (deferred to a polish phase; track button + modal + endpoint-call shape)
- Validation logic for non-SAML users hitting the conversion endpoint (422 with clear detail)
- Password complexity (`min_length=8` matching existing `UserCreate.password`)
- Curl example token-acquisition steps in the runbook (single curl with `$TOKEN` placeholder + a one-line "obtain via /auth/token" note)
- Cleanup-fixture extension robustness (delete in dependency order; trust SET NULL FK semantics where possible)
- Audit-log action catalog hygiene (register `auth.convert_saml_to_local` in a central enum if one exists; otherwise string literal at call site)
- Self-conversion guard (block `current_user.id == user_id` to prevent admin self-lockout fat-finger)

---

## Deferred Ideas

(Mirrored to CONTEXT.md `<deferred>` section.)

- Frontend admin UI affordance for the conversion endpoint (polish phase, likely v14+)
- OIDC conversion tooling (endpoint or CLI) — out of v13.2; defer until manual-procedure volume justifies automation
- Reverse conversion (local → SAML on reactivation) — out of v13.2
- CLI subcommand `geolens admin user convert-saml-to-local` — out of v13.2
- Audit-log action-name catalog enum — out of v13.2 hygiene improvement
- Conversion History admin UI surface (filtered audit-log view) — out of Phase 221
- Compose-stack-swap fidelity for round-trip test — Phase 220 carry-over, still deferred
- `is_enterprise()` gating on registry accessors — Phase 220 carry-over, still deferred
- Audit-log entry on `init_edition()` transitions — Phase 220 carry-over, still deferred
- Doc-test for `docs/saml.md` SC#3 — Phase 220 carry-over, still deferred
