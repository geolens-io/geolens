---
phase: 1054-seeder-console-route-import-polish
plan: "03"
subsystem: ui
tags: [react, i18n, routing, enterprise-edition, saml]

requires: []

provides:
  - "ROUTE-01 closed: /admin/saml renders Enterprise Feature notice in community edition instead of silent redirect"
  - "AdminSamlPage vitest suite: 4 tests covering community/enterprise/loading/no-redirect"
  - "saml.enterpriseOnly.{title,description,heading,body,docsLink} in en/de/es/fr admin namespaces"

affects: [admin-routing, edition-gating, i18n-parity]

tech-stack:
  added: []
  patterns:
    - "Enterprise-feature notice pattern: render inline notice at current URL rather than Navigate away, keeping URL bookmarkable"

key-files:
  created:
    - "frontend/src/pages/admin/__tests__/AdminSamlPage.test.tsx"
  modified:
    - "frontend/src/pages/admin/AdminSamlPage.tsx"
    - "frontend/src/i18n/locales/en/admin.json"
    - "frontend/src/i18n/locales/de/admin.json"
    - "frontend/src/i18n/locales/es/admin.json"
    - "frontend/src/i18n/locales/fr/admin.json"

key-decisions:
  - "Render enterprise-only notice at /admin/saml instead of navigating away — URL stays bookmarkable and operators get a clear signal (ROUTE-01)"
  - "No shared EnterpriseFeatureNotice component — YAGNI; only one gated page currently; refactor when a second appears"
  - "Navigate removed from import list entirely; comment in file header updated to reflect layer-3 now renders a notice rather than redirecting"

patterns-established:
  - "Enterprise feature gating at page level: replace Navigate with inline notice, keeping URL stable"

requirements-completed:
  - ROUTE-01

duration: 12min
completed: 2026-05-19
---

# Phase 1054 Plan 03: ROUTE-01 Enterprise Feature Notice Summary

**`/admin/saml` now renders a bookmarkable Enterprise Feature notice in community edition — no silent redirect, no vanish, URL stays at `/admin/saml`**

## Performance

- **Duration:** 12 min
- **Started:** 2026-05-19T21:46:00Z
- **Completed:** 2026-05-19T21:58:00Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 6

## Accomplishments

- Replaced `<Navigate to="/admin" replace />` with an inline Enterprise Feature notice that keeps the URL at `/admin/saml`
- Notice includes a heading, explanatory body, and a docs link to `https://docs.getgeolens.com/guides/enterprise/saml/`
- Added `saml.enterpriseOnly` key block (5 keys) to en/de/es/fr admin locales — all 4 locales have full parity
- Created `AdminSamlPage.test.tsx` with 4 vitest tests: community notice, enterprise full render, loading state, no-redirect regression
- Enterprise edition path unchanged: still renders full `SamlProvidersSection`

## Task Commits

TDD RED → GREEN sequence:

1. **RED — failing tests** - `2a592af1` (test)
2. **GREEN — implementation + i18n** - `1629ee05` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `frontend/src/pages/admin/AdminSamlPage.tsx` — Removed Navigate import/usage; added inline enterprise-only notice block; updated security-layer comment
- `frontend/src/pages/admin/__tests__/AdminSamlPage.test.tsx` — New: 4 tests via vi.mock(useEdition) for community/enterprise/loading/no-redirect
- `frontend/src/i18n/locales/en/admin.json` — Added `saml.enterpriseOnly.{title,description,heading,body,docsLink}`
- `frontend/src/i18n/locales/de/admin.json` — Parallel keys in German (formal Sie register)
- `frontend/src/i18n/locales/es/admin.json` — Parallel keys in Spanish (neutral register)
- `frontend/src/i18n/locales/fr/admin.json` — Parallel keys in French (formal register)

## i18n Keys Added

5 keys per locale × 4 locales = 20 keys total:

| Key | en |
|-----|----|
| saml.enterpriseOnly.title | SAML SSO |
| saml.enterpriseOnly.description | Available with the GeoLens Enterprise overlay. |
| saml.enterpriseOnly.heading | This is an Enterprise feature |
| saml.enterpriseOnly.body | SAML 2.0 single sign-on is part of... |
| saml.enterpriseOnly.docsLink | Read more about SAML in the Enterprise docs → |

All 4 locales (en/de/es/fr) verified with parity check: `flattenKeys(admin.json)` matches English in de, es, fr.

## Tests Added

`frontend/src/pages/admin/__tests__/AdminSamlPage.test.tsx` — 4/4 pass:

1. Community edition renders enterprise-only notice with docs link, not SamlProvidersSection
2. Enterprise edition renders SamlProvidersSection, not the notice
3. Loading state renders LoadingState (neither notice nor providers)
4. No-redirect regression: community edition stays at /admin/saml, no Navigate fires

## Requirements Closed

- **ROUTE-01** — `/admin/saml` in community edition no longer silently redirects; renders an informative Enterprise Feature notice with docs link

## Decisions Made

- **No shared component**: kept the notice inline in `AdminSamlPage`. Only one page uses this pattern today; if a second enterprise-gated page appears, extract to a shared `EnterpriseFeatureNotice` component then.
- **Security comment updated**: the `T-217-04-EDITION` three-layer comment now accurately describes layer 3 as "render notice that does not fetch from gated endpoints" rather than "redirect away". The security property is identical.

## Deviations from Plan

None — plan executed exactly as written.

**Note on `pnpm check:i18n:changed`:** The `check:i18n:changed` script flagged `import.json` alongside `admin.json` because `import.json` files were already modified in the working tree (pre-existing work from a prior plan). The `admin.json` namespace has verified parity across all 4 locales. The `import.json` mismatch is out of scope for this plan and tracked as a pre-existing issue.

## Known Stubs

None — the notice renders real translated copy with a live docs link.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes introduced.

## Self-Check: PASSED

- `frontend/src/pages/admin/AdminSamlPage.tsx` — exists, Navigate import removed
- `frontend/src/pages/admin/__tests__/AdminSamlPage.test.tsx` — exists, 4/4 tests pass
- `frontend/src/i18n/locales/en/admin.json` — `enterpriseOnly` block present
- Commits `2a592af1` and `1629ee05` exist in git log

---
*Phase: 1054-seeder-console-route-import-polish*
*Completed: 2026-05-19*
