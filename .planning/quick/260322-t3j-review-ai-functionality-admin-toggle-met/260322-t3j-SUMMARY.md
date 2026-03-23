---
phase: quick-260322-t3j
plan: 01
subsystem: ai, ui
tags: [ai-chat, tools, i18n, experimental-badge, toast]

requires:
  - phase: v12.3
    provides: Map builder chat panel, AI tool infrastructure
provides:
  - set_opacity tool definition in CHAT_TOOLS_ANTHROPIC/OPENAI
  - Error toast handling for AI metadata mutation hooks
  - Experimental badges on AI chat panel headers
affects: [ai-chat, map-builder]

tech-stack:
  added: []
  patterns: [onError toast pattern for mutation hooks]

key-files:
  created: []
  modified:
    - backend/app/ai/tools.py
    - frontend/src/hooks/use-ai-metadata.ts
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json
    - frontend/src/i18n/locales/de/builder.json

key-decisions:
  - "Amber badge styling (border-amber-500/50 text-amber-600 dark:text-amber-400) for experimental indicator"

patterns-established:
  - "onError toast pattern: mutation hooks surface errors via sonner toast.error with fallback messages"

requirements-completed: [QUICK-T3J]

duration: 1min
completed: 2026-03-23
---

# Quick Task 260322-t3j: AI Functionality Gaps & Experimental Badges Summary

**set_opacity tool added to chat tools, metadata mutation error toasts, and amber experimental badges on AI chat panel headers in all 4 locales**

## Performance

- **Duration:** 1 min
- **Started:** 2026-03-23T01:08:30Z
- **Completed:** 2026-03-23T01:09:50Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Added set_opacity tool definition to CHAT_TOOLS_ANTHROPIC (auto-derived to OpenAI format)
- Added onError callbacks with toast.error to all 4 AI metadata mutation hooks
- Added amber "Experimental" badge to both compact (Sheet) and wide (inline) chat panel headers
- Updated tooltips.aiChat to include "(Experimental)" in en/es/fr/de locales

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix set_opacity tool definition and metadata error handling** - `f05b3713` (fix)
2. **Task 2: Add experimental badges and i18n keys** - `c0070076` (feat)

## Files Created/Modified
- `backend/app/ai/tools.py` - Added set_opacity tool definition to CHAT_TOOLS_ANTHROPIC
- `frontend/src/hooks/use-ai-metadata.ts` - Added toast import and onError to all 4 mutation hooks
- `frontend/src/pages/MapBuilderPage.tsx` - Added Badge with amber styling to both chat panel header variants
- `frontend/src/i18n/locales/en/builder.json` - Added chat.experimental key, updated tooltips.aiChat
- `frontend/src/i18n/locales/es/builder.json` - Added chat.experimental key, updated tooltips.aiChat
- `frontend/src/i18n/locales/fr/builder.json` - Added chat.experimental key, updated tooltips.aiChat
- `frontend/src/i18n/locales/de/builder.json` - Added chat.experimental key, updated tooltips.aiChat

## Decisions Made
- Amber badge styling matches existing pattern from SettingsAITab warning (border-amber-500/50 text-amber-600 dark:text-amber-400)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Known Stubs
None

---
*Phase: quick-260322-t3j*
*Completed: 2026-03-23*
