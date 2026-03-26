---
phase: 207-branding-toggle
plan: 02
subsystem: ui
tags: [react, react-query, i18n, branding, admin-settings]

requires:
  - phase: 207-branding-toggle plan 01
    provides: GET/PUT /api/settings/branding/ backend endpoints
  - phase: 206-edition-seam
    provides: useEdition() hook and edition API

provides:
  - getBranding/updateBranding API client functions
  - useBranding/useUpdateBranding React Query hooks
  - SettingsAppearanceTab admin component with branding toggle
  - Badge rendering gated on branding setting in AppLayout and PublicViewerPage

affects: [admin-settings, branding, public-viewer]

tech-stack:
  added: []
  patterns: [enterprise-only admin tab filtering, immediate-save toggle pattern]

key-files:
  created:
    - frontend/src/components/admin/settings/SettingsAppearanceTab.tsx
  modified:
    - frontend/src/api/settings.ts
    - frontend/src/hooks/use-settings.ts
    - frontend/src/pages/admin/AdminSettingsPage.tsx
    - frontend/src/components/admin/AdminSidebar.tsx
    - frontend/src/components/layout/AppLayout.tsx
    - frontend/src/pages/PublicViewerPage.tsx
    - frontend/src/components/layout/__tests__/AppLayout.test.tsx
    - frontend/src/i18n/locales/en/admin.json
    - frontend/src/i18n/locales/es/admin.json
    - frontend/src/i18n/locales/fr/admin.json
    - frontend/src/i18n/locales/de/admin.json

key-decisions:
  - "Appearance tab uses immediate-save on toggle (no dirty state) rather than batch save pattern used by other settings tabs"
  - "Enterprise-only filtering uses enterpriseOnly flag on settingsItems array for AdminSidebar and visibleTabs filter in AdminSettingsPage"

patterns-established:
  - "Enterprise-only admin tabs: add enterpriseOnly flag to nav items and filter with useEdition().isEnterprise"
  - "Branding badge logic: !isEnterprise || branding?.show_badge !== false (community always shows, enterprise respects setting)"

requirements-completed: [COMP-04, COMP-05]

duration: 7min
completed: 2026-03-26
---

# Phase 207 Plan 02: Frontend Branding Toggle Summary

**Branding toggle admin UI with enterprise-gated Appearance tab, useBranding hook, and badge rendering in AppLayout/PublicViewerPage**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-26T19:34:21Z
- **Completed:** 2026-03-26T19:41:33Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments
- Branding API client (getBranding/updateBranding) and React Query hooks (useBranding/useUpdateBranding) with instant invalidation
- SettingsAppearanceTab with Switch toggle that saves immediately on change
- Enterprise-only visibility for Appearance tab in AdminSettingsPage and AdminSidebar
- AppLayout footer and PublicViewerPage embed badge conditionally render based on branding setting
- Tests cover enterprise show/hide and community always-show scenarios (6 tests pass)
- i18n keys added for all 4 locales (en, es, fr, de)

## Task Commits

1. **Task 1: Add branding API client, useBranding hook, and SettingsAppearanceTab** - `05ddf782` (feat)
2. **Task 2: Update AppLayout and PublicViewerPage badge rendering** - `6294358e` (feat)

## Files Created/Modified
- `frontend/src/components/admin/settings/SettingsAppearanceTab.tsx` - New admin tab with branding toggle
- `frontend/src/api/settings.ts` - BrandingConfig type and getBranding/updateBranding functions
- `frontend/src/hooks/use-settings.ts` - useBranding and useUpdateBranding hooks
- `frontend/src/pages/admin/AdminSettingsPage.tsx` - Wired appearance tab with enterprise filtering
- `frontend/src/components/admin/AdminSidebar.tsx` - Appearance nav item with Paintbrush icon (enterprise-only)
- `frontend/src/components/layout/AppLayout.tsx` - Footer badge gated on branding setting
- `frontend/src/pages/PublicViewerPage.tsx` - Embed badge gated on branding setting
- `frontend/src/components/layout/__tests__/AppLayout.test.tsx` - 6 tests covering branding-aware badge rendering
- `frontend/src/i18n/locales/{en,es,fr,de}/admin.json` - Appearance tab and branding i18n keys

## Decisions Made
- Appearance tab uses immediate-save on toggle rather than the batch save pattern used by other settings tabs, since branding has its own dedicated endpoint
- Enterprise-only filtering uses `enterpriseOnly` flag on settingsItems array and `visibleTabs` filter derived from `useEdition().isEnterprise`

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Branding toggle feature is complete end-to-end (backend + frontend)
- Enterprise admins can toggle badge visibility from admin settings
- Community edition always shows badge, appearance tab hidden

---
*Phase: 207-branding-toggle*
*Completed: 2026-03-26*
