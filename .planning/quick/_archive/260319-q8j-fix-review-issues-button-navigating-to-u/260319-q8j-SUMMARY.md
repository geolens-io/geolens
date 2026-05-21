---
phase: 260319-q8j
plan: 01
subsystem: frontend
tags: [bugfix, navigation, validation]
key-files:
  modified:
    - frontend/src/components/dataset/tabs/OverviewTab.tsx
decisions: []
metrics:
  duration: "<1min"
  completed: "2026-03-19"
---

# Quick Task 260319-q8j: Fix Review Issues Button Navigation

**One-liner:** Fix Review issues button passing wrong field ('title' -> 'validation') so it navigates to the Metadata tab validation card.

## What Changed

The "Review issues" button in OverviewTab.tsx called `onNavigateToValidationField?.('title')`, but 'title' has no mapping in `getValidationNavigationAction()` so the click was silently ignored. Changed to `onNavigateToValidationField?.('validation')` which maps to `{ tab: 'metadata', anchor: 'validation' }`, correctly navigating to the validation card on the Metadata tab.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Fix Review issues button navigation field | a4641c42 | frontend/src/components/dataset/tabs/OverviewTab.tsx |

## Deviations from Plan

None - plan executed exactly as written.

## Verification

- grep confirms `onNavigateToValidationField?.('validation')` on line 163

## Self-Check: PASSED
