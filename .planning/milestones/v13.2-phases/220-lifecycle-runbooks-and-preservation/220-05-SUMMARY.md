---
phase: 220-lifecycle-runbooks-and-preservation
plan: 05
status: complete
completed: 2026-04-30
requirements_completed: [LIFECYCLE-04]
---

# Plan 220-05 — requirements-precision-fix — SUMMARY

## What shipped

Two single-line edits that align the LIFECYCLE-04 wording with schema truth (the 4 SAML columns are on `catalog.oauth_providers`, not on `users`).

| File | Line | Before | After |
|---|---|---|---|
| `.planning/REQUIREMENTS.md` | 24 | `… the 4 \`deferred=True\` SAML columns on \`User\` …` | `… the 4 \`deferred=True\` SAML columns on \`oauth_providers\` …` |
| `.planning/ROADMAP.md` | 80 | `… 4 \`deferred=True\` User columns are intact …` | `… 4 \`deferred=True\` \`oauth_providers\` columns are intact …` |

## Verification (all passed)

- Positive: `grep 'the 4 \`deferred=True\` SAML columns on \`oauth_providers\`' .planning/REQUIREMENTS.md` ✓
- Positive: `grep '4 \`deferred=True\` \`oauth_providers\` columns' .planning/ROADMAP.md` ✓
- Negative: legacy `SAML columns on \`User\`` absent in REQUIREMENTS.md ✓
- Negative: legacy `4 \`deferred=True\` User columns` absent in ROADMAP.md ✓
- Diff scope: 1+1 in each file (single-line replace; total 4 lines) ✓

## Decision compliance

- CONTEXT.md Claude's Discretion (recommendation): silent text-precision fix as part of Phase 220's docs work — implemented exactly that way.
- RESEARCH.md Pitfall 5: schema truth alignment — implemented.

## Deviations

None.

## Self-Check: PASSED
