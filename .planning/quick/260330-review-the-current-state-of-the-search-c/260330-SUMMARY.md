---
phase: quick-260330
plan: 01
subsystem: search-cards
tags: [search, cards, ui, ux, audit, playwright]
dependency_graph:
  requires: [quick-260329-ga7, quick-260329-kq7]
  provides: [search-card-audit, search-card-layout-guidance]
  affects: [SearchResultCard, SearchPage, useQuicklook]
tech_stack:
  added: []
  patterns: [Playwright-backed card audit, docs-only quick task]
key_files:
  created:
    - .planning/quick/260330-review-the-current-state-of-the-search-c/260330-CONTEXT.md
    - .planning/quick/260330-review-the-current-state-of-the-search-c/260330-PLAN.md
    - .planning/quick/260330-review-the-current-state-of-the-search-c/260330-RESEARCH.md
    - .planning/quick/260330-review-the-current-state-of-the-search-c/260330-REVIEW.md
    - .planning/quick/260330-review-the-current-state-of-the-search-c/260330-SUMMARY.md
    - .planning/quick/260330-review-the-current-state-of-the-search-c/260330-VERIFICATION.md
  modified: []
decisions:
  - Keep this pass docs-only and grounded in the live local app
  - Treat desktop and tablet as the primary design targets
  - Build on the same-day card redesigns instead of proposing another wholesale reset
metrics:
  duration: 20min
  completed: 2026-03-29
---

# Quick Task 260330: Search Card Layout + Style Review Summary

Playwright-backed audit of the current search result cards, focused on whether the live cards already feel simple, elegant, and intuitive on desktop and tablet.

## What Was Done

### Task 1: Live card audit
- Inspected the live search page on the running local stack at `http://localhost:8080`
- Audited the default desktop result stack and the tablet result stack
- Measured card geometry, preview sizing, and content heights
- Inspected a long-source dataset card and a collection-result case

### Task 2: Source trace
- Confirmed the empty-state/results contradiction in `SearchPage.tsx`
- Confirmed the preview/header geometry and text-width caps in `SearchResultCard.tsx`
- Confirmed the current quicklook failure path in `useQuicklook.ts` and `SearchResultCard.tsx`

### Task 3: Review + recommendation
- Wrote a ranked review of the current card state
- Distinguished true defects from hierarchy/layout polish issues
- Produced a concrete target direction for the next implementation pass

## Key Findings

- A collection query can show `No results found` and a valid collection card at the same time
- Desktop cards leave too much dead space between the text column and the preview tile
- Source, description, facts, and tags are not prioritized clearly enough
- Preview failure states still feel accidental rather than deliberate
- Collections need a dedicated compact variant instead of inheriting the dataset-card structure by omission

## Recommended Next Step

Implement a focused refinement pass, not a redesign:

1. Fix the empty-state/collection contradiction.
2. Remove the text-width cap that creates the dead gutter.
3. Tune preview size by breakpoint.
4. Strengthen hierarchy so facts outrank tags.
5. Give collections their own intentionally simple card variant.

## Deviations from Plan

None. This remained a docs-only audit from start to finish.

## Task Commits

1. **Search card audit artifacts** - `b6e97535` (docs)
