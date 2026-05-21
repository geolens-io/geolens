---
quick_id: 260425-oxh
description: "layer popup config: enable/disable + custom expression with validation"
subsystem: ui
tags: [react, fastapi, postgis, jsonb, alembic, dnd-kit, i18n]

# Dependency graph
requires:
  - phase: existing label_config pattern
    provides: JSONB-on-MapLayer + Pydantic dict|None + sidebar tab pipeline
provides:
  - Per-layer popup configuration (enabled toggle, title-template expression, ordered visible-fields allowlist)
  - popup-template util (extract / validate / substitute / isPopupConfigValid)
  - PopupConfigEditor sidebar tab + handlePopupChange hook handler
  - FeaturePopup title heading + ordered visibleFields allowlist support
  - BuilderMap click-handler resolution that respects popup_config.enabled and substitutes per-feature title
affects: [map-builder, feature-popups, shared-maps, chat-map-edit]

tech-stack:
  added: []
  patterns:
    - "Template-string parser using anchored identifier regex /\\{[a-zA-Z_]\\w*\\}/g; React JSX text-node rendering only (no dangerouslySetInnerHTML)"
    - "Save-time gate util in shared lib; consumed in use-builder-save with toast on failure"
    - "Mode-toggle pattern for tri-state visible-fields (null=all, []=none, [...]=ordered allowlist)"

key-files:
  created:
    - "backend/alembic/versions/2026_04_25_0001-add_popup_config_to_map_layers.py"
    - "frontend/src/lib/popup-template.ts"
    - "frontend/src/lib/__tests__/popup-template.test.ts"
    - "frontend/src/components/builder/PopupConfigEditor.tsx"
    - "frontend/src/components/builder/__tests__/PopupConfigEditor.test.tsx"
  modified:
    - "backend/app/modules/catalog/maps/models.py"
    - "backend/app/modules/catalog/maps/schemas.py"
    - "backend/app/modules/catalog/maps/service.py"
    - "backend/app/modules/catalog/maps/router.py"
    - "frontend/src/types/api.ts"
    - "frontend/src/components/builder/LayerEditorPanel.tsx"
    - "frontend/src/components/builder/hooks/use-layer-map-sync.ts"
    - "frontend/src/components/builder/hooks/use-builder-layers.ts"
    - "frontend/src/components/builder/hooks/use-builder-save.ts"
    - "frontend/src/components/builder/BuilderMap.tsx"
    - "frontend/src/components/map/FeaturePopup.tsx"
    - "frontend/src/pages/MapBuilderPage.tsx"
    - "frontend/src/i18n/locales/en/builder.json"
    - "frontend/src/i18n/locales/de/builder.json"
    - "frontend/src/i18n/locales/es/builder.json"
    - "frontend/src/i18n/locales/fr/builder.json"

key-decisions:
  - "Mirror label_config end-to-end: JSONB column on MapLayer, Pydantic dict|None, MapLayerInput field_validator only enforces shape (not column-existence), 4 service.py / router.py copy sites"
  - "PopupConfigEditor saves immediately via update() while debouncing only the validation render (250ms) so the UX stays responsive without losing typed input"
  - "isPopupConfigValid lives in popup-template.ts and is consumed by use-builder-save.handleSave to block save with toast when expressions reference unknown columns"
  - "Custom-fields picker reuses @dnd-kit/sortable inline (~70 lines) — RESEARCH §7 confirmed no shared sortable-multiselect primitive exists"
  - "Title rendered via JSX text node with white-space: pre-wrap; never via dangerouslySetInnerHTML (React handles XSS escaping)"
  - "Click-handler short-circuit uses popup_config?.enabled !== false so null/undefined remain enabled-by-default — only an explicit false suppresses popups"

patterns-established:
  - "Template-string subsystem: extract → validate → substitute pipeline shared between editor (live validation), save-gate (block on invalid), and click-handler (per-feature substitution)"
  - "Tab-union extension across 5 mechanical sites (handler interface, props interface, tab array, filter logic, useState union) — same shape can be used for any future sidebar tab"
  - "i18n parity preserved by adding identical-key translations to all 4 locales (en/de/es/fr)"

requirements-completed:
  - oxh-popup-toggle
  - oxh-popup-template
  - oxh-visible-fields
  - oxh-validation

# Metrics
duration: ~50min
completed: 2026-04-25
---

# Quick Task 260425-oxh: Layer Popup Config Summary

**Per-layer popup config UI + persistence: enable/disable toggle, `{column}` title-template expression with debounced live validation against the layer's columns, and a sortable visible-fields allowlist (`null` = all, `[]` = none, `[...]` = ordered subset).**

## Performance

- **Duration:** ~50 min
- **Tasks:** 3
- **Files created:** 5
- **Files modified:** 16
- **Commits:** 3 atomic + this SUMMARY

## Accomplishments

- `popup_config` JSONB column persisted end-to-end (DB column → Pydantic schema → API response → frontend state → reload restores → fork copies)
- New "Popup" tab (4th in the layer editor) renders `PopupConfigEditor` with a Switch toggle, debounced (250ms) live-validating expression Input, and two-mode visible-fields picker (`Show all (default)` vs `Custom selection`)
- Title rendered above the existing FeaturePopup property table via plain JSX text node — no `dangerouslySetInnerHTML` introduced
- Click handler in `BuilderMap` filters hits by `popup_config?.enabled !== false` so disabling popups on layer A still surfaces layer B's features at the same point
- Save is blocked with a translated toast (`toasts.popupConfigInvalid`) when any layer's expression has unknown placeholders
- All 4 locales (en/de/es/fr) carry the new keys; i18n parity test passes

## Task Commits

1. **Task 1: Backend popup_config column and schema** — `88e6e9a7` (feat)
2. **Task 2: popup config editor + frontend types** — `b4f3fbc3` (feat)
3. **Task 3: FeaturePopup title + BuilderMap click-handler integration** — `31f8b70c` (feat)

## Files Created/Modified

### Created
- `backend/alembic/versions/2026_04_25_0001-add_popup_config_to_map_layers.py` — Alembic migration `t6u7v8w9x0y1` (down_revision `s5t6u7v8w9x0`) adding `catalog.map_layers.popup_config` JSONB nullable
- `frontend/src/lib/popup-template.ts` — `extractPlaceholders`, `validatePlaceholders`, `substitutePopupTemplate`, `isPopupConfigValid` (15 effective lines of logic)
- `frontend/src/lib/__tests__/popup-template.test.ts` — 25 unit tests covering all 4 utilities + edge cases
- `frontend/src/components/builder/PopupConfigEditor.tsx` — Switch + Input + dnd-kit sortable picker (~270 lines)
- `frontend/src/components/builder/__tests__/PopupConfigEditor.test.tsx` — 5 RTL/Vitest component tests including fake-timer debounce validation

### Modified

**Backend (Task 1):**
- `backend/app/modules/catalog/maps/models.py` — `MapLayer.popup_config: Mapped[dict | None]` JSONB column
- `backend/app/modules/catalog/maps/schemas.py` — `popup_config: dict | None` on `MapLayerInput`/`MapLayerResponse`/`SharedLayerResponse` + `field_validator` enforcing shape
- `backend/app/modules/catalog/maps/service.py` — 3 sites copy `popup_config` (add/replace, fork, `_build_shared_layer_dict`)
- `backend/app/modules/catalog/maps/router.py` — `_build_layer_response` round-trips it

**Frontend (Task 2):**
- `frontend/src/types/api.ts` — `PopupConfig` interface + `popup_config?` on `MapLayerResponse`/`MapLayerInput`/`SharedLayerResponse`/`ChatMapLayer`
- `frontend/src/components/builder/LayerEditorPanel.tsx` — 4th `'popup'` tab + `onPopupChange` handler in `LayerEditorHandlers`
- `frontend/src/components/builder/hooks/use-layer-map-sync.ts` — `handlePopupChange` callback (no map side-effect)
- `frontend/src/components/builder/hooks/use-builder-layers.ts` — tab union widened, `handlePopupChange` re-exposed
- `frontend/src/components/builder/hooks/use-builder-save.ts` — popup_config in PUT payload + save gate via `isPopupConfigValid`
- `frontend/src/pages/MapBuilderPage.tsx` — wires `onPopupChange: layers.handlePopupChange`
- `frontend/src/i18n/locales/{en,de,es,fr}/builder.json` — `layerItem.popupTab/popupTitle`, `popup` namespace, `toasts.popupConfigInvalid`

**Frontend (Task 3):**
- `frontend/src/components/map/FeaturePopup.tsx` — `FeatureInfo` extended with `title?` and `visibleFields?`; title heading rendered above existing layerName row; visible-entries resolution honors ordered allowlist
- `frontend/src/components/builder/BuilderMap.tsx` — `substitutePopupTemplate` import; `popupInfo` state widened; `handleClick` filters disabled hits and substitutes per-feature title

## Decisions Made

All locked decisions from `260425-oxh-CONTEXT.md` honored verbatim:
- **Storage shape:** Single JSONB `popup_config` column with `{enabled, expression, visible_fields}` shape
- **Expression dialect:** Plain template strings with `{column_name}` placeholders, missing → empty string, no escape syntax
- **Visible fields semantics:** `null` = all (default), `[]` = none (title-only), `[...]` = ordered allowlist
- **Validation UX:** Live (debounced ~250ms) + on-save block; backend schema enforces shape only
- **Disabled fallback:** Other layers' popups remain functional when one layer has popups disabled

Additional execution-time decisions:
- **Test debounce verification with `fireEvent.change` + fake timers** instead of `userEvent.type`. The latter races against fake timers in this version of `@testing-library/user-event` and times out — `fireEvent.change` reliably dispatches the input event in one shot so the 250ms `vi.advanceTimersByTime(300)` exercises the path deterministically.
- **Save-gate uses every-layer scan** rather than instrumenting per-layer state. Simpler and the layer count is bounded; cost is negligible.
- **Validation re-evaluates against debounced expression** (not the prop) so the helper-text UI doesn't flicker on every keystroke; the parent state still receives the immediate update so save correctness is preserved.

## Deviations from Plan

None affecting plan intent. Two minor implementation refinements documented above:

1. **Test technique** — used `fireEvent.change` for the debounce test instead of `userEvent.type` to avoid a fake-timer race. The behavior under test (debounce → validation re-renders) is unchanged.
2. **i18n breadth** — plan only specified `en/builder.json`; I added the same keys to `de/es/fr` so the `i18n/resources.test.ts` parity test continues to pass (Rule 3 — auto-fix blocking issue: parity test would fail otherwise).

**Total deviations:** 1 auto-fix (Rule 3 — i18n parity test would otherwise break)
**Impact on plan:** None. All locked specs honored; the i18n addition is a project-conventions follow-through, not a behavior change.

## Issues Encountered

- **Initial `alembic upgrade` failed inside the docker `api` container** because the `alembic` binary on PATH is system-installed, not the venv-installed one. Resolved by invoking `/app/.venv/bin/alembic` directly. Migration applied, downgrade tested, re-applied — all clean.
- **Pre-existing typecheck/test errors observed** during full-suite runs in `use-builder-save.test.ts`, `use-builder-layers.test.ts`, and `AppLayout.test.tsx`. Confirmed pre-existing by running the same checks against `git stash`-ed baseline; not related to this task.

## Verification

- `docker compose exec -T api /app/.venv/bin/alembic upgrade head` → applies cleanly
- `docker compose exec -T api /app/.venv/bin/alembic downgrade -1 && upgrade head` → round-trips cleanly
- `\d catalog.map_layers` → shows `popup_config | jsonb`
- Backend Pydantic round-trip: `MapLayerInput(popup_config={...})` accepts valid shape; rejects non-bool `enabled`, non-string `visible_fields[]`, unknown keys with `ValidationError`
- Backend tests: `pytest tests/test_maps.py -x` → **101 passed**
- Frontend popup-template tests: **25 passed**
- Frontend PopupConfigEditor tests: **5 passed**
- Frontend hooks tests (use-builder-save, use-builder-layers, ChatPanel): **35 passed**
- Frontend i18n parity test: **2 passed** (every locale carries every key)
- ESLint: 0 errors on touched files (only pre-existing warnings)
- TypeScript: 0 new errors on touched files

## Self-Check: PASSED

Files verified to exist:
- backend/alembic/versions/2026_04_25_0001-add_popup_config_to_map_layers.py — FOUND
- frontend/src/lib/popup-template.ts — FOUND
- frontend/src/lib/__tests__/popup-template.test.ts — FOUND
- frontend/src/components/builder/PopupConfigEditor.tsx — FOUND
- frontend/src/components/builder/__tests__/PopupConfigEditor.test.tsx — FOUND

Commits verified in git log:
- 88e6e9a7 — FOUND
- b4f3fbc3 — FOUND
- 31f8b70c — FOUND
- 8ca90a9f — FOUND (post-review remediation)

## Post-Review Remediation (commit 8ca90a9f)

Code review surfaced 1 MAJOR + 4 MINOR issues; all five were fixed inline before finalizing this quick task.

| ID | Severity | Issue | Fix |
|----|----------|-------|-----|
| MJ-01 | MAJOR | `lastEnabledConfigRef` leaked Layer A's expression/visible_fields into Layer B when toggling popup ON | `key={layer.id}` on `<PopupConfigEditor>` in LayerEditorPanel.tsx + ref now resets via useEffect on `[popupConfig]` |
| MN-01 | MINOR | 250ms debounce was bypassed in production because a useEffect synchronously synced `debouncedExpr` from the prop on every keystroke | Removed the syncing useEffect; per-layer `key=` ensures fresh state on layer switch; the setTimeout is now the only path that updates `debouncedExpr` |
| MN-02 | MINOR | Backend popup_config validator had no length caps | Added bounds: expression ≤ 500 chars, visible_fields ≤ 100 entries, each entry ≤ 128 chars |
| MN-03 | MINOR | `POST /maps/{id}/layers/` silently dropped popup_config (and filter, label_config, style_config, display_name, show_in_legend) | Extended `service.add_layer` (kwargs) and the POST handler to forward and persist all six fields |
| MN-04 | MINOR | Hover cursor showed pointer over disabled-popup features | BuilderMap mousemove now mirrors handleClick's per-feature filter on `popup_config?.enabled !== false` |

**Verification of remediation:**
- 101/101 backend maps tests pass
- 46/46 frontend popup + builder-save tests pass
- 0 new TypeScript errors on touched files

---

*Quick task: 260425-oxh*
*Completed: 2026-04-25*
