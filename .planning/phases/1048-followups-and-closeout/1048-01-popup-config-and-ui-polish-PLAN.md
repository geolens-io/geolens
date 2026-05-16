---
phase: 1048-followups-and-closeout
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/builder/hooks/use-builder-save.ts
  - frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts
  - frontend/src/components/builder/BulkActionBar.tsx
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/i18n/locales/de/builder.json
  - frontend/src/i18n/locales/es/builder.json
  - frontend/src/i18n/locales/fr/builder.json
  - e2e/builder.spec.ts
autonomous: true
requirements:
  - FOLLOWUP-01
must_haves:
  truths:
    - "User attempting save with invalid popup_config sees a toast naming the offending layer (not a generic 'cannot save' message)."
    - "If the frontend pre-check is bypassed and the backend rejects a popup_config payload, the user sees a structured, translated error toast — not the generic 'saveFailed'."
    - "On a previously-blocked map, fixing the popup expression and saving completes the PUT round-trip successfully (e2e covers this)."
    - "Phase 1047 UI-REVIEW 3-item polish (partial-failure suffix, cursor-not-allowed container, text-[13px] replacement) is shipped in BulkActionBar + builder locales."
  artifacts:
    - path: frontend/src/components/builder/hooks/use-builder-save.ts
      provides: "popup_config validation surface that names the offending layer + structured backend-error translation"
    - path: frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts
      provides: "vitest cases: (a) frontend pre-check toast names layer; (b) backend 4xx popup_config rejection produces translated toast (not saveFailed)"
    - path: frontend/src/components/builder/BulkActionBar.tsx
      provides: "container cursor-not-allowed during deleting state; text-[13px] replaced with text-xs"
    - path: frontend/src/i18n/locales/en/builder.json
      provides: "popupConfigInvalid_named, popupConfigBackendRejected, deletePartialFailure suffix update"
  key_links:
    - from: frontend/src/components/builder/hooks/use-builder-save.ts handleSave catch{}
      to: ApiError instance + structured detail check (popup_config tag)
      via: "instanceof ApiError + status + detailRaw inspection"
      pattern: "instanceof ApiError"
    - from: frontend/src/components/builder/BulkActionBar.tsx container className
      to: isDeleting state
      via: "cn() conditional"
      pattern: "isDeleting.*cursor-not-allowed"
---

<objective>
Resolve FOLLOWUP-01 (invalid `popup_config` silently blocking PUT round-trip) and bundle the 3 priority UI-REVIEW carry-overs from Phase 1047 into the same builder UI commit run.

Purpose: An invalid popup expression today shows a generic toast (`popupConfigInvalid`) that does not name which layer is broken; if the frontend pre-check is bypassed (e.g., stale state, programmatic save), the backend rejection currently falls into a generic `saveFailed` toast that gives the user no path to recovery. The followup makes both failure surfaces actionable.

Output: Save hook re-architected to (a) surface the offending layer name in the pre-check toast and (b) detect popup_config-specific backend rejections and route them to a distinct, translated toast. Vitest covers both surfaces; e2e covers the success-path round-trip on a fixture map that was previously blocked. UI-REVIEW polish (partial-failure toast suffix in all four locales, container cursor-not-allowed, text-[13px] → text-xs) ships in the same plan because all touches are on builder UI + locales.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/ROADMAP.md
@.planning/REQUIREMENTS.md
@.planning/phases/1048-followups-and-closeout/1048-CONTEXT.md
@.planning/phases/1047-perf-and-code-quality-fixes/1047-UI-REVIEW.md

<interfaces>
<!-- Existing identifiers the executor needs. Extracted from codebase; no exploration needed. -->

From frontend/src/api/client.ts:
- `export class ApiError extends Error` with fields:
  - `status: number`
  - `detail: string` (translated message)
  - `detailRaw: unknown` (raw backend response body — used to inspect structured rejections)

From frontend/src/components/builder/hooks/use-builder-save.ts:
- import: `import { ApiError } from '@/api/client';` (line 10) — already imported, available in handleSave's catch block
- imports `extractPlaceholders, validatePlaceholders` from `@/lib/popup-template` (line 14)
- `handleSave()` async function starting at line 354
- Pre-check loop at lines 373–382 finds `invalidLayer` then calls `toast.error(t('toasts.popupConfigInvalid'), { id: 'popup-config-invalid', duration: 6000 }); return;`
- Generic catch at lines 441–444: `catch { setLastSaveFailed(true); toast.error(t('toasts.saveFailed')); }`
- The catch is currently `catch {` (no error binding) — replace with `catch (err) {` so we can introspect ApiError.

From frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts:
- Existing test at line 518: `it('surfaces popupConfigInvalid toast with dedupe id + extended duration when layer has invalid popup expression', ...)`
- Helper `makeLayer({ popup_config, dataset_column_info, display_name? })`
- Helper `makeSaveState({ hasUnsavedChanges, localLayers })`
- Mock pattern: `mockUpdateMapMutateAsync`, `mockPatchMapLayersMutateAsync` are vi.fn() handles already wired

From frontend/src/components/builder/BulkActionBar.tsx:
- Container `<div role="toolbar">` at lines 126–138 with `className={cn('sticky bottom-0 flex items-center gap-2 px-3', 'h-12 bg-[var(--surface-2)] border-t border-[var(--border)]', 'rounded-bl-[var(--radius-md)] rounded-br-[var(--radius-md)]', 'transition-all duration-[--motion-fast]', mounted ? 'translate-y-0 opacity-100' : 'translate-y-2 opacity-0')}` — `isDeleting` is already a prop in scope
- Selected-count label at line 227: `<span className="text-[13px] font-medium text-muted-foreground shrink-0">`

From frontend/src/i18n/locales/{en,de,es,fr}/builder.json:
- Existing key `toasts.popupConfigInvalid` at line 617 (generic — keep as fallback)
- Existing key `bulkActions.deletePartialFailure` at line 789 (en: "{{deleted}} of {{count}} layers deleted. {{failed}} failed.")
- Existing key `bulkActions.retryAction` at line 791 (retry CTA)

From backend/app/modules/catalog/maps/schemas.py:
- `class PopupConfig(BaseModel)` line 108: `model_config = ConfigDict(extra="forbid")` — backend already rejects unknown keys with 422
- Field constraints: `expression: str | None` max_length=500; `visible_fields` items min_length=1, max_length=128, max 100 items, unique

From backend/app/modules/catalog/maps/router.py:
- Line 253: `if "popup_config" in patch:` — popup_config is patched via the same FastAPI 422 path as any other field
- Backend returns FastAPI's standard 422 with `{detail: [{loc: ['body', 'layers', i, 'popup_config', ...], msg: ..., type: ...}]}`

From e2e/builder.spec.ts (existing patterns):
- Builder spec uses Playwright `page.goto('/maps/...')` + dataset-add helper. Look for an existing test that opens a map and adds a layer (`Add Data` flow). Pattern: `await page.getByRole('button', { name: /Add Data/i }).click()`.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Save-hook structured popup_config error surface (frontend pre-check + backend rejection translation)</name>
  <files>
    frontend/src/components/builder/hooks/use-builder-save.ts
    frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts
    frontend/src/i18n/locales/en/builder.json
    frontend/src/i18n/locales/de/builder.json
    frontend/src/i18n/locales/es/builder.json
    frontend/src/i18n/locales/fr/builder.json
  </files>
  <read_first>
    - frontend/src/components/builder/hooks/use-builder-save.ts (lines 1–50, 350–445)
    - frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts (lines 1–60, 510–570 — the existing popupConfigInvalid test is the harness)
    - frontend/src/api/client.ts (lines 1–170 — ApiError fields + how detailRaw is populated)
    - frontend/src/i18n/locales/en/builder.json (line 617 area — toasts.* namespace)
  </read_first>
  <behavior>
    - Test A (frontend pre-check, named layer): handleSave called with hasUnsavedChanges=true and a layer whose `display_name = "My Test Layer"` has `popup_config = { enabled: true, expression: '{{missing_column}}', visible_fields: null }` and `dataset_column_info = [{ name: 'present_column', type: 'text' }]`. Expect `toast.error` called with key `toasts.popupConfigInvalidNamed` (NEW key) and an options object containing `id: 'popup-config-invalid'`, `duration: 6000`. The interpolation values payload MUST contain `{ layerName: 'My Test Layer' }`. updateMap and patchMapLayers MUST NOT be called.
    - Test B (frontend pre-check, fallback when display_name null): same as Test A but `display_name: null`. Expect the toast key to still be `toasts.popupConfigInvalidNamed` and `layerName` to fall back to `t('layerFallbackName')` OR a literal `'Untitled layer'` (whichever exists in en/builder.json — use existing fallback if present, else add new key `layerFallbackName`).
    - Test C (backend rejection translation): handleSave called with hasUnsavedChanges=true and a layer that bypasses the frontend pre-check (valid placeholders). Mock `mockUpdateMapMutateAsync` to reject with `new ApiError('detail', 422, { detail: [{ loc: ['body', 'layers', 0, 'popup_config', 'expression'], msg: 'String should have at most 500 characters', type: 'string_too_long' }] })`. Expect `toast.error` called with key `toasts.popupConfigBackendRejected` (NEW key) — NOT `toasts.saveFailed`. The interpolation payload MUST contain `{ field: 'popup_config.expression' }` or `{ field: 'expression' }`. `setLastSaveFailed(true)` is still called.
    - Test D (non-popup ApiError still falls through to saveFailed): handleSave with mock rejecting with `new ApiError('detail', 500, undefined)`. Expect `toast.error` called with key `toasts.saveFailed`. Existing behavior preserved.
  </behavior>
  <action>
    Step 1 — locales: Add two NEW keys to `toasts.*` namespace in all four `frontend/src/i18n/locales/{en,de,es,fr}/builder.json` files. Names: `popupConfigInvalidNamed`, `popupConfigBackendRejected`. English copy: `popupConfigInvalidNamed` = `"Cannot save: layer "{{layerName}}" has an invalid popup expression."`; `popupConfigBackendRejected` = `"Server rejected the popup configuration ({{field}}). Adjust the layer's popup template and save again."`. Translate to de/es/fr — use translation tone consistent with sibling keys in the same file (`popupConfigInvalid` at line 617 is the model). If a generic `layerFallbackName` key does not already exist in `builder.json` (grep first), add one with en value `"Untitled layer"` and translate. Maintain key-count parity across all four locales — `npm run check:i18n` from CLOSE-01 will catch drift, but you should keep parity here too.

    Step 2 — use-builder-save.ts pre-check rewrite (lines 373–382): Replace the boolean `invalidLayer` lookup with a `find` that captures the layer reference. Use it directly. Change the toast call from `t('toasts.popupConfigInvalid')` to `t('toasts.popupConfigInvalidNamed', { layerName: invalidLayer.display_name ?? t('layerFallbackName') })`. Keep the toast options `{ id: 'popup-config-invalid', duration: 6000 }` unchanged so dedupe behavior + the existing observability path (snapshot tests, log scraping) keep working.

    Step 3 — use-builder-save.ts catch rewrite (lines 441–444): Change `} catch {` to `} catch (err) {`. Inside, introspect: if `err instanceof ApiError && err.status === 422 && err.detailRaw` and the detailRaw shape contains a `detail` array whose items have `loc` arrays containing the string `'popup_config'`, then call `toast.error(t('toasts.popupConfigBackendRejected', { field: <derived field path> }))` where `<derived field path>` is the loc segments after `'popup_config'` joined with `.` (e.g., `['body','layers',0,'popup_config','expression']` → `'popup_config.expression'`). Otherwise call the existing `toast.error(t('toasts.saveFailed'))`. In both branches, still call `setLastSaveFailed(true)`. Defensive coding: any unexpected `detailRaw` shape (not an object, missing `detail` array) falls through to the generic saveFailed path — do not throw inside the catch.

    Step 4 — vitest cases: Add Tests A, B, C, D to `frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts` immediately after the existing test at line 518. Reuse the existing `makeSaveState` + `makeLayer` helpers. For Test C, construct an `ApiError` via `new (await import('@/api/client')).ApiError('detail', 422, { detail: [{ loc: ['body','layers',0,'popup_config','expression'], msg: 'msg', type: 'string_too_long' }] })` and pass that to `mockUpdateMapMutateAsync.mockRejectedValueOnce(...)`. Use `mockPatchMapLayersMutateAsync.mockRejectedValueOnce` too if the diff path is taken (check existing tests — `unsupported: true` forces the updateMap path, which is simpler; ensure the test fixture takes that branch by setting baseline = empty so all layers are 'added' → unsupported diff path).

    Step 5 — preserve existing test at line 518: do NOT delete it; rename if needed (existing test asserts `popupConfigInvalid` is called; either change that assertion to `popupConfigInvalidNamed` and update the layer fixture to include `display_name`, OR keep it and add Test A as a new test. Prefer updating the existing test to assert the new key, because the old key `popupConfigInvalid` may become unused — remove it from all 4 locales if so, OR keep it as a redundant fallback. Choose ONE path and be consistent.)
  </action>
  <verify>
    <automated>cd frontend &amp;&amp; npx vitest run src/components/builder/hooks/__tests__/use-builder-save.test.ts</automated>
  </verify>
  <done>
    - 4 new vitest cases pass (A: named layer in pre-check, B: fallback name, C: backend 422 routed to popupConfigBackendRejected, D: non-popup ApiError routed to saveFailed)
    - i18n parity: 4 locales each contain the new keys; `node ./frontend/scripts/check-i18n-changed-namespaces.mjs` (or equivalent existing i18n parity script) reports no drift
    - Grep `popup_config` in `handleSave` catch shows new structured-detection block; grep `popupConfigInvalidNamed` shows it referenced once in source
  </done>
</task>

<task type="auto">
  <name>Task 2: BulkActionBar UI-REVIEW polish (container cursor + text-[13px] + partial-failure toast suffix)</name>
  <files>
    frontend/src/components/builder/BulkActionBar.tsx
    frontend/src/i18n/locales/en/builder.json
    frontend/src/i18n/locales/de/builder.json
    frontend/src/i18n/locales/es/builder.json
    frontend/src/i18n/locales/fr/builder.json
  </files>
  <read_first>
    - frontend/src/components/builder/BulkActionBar.tsx (lines 126–145, 220–235)
    - frontend/src/i18n/locales/en/builder.json (lines 785–795 — bulkActions.* keys)
    - .planning/phases/1047-perf-and-code-quality-fixes/1047-UI-REVIEW.md (top-3 priority fixes)
  </read_first>
  <action>
    Polish item 1 (cursor-not-allowed container): At `frontend/src/components/builder/BulkActionBar.tsx` lines 126–138, the container `<div role="toolbar">` className is a `cn(...)` call. Append a conditional class: when `isDeleting` is true, add `'cursor-not-allowed'`. Use the existing `cn()` pattern (the prop is already in scope per the existing line 144/148/166 references). Example: add `isDeleting ? 'cursor-not-allowed' : ''` as a new argument to `cn(...)`.

    Polish item 2 (text-[13px] → text-xs): At line 227, the selected-count label uses `className="text-[13px] font-medium text-muted-foreground shrink-0"`. Replace `text-[13px]` with `text-xs` (12px, the Label role in the UI-SPEC type scale). Per `feedback_filter_bar_density` we already constrain density; using `text-xs` keeps the bar within the 12/14/16 type scale.

    Polish item 3 (partial-failure toast " — tap to retry." suffix): In all four `frontend/src/i18n/locales/{en,de,es,fr}/builder.json`, append a translated " — tap to retry." suffix to the `bulkActions.deletePartialFailure` value. en: append ` — Tap to retry.`. de: append ` — Zum Wiederholen tippen.`. es: append ` — Toca para reintentar.`. fr: append ` — Appuyer pour réessayer.`. The action button still exists; the suffix makes the affordance discoverable for screen-reader-only users who dismiss the toast quickly per UI-REVIEW finding #1.
  </action>
  <verify>
    <automated>cd frontend &amp;&amp; npx vitest run src/components/builder/__tests__/BulkActionBar.test.tsx 2&gt;/dev/null || cd frontend &amp;&amp; npx vitest run src/components/builder/</automated>
  </verify>
  <done>
    - `grep -c 'cursor-not-allowed' frontend/src/components/builder/BulkActionBar.tsx` returns ≥ 2 (container + button)
    - `grep -c 'text-\[13px\]' frontend/src/components/builder/BulkActionBar.tsx` returns 0
    - `grep 'deletePartialFailure' frontend/src/i18n/locales/en/builder.json` shows the new suffix
    - Existing vitest suite for builder still green (BulkActionBar tests may snapshot — update snapshots if needed and verify diff is only the polish changes)
  </done>
</task>

<task type="auto">
  <name>Task 3: e2e success-path round-trip for popup_config on previously-blocked map</name>
  <files>
    e2e/builder.spec.ts
  </files>
  <read_first>
    - e2e/builder.spec.ts (full file — find the existing builder-spec helpers: dataset add, layer save, toast assertion patterns)
    - frontend/src/components/builder/PopupConfigEditor.tsx (lines 80–180 — how the user edits the popup expression in UI; the e2e drives this UI)
    - frontend/src/components/builder/hooks/use-builder-save.ts (line 380 — the toast id 'popup-config-invalid' is the dedupe id the e2e asserts against)
  </read_first>
  <action>
    Append a single Playwright test to `e2e/builder.spec.ts` named `popup_config success-path round-trip (FOLLOWUP-01)`. The test must:
    1. Sign in and create or open a builder map (use the existing test-helper pattern in the file; if none, use `page.goto('/maps/new')` then `page.getByRole('button', { name: /save/i }).click()` to seed).
    2. Add a dataset layer (any vector layer with at least one named column — use the same Add Data flow other tests use; pick the first available dataset).
    3. Open the layer editor → Popup tab. Enable popup. Type an expression referencing a non-existent column, e.g. `{{__missing_column__}}`.
    4. Click Save. Assert a toast appears with id `popup-config-invalid` and text matching the regex `/popup expression|invalid popup/i` (matches both old generic and new named copy).
    5. Re-open the layer editor → Popup tab. Replace the expression with a valid placeholder using a known column (e.g. `{{${firstColumnName}}}`). Locate the column name from the editor's column-picker UI or from the test's seeded layer metadata. (If the column list is not deterministically accessible, fall back: clear the expression entirely, which disables placeholder validation since `cfg.expression` becomes empty — empty/null is treated as enabled-without-template.)
    6. Click Save again. Assert NO popup-config-invalid toast appears (use `expect(toast).not.toBeVisible()` with a 1500ms timeout). Assert a `toasts.mapSaved`-equivalent success toast appears.
    7. Reload the page. Assert the layer is still present and the popup expression matches the saved value (i.e. the PUT round-trip persisted).

    Mark the test with the existing tag used by `e2e:smoke:builder` so it's picked up by CLOSE-01's smoke gate. Look at sibling tests in the file for the tag/describe pattern.

    Do NOT add a new test file — keep this in `e2e/builder.spec.ts` so the existing `e2e:smoke:builder` script picks it up without changes to root `package.json`.
  </action>
  <verify>
    <automated>npx playwright test e2e/builder.spec.ts -g "popup_config success-path round-trip" --list</automated>
  </verify>
  <done>
    - New test exists in `e2e/builder.spec.ts` with the name `popup_config success-path round-trip (FOLLOWUP-01)` and is discoverable by Playwright (`--list` shows it)
    - Test follows the existing builder-spec helper pattern (auth, dataset add, layer save) — no new fixtures introduced
    - Test will execute in CLOSE-01 (Plan 04) under `npm run e2e:smoke:builder` against the Docker stack
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client → API (PUT /maps/:id, PATCH /maps/:id/layers) | Frontend save sends untrusted popup_config payload across the boundary; backend Pydantic validates shape; expression placeholder validity is frontend-only by design (per RESEARCH §4 referenced in CONTEXT.md) |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1048-01 | Information disclosure | save-hook catch{} that surfaces backend error detail in a toast | mitigate | Translate detail via i18n keys; do not interpolate raw backend `msg` strings into the toast — interpolate only the field path which is derived from `loc` (already a non-secret structural identifier). Raw `msg` is logged via existing observability path, not displayed. |
| T-1048-02 | Tampering | client-side popup expression validation can be bypassed (curl, devtools) | accept | Backend Pydantic still enforces shape constraints (`extra=forbid`, max_length=500, visible_fields uniqueness). Frontend pre-check is UX, not security. Existing posture, unchanged by this plan. |
</threat_model>

<verification>
- Run vitest for `use-builder-save.test.ts` — 4 new tests pass plus the pre-existing test surface continues to pass (popup_config invalid test, widget tests, saveFailed test).
- Run vitest for any BulkActionBar test file — snapshots may need updating for the cursor + text size changes; review snapshot diffs to confirm only the targeted changes appear.
- Run i18n parity check: `cd frontend && node ./scripts/check-i18n-changed-namespaces.mjs` — no drift across en/de/es/fr.
- Playwright test discoverable (`--list` shows it).
</verification>

<success_criteria>
- FOLLOWUP-01 (popup_config error surface) is implementation-complete: pre-check toast names the offending layer; backend 4xx rejection of popup_config produces a distinct translated toast; both surfaces covered by vitest.
- e2e/builder.spec.ts has a new test that drives the success-path round-trip on a previously-blocked popup expression.
- BulkActionBar cursor-not-allowed extends to the container during isDeleting.
- BulkActionBar text-[13px] is gone; text-xs replaces it.
- `bulkActions.deletePartialFailure` in all four locales now ends with a translated " — Tap to retry." (or locale-equivalent) suffix.
- All four locales remain at key-count parity.
</success_criteria>

<output>
Create `.planning/phases/1048-followups-and-closeout/1048-01-SUMMARY.md` when done. Record:
- New i18n keys added (count, names)
- Vitest case names added (4)
- Playwright test name added
- UI-REVIEW item closure (3 items: deletePartialFailure suffix, cursor-not-allowed scope, text-[13px] replacement)
- FOLLOWUP-01 status: implementation complete; live e2e execution deferred to CLOSE-01 Docker gate
</output>
