---
phase: 221-lifecycle-user-continuity-and-verification
plan: 02
subsystem: docs
tags: [runbook, saml, lifecycle, edition-deactivation, edition-reactivation]

requires:
  - phase: 220-lifecycle-runbooks-and-preservation
    provides: edition-deactivation.md scaffold with line-81 TODO marker; edition-reactivation.md scaffold with smoke-test section
  - phase: 221-01
    provides: POST /admin/users/{user_id}/convert-saml-to-local/ endpoint, audit action `auth.convert_saml_to_local`, allow-listed details {from, to, provider_slug}, self-conversion 422 guard
provides:
  - Operator-facing "Handling existing SAML users" section in docs/edition-deactivation.md (6 substeps + OIDC manual-procedure appendix)
  - Forward-pointer "Note on previously converted SAML users" section in docs/edition-reactivation.md
  - Removal of Phase 220's line-81 TODO marker and replacement with anchor link + "convert AFTER overlay removal" ordering note
affects: [221-03 (UAT runbook references the new section), v13.2 release notes]

tech-stack:
  added: []
  patterns:
    - Verification-by-grep discipline for runbook edits (positive + negative greps)
    - Trailing-slash convention applied to documented curl examples (Pitfall 4)
    - Allow-list discipline for audit-log details documentation (no password material referenced anywhere)

key-files:
  created: []
  modified:
    - docs/edition-deactivation.md (replaced lines 79-81 TODO blockquote; inserted ~92-line "Handling existing SAML users" section between "Database state after the safe path" and "Destructive path")
    - docs/edition-reactivation.md (inserted 5-line "Note on previously converted SAML users" section between "End-to-end smoke test" and "Why this works")

key-decisions:
  - "Curl example uses /auth/login/ form-data login (NOT /auth/token) per Pitfall 5 — verified against backend/tests/conftest.py:328-334"
  - "All endpoint URLs in the runbook end with trailing slash (/convert-saml-to-local/) per Pitfall 4 to avoid FastAPI 307 redirect dropping JSON body"
  - "Ordering note uses two surfaces: forward-link replacing line 81 says 'after the overlay is removed', and the new section's preamble blockquote restates 'Run conversions AFTER the overlay is removed' — both surfaces agree (Pitfall 8)"
  - "Self-conversion guard surfaced as a > **Self-conversion is blocked.** callout in Step 3 with the exact 422 detail string ('Cannot convert your own account; use a different admin account') matching the implementation in router.py:282 (T-221-01)"
  - "Audit-log allow-list documented explicitly as {from, to, provider_slug} with explicit 'Password material is never logged' sentence — negative grep enforces no `details.*\"password\"` patterns appear (T-221-03)"

patterns-established:
  - "Pattern: in-place TODO replacement with anchor link to new section keeps the original content placement coherent while the new procedural content lives in its proper structural location"
  - "Pattern: cross-document symmetry — both runbooks reference each other and both reference the same endpoint, audit-action name, and procedural ordering"

requirements-completed: [LIFECYCLE-06]

duration: 8m
completed: 2026-04-30
---

# Phase 221 Plan 02: lifecycle-user-continuity-and-verification Summary

**Replaced Phase 220's line-81 TODO marker in docs/edition-deactivation.md with a real, copy-paste-able 6-step "Handling existing SAML users" runbook section, and added a forward-pointer to docs/edition-reactivation.md noting that local-password conversions persist after reactivation.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-04-30T12:20:00Z
- **Completed:** 2026-04-30T12:28:43Z
- **Tasks:** 2 / 2
- **Files modified:** 2

## Accomplishments

- Phase 220's line-81 TODO blockquote ("Phase 221 ships the user re-onboarding procedure") is gone from the repo, replaced by a forward-link with the explicit "convert AFTER overlay removal" ordering note (Pitfall 8).
- New top-level `## Handling existing SAML users` section in `docs/edition-deactivation.md` walks operators through inventory → decide → convert → communicate → verify → audit-confirm with copy-paste-able curl examples that hit the endpoint Plan 221-01 shipped (`/admin/users/{user_id}/convert-saml-to-local/`).
- OIDC conversion documented as a manual two-step procedure in an appendix; automated OIDC support flagged as deferred.
- Self-conversion 422 guard, audit-log action name (`auth.convert_saml_to_local`), and allow-listed details (`{from, to, provider_slug}`) are all surfaced verbatim in the runbook so the doc and the code are exactly in sync.
- New `## Note on previously converted SAML users` section in `docs/edition-reactivation.md` warns operators that local-password conversions persist after reactivation and names two manual reverse-conversion options for operators who need them today.

## Task Commits

Each task was committed atomically:

1. **Task 1: Replace line-81 TODO and add Handling existing SAML users section** — `f0deb739` (docs)
2. **Task 2: Add Note on previously converted SAML users to edition-reactivation.md** — `bffacb5c` (docs)

## Files Created/Modified

- `docs/edition-deactivation.md` — Replaced lines 79-81 TODO blockquote with a one-line forward-link plus ordering note; inserted new `## Handling existing SAML users` section (6 substeps + OIDC appendix) between `## Database state after the safe path` (line 138) and `## Destructive path: permanent decommissioning` (line 238). Net diff: +97 / -3.
- `docs/edition-reactivation.md` — Inserted new `## Note on previously converted SAML users` section between `## End-to-end smoke test` (line 64) and `## Why this works` (line 74). Net diff: +6.

## Decisions Made

- **Anchor link in §pre-flight step 3 instead of inlining the procedure there:** keeps the pre-flight step short while the full procedure lives in its structurally correct location (after the canonical-path section, before the destructive-path section). This also makes the forward-link easy to find via positive grep for `handling-existing-saml-users`.
- **Two surfaces both state the ordering rule:** the forward-link at step 3 says "convert each user *after* the overlay is removed" AND the new section's preamble blockquote says "Run conversions AFTER the overlay is removed". Pitfall 8 mitigation lives at both points so an operator skimming either surface sees it.
- **Curl example uses concrete localhost URLs, not `https://geolens.example.com` placeholders:** matches the conftest test pattern verbatim (Pitfall 5) and gives operators something they can run against a local dev stack to dry-run the procedure before executing in production.
- **No `geolens-enterprise` token mentioned in the deactivation runbook curl example:** the conversion endpoint is core (community + enterprise both ship it via Plan 221-01), and the runbook is intentionally on-prem-focused — admins use their existing local-password admin credentials (`GEOLENS_ADMIN_USERNAME` / `GEOLENS_ADMIN_PASSWORD` per project memory) to obtain a JWT.

## Deviations from Plan

None — plan executed exactly as written. Both task `<action>` blocks specified the exact section content verbatim, both `<verify>` automated greps passed on first run, and both `<acceptance_criteria>` blocks (positive + negative + preservation greps + section-ordering check) passed without adjustment.

## Issues Encountered

None.

## Threat Surface

All five Plan 02 STRIDE threats from the plan's `<threat_model>` have a concrete, grep-checkable mitigation:

| Threat ID | Mitigation Location |
|-----------|---------------------|
| T-221-01 (self-conversion lockout) | Step 3 `> **Self-conversion is blocked.**` callout (positive grep `self-conversion is blocked` passes) |
| T-221-03 (audit-log password disclosure) | Step 3 explicit "Password material is never logged"; Step 6 `details` allow-list documented as `{from, to, provider_slug}` only; negative grep `details.*"password"` returns nothing |
| T-221-04 (SAML-login race) | Two surfaces both state "convert AFTER overlay removed" (forward-link + section preamble blockquote) |
| T-221-PITFALL-4 (trailing-slash 307) | All curl examples include trailing slash on `/convert-saml-to-local/` and `/auth/login/` |
| T-221-PITFALL-5 (wrong token endpoint) | Token-acquisition curl uses `/auth/login/` form-data; negative grep `/auth/token` returns nothing |

No new threat surface introduced by this plan beyond what the plan's threat model already enumerated.

## User Setup Required

None — pure documentation edits to existing operator-facing runbooks; no environment variables, no service configuration, no migration.

## Next Phase Readiness

- Plan 221-03 (UAT + verification) can reference the new `## Handling existing SAML users` section directly via the anchor `#handling-existing-saml-users` for the manual UAT walkthrough.
- All LIFECYCLE-06 SC#2 (docs surface) acceptance criteria met; combined with Plan 221-01's endpoint shipping the SC#1 (procedure) acceptance criteria, LIFECYCLE-06 is now fully addressed pending UAT verification in Plan 221-03.
- No blockers.

## Self-Check: PASSED

- `docs/edition-deactivation.md` — FOUND, contains `## Handling existing SAML users` heading and the new section content (verified by positive greps).
- `docs/edition-reactivation.md` — FOUND, contains `## Note on previously converted SAML users` heading and the new section content (verified by positive greps).
- Commit `f0deb739` — FOUND in `git log --oneline` (Task 1).
- Commit `bffacb5c` — FOUND in `git log --oneline` (Task 2).
- Negative greps (TODO removed, `/auth/token` absent, `manually via the admin UI` absent) all returned non-zero as required.
- Section ordering verified for both files: deactivation runbook has new section between Database-state and Destructive-path; reactivation runbook has new section between End-to-end-smoke-test and Why-this-works.

---

*Phase: 221-lifecycle-user-continuity-and-verification*
*Completed: 2026-04-30*
