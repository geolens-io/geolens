---
audit_type: post-impl
audit_date: 2026-04-25
scope: popup_config feature (quick task 260425-oxh)
prior_audit: post-impl-20260425-c.md
overall_grade: B
total_findings: 34
priority_breakdown: { p0: 0, p1: 5, p2: 12, p3: 17 }
---

# Post-Implementation Audit — 2026-04-25 (Layer Popup Config)

## Scorecard

| Dimension | Grade | Findings | P0 | P1 | P2 | P3 |
|-----------|-------|----------|----|----|----|----|
| KISS & Simplification | B | 7 | 0 | 0 | 3 | 4 |
| Performance | B | 7 | 0 | 2 | 3 | 2 |
| Cleanup & Dead Code | A | 5 | 0 | 0 | 1 | 4 |
| Type Safety | B | 7 | 0 | 1 | 1 | 5 |
| Error Handling & Resilience | B | 8 | 0 | 2 | 4 | 2 |
| **Overall** | **B** | **34** | **0** | **5** | **12** | **17** |

## Executive Summary

Focused audit on the layer popup-config feature shipped today as quick task `260425-oxh` (commits `88e6e9a7` → `2371d426`). The feature is structurally sound and ships with **zero P0 crash risks**. The five **P1** findings cluster around two themes: (1) two map components (`BuilderMap`, `ViewerMap`) repeat an `O(L×F)` linear-scan layer lookup on every cursor move, which is the only real performance concern given the new mousemove gating; (2) the editor's expression input has no `maxLength` cap, so users can compose a 10 000-char template and only learn at save time that the backend rejects anything over 500 — and the save-error toast is generic, hiding the backend validator's specific error message. The strongest **P2** simplification opportunity is replacing the loose `popup_config: dict | None` plus 39-line manual validator with a typed `PopupConfig` Pydantic submodel — this collapses three findings (KISS-6, TYPE-2, TYPE-3) at once and restores type information through the service layer. Cleanup grade is A: prior audits and the post-review remediation in `8ca90a9f` left almost no fresh debt — only one truly dead i18n key (`layerItem.popupTitle`) and a single inconsistent `defaultValue` override.

## Scope

- **Audit type:** Focused, popup_config feature only — prior audit `post-impl-20260425-c.md` covered the rest of the repo.
- **Files audited:** 18 (13 frontend, 5 backend) — see appendix.
- **Commits:** `88e6e9a7`, `b4f3fbc3`, `31f8b70c`, `8ca90a9f`, `54f077d6`, `2371d426`.
- **Test baseline:** Backend 1 951/1 965 pass (14 pre-existing failures in `test_stac_record_output.py` and `test_public_urls.py` — unrelated to popup_config; popup_config-specific tests 101/101 pass in `test_maps.py`). Frontend 994/1 003 pass (9 pre-existing failures in `AppLayout.test.tsx` footer/skip-link tests — unrelated; popup-specific tests 30/30 pass).
- **Static analysis baseline:** ruff 0 errors; eslint 5 warnings (0 errors); tsc 55 errors (all pre-existing, none in popup files); mypy not installed in the local venv.

---

## 1. KISS & Simplification (B)

### Findings

1. **[KISS-1] `BuilderMap.tsx:254-301`** — `handleClick` is ~48 lines and mixes layer-id parsing, popup-disabled filtering, feature mapping, popup-state writes, and `onFeatureSelect` notification; the same per-feature mapping (`replace(/^layer-/, '')` + `find()` + cfg + substitute) is duplicated in `handleMouseMove` (lines 318-323).
2. **[KISS-2] `ViewerMap.tsx:294-339`** — Same anti-pattern. The viewer click handler does the `(feature) → { sortOrder, matched, cfg }` derivation twice — once in the filter pass (303-307), once inside the `.map` (313-326).
3. **[KISS-3] `PopupConfigEditor.tsx:134-149`** — `handleToggle` writes a different shape depending on whether config exists, but the `else` branch builds the same shape `update()` would produce. The keyed remount on `layer.id` already gives per-layer fresh-start so the `lastEnabledConfigRef` saved-state is functionally redundant.
4. **[KISS-4] `PopupConfigEditor.tsx:91-102, 162-171`** — Two parallel state pieces (`localExpr` + `debouncedExpr`) plus a `debounceRef` reimplement debouncing for a *display-only* concern (validation styling). The parent gets `expression` synchronously via `update()` already — `localExpr` adds nothing beyond what the prop provides.
5. **[KISS-5] `popup-template.ts:56-64`** — `isPopupConfigValid` is used at exactly one call site (`use-builder-save.ts:148`). Two-line wrapper around `extractPlaceholders` + `validatePlaceholders`.
6. **[KISS-6] `schemas.py:60-98`** — 39 lines of manual `isinstance`/length checks for a fixed-shape object. Pydantic does this for free with a typed submodel.
7. **[KISS-7] `service.py:646-663`** — `add_layer` now takes 14 parameters (6 positional + 8 keyword-only). Six of those keyword-only fields exactly mirror `MapLayerInput`. Accept the schema instead of unpacking.

### Recommendations
- Extract a single `mapHitToFeature(hit, layers)` helper used by both BuilderMap and ViewerMap (collapses 4 duplicated blocks).
- Replace `popup_config: dict | None` + manual validator with a typed `PopupConfig` Pydantic model (eliminates 39 lines, propagates types through service signatures — see Type Safety).
- Drop `localExpr` in `PopupConfigEditor`; keep only `debouncedExpr` for the validation memo.

---

## 2. Performance (B)

### Findings

1. **[PERF-1] `BuilderMap.tsx:268-272, 275-290, 319-323`** — `mousemove` fires at up to ~60Hz (rAF-throttled). On every move, `layersRef.current.find()` runs **per queried feature**. With 10 layers × N hits per move that's `O(L×F)` linear scans plus a regex `.replace()` per feature. On a polygon-heavy map (50 hits) over a 10-layer composition this is ~500 array scans/sec just for cursor logic.
2. **[PERF-2] `ViewerMap.tsx:303-307, 313-328, 358-362`** — Same anti-pattern with an integer parse on every feature (`parseInt(...replace(/^viewer-layer-/, ''), 10)`).
3. **[PERF-3] `popup-template.ts:13, 41-50`** — Module-level global RegExp is the right choice (no per-call alloc). `String.prototype.replace(/g, fn)` resets `lastIndex` so it's safe. No-op note.
4. **[PERF-4] `FeaturePopup.tsx:60-69, 72-93`** — `formatValue`, `baseEntries`, and visible-field resolution rebuild on every render of the popup (e.g. when paging via `activeIndex` or copy-toast state).
5. **[PERF-5] `schemas.py:60-98`** — Backend validator is `<1ms` worst case. No-op note.
6. **[PERF-6] `BuilderMap.tsx:493`** — `<FeaturePopup key={lng-lat}>` remounts the popup on every click, discarding `useState` (activeIndex, copiedKey).
7. **[PERF-7] `BuilderMap.tsx:285` / `ViewerMap.tsx:323`** — `t('common:viewer.featureFallback')` is invoked inside the per-feature `.map()`. i18next lookups are cheap but allocate strings per hit per click.

### Recommendations
- Replace per-feature `layersRef.current.find()` in both BuilderMap and ViewerMap click+mousemove handlers with a precomputed `Map<layerId, layer>` lookup. Single biggest win.
- Memoize `baseEntries` / `visibleEntries` / `formatValue` inside `FeaturePopup` so paging doesn't re-derive the property list for 100-attribute features.
- Stabilize the `<FeaturePopup key=…>` so it doesn't remount per click.

---

## 3. Cleanup & Dead Code (A)

### Findings

1. **[CLEANUP-1] `i18n/locales/{en,de,es,fr}/builder.json:41`** — Dead i18n key `layerItem.popupTitle: "Popup"` was added in `b4f3fbc3` alongside `popupTab` but `grep` finds zero non-locale references. Only `popupTab` is used (via dynamic `t(\`layerItem.${tab}Tab\`)` in `LayerEditorPanel.tsx:120`).
2. **[CLEANUP-2] `PopupConfigEditor.tsx:286`** — Inline `defaultValue: 'Remove field'` fallback is redundant — the key exists in all four locales, and the other 11 popup keys in this file all use plain `t('popup.X')`.
3. **[CLEANUP-3] `PopupConfigEditor.tsx:104-112`** — `lastEnabledConfigRef` is functionally redundant given the `key={layer.id}` remount and the `handleToggle(false)` path that preserves `expression`/`visible_fields`.
4. **[CLEANUP-4] `BuilderMap.tsx:88-89` vs `ViewerMap.tsx:152-153` vs `FeaturePopup.tsx:9-19`** — Inconsistent typing of `popupInfo.features[].title`/`visibleFields`: BuilderMap declares them required, ViewerMap and FeaturePopup declare optional. Both code paths always populate these fields.
5. **[CLEANUP-5] `i18n/locales/*/builder.json` (popup section)** — Naming consistency: `popup.expression` is the key for what the UI renders as "Title template". Rename to `popup.titleTemplate` for parity.

### Recommendations
- Remove the dead `layerItem.popupTitle` key from all four locale files.
- Drop the inline `defaultValue: 'Remove field'` override.
- Pick one canonical `FeatureInfo` shape (probably the `FeaturePopup` optional version) and import it everywhere.

### Patterns NOT flagged (intentional)
- Backend snake_case (`popup_config`) ↔ frontend camelCase (`popupConfig`) — consistent boundary translation.
- No TODO/FIXME/HACK comments in any popup file. No `console.log/debug/info`. No `print()`.
- No backwards-compat shims; no legacy popup default code paths.
- `extractPlaceholders` / `validatePlaceholders` / `substitutePopupTemplate` / `isPopupConfigValid` share a single `PLACEHOLDER_RE` regex — no duplicate logic.

---

## 4. Type Safety (B)

### Findings

1. **[TYPE-1] `BuilderMap.tsx:81-91` vs `ViewerMap.tsx:148-155` vs `FeaturePopup.tsx:9-19`** — Three near-identical `popupInfo` feature shapes with different `optional`/`nullable` mixes. BuilderMap requires `title: string | null` + `visibleFields: string[] | null`; ViewerMap and FeaturePopup both make them optional. Works only because `FeaturePopup`'s runtime check at line 83 covers both `undefined` and `null`.
2. **[TYPE-2] `schemas.py:44-98`** — `popup_config: dict | None` plus a 35-line `field_validator` manually checking shape, types, lengths, and key allowlist. A nested `PopupConfig(BaseModel)` with `enabled: bool`, `expression: str | None = Field(max_length=500)`, `visible_fields: list[constr(max_length=128)] | None = Field(max_length=100)` and `model_config = ConfigDict(extra='forbid')` would do all this for free with better OpenAPI schemas. (The `label_config` analog has no inline validator, so popup_config's manual shape check is the divergence to fix.)
3. **[TYPE-3] `service.py:659-660, 704`** — `add_layer()` and `_replace_layers()` receive `popup_config` as an untyped dict. If the schema were a typed model, the type would survive the journey to the ORM column (which can still serialize via JSONB).
4. **[TYPE-4] `PopupConfigEditor.tsx:154-158, 88, 145`** — Mixes `null`-as-storage and `''`-as-display. `update()` seeds `expression: null`, but the editor binds `expression ?? ''` for the input. Pick one storage shape.
5. **[TYPE-5] `ViewerMap.tsx:78-79, 100-101`** — Unnecessary `(layer.paint as Record<string, unknown>) ?? {}` casts. `SharedLayerResponse.paint`/`layout` is already typed `Record<string, unknown>`.
6. **[TYPE-6] `types/api.ts:761-764, 880-883`** — `MapLayerResponse.popup_config?: PopupConfig | null` is technically wrong: backend always serializes the field. The `?:` is defensive against legacy data. Tighten to `popup_config: PopupConfig | null`.
7. **[TYPE-7] `PopupConfigEditor.tsx:140`** — `onPopupChange({ enabled: true, expression: '', visible_fields: null })` writes `''` (passes backend `isinstance(str)` and template parser returns `[]` placeholders). Storage convention elsewhere prefers `null`.

### Recommendations
- Convert backend `popup_config` to a structured `PopupConfig` Pydantic submodel and propagate the type through `add_layer` / `_replace_layers` (collapses TYPE-2, TYPE-3, KISS-6).
- Make a single canonical `FeatureInfo` exported from `FeaturePopup.tsx` and import it in BuilderMap and ViewerMap (collapses TYPE-1, CLEANUP-4).
- Tighten `popup_config?:` to required, drop redundant `as` casts.

---

## 5. Error Handling & Resilience (B)

### Findings

1. **[RESILIENCE-1] CRASH `popup-template.ts:45`** — `substitutePopupTemplate` reads `properties[key]` directly. Current callers guard with `(feature.properties ?? {})`, but a future caller passing `null`/`undefined` would crash. One-line defensive guard.
2. **[RESILIENCE-2] DEGRADED `use-maps.ts:67`** — `useUpdateMap.onError` shows a generic "Failed to save map" toast. If the backend popup_config validator returns 422 with a specific message ("expression must be 500 characters or fewer"), the message is dropped. User can't tell whether the popup template caused the failure.
3. **[RESILIENCE-3] DEGRADED `schemas.py:78-91`** — `visible_fields` validator accepts duplicates and empty strings. The frontend prevents both, but a malicious/buggy client could send them through. Add `set(vf)` check + `any(not x for x in vf)` check.
4. **[RESILIENCE-4] DEGRADED `PopupConfigEditor.tsx:166, 215`** — Expression `<Input>` has no `maxLength` cap. User can paste a 10 000-char template, type more, and only learn the 500-char limit on save (with a generic toast — see RESILIENCE-2).
5. **[RESILIENCE-5] CRASH `FeaturePopup.tsx:107-108`** — `handlePrev`/`handleNext` clamp by `features.length`, but `activeIndex` can exceed `features.length - 1` if features shrinks while the popup is open. Line 55 fallback prevents a hard crash but the pager UI shows "5/2" briefly.
6. **[RESILIENCE-6] DEGRADED `BuilderMap.tsx:269, 276, 322`** — `feature.layer.id.replace(/^layer-/, '')` doesn't verify the prefix matched. If a non-managed layer surfaces (e.g., basemap label slips past the queryLayerIds filter), the unstripped string is treated as a UUID and `find()` returns undefined; `popup_config?.enabled !== false` then evaluates to `true` and an empty popup would render.
7. **[RESILIENCE-7] DEGRADED `BuilderMap.tsx:334`, `ViewerMap.tsx:371`** — Cleanup calls `map.getCanvas().style.cursor = ''` guarded by `if (map.getCanvas())`, but `getCanvas()` can throw post-`map.remove()` on some MapLibre versions.
8. **[RESILIENCE-8] DEGRADED `PopupConfigEditor.tsx:114-130`** — Empty `columns` (layer with no `dataset_column_info`) renders the editor with a working toggle and expression input but the "Add Field" picker silently disappears. No empty-state copy.

### Recommendations
- Surface backend validation messages in save toasts (RESILIENCE-2) — one-line change with the highest UX leverage. Unblocks debugging for RESILIENCE-3 and RESILIENCE-4 simultaneously.
- Add `maxLength={500}` to the popup expression input (RESILIENCE-4).
- Harden `substitutePopupTemplate` and the `feature.layer.id` regex strip (RESILIENCE-1, RESILIENCE-6) — both are 1-2 line defensive guards.

---

## 6. Prioritized Action Items

| Priority | Finding | File:line | Fix | Effort |
|----------|---------|-----------|-----|--------|
| **P1** | Surface backend validation messages in save toast | `frontend/src/hooks/use-maps.ts:67` | Read `error.detail`/`error.message` from `ApiError` and pass into `toast.error` | 10m |
| **P1** | Cap expression input to 500 chars | `PopupConfigEditor.tsx:215` | `<Input maxLength={500} … />` | 5m |
| **P1** | Replace per-feature `find()` with `Map` lookup in click+mousemove | `BuilderMap.tsx:268-323`, `ViewerMap.tsx:303-362` | Build `mapById = useMemo(() => new Map(layers.map(l => [getLayerId(l.id), l])), [layers])`; reuse via ref in handlers | 30m |
| **P1** | Memoize `popupInfo`-derived data in `FeaturePopup` | `FeaturePopup.tsx:60-93` | `useMemo` for `baseEntries`, `visibleEntries`, lift `formatValue` | 15m |
| **P1** | Make canonical `FeatureInfo` and import everywhere | `FeaturePopup.tsx`, `BuilderMap.tsx:81-91`, `ViewerMap.tsx:148-155` | Export `FeatureInfo` from `FeaturePopup.tsx`; import + use in both maps | 15m |
| **P2** | Convert `popup_config` to typed `PopupConfig` Pydantic submodel | `schemas.py:44-98`, `service.py:646-663` | Define `class PopupConfig(BaseModel)` with `extra='forbid'`; thread through `add_layer` / `_replace_layers` | 45m |
| **P2** | Extract `mapHitToFeature` shared by builder + viewer | `BuilderMap.tsx`, `ViewerMap.tsx` | New helper in `lib/popup-hit-mapper.ts`; use in click + mousemove | 30m |
| **P2** | Drop `localExpr` from `PopupConfigEditor` | `PopupConfigEditor.tsx:91-102` | Use `expression` prop directly; keep only `debouncedExpr` | 15m |
| **P2** | Stabilize `<FeaturePopup key>` to avoid per-click remount | `BuilderMap.tsx:493` | Replace `key={lng-lat}` with stable key or remove key | 10m |
| **P2** | Hoist `t('viewer.featureFallback')` above `.map()` | `BuilderMap.tsx:285`, `ViewerMap.tsx:323` | Bind once before the loop | 5m |
| **P2** | Defensive null-properties guard in `substitutePopupTemplate` | `popup-template.ts:45` | `if (!properties) return template.replace(re, () => '')` | 5m |
| **P2** | Reject duplicate / empty `visible_fields` in backend validator | `schemas.py:78-91` | Add `set()` check + non-empty entry check | 10m |
| **P2** | Reset `activeIndex` when `features.length` changes | `FeaturePopup.tsx:48-52` | `useEffect(() => { if (activeIndex >= features.length) setActiveIndex(0); }, [features.length])` | 5m |
| **P2** | Verify regex prefix matched before slicing layer id | `BuilderMap.tsx:269, 276, 322`, `ViewerMap.tsx:299, 314, 359` | `if (!feature.layer.id.startsWith('layer-')) return null` | 10m |
| **P2** | Wrap `getCanvas()` cleanup in try/catch | `BuilderMap.tsx:334`, `ViewerMap.tsx:371` | `try { ... } catch {}` | 5m |
| **P2** | Empty-state copy for popup editor with no columns | `PopupConfigEditor.tsx:114-130` | Render hint when `columns.length === 0` | 10m |
| **P3** | Remove dead `layerItem.popupTitle` i18n key | 4 × `builder.json` | Delete the line | 2m |
| **P3** | Drop inline `defaultValue: 'Remove field'` | `PopupConfigEditor.tsx:286` | `t('popup.removeField')` | 1m |
| **P3** | Remove redundant `lastEnabledConfigRef` | `PopupConfigEditor.tsx:104-112` | Inline + simplify `handleToggle` | 15m |
| **P3** | Rename `popup.expression` → `popup.titleTemplate` | 4 × `builder.json` + 1 use site | Rename key for parity with UI label | 5m |
| **P3** | Inline `isPopupConfigValid` (single call site) | `popup-template.ts:56-64`, `use-builder-save.ts:148` | Inline two-line check at the call site | 5m |
| **P3** | `add_layer` accepts `MapLayerInput` instead of 14 params | `service.py:646-663`, `router.py:777-792` | Pass schema; extract fields inside | 20m |
| **P3** | Drop redundant `as Record<string, unknown>` casts | `ViewerMap.tsx:78-79, 100-101` | Remove the casts | 2m |
| **P3** | Tighten `popup_config?: PopupConfig | null` → required | `types/api.ts:761-764, 880-883` | Drop the `?` | 5m |
| **P3** | Normalize empty expression to `null` in `handleToggle` | `PopupConfigEditor.tsx:140` | `expression: '' ? '' : null` → `null` | 2m |
| **P3** | Thread typed model through service signatures | `service.py:659-660, 704` | After P2 conversion to `PopupConfig` | 10m |
| **P3** | Pick one storage shape: `null` or `''` for empty expression | `PopupConfigEditor.tsx:154-158, 88, 145` | Convert `''` → `null` at boundaries | 10m |

**Total P1 effort:** ~75 min  
**Total P2 effort:** ~165 min  
**Total P3 effort:** ~85 min

---

## 7. Debt Summary

| Metric | Value |
|--------|-------|
| Total findings | 34 |
| P0 (must-fix immediately) | 0 |
| P1 (must-fix this cycle) | 5 |
| P2 (should-fix soon) | 12 |
| P3 (nice-to-have) | 17 |
| Estimated P0+P1 effort | ~75 minutes |
| Estimated P0+P1+P2 effort | ~240 minutes |

Compared to the prior audit (`post-impl-20260425-c.md` — 40 findings, 4 P1):
- Cleanup grade improved A → A (no new debt accumulated; the post-review remediation in `8ca90a9f` already eliminated dead code)
- Resilience grade held at B but new findings cluster around the popup feature surface (expected for new code)
- Type safety regressed slightly because `popup_config: dict | None` introduces a new untyped field (can be remediated by P2 conversion to typed submodel)
- Performance held at B; the BuilderMap mousemove `O(L×F)` finding is partly inherited (this lookup pattern existed before popup_config — popup_config just runs through it)

---

## 8. Static Analysis Baseline

| Tool | Before | Notes |
|------|--------|-------|
| Backend ruff | 0 errors | Clean. |
| Backend mypy | n/a | Module not installed in local venv. |
| Frontend eslint | 0 errors / 5 warnings | All warnings pre-existing (e.g. `MapBuilderPage.tsx:230` exhaustive-deps), none in popup files. |
| Frontend tsc | 55 errors | All pre-existing across `ImportPreview.tsx`, `RegisterForm.tsx`, `LegendWidget.tsx`, `SearchResultCard.tsx`, `layer-capabilities.test.ts`, `normalize-style-config.ts`, `PublicViewerPage.test.tsx`, `SearchPage.test.tsx`, `DatasetPage.tsx`, `ImportPage.tsx`, `use-builder-save.test.ts`. None in popup files. |
| Backend pytest | 1 951 pass / 14 fail | 14 pre-existing failures in `test_stac_record_output.py` and `test_public_urls.py` — none in popup-related modules. Popup tests 101/101 pass in `test_maps.py`. |
| Frontend vitest | 994 pass / 9 fail | 9 pre-existing failures in `AppLayout.test.tsx` (footer/skip-link). None in popup-related modules. Popup tests 30/30 pass. |

---

## 9. Explicitly NOT Flagged

- **Backend `popup_config: dict | None` mirroring `label_config`**: Reviewed — although the dict pattern matches `label_config`, the *manual validator* on popup_config is the divergence (label_config has no validator). Flagged as TYPE-2 / KISS-6 because the validator's existence is the signal that a typed submodel would help.
- **`React.memo` on `LayerEditorPanel` / `PopupConfigEditor`**: Pre-existing memoization pattern; recent layer changes don't justify adding more memo overhead until profiling shows a hotspot.
- **`{title && (...)}` falsy rendering in `FeaturePopup`**: Empty-string expressions (`""`) render no title — intentional per the locked CONTEXT.md decision (title is optional).
- **`@dnd-kit/sortable` reuse**: Already present in the project (`LayerPanel.tsx`); no new dep.
- **Manual debounce in `PopupConfigEditor`**: Flagged as KISS-4 for simplification, not as a "reimplemented stdlib" finding — the codebase has no shared `useDebouncedValue` hook to reuse.
- **`<Switch>` from Radix not auto-keyed by layer.id**: Already addressed in `8ca90a9f` (`LayerEditorPanel` now passes `key={layer.id}` to `<PopupConfigEditor>`).
- **MapLibre tile errors while popup is open**: Tile errors are handled by MapLibre's own error events; popup state is independent — no new resilience surface.
- **Inline `style={{ whiteSpace: 'pre-wrap' }}` on the title**: Required because Tailwind's whitespace utilities don't expose `pre-wrap` in the project's preset; this is an MapLibre-popup-content specific need.

---

## Appendix — Files audited

**Backend (5):**
- `backend/app/modules/catalog/maps/models.py`
- `backend/app/modules/catalog/maps/schemas.py`
- `backend/app/modules/catalog/maps/service.py`
- `backend/app/modules/catalog/maps/router.py`
- `backend/alembic/versions/2026_04_25_0001-add_popup_config_to_map_layers.py`

**Frontend (13):**
- `frontend/src/lib/popup-template.ts`
- `frontend/src/components/builder/PopupConfigEditor.tsx`
- `frontend/src/components/builder/LayerEditorPanel.tsx`
- `frontend/src/components/builder/BuilderMap.tsx`
- `frontend/src/components/builder/hooks/use-builder-layers.ts`
- `frontend/src/components/builder/hooks/use-builder-save.ts`
- `frontend/src/components/builder/hooks/use-layer-map-sync.ts`
- `frontend/src/components/map/FeaturePopup.tsx`
- `frontend/src/components/viewer/ViewerMap.tsx`
- `frontend/src/pages/PublicMapViewerPage.tsx`
- `frontend/src/pages/MapBuilderPage.tsx` (popup tab wiring only)
- `frontend/src/types/api.ts` (popup_config fields)
- `frontend/src/i18n/locales/{en,de,es,fr}/builder.json` (popup keys)
