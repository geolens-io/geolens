# v1026 Milestone Audit: Mapbuilder Style Reconciler

**Completed:** 2026-05-25
**Status:** Complete
**Verdict:** Clear to continue

## Scope

v1026 replaced additive-only style mutation with a canonical style reconciliation contract across builder adapters, manual controls, AI chat style actions, persistence, viewer/embed rendering, and live MapLibre state.

## Requirement Closure

- 28/28 requirements complete.
- 6/6 phases complete.
- 6/6 plans complete.

## Evidence

- Phase 1112 documented the style mutation inventory, adapter-owned properties, semantics, and stale-style regression matrix.
- Phase 1113 added the shared reconciler and focused set/no-op/clear/filter/expression/error tests.
- Phase 1114 migrated adapters and companion layers to owned-property reconciliation.
- Phase 1115 aligned manual high-risk controls and AI chat patch/clear/replace semantics.
- Phase 1116 proved save/viewer/style JSON parity for canonical reconciled paint.
- Phase 1117 passed focused automated gates, frontend typecheck/lint, backend style/sprite/AI tests, OpenAPI/SDK drift checks, and Playwright MCP UAT on the ADK 3D Relief target map.

## Inline Close-Gate Fixes

- GeoLens sprites use an absolute `/api/maps/sprites/geolens` URL so MapLibre accepts the sprite registration.
- Hidden high-DPI sprite aliases serve MapLibre `@2x` JSON/PNG requests while staying out of OpenAPI/SDK output.
- Builder terrain activation retries after `idle` when MapLibre style loading would otherwise drop the terrain apply.

## Residual Risk

- Full production CI live-verify remains blocked by the existing GitHub Actions billing prerequisite carried forward from v1023. This is outside the style reconciler invariant.
- The ADK target map remains a local dogfood/marketing artifact; browser UAT did not save the unsaved style toggles exercised during verification.

## Carry Forward

- `CI-01-v1026`: live-verify `pytest-parallel-isolation` on real GitHub Actions after billing is resolved.
