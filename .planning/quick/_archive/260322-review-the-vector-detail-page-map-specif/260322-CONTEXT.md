# Quick Task 260322: Vector detail page map editing review - Context

**Gathered:** 2026-03-20
**Status:** Complete

## Scope

Review the vector dataset detail page map, with emphasis on editing capabilities and visualization correctness.

## Success Criteria

- Confirm the live editing affordances for point, line, and polygon datasets.
- Trace the full edit path from map selection to backend persistence.
- Identify any correctness gaps, visualization issues, or engineering concerns.
- Produce a review that is defensible with code references, tests, and live verification.

## Review Inputs

- Frontend map stack: `DatasetMap`, `use-feature-editing`, `use-terra-draw`, `DrawingToolbar`, `AttributeForm`
- Backend persistence path: feature PATCH/PUT validation and update logic
- Existing unit tests and Playwright coverage
- Live app running at `http://localhost:8080`

## Key Questions

1. Are the geometry-specific editing affordances correct for point, line, and polygon layers?
2. Is the feature selection/edit/save path safe for multi-part geometries?
3. Do current tests actually cover the real MapLibre/Terra Draw editing flow?
4. Is there enough evidence to claim the map editing stack is complete and following best practices?
