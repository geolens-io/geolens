---
quick_id: 260425-oxh
review_depth: quick
status: review_complete
remediation_status: all_resolved
remediation_commit: 8ca90a9f
files_reviewed: 21
---

# Quick Task 260425-oxh — Code Review

**Scope:** Layer popup config (enable/disable + custom expression with validation).

**Findings:** 1 MAJOR, 4 MINOR, 0 BLOCKER. The XSS, click-isolation, schema-validation, empty/null semantics, migration, i18n parity, and tab-union concerns from the prompt are all clean.

**Status:** All 5 findings remediated in commit `8ca90a9f` (post-review). See bottom of file for remediation summary.

---

## MAJOR

### MJ-01: `lastEnabledConfigRef` leaks popup config across layers

**File:** `frontend/src/components/builder/PopupConfigEditor.tsx:108-110, 132-147`

**Issue:** The ref that backs "toggle off → toggle on restores last values" is only updated *inside render* via `if (popupConfig && popupConfig.enabled) lastEnabledConfigRef.current = popupConfig;`. `LayerEditorPanel` mounts `PopupConfigEditor` without a layer-keyed `key` prop (`MapBuilderPage.tsx:420-426` and `LayerEditorPanel.tsx:162-167`), so the ref persists across layer switches.

Reproduction:
1. Open Layer A (popup enabled, `expression="A title"`, `visible_fields=["col_a"]`). Ref captures Layer A's config.
2. Switch to Layer B in the layer panel (its popup is currently disabled). The render-time guard `popupConfig.enabled` is false, so the ref is NOT updated; it still points at Layer A.
3. Toggle popup ON for Layer B. `handleToggle(true)` calls `onPopupChange({ ...lastEnabledConfigRef.current, enabled: true })`, which writes **Layer A's expression and visible_fields onto Layer B**.

This silently corrupts the user's saved popup config — they have no way to know an unrelated layer's expression and field allowlist were just copied in.

**Fix:** Either (a) key the editor by layer so it remounts and the ref re-initialises, or (b) reset the ref when the underlying layer changes. Option (a) — add a key in `LayerEditorPanel.tsx`:

```diff
- <PopupConfigEditor
-   columns={columns}
-   popupConfig={layer.popup_config ?? null}
-   onPopupChange={(config) => handlers.onPopupChange(layer.id, config)}
- />
+ <PopupConfigEditor
+   key={layer.id}
+   columns={columns}
+   popupConfig={layer.popup_config ?? null}
+   onPopupChange={(config) => handlers.onPopupChange(layer.id, config)}
+ />
```

Option (b) replaces the ref-during-render anti-pattern with a layer-keyed effect inside `PopupConfigEditor.tsx`:

```ts
const lastEnabledConfigRef = useRef<PopupConfig | null>(null);
useEffect(() => {
  // Reset when a different layer's config arrives, then capture only enabled state.
  lastEnabledConfigRef.current = popupConfig?.enabled ? popupConfig : null;
}, [popupConfig]);
```

(Either approach works; (a) is one line.) The existing test `renders disabled state when popupConfig is null and toggling on emits defaults` only mounts in isolation, so it does not exercise the cross-layer path.

---

## MINOR

### MN-01: Debounce on expression validation is effectively bypassed in production

**File:** `frontend/src/components/builder/PopupConfigEditor.tsx:90-99, 154-163`

**Issue:** `handleExpressionChange` calls `update({ expression: next })` synchronously, which propagates through `useLayerMapSync.handlePopupChange` → parent `setLocalLayers` → re-render with the new `popupConfig.expression` prop. The `useEffect(() => { setLocalExpr(expression); setDebouncedExpr(expression); }, [expression])` then fires and **synchronously** updates `debouncedExpr` to the latest typed value, overriding the 250 ms `setTimeout`. The `validation` memo recomputes on the next render, so the "Unknown placeholders" message appears immediately on each keystroke, not after the debounce window.

The unit test `shows validation error after debounce when an unknown placeholder is typed` only passes because `onPopupChange` is a `vi.fn()` mock that never updates the prop, so the useEffect bypass never triggers.

This is a code-quality / dead-code issue, not a correctness bug — the UI still validates correctly, just sooner than designed. If the intent is real keystroke debouncing, drive validation off `localExpr` only and stop syncing `debouncedExpr` from the prop:

```ts
useEffect(() => {
  setLocalExpr(expression);     // still needed for cross-layer reset
  // setDebouncedExpr(expression); // remove — let setTimeout drive it
}, [expression]);
```

If immediate validation is acceptable, delete the debounce machinery entirely (`debouncedExpr` state, `debounceRef`, `setTimeout`, cleanup effect) and validate `localExpr` directly.

### MN-02: Backend `popup_config` validator imposes no length caps

**File:** `backend/app/modules/catalog/maps/schemas.py:60-85`

**Issue:** `_validate_popup_config_shape` checks shape and key allowlist but never bounds the size of `expression` or `visible_fields`. An authenticated user (or compromised credential) can `PUT /maps/{id}` with `expression` of, say, 10 MB or `visible_fields` containing tens of thousands of strings. The blob lands in JSONB and is returned on every `GET /maps/{id}` to all readers (including anonymous viewers for public maps), inflating response payloads.

Other layer fields use `Field(max_length=...)` (e.g. `display_name` at 255 chars). Pydantic `field_validator` runs *after* type coercion but you can add explicit caps inside the validator:

```python
expr = v.get("expression", None)
if expr is not None:
    if not isinstance(expr, str):
        raise ValueError("popup_config.expression must be a string or null")
    if len(expr) > 500:
        raise ValueError("popup_config.expression must be <= 500 characters")
vf = v.get("visible_fields", None)
if vf is not None:
    if not isinstance(vf, list) or not all(isinstance(x, str) for x in vf):
        raise ValueError("popup_config.visible_fields must be a list of strings or null")
    if len(vf) > 100:
        raise ValueError("popup_config.visible_fields supports at most 100 entries")
    if any(len(x) > 128 for x in vf):
        raise ValueError("popup_config.visible_fields entries must be <= 128 characters")
```

Tune the limits to whatever the column-name and template policies tolerate.

### MN-03: `POST /maps/{id}/layers/` silently discards `popup_config` (and `label_config`, `filter`, `style_config`)

**File:** `backend/app/modules/catalog/maps/router.py:777-787` and `backend/app/modules/catalog/maps/service.py:646-697`

**Issue:** `MapLayerInput` accepts `popup_config`, but `add_layer_endpoint` only forwards the seven legacy fields (`dataset_id`, `sort_order`, `visible`, `opacity`, `paint`, `layout`, `layer_type`) into `service.add_layer`, and `service.add_layer` has no `popup_config` parameter. So an API client that sends `POST /maps/{id}/layers/ {... "popup_config": {...}}` gets a 201 back with the body silently dropped. The same is true for `filter`, `label_config`, and `style_config`.

In the builder UX this never surfaces because saves go through `PUT /maps/{id}` (full layer replacement, see `service._replace_layers:452`), which does honor `popup_config`. But documented behavior diverges from actual behavior, and any caller that builds maps incrementally via the layer endpoint will lose data.

**Fix:** either extend `add_layer` to accept and persist the configuration JSON columns, or document that POST `/layers/` ignores configuration fields. Preferred fix:

```python
async def add_layer(
    session: AsyncSession,
    map_id: uuid.UUID,
    dataset_id: uuid.UUID,
    sort_order: int = 0,
    visible: bool = True,
    opacity: float = 1.0,
    paint: dict | None = None,
    layout: dict | None = None,
    layer_type: str | None = None,
    *,
    display_name: str | None = None,
    filter: list | None = None,
    label_config: dict | None = None,
    popup_config: dict | None = None,
    style_config: dict | None = None,
    show_in_legend: bool = True,
) -> MapLayer:
    ...
    layer = MapLayer(
        ...,
        display_name=display_name,
        filter=filter,
        label_config=label_config,
        popup_config=popup_config,
        style_config=style_config,
        show_in_legend=show_in_legend,
    )
```

and pass them through from `add_layer_endpoint`.

### MN-04: Hover cursor doesn't honor `popup_config.enabled === false`

**File:** `frontend/src/components/builder/BuilderMap.tsx:304-318`

**Issue:** `handleClick` filters per-feature on `popup_config.enabled !== false` (line 268-272), but `handleMouseMove` uses the same `queryRenderedFeatures(...)` and sets `cursor = 'pointer'` whenever any feature is under the cursor — including features on layers whose popup is explicitly disabled. The user gets a "clickable" affordance that does nothing on click. Mirror the same per-feature filter the click handler uses:

```ts
const features = map.queryRenderedFeatures(e.point, { layers: queryLayers });
const interactive = features.some((f) => {
  const layerId = f.layer.id.replace(/^layer-/, '');
  const matched = layersRef.current.find((l) => l.id === layerId);
  return matched?.popup_config?.enabled !== false;
});
map.getCanvas().style.cursor = interactive ? 'pointer' : '';
```

UX polish, not a correctness bug.

---

## Notes on the prompt's specific concerns (all clean)

1. **XSS / injection** — `substitutePopupTemplate` (`frontend/src/lib/popup-template.ts:41-50`) returns a plain string; the only render sites are `FeaturePopup.tsx:123-125` for the title and `ValueDisplay` for property values, both as JSX text nodes (auto-escaped). No `dangerouslySetInnerHTML`, no `eval`, no `new Function`. Property URLs only render as anchors when they start with `http://`/`https://` (`FeaturePopup.tsx:36-39`), so `javascript:` URLs are not a vector.
2. **Backend schema validation** — `_validate_popup_config_shape` is registered with `@field_validator("popup_config")` on `MapLayerInput`, which is the body type for `POST /maps/{id}/layers/` and the element type for `MapUpdate.layers`, the only ingress paths that persist popup_config (see MN-03 for a partial gap on POST). The shape checks (bool / string-or-null / list-of-strings-or-null / unknown-key allowlist) are correct.
3. **Click-handler isolation** — `BuilderMap.tsx:268-272` filters per-feature, not per-click. Overlapping layers with mixed enabled state behave correctly: the disabled layer's hits are dropped, the enabled layer's hits surface in the popup carousel. `feature.layer.id.replace(/^layer-/, '')` is safe because `queryLayerIdsRef` only contains main `layer-${id}` IDs (no `-outline`/`-label` companions).
4. **Empty/null semantics** — `FeaturePopup.tsx:81-92` correctly handles all three branches: `null/undefined → columnInfo legacy fallback`; `[] → zero rows`; ordered list → preserves user order via `propMap.get(k)` lookup.
5. **Validation timing** — `useBuilderSave.handleSave` (`hooks/use-builder-save.ts:148-154`) blocks save with `isPopupConfigValid` before mutating; live validation runs in `PopupConfigEditor` (see MN-01 for the debounce being effectively a no-op, but it doesn't break anything).
6. **Migration safety** — `2026_04_25_0001-add_popup_config_to_map_layers.py` adds a nullable JSONB column on upgrade and drops it on downgrade; the operations are inverses (downgrade is destructive of any populated values, which is correct semantics for a downgrade).
7. **i18n parity** — All four locales include the 11 `popup.*` keys (`enable`, `expression`, `expressionHelp`, `expressionPlaceholder`, `unknownPlaceholders`, `visibleFields`, `visibleFieldsAll`, `visibleFieldsCustom`, `addField`, `removeField`, `noFieldsSelected`) plus `layerItem.popupTab`/`layerItem.popupTitle`. No missing keys. Single-curly `{column_name}` in help text is rendered literally by i18next (only `{{var}}` is interpolated), so no escaping issue.
8. **Tab union extensions** — `'style' | 'filter' | 'labels' | 'popup'` is consistent across `LayerEditorPanel.tsx:17,30,98`, `use-builder-layers.ts:36,178`. `MapBuilderPage.tsx:222` wires `onPopupChange` into `layerEditorHandlers`. `LayerEditorPanel.tsx:102` gates the popup tab on `caps.supportsFilterEditor || caps.supportsLabelEditor` — semantically misleading but functionally equivalent to "vector layer with geometry," which is the right gate for popups.

---

_Reviewed: 2026-04-25_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: quick_

---

## Remediation (2026-04-25, commit `8ca90a9f`)

| ID | Resolution |
|----|------------|
| **MJ-01** | `key={layer.id}` added on `<PopupConfigEditor>` in `LayerEditorPanel.tsx`; `lastEnabledConfigRef` now resets via `useEffect([popupConfig])` rather than a render-time mutation. The component remounts on layer switch, so the ref starts fresh per layer. |
| **MN-01** | The `useEffect(() => { setLocalExpr(expression); setDebouncedExpr(expression); }, [expression])` was removed. With the per-layer key the editor remounts on layer switch, so the debounce setTimeout is now the only writer of `debouncedExpr`. The 250 ms debounce now actually debounces. |
| **MN-02** | `_validate_popup_config_shape` now enforces: `expression` ≤ 500 chars, `visible_fields` ≤ 100 entries, each entry ≤ 128 chars. |
| **MN-03** | `service.add_layer` extended with kwargs (`display_name`, `filter`, `label_config`, `popup_config`, `style_config`, `show_in_legend`); `POST /maps/{id}/layers/` now forwards them. Existing call sites are unaffected (all kwargs default to None / True). |
| **MN-04** | `BuilderMap.handleMouseMove` now mirrors `handleClick`'s per-feature filter: cursor goes pointer only when at least one hit is on a popup-enabled layer. |

**Test verification of remediation:** 101/101 backend maps tests + 46/46 frontend popup/builder-save tests pass.
