---
phase: 260319-arw
plan: 01
subsystem: frontend
tags: [ui-polish, detail-page, layout]
dependency-graph:
  requires: []
  provides: [footer-conditional-hide, visibility-badge, muted-ai-buttons, tighter-spacing]
  affects: [AppLayout, DatasetPage, AiAssistButton, PageShell]
tech-stack:
  added: []
  patterns: [useMatch-conditional-render, visibilityColors-badge]
key-files:
  created: []
  modified:
    - frontend/src/components/layout/AppLayout.tsx
    - frontend/src/components/layout/__tests__/AppLayout.test.tsx
    - frontend/src/components/layout/PageShell.tsx
    - frontend/src/pages/DatasetPage.tsx
    - frontend/src/components/dataset/AiAssistButton.tsx
decisions:
  - "useMatch('/datasets/:id') to conditionally hide footer on detail pages"
  - "Muted/foreground styling for AI buttons instead of violet"
metrics:
  duration: 2min
  completed: "2026-03-19T11:51:00Z"
  tasks_completed: 1
  tasks_total: 1
  files_modified: 5
---

# Phase 260319-arw Plan 01: Detail Page Polish Round 4 Summary

Footer hidden on dataset detail pages, visibility badge added to stats line, AI Assist toned to muted styling, PageShell spacing tightened from 6 to 4.

## Changes Made

### Task 1: Footer hide, visibility badge, spacing, AI Assist tone-down (70bcc150)

**Footer conditional hide:**
- Added `useMatch('/datasets/:id')` to AppLayout
- Footer now hidden on dataset detail pages, still visible on search, admin, etc.
- Added test verifying footer absent on `/datasets/:id` route

**Visibility badge in header stats:**
- Added Badge with Eye/EyeOff/ShieldAlert icons inline in the stats second row
- Uses `visibilityColors` from status-colors.ts for consistent semantic coloring

**AI Assist muted styling:**
- Changed AiAssistButton from `text-violet-600` to `text-muted-foreground hover:text-foreground`
- Changed AiDraftPreview and AiKeywordSuggestions from `border-violet-400 bg-violet-50` to `border-muted bg-muted/30`

**Tighter spacing:**
- PageShell: `space-y-6` to `space-y-4`, `py-6` to `py-4`

## Deviations from Plan

None - plan executed exactly as written.

## Verification

- TypeScript compiles without errors (`npx tsc --noEmit` passes)
- AppLayout test updated with new test case for footer hiding

## Self-Check: PASSED
