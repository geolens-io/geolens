# Phase 1111 Context: Builder Lint Closeout

## Trigger

After Phase 1110 closed the Playwright QA path, `cd frontend && npm run lint` surfaced mapbuilder-related lint/a11y/rules issues. Because v1025 explicitly asked to fix discovered issues inline, Phase 1111 was added as a closeout phase rather than leaving the lint debt as an untracked follow-up.

## Findings

- `jsx-a11y/no-static-element-interactions` and `jsx-a11y/no-noninteractive-tabindex` flagged composite stack rows in `BasemapGroupRow`, `FolderGroupRow`, `StackRow`, and basemap sublayer rows.
- Existing Phase 1052 context explains why these rows intentionally avoid listbox/option roles: each row contains nested controls and axe rejects the listbox/option model.
- `EmptyStackState` carried redundant native `role` attributes.
- `RenderModeSwitch` and `MapBuilderPage` had stale lint-disable comments.
- `UnifiedStackPanel.render-perf.test.tsx` mutated a captured handler during render.
- `ViewerMap` and `MapBuilderPage` had hook dependency warnings that could be fixed by depending on specific stable inputs.

## Decision

Keep the role-free composite row accessibility model and document the ESLint exception with a qualified phase id. Fix everything else directly.
