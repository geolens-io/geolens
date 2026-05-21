---
quick_id: 260425-oxh
status: passed
truths_passed: 7
truths_total: 7
verified_at: 2026-04-25
---

# Quick Task 260425-oxh Verification Report

**Task Goal:** layer popup config: enable/disable + custom expression with validation
**Status:** PASSED
**Verifier:** goal-backward (codebase evidence, not SUMMARY claims)

## Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | User can open the new "Popup" tab in the layer editor for a vector layer | VERIFIED | `LayerEditorPanel.tsx:98` adds `'popup'` to tab array; `:160-168` renders `PopupConfigEditor` when `activeTab === 'popup'`; capability gate at `:102` allows tab when `supportsFilterEditor || supportsLabelEditor` |
| 2 | User can toggle popups on/off; off makes clicks on that layer's features show no popup | VERIFIED | `PopupConfigEditor.tsx:132-147` `handleToggle` writes `{enabled: false, ...}`; `BuilderMap.tsx:268-272` filters hits via `popup_config?.enabled !== false` (silent disabled fallback per LOCKED decision) |
| 3 | User can type a template like '{city}, {state}' and the substituted result appears as a title above the existing FeaturePopup property table | VERIFIED | `BuilderMap.tsx:280-282` calls `substitutePopupTemplate(cfg.expression, props)` per feature; `FeaturePopup.tsx:118-125` renders `title` as `<div>` ABOVE existing `layerName` header at line 127 (additive composition per LOCKED decision); plain JSX text node (no `dangerouslySetInnerHTML`) |
| 4 | User can pick a sortable allowlist of visible fields; only those fields show, in the order specified; empty list shows no rows; null shows all (current default) | VERIFIED | `PopupConfigEditor.tsx:165-191` mode toggle (`null` → all, `[]` → custom-empty), drag-reorder via `@dnd-kit/sortable` `arrayMove`; `FeaturePopup.tsx:81-92` resolution: `visibleFields` defined → ordered allowlist; `null/undefined` → fall back to `columnInfo`; `[]` → zero rows |
| 5 | Live validation highlights unknown {placeholders} as the user types (debounced ~250ms); save is blocked when invalid | VERIFIED | `PopupConfigEditor.tsx:34` `DEBOUNCE_MS = 250`; `:159-163` `setTimeout(setDebouncedExpr, DEBOUNCE_MS)`; `:114-118` `validatePlaceholders` re-runs against debounced value; `:212` `border-destructive` applied when `!validation.ok`; `use-builder-save.ts:148-154` `handleSave` finds invalid layer via `isPopupConfigValid` and calls `toast.error(t('toasts.popupConfigInvalid'))` then returns early |
| 6 | popup_config persists end-to-end (DB column → API response → frontend state → reload restores) | VERIFIED | DB: `\d catalog.map_layers` confirms `popup_config jsonb`; migration `2026_04_25_0001-add_popup_config_to_map_layers.py` revision `t6u7v8w9x0y1` applied. Pydantic round-trip tested in shell: valid input accepted, malformed (non-bool `enabled`, extra keys) rejected. service.py copies in 3 sites (`:452` add, `:627` fork, `:877` shared dict); router.py `:102` returns it. Frontend `use-builder-save.ts:187` includes `popup_config` in PUT payload |
| 7 | Other layers' popup behavior is unchanged when one layer has popups disabled | VERIFIED | `BuilderMap.tsx:268-272` filters PER-FEATURE: each hit's layer is independently checked; only features whose `popup_config?.enabled === false` are dropped, leaving other layers' features in `filteredHits` to render normally |

**Score:** 7/7 truths verified

## Required Artifacts

| Artifact | Status | Evidence |
|----------|--------|----------|
| `backend/alembic/versions/2026_04_25_0001-add_popup_config_to_map_layers.py` | VERIFIED | File exists; revision `t6u7v8w9x0y1`, down_revision `s5t6u7v8w9x0`; `op.add_column` JSONB nullable; downgrade drops it. DB applied: column visible in `\d catalog.map_layers` |
| `backend/app/modules/catalog/maps/models.py` | VERIFIED | `:113` `popup_config: Mapped[dict \| None] = mapped_column(JSONB, nullable=True)` |
| `backend/app/modules/catalog/maps/schemas.py` | VERIFIED | `:44` `MapLayerInput.popup_config`; `:181` `MapLayerResponse.popup_config`; `:259` `SharedLayerResponse.popup_config`; `:60-85` `field_validator` enforces shape (rejects non-bool enabled, non-string expression, non-list visible_fields, extra keys) |
| `frontend/src/types/api.ts` | VERIFIED | `:698-702` `PopupConfig` interface; `:762, 856, 882, 962` `popup_config?` on MapLayerResponse / MapLayerInput / SharedLayerResponse / ChatMapLayer |
| `frontend/src/lib/popup-template.ts` | VERIFIED | Exports `extractPlaceholders`, `validatePlaceholders`, `substitutePopupTemplate`, `isPopupConfigValid` (4/4); 25/25 unit tests pass |
| `frontend/src/components/builder/PopupConfigEditor.tsx` | VERIFIED | 311 lines (>>100 min); Switch toggle, debounced expression Input (250ms), sortable visible-fields picker via `@dnd-kit`; 5/5 component tests pass |
| `frontend/src/components/builder/LayerEditorPanel.tsx` | VERIFIED | `:7` imports `PopupConfigEditor`; `:14` imports `PopupConfig` type; `:17, :30, :98` tab union extended to include `'popup'`; `:160-168` tabpanel renders editor |
| `frontend/src/components/map/FeaturePopup.tsx` | VERIFIED | `:8-18` `FeatureInfo` extended with `title?` and `visibleFields?`; `:81-92` allowlist resolution logic; `:118-125` title rendered above layerName via plain JSX text node with `whiteSpace: pre-wrap` |
| `frontend/src/components/builder/BuilderMap.tsx` | VERIFIED | `:14` imports `substitutePopupTemplate`; `:268-272` filters hits by `popup_config?.enabled !== false`; `:280-282` substitutes expression per feature; `:288` passes `visible_fields` |

## Key Link Verification

| From | To | Status | Evidence |
|------|-----|--------|----------|
| `PopupConfigEditor.tsx` | `popup-template.ts` (validation) | WIRED | `:25` imports `extractPlaceholders, validatePlaceholders`; `:114, 116` consumes both |
| `LayerEditorPanel.tsx` | `PopupConfigEditor.tsx` | WIRED | `:7` import; `:162` rendered when `activeTab === 'popup'` |
| `use-layer-map-sync.ts` | `PopupConfig` type | WIRED | `:325-331` `handlePopupChange` writes `popup_config` via `applyLayerUpdate` (no map side-effect, per spec) |
| `BuilderMap.tsx` | `FeaturePopup.tsx` | WIRED | `:283-289` builds feature object with `title` + `visibleFields`; passed via `setPopupInfo` |
| `service.py` | `models.py` (popup_config) | WIRED | 3 sites: `:452` add/replace, `:627` fork, `:877` shared response dict |
| `MapBuilderPage.tsx` | `LayerEditorHandlers` | WIRED | `:222` `onPopupChange: layers.handlePopupChange` |
| `use-builder-save.ts` | `popup-template.ts (isPopupConfigValid)` | WIRED | `:12` import; `:148-154` save gate; `:187` payload includes `popup_config` |

## LOCKED Decisions Verification (CONTEXT.md)

| Decision | Status | Evidence |
|----------|--------|----------|
| Dialect = template strings ONLY (no MapLibre expressions accepted) | VERIFIED | `popup-template.ts:13` regex `/\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g` parses `{name}` placeholders; substitution coerces values to strings via `String(v)`. Editor input is `<Input type="text">` (no JSON/array parsing). Pydantic schema accepts only `string \| null` for `expression`. |
| Body composition = title + property list (additive) | VERIFIED | `FeaturePopup.tsx:118-125` title rendered as new `<div>` BEFORE existing layerName header at `:127`. Existing property table preserved untouched at `:156-197`. No replacement, no rewrites. |
| Visible fields = ordered allowlist; null=all, []=none | VERIFIED | Frontend `FeaturePopup.tsx:81-92`: `visibleFields !== null/undefined` → ordered allowlist via `propMap`; `null` → fall back to `columnInfo` (legacy default = "show all"); `[]` → zero rows (intentional). Editor `PopupConfigEditor.tsx:125` mode toggle drives the same semantics. |
| Validation = live + on save | VERIFIED | Live: `PopupConfigEditor.tsx:34, 159-163` debounced 250ms re-validation; red border via `:212` `cn('border-destructive', !validation.ok)`. On save: `use-builder-save.ts:148-154` `isPopupConfigValid` gate blocks save with `toast.error(t('toasts.popupConfigInvalid'))` and early return. Backend defense-in-depth: `schemas.py:60-85` `field_validator` enforces shape only (per spec). |
| Disabled = silent (no popup) | VERIFIED | `BuilderMap.tsx:268-272` filters hits silently — no error, no toast, no fallback popup. The layer's hits are simply removed from `filteredHits`. Other layers' features at the same point still surface. Verified by per-feature filter loop. |

## Anti-Pattern Scan

| Pattern | Result |
|---------|--------|
| `dangerouslySetInnerHTML` introduced | NONE (only mention is documentation comment in `popup-template.ts:8`) |
| Hardcoded empty data flowing to render | NONE — `visibleFields` defaults are intentional spec semantics |
| TODO/FIXME/PLACEHOLDER in modified files | NONE in new/touched code paths |
| Unwired imports | NONE — all popup-template imports consumed |

## Behavioral Spot-Checks

| Behavior | Test | Result |
|----------|------|--------|
| `popup_config` column persisted in DB | `\d catalog.map_layers` | PASS — `popup_config | jsonb` present |
| Pydantic accepts valid shape | docker `MapLayerInput(popup_config={'enabled': True, 'expression': '{x}', 'visible_fields': ['x']})` | PASS |
| Pydantic rejects bad enabled (`'yes'`) | docker `MapLayerInput(popup_config={'enabled': 'yes'})` | PASS — raises ValidationError |
| Pydantic rejects extra keys | docker `MapLayerInput(popup_config={'enabled': True, 'extra': 1})` | PASS — raises ValidationError |
| Response models expose `popup_config` | `popup_config in MapLayerResponse.model_fields and SharedLayerResponse.model_fields` | PASS |
| `popup-template` unit tests | `npm test -- --run popup-template.test.ts` | PASS — 25/25 |
| `PopupConfigEditor` component tests | `npm test -- --run PopupConfigEditor.test.tsx` | PASS — 5/5 |
| i18n parity (en/de/es/fr have new keys) | `npm run test:i18n` | PASS — 2/2 |
| 3 atomic task commits | `git log --grep="260425-oxh"` | PASS — `88e6e9a7`, `b4f3fbc3`, `31f8b70c` (plus pre-dispatch plan commit) |
| TypeScript build clean for popup files | `npx tsc -b --noEmit` | PASS — no errors related to popup work (only pre-existing baseUrl deprecation warning) |

## Gaps

None. All 7 must_haves truths verified, all 9 must_haves artifacts present and substantive, all 7 key links wired, all 5 LOCKED decisions honored, all behavioral spot-checks pass.

## Recommended Remediation

None.

---

*Verified: 2026-04-25*
*Verifier: Claude (gsd-verifier, goal-backward)*
