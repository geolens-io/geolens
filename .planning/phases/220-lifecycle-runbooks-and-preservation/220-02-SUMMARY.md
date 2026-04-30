---
phase: 220-lifecycle-runbooks-and-preservation
plan: 02
status: complete
completed: 2026-04-30
requirements_completed: [LIFECYCLE-02]
---

# Plan 220-02 — reactivation-runbook — SUMMARY

## What shipped

Authored `docs/edition-reactivation.md` (75 lines) — a thin operator runbook for the community→enterprise re-upgrade. Closes LIFECYCLE-02. Per RESEARCH.md A3 + CONTEXT.md Claude's Discretion: the doc does not duplicate the saml.md activation walkthrough; it links to it and focuses on the 5-step post-reactivation verification checklist.

## Key files created

- `docs/edition-reactivation.md` — top-level operator runbook (no `docs/lifecycle/` subdir, per D-07).

## Section structure

1. Title + audience callout (delegates first-time activation to saml.md)
2. One-paragraph orientation (re-upgrade is structurally inverse of deactivation; data persists physically due to `deferred=True`)
3. Re-mount the overlay (3-line bash block + link to saml.md Installation for full context)
4. Post-reactivation verification checklist (5 verifiable checks)
5. End-to-end smoke test (1-line manual login walkthrough)
6. Why this works (architectural rationale)
7. References

## Verifiable checks the runbook prescribes

1. SAML routes mounted (`curl /openapi.json | jq …`)
2. Enterprise overlay loaded (`docker compose logs api | grep 'loaded extension'`)
3. Pre-deactivation SAML providers re-appear in admin UI
4. Schema confirmation: 4 `deferred=True` columns present (`information_schema.columns` query)
5. SAML provider row count matches pre-deactivation `pg_dump` snapshot

## Verification (all passed)

- File exists ✓
- `verify` / `verification` ✓
- `/auth/saml` ✓
- `edition-deactivation` cross-link ✓
- `oauth_providers` ✓
- `deferred` ✓
- Line count: 75 ≤ 120 (thin runbook discipline) ✓

## Decision compliance

- D-07: top-level `docs/edition-reactivation.md` placement.
- A3 (RESEARCH.md recommendation): thin runbook; activation reference goes through saml.md, not duplicated.

## Deviations

None.

## Self-Check: PASSED
