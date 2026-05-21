---
phase: quick-260331
plan: "01"
subsystem: frontend/map-builder
tags: [ui-ux, map-builder, style-spec, layer-editing, research]
requires: []
provides:
  - layer editing UX findings report
  - easy-win enhancement list
  - Mapbox style-spec-aligned extensibility recommendation
key_files:
  created:
    - .planning/quick/260331-what-is-the-best-ui-ux-for-layer-editing/260331-PLAN.md
    - .planning/quick/260331-what-is-the-best-ui-ux-for-layer-editing/260331-RESEARCH.md
    - .planning/quick/260331-what-is-the-best-ui-ux-for-layer-editing/260331-SUMMARY.md
    - .planning/quick/260331-what-is-the-best-ui-ux-for-layer-editing/260331-VERIFICATION.md
  modified: []
decisions:
  - Treat Mapbox style-spec structure as the target authoring model, while preserving a runtime support matrix for MapLibre-backed rendering.
  - Recommend a two-pane UX: layer stack plus dedicated layer inspector.
  - Keep this task documentation-only with no product code changes.
completed: 2026-03-29
---

# Quick Task 260331 Summary

## Outcome

Completed a research-only assessment of the map creator’s layer editing UX using direct code review, a live Playwright inspection of the sample map, and official style-spec references.

## Main Recommendation

The best future UI is a **Layer Stack + Layer Inspector** model:

- The layer stack stays focused on ordering, visibility, naming, and quick status cues.
- The inspector becomes the home for spec-aligned authoring sections like `General`, `Filter`, `Paint`, `Layout`, `Labels/Symbol`, and `Advanced JSON`.

## Main Findings

1. The current row-accordion editor works for simple maps but will not scale cleanly to many layers or richer styling.
2. `paint`, `layout`, and `filter` already form a good low-level foundation for style-spec-aligned authoring.
3. `style_config` is too narrow for multiple concurrent data-driven property rules.
4. Labels should become first-class symbol-style authoring rather than stay as a side tab.
5. The filter builder is intentionally limited and will need nested/grouped rule support if advanced authoring becomes important.
6. The live UI currently shows untranslated label zoom keys, and live label zoom-range syncing appears incomplete in the interactive editing path.

## Easy Wins

- Fix missing label zoom i18n keys.
- Apply label zoom-range changes live in `useBuilderLayers`.
- Collapse or search the fields reference list instead of showing it inline at full length.
- Add richer row summaries for active style/filter/label rules.
- Add advanced JSON editing for `paint` and `layout`, similar to the filter JSON mode.

## No-Code Constraint

No product code was changed for this task. Output is limited to research and workflow documentation.
