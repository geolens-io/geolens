---
phase: 220-lifecycle-runbooks-and-preservation
plan: 03
status: complete
completed: 2026-04-30
requirements_completed: [LIFECYCLE-03]
---

# Plan 220-03 — saml-doc-edit — SUMMARY

## What shipped

Surgical edit to `docs/saml.md` Installation section (D-03; LIFECYCLE-03):

- **Replaced** the legacy "The migration is reversible (`alembic downgrade -1`...) — back up first." line at saml.md:48 with a 9-line blockquote callout that points operators at `docs/edition-deactivation.md` as the canonical deactivation path and labels the alembic-downgrade path destructive with a mandatory `pg_dump` pre-step.
- **Added** a new `### Deactivating SAML` subsection (4 lines) at the end of the Installation section, immediately before `## IdP Configuration`, summarizing the safe path and linking to the runbook.

Total diff: 13 insertions, 1 deletion. All other sections of saml.md (IdP Configuration, Hardening defaults, Troubleshooting, Audit, Security Posture) are byte-identical to the pre-edit state.

## Verification (all passed)

- Negative: `grep -E 'migration is reversible.*alembic downgrade' docs/saml.md` → 0 matches ✓
- Positive: `grep -c 'edition-deactivation.md' docs/saml.md` → 2 (callout + subsection) ✓
- Positive: `grep -q -i 'destructive' docs/saml.md` ✓
- Positive: `grep -q 'Deactivating SAML' docs/saml.md` ✓
- Positive: `grep -q 'pg_dump' docs/saml.md` ✓
- Diff size: 14 total lines (13+1) < 35 line budget — confirms surgical scope ✓

## Decision compliance

- D-03: targeted edit only (one bullet replaced + one short subsection added).
- LIFECYCLE-03: saml.md no longer presents `alembic downgrade -1` as the primary deactivation path; cross-link to runbook is in place; alembic path explicitly labeled destructive with mandatory pre-export step.

## Deviations

None.

## Self-Check: PASSED
