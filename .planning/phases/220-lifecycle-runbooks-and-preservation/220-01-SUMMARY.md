---
phase: 220-lifecycle-runbooks-and-preservation
plan: 01
status: complete
completed: 2026-04-30
---

# Plan 220-01 — deactivation-runbook — SUMMARY

## What shipped

Authored `docs/edition-deactivation.md` (186 lines, 10 sections) — the canonical operator runbook for the enterprise→community downgrade. Closes LIFECYCLE-01 (pre-flight + sequence + env-var defense-in-depth labeling + data-fate matrix) and LIFECYCLE-05 (destructive alembic path documented with mandatory `pg_dump` pre-step). The runbook is the cross-link target for the saml.md edit shipping in plan 220-03.

## Key files created

- `docs/edition-deactivation.md` — top-level operator runbook (no `docs/lifecycle/` subdir, per D-07).

## Section structure

1. Title + audience callout
2. At-a-glance table
3. Why overlay-removal is the canonical lever (D-01 architectural rationale)
4. Data-fate matrix (oauth_providers / oauth_accounts / users / audit / CHECK constraint × safe vs destructive)
5. Pre-flight checklist (snapshot pg_dump, SAML inventory, user comms with Phase 221 TODO marker, maintenance window, sandbox restore confirmation)
6. Deactivation sequence (canonical path) — 6 steps with worker-symmetry callout
7. Database state after the safe path (deferred-column behavior explained)
8. Destructive path: permanent decommissioning — enumerates `e002.downgrade()` deletion order verbatim, with mandatory pre-step `pg_dump` block
9. Audit log limitation (current-state callout)
10. References

## Verification (all passed)

12 grep assertions from VALIDATION.md LIFECYCLE-01 + LIFECYCLE-05 blocks:

- `pre-flight` ✓
- `pg_dump` ✓
- `oauth_providers` ✓
- `docker compose down` ✓
- `GEOLENS_EDITION` ✓
- `defense-in-depth` ✓
- `destructive` ✓
- `mandatory` / `required` ✓
- `edition-reactivation` ✓
- `(saml.md)` (markdown link literal) ✓
- `data-fate` (lowercase, regex-friendly without `-i`) ✓
- Destructive-path deletion order matches `e002.downgrade()` exactly: `oauth_accounts` DELETE → `oauth_providers` DELETE → CHECK drop → CHECK recreate → 4 columns drop ✓

## Decision compliance

- D-01: overlay-removal labeled canonical; `GEOLENS_EDITION=community` labeled defense-in-depth (with explicit "incomplete deactivation" callout for env-var-only).
- D-02: destructive `alembic downgrade -1` documented with mandatory `pg_dump` pre-step. NO non-destructive `e003`-style path proposed.
- D-07: top-level `docs/edition-deactivation.md` placement.

## Deviations

None.

## Self-Check: PASSED
