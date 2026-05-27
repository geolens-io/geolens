# Pitfalls Research — v1030 Map Builder Polish Sweep

**Domain:** Mature map builder polish on v1026 reconciler + v1027 action boundary substrate
**Researched:** 2026-05-27
**Confidence:** HIGH (grounded in actual GeoLens source — `builder-action-contract.ts`, `layer-adapters/shared.ts`, `ChatPanel.tsx`, `SharePanel.tsx`, `chat_actions.py`, AI `router.py`) and direct prior-milestone post-mortems (v1009.1, v1010.2, v1011, v1011.1, v1028)

---

## Critical Pitfalls

### Pitfall 1: Bypassing the v1027 typed action boundary for "just one direct call"

**What goes wrong:**
A new AI action type (e.g. `add_layer_with_style`, `analyze_layer`) is wired by calling `map.addLayer()` / `setPaintProperty()` / `useBuilderLayers.handleAddDataset()` directly from `ChatPanel.tsx` instead of dispatching through `BuilderLayerAction` → `BuilderLayerActionHandlers`. Manual vs AI provenance is lost (`BuilderActionSource` not threaded), undo snapshots miss the mutation, dirty-state never flips, and the v1026 reconciler's owned-property set diverges from the layer JSON.

**Why it happens:**
`builder-action-contract.ts` discriminated-union is verbose to extend (16+ action types). When a new chat action arrives, the path-of-least-resistance is to mirror one of the existing imperative handlers in `handleChatAction()` rather than to add a typed action variant and a handler — especially for "compound" actions like "add a layer and immediately apply a graduated style", where the temptation is to chain two existing handlers inline.

**How to avoid:**
- Phase 1133 audit must enumerate every existing `case` branch in `ChatPanel.handleChatAction()` and `dispatchBuilderLayerAction()` and require that every NEW chat action type land as a new `BuilderLayerAction` discriminated-union variant FIRST, with a matching `BuilderLayerActionHandlers` method.
- Add a planner guardrail: if a v1030 plan touches `ChatPanel.tsx` AND adds a new `action.type` switch case, the plan MUST also touch `builder-action-contract.ts`. Otherwise the action is bypassing the boundary.
- Re-use the v1009.1 / v1010.2 "code-review catches secondary findings" pattern (`feedback_review_findings_inline.md`): post-shipping review must grep for new `map.setPaintProperty`, `map.setLayoutProperty`, `map.addLayer`, `map.addSource` callsites outside `layer-adapters/`, `map-sync.ts`, and `basemap-state-controller.ts`.
- A diagnostic test asserting "no setPaintProperty calls outside known files" exists for adapters; extend it to chat-side callers.

**Warning signs:**
- A new action's effect doesn't show up in the AI undo snapshot (BLD-20260526-04 pattern).
- Dirty-state badge (orange Save indicator) doesn't appear after an AI action.
- Style JSON export omits a paint property that's visibly on the canvas (the reconciler's owned-set was never told about it).

**Phase to address:** Phase 1133 (audit + walkthrough) names this in the AUDIT.md as P0; Phase that adds AI layer-creation/data-analysis actions MUST land the new `BuilderLayerAction` variants before the wire-up.

---

### Pitfall 2: Collapsing the v1026 reconciler patch/replace/clear tri-state

**What goes wrong:**
A polish change to an editor (e.g. LineEditor, FillEditor) or to a chat action handler treats paint changes as a simple object merge (`{ ...current, ...next }`) — losing the distinction between (a) **patch** a single property, (b) **replace** the whole paint dict, and (c) **clear** specific keys. After save/reload, properties that were intentionally cleared come back, or a `replace_paint: true` AI action accidentally merges with stale state. This was the exact bug class v1026 was built to eliminate, and `buildChatActionPaint()` in `ChatPanel.tsx:80` is the canonical encoder of the contract — it MUST be the single source of truth.

**Why it happens:**
The contract is implicit (three booleans/arrays — `paint`, `clear_paint`, `replace_paint`) rather than a tagged union, and a refactor of "let's just set the value" often loses the `clear_paint` branch. Tests pass because the canvas looks right at first apply; the regression appears only after a save → reload → reapply cycle, which lives outside per-PR test coverage.

**How to avoid:**
- All polish changes to paint handling MUST route through `buildChatActionPaint(currentPaint, action)` (`ChatPanel.tsx:80`) for chat-driven mutations and through the `syncOwnedPaintProperties()` reconciler (`layer-adapters/shared.ts:293`) for editor-driven mutations. No new path may be added.
- Save/reload symmetry test (vitest) for each render-mode editor: render → mutate one property → simulate save → reload → assert paint matches `expected`. The fixture must include a `clear_paint` case (set color, then clear it, assert it's gone after reload).
- A unit test pin on `buildChatActionPaint` for each (patch, replace, clear, patch+clear, replace+patch) combination — `ChatPanel.test.tsx` already pins some of these; extend coverage for new action types.

**Warning signs:**
- After save/reload, a property the user explicitly cleared (e.g. a custom `line-gradient` they removed) reappears.
- AI `set_style` with `replace_paint: true` produces a layer that has BOTH the new and old properties.
- Style JSON export round-trip drops a property that the editor still shows on the canvas.

**Phase to address:** Per-render-mode editor polish phases (FillEditor / LineEditor / CircleEditor / SymbolEditor / HeatmapEditor / ClusterEditor / RasterEditor) must each include a save/reload symmetry vitest. AI chat phases must extend `ChatPanel.test.tsx` `buildChatActionPaint` table.

---

### Pitfall 3: AI confirm-before-apply collapsing the snapshot/undo contract

**What goes wrong:**
The current snapshot/undo pattern (`lastSnapshotRef` in `ChatPanel.tsx:172`) is "auto-apply then undo." If a polish phase introduces a true confirm-before-apply UX without changing the action contract, the staged action's intermediate map state can drift: the user sees a "preview" that was actually applied to the live map and reconciler, save dirty state flips, and rejecting the suggestion leaves the map in a partially-applied state (because `handleChatAction` already ran through `dispatchBuilderLayerAction`).

**Why it happens:**
The v1027 boundary was designed for **commit immediately**. Adding "confirm" requires either (a) a true two-phase staging buffer (NEW pending state distinct from `layers`) OR (b) a forced-undo-on-reject path. Mixing them — preview by applying and rejecting via undo — creates the trap where mid-stream errors leave half-applied changes (already a known edge case at `ChatPanel.tsx:440-450`).

**How to avoid:**
- Stage one option upfront in the requirements: either **(A) Pre-apply preview + atomic undo** (extend existing snapshot pattern, but make `supportsUndo` false-state surface a "cannot preview" UI rather than silently committing) OR **(B) True staging buffer** (separate `pendingLayers` + `pendingPaint`, never write to reconciler until accepted). Don't mix.
- If (A) chosen: extend `BuilderActionBase` with `source: 'ai-pending' | 'ai-committed'`, and make the v1026 reconciler skip side-effects when `source === 'ai-pending'`. Save/dirty state must not flip for pending. This requires a `BuilderActionSource` widening — not a one-line fix.
- If (B) chosen: a separate `useBuilderPendingActions` hook that buffers `BuilderMapAction[]`. `MapBuilderPage` decides whether to render `effectiveLayers = pendingActions.reduce(layers, applyAction)` for preview. Only commit on accept.
- Either way: assert no AI action mutates `lastSnapshotRef` AND backend state in the same code path.

**Warning signs:**
- A "Reject" or "Cancel" click leaves the map visually changed.
- Save indicator turns orange (dirty) when previewing an AI suggestion the user hasn't accepted.
- AI shows the same suggestion twice and both apply because the user clicked Apply on the first and the second was already pre-applied.

**Phase to address:** The AI chat phase that introduces confirm-before-apply MUST pick the staging shape (A or B) in CONTEXT.md before plan-01 lands. A regression test that "rejecting a pending AI action leaves layers byte-equal to pre-prompt" is mandatory.

---

### Pitfall 4: AI provider-disabled state regresses to broken-canvas

**What goes wrong:**
v1028 already shipped an "actionable AI unavailable state" (per PROJECT.md line 72). A polish change to add new AI features (layer creation, data analysis) wires them only on the AI-enabled path and ships without re-verifying the disabled path: clicking suggestions on a deployment with no `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` shows a generic 503 toast, the suggestion chip is still clickable, and `useAIStatus` consumer-side gating is missed for one new endpoint (mirrors the v1010.2 SF-06 / `useEmbeddingStats` gap where the plan named only `useAIStatus`).

**Why it happens:**
- `_check_ai_available(db)` (`ai/router.py:70`) ALREADY handles the 403 (admin-disabled) / 503 (no key) distinction correctly. The frontend gap is on the consumer side — every NEW hook that hits `/ai/*` needs `{ enabled: !!token && aiEnabled }` and an explicit empty-state UI.
- New "data analysis" prompts may hit new endpoints (`/ai/analyze/`, hypothetical) that don't reuse the `AI_ENABLED` gate, or reuse it but don't surface the 503 distinctly.

**How to avoid:**
- Phase 1133 audit must enumerate every existing `/ai/*` endpoint and every frontend hook that calls one. Output a "consumer gating matrix" with columns: hook, endpoint, gated-on-aiEnabled, surfaces-503-distinctly, surfaces-403-distinctly.
- Any new AI endpoint added in v1030 MUST: (1) call `await _check_ai_available(db)` first; (2) reuse `_AI_GENERATE_LIMIT` (`10/minute`) or document why a different rate limit is justified; (3) be permission-gated with `require_permission("use_ai_chat")`.
- Any new frontend AI hook MUST: (1) be gated on `enabled: !!token && aiEnabled && isAdmin?` (mirror `useAIStatus` per v1010.2 SF-06 fix); (2) surface 403 ("admin-disabled") and 503 ("no key") with the i18n keys `chat.errorForbidden` / `chat.errorAiUnavailable` already in `ChatPanel.tsx:202`.
- A Playwright MCP smoke gate with `AI_ENABLED=false` AND with the key envvars unset: no suggestion chips visible, no 401/403/503 noise in browser console, no broken-canvas state.

**Warning signs:**
- Chat suggestion chips render when `AI_ENABLED=false`.
- Browser console shows repeated 503 noise from a new analyze endpoint.
- Disabled-AI UAT was last verified more than one milestone ago.

**Phase to address:** Phase 1133 audit names the matrix; every AI phase exits with a "disabled-AI smoke check" line in CHECKPOINT.md. Final close-gate phase re-verifies with `AI_ENABLED=false`.

---

### Pitfall 5: AI data-analysis prompt leaks across maps via prompt cache or visibility

**What goes wrong:**
- A new "analyze this map" prompt feeds layer metadata (column names, sample values, geometry types) to the LLM. If layer visibility is NOT respected (`layer.visible === false` layers included in `_validate_chat_layers` payload), the analysis quietly references hidden layers.
- The schema-context cache is keyed per-map (`PERF-04`-style — `chat_actions.py:73` comment). If a polish refactor introduces a new cache that's keyed only by `dataset_id` (not `(map_id, dataset_id)`), Map A's analysis can pull cached schema from Map B that the user never opened, leaking dataset names + column lists between maps the user owns.
- Server-side AI provider API keys (`settings.anthropic_api_key`, `settings.openai_api_key`) appear in `_check_ai_available`'s `keys` dict at `router.py:84`. If a new error path includes `keys.get(provider)` in the exception detail (a temptingly-easy debug hint), the key leaks to the client through a 500 response.

**Why it happens:**
- Polish work often "just passes through the existing layers list" without thinking about visibility — and the existing `_validate_chat_layers` (`router.py:94`) does not filter on `layer.visible`.
- Cache key shortcuts are common when refactoring (e.g. memoizing on dataset alone).
- "Helpful" error messages can include configuration in non-prod paths and get shipped.

**How to avoid:**
- Phase 1133 audit must check `_validate_chat_layers` against the new analyze prompts — if the prompt is "analyze visible layers", filter on `layer.visible` BEFORE validation. If the prompt is "analyze all layers", document that explicitly.
- A regression test: prompt analyze on a 2-map session where Map A and Map B share a dataset_id but have different visible-layer sets; assert Map A's schema-context cache key is NOT reused on Map B.
- Lint rule (eslint `no-restricted-syntax` or grep guard): forbid string-interpolating `settings.anthropic_api_key`, `settings.openai_api_key`, `keys.get(provider)` into any `detail=`, `message=`, or `HTTPException` body. Mirror SEC-S14 ESLint ban pattern.
- Per-dataset access via existing `build_table_allowlist(db, user)` is the right gate — DO NOT introduce a parallel "this is just a read" shortcut path. Every analyze call must go through the allowlist.

**Warning signs:**
- An analyze response mentions a column from a layer the user has toggled off.
- An analyze response is suspiciously fast on a brand-new map (cache leak from another map).
- An error message in the network tab includes any string that looks like an API key fragment (`sk-`, `claude-`, `key=`).

**Phase to address:** Phase that adds AI data-analysis explicitly lists a "leak-shape regression set" in CONTEXT.md: visibility leak, cache leak, key leak, cross-map leak.

---

### Pitfall 6: SharePanel raw-token clearing on dialog re-render or visibility change

**What goes wrong:**
The just-shipped `3ed5ceb3` separated `rawShareToken` (local state, only set when JUST CREATED) from `persistedShareTokenHint` (query-derived flag). A subsequent polish change "tidies up" the local state by clearing `setRawShareToken(null)` on dialog `onOpenChange={false}` or on a visibility-change cleanup effect. Result: user creates a public link, switches tab, comes back, the share-URL field is empty because the dialog re-rendered, and the user clicks "Get Share Link" thinking it failed, creating a SECOND token and orphaning the first (now-revoked but linked-to-elsewhere).

**Why it happens:**
The local-state-survives-rerender contract is subtle: `rawShareToken` is intentionally NOT cleared on dialog close (see `SharePanel.tsx:444` `handleRevoked` — clears on revoke only) because the dialog stays mounted while the dropdown closes. Any "cleanup-on-unmount" or "reset-on-close" polish change breaks the v1011 SP-09 / v1010.2 pattern of "raw token survives session, hint persists."

**How to avoid:**
- A regression test that pins `rawShareToken` survival across dialog open/close cycles AND `visibilitychange` events. Add to `SharePanel.test.tsx`.
- A docstring-level contract at the `useState<string | null>(null)` declaration in `SharePanel.tsx:330` explaining: "Do NOT clear on dialog close or visibility change. This is the raw token the server returned only once; if cleared, the user must regenerate."
- Pin in the test: assert that after `await handleGetShareLink()`, then `onOpenChange(false)`, then `onOpenChange(true)`, the share URL field is still populated.

**Warning signs:**
- Test removes a `setRawShareToken(null)` call — verify it's not the load-bearing one.
- A polish PR touches `SharePanel.tsx` and adds a `useEffect` that depends on `open`.

**Phase to address:** Any phase touching `SharePanel.tsx` must include the SP-survival pin. v1011 SP-09 / `feedback_dndkit_listener_jsx_spread.md` "preserve load-bearing state across rerenders" pattern applies.

---

### Pitfall 7: Embed token race — create vs list

**What goes wrong:**
`SharePanel.handleGetShareLink()` calls `createShareToken.mutateAsync()`, then `runVisibilityCheck()`, then `maybeCreateEmbedToken()`. The embed-token list query (`useMapEmbedTokens`) is gated on `open && hasShareToken` (`SharePanel.tsx:340`). When `hasShareToken` flips true after `setRawShareToken`, the list query fires in parallel with `createEmbedToken.mutateAsync()`. If the list query returns BEFORE the create completes, `activeEmbedToken` is undefined, `maybeCreateEmbedToken` proceeds to create — but its `mutateAsync.onSuccess` invalidates the list query, triggering a second list fetch that races with the just-created token's commit. Worst case: TWO embed tokens get created.

**Why it happens:**
TanStack Query mutations + dependent queries that gate on derived booleans is a classic race. The `maybeCreateEmbedToken` guard `if (activeEmbedToken) return;` only protects against the case where the list query has already completed AND contains a token — it doesn't protect against concurrent in-flight creates.

**How to avoid:**
- Add a synchronous in-flight ref inside `SharePanel`: `const inflightEmbedCreate = useRef(false);` set true at the top of `maybeCreateEmbedToken`, clear in `finally`. Mirror the `inflightRef` pattern in `ChatPanel.tsx:165` ("setIsLoading is async-batched, so two same-tick handleSend calls would both see isLoading=false and both fetch").
- A regression test: simulate the race — open dialog, click "Get Share Link" twice within one tick — assert only ONE `createEmbedToken` was issued (use a spy on the mutation).
- Backend defense: `create_embed_token` SHOULD upsert/idempotent on `(map_id, allowed_origins)` collision. Check `backend/app/modules/catalog/maps/router.py` to confirm — if it always inserts, polish phase needs to add a unique constraint or in-flight check on the backend side as well.

**Warning signs:**
- Two embed tokens visible in the embed-tokens list for the same map with the same origins.
- `Network` tab shows two simultaneous `POST /api/maps/{id}/embed-tokens/` calls.

**Phase to address:** Sharing-polish phase explicitly lists "embed-token race regression" in REQUIREMENTS.md. Test pin lives in `SharePanel.test.tsx`.

---

### Pitfall 8: Allowed-origins UX regression breaks iframe enforcement

**What goes wrong:**
A polish change to the allowed-origins UX (better input validation, comma-vs-newline normalization, default-to-current-origin convenience) accidentally:
- Strips trailing slashes inconsistently between create and update paths (`parseOrigins` in `SharePanel.tsx:24` already does `replace(/\/+$/, '')` — but only on create).
- Replaces a non-empty list with `null` instead of `[]` when the user clears the field (different backend semantics: `null` may mean "any origin" depending on default; `[]` means "self only").
- Auto-adds `https://` to a bare hostname AFTER it's already in the list, producing duplicates.

The CSP `frame-ancestors` directive at `router.py:111-123` is built from this list. A broken update path means the embed silently allows ANY origin (frame-ancestors falls back to `'self'` only when list is empty, but if a downstream change makes the empty-list path emit `*`, every embed is vulnerable).

**Why it happens:**
- `parseOrigins` is called only at create/regenerate; the update path (PATCH `allowed_origins`) is rarely tested with the same diversity of input.
- The `null` vs `[]` distinction is invisible to most polish changes.
- The CSP construction at `router.py:111` (`_build_csp_frame_ancestors`) has CRLF guards but not "fail-closed" semantics for unexpected inputs (e.g. wildcard).

**How to avoid:**
- Round-trip test: input → `parseOrigins` → POST/PATCH → GET → assert canonical normalized form persisted. Run for: empty, one bare host, one with scheme, one with trailing slash, comma-separated with whitespace.
- A backend pin that `_build_csp_frame_ancestors([])` returns `frame-ancestors 'self'` exactly (no wildcard, no leak).
- A backend pin that `frame-ancestors` directive NEVER contains `*` regardless of input.
- E2E pin: load embed iframe from an origin NOT in the allow-list, assert browser refuses to render (load event blocked). Playwright MCP can verify with an iframe in a `data:` URL.

**Warning signs:**
- Two identical entries in `allowed_origins` (one with scheme, one without).
- CSP response header on `/api/maps/shared/{token}` contains an asterisk.
- Update path doesn't `parseOrigins` before persisting.

**Phase to address:** Sharing-polish phase MUST cover the update path (PATCH `allowed_origins`) explicitly. Add a round-trip vitest + a CSP-header regression pin.

---

### Pitfall 9: Per-render-mode editor adds direct `map.setPaintProperty` for "performance"

**What goes wrong:**
A polish change to one editor (e.g. LineEditor for `line-gradient` smoothness, or HeatmapEditor for the radius slider) decides the v1026 reconciler debouncing is "too slow" for live preview and bypasses it with `map.setPaintProperty()` directly inside a slider `onChange`. The canvas tracks the slider, but: (a) the layer JSON is now divergent from the canvas; (b) the v1010 `coalesceFrame` rAF utility is bypassed (200ms debounce target broken — PERF-02 regression); (c) on save, the reconciled paint wins, the user's last drag value is lost.

**Why it happens:**
- v1010 established `coalesceFrame` + 100ms opacity / 200ms color+filter debounces for exactly this reason. Polish work that runs without re-reading the v1010 perf baseline reinvents the bypass.
- Direct `map.setPaintProperty()` looks like an obvious speedup, and a single slider may genuinely feel snappier.
- The save/reload divergence is not caught by interaction tests — only by save/reload round-trip.

**How to avoid:**
- Reference the v1010 PERF baseline (`.planning/audits/BUILDER-PERF-BASELINE.md`) at the top of every editor polish phase. PERF-02 hover p50 ≤30ms is the bar.
- All slider/picker `onChange`s in editors must call through `BuilderLayerActionHandlers.setPaint` (or `setStyleConfig`) — direct `map` access is forbidden by convention.
- Add an eslint or grep guard: `map.setPaintProperty` is only allowed inside `frontend/src/components/builder/layer-adapters/` and `frontend/src/components/builder/map-sync.ts` (the existing pattern).
- A save/reload symmetry vitest for every editor that has a slider.

**Warning signs:**
- A PR diff adds `import type { Map as MaplibreMap }` to a file in `LayerStyleEditor/`.
- After dragging a slider, hitting save, and reloading, the slider value resets to a stale value.

**Phase to address:** Per-render-mode editor polish phase. The first plan in each phase must include the grep guard + symmetry test BEFORE any slider tuning lands.

---

### Pitfall 10: Smaller-screen NavigationControl move breaks builder-vs-viewer asymmetric offset contract

**What goes wrong:**
Fixing "right sidebar overlaps zoom controls on smaller screens" (todo.md line 147) by moving the NavigationControl back to `top-right` re-creates the v1011 RESP-01/RESP-02 collision: builder's `top-left` placement was load-bearing for the `MapCoordReadout` at `top-2 right-14` (the 56px right offset clears the NavigationControl ONLY when nav is `top-right` — which is true in ViewerMap but NOT in BuilderMap, where Phase 1051 deliberately moved nav to `top-left` to clear the right-sidebar drill-down at <800px). Moving nav to `top-right` in builder re-introduces the collision at <800px AND breaks the docstring contract at `MapCoordReadout.tsx:26-37`.

**Why it happens:**
- The asymmetry (BuilderMap nav `top-left`, ViewerMap nav `top-right`) is visually surprising and looks like a bug to anyone who didn't read v1011 RESP-01/RESP-02.
- The docstring is at the shared component (`MapCoordReadout.tsx`), but the load-bearing positioning is at the parent (`BuilderMap.tsx`, `ViewerMap.tsx`).
- The `data-builder-canvas="true"` + scoped CSS rule at `index.css` (`[data-builder-canvas="true"] .maplibregl-ctrl-top-left { margin-top: 32px }`) is also part of the contract — moving the control invalidates that scoped CSS.

**How to avoid:**
- The smaller-screen polish phase MUST read `MapCoordReadout.tsx:26-37` docstring and v1011 RESP-01/RESP-02 commits (`391459bb` move + `4f4a9917` followup) BEFORE proposing any nav-position change.
- Don't fix this by moving the NavigationControl. Fix it by adjusting the right-sidebar collapse trigger (sidebar should narrow or float to NOT overlap a fixed top-left or top-right nav).
- A regression test: at <800px viewport, the right-sidebar fly-out should not overlap any `.maplibregl-ctrl-top-*` controls.
- A 800px Playwright MCP screenshot in close-gate (mirrors v1011 RESP-02-FOLLOWUP `4f4a9917`).

**Warning signs:**
- A PR diff changes `<NavigationControl position="top-left" />` to `top-right` in BuilderMap.tsx.
- A PR diff removes the `data-builder-canvas="true"` attribute or its scoped CSS.
- A PR diff reduces `right-14` to `right-2` in MapCoordReadout.tsx.

**Phase to address:** Smaller-screen layout polish phase. Phase 1133 audit MUST flag this surface as "load-bearing — read v1011 RESP-01/RESP-02 first."

---

### Pitfall 11: Basemap-selector "double X" fix introduces sheet-close regression

**What goes wrong:**
v1011 RESP-03 closed the basemap-selector double-X bug by setting `<SheetContent showCloseButton={false}>` on both Sheet wrappers + adding a NEGATIVE-CONTROL bug-shape pin. A polish change "adds back the close button for consistency with other dialogs" — re-introducing the double-X. OR the polish change adds a different `<SheetContent>` somewhere (e.g. a new layer-config sheet) WITHOUT setting `showCloseButton={false}`, creating a new instance of the same bug class on a different surface.

**Why it happens:**
- shadcn's `Sheet` renders a close button by default; the convention is opt-OUT, not opt-in.
- The "consistency" pressure is real — designers may want close buttons on all sheets.
- The v1011 regression pin only covers the basemap selector, not new sheets.

**How to avoid:**
- Generalize the v1011 RESP-03 NEGATIVE-CONTROL pin: assert that EVERY `<SheetContent>` rendered inside the builder canvas has `showCloseButton={false}` if its parent already has an X. A vitest that mounts each canvas-overlay sheet and asserts ≤1 close button visible.
- A grep guard: any new `<SheetContent>` MUST have `showCloseButton={false}` OR a comment justifying the close button.

**Warning signs:**
- A `<SheetContent>` without `showCloseButton` prop in the builder.
- Two X buttons visible on a sheet at the same time.

**Phase to address:** Smaller-screen layout polish phase. Audit must enumerate every `<SheetContent>` in `frontend/src/components/builder/` and `frontend/src/components/ui/sheet.tsx`.

---

### Pitfall 12: Polish-sweep scope creep into architecture work

**What goes wrong:**
v1030 is explicitly product polish, NOT architecture. But polish work routinely surfaces "while we're here, let's just refactor the action-boundary types" or "since we're touching ChatPanel, let's split it into ChatMessages + ChatActions." Scope creep extends the milestone by a week, the architecture change isn't planned-first (no audit, no CONTEXT.md), and the polish work that motivated the milestone is left half-done.

**Why it happens:**
- Polish work exposes "obvious" structural issues (overlong files, repeated patterns, missing abstractions).
- v1010 / v1026 / v1027 set a precedent that "architecture rewrites are how we ship quality."
- `/gsd-autonomous` runs end-to-end and lacks the human pause-point that would catch scope creep.

**How to avoid:**
- v1030 CONTEXT.md MUST list "Out of scope" items explicitly, mirroring v1028's "broad AI-chat redesign, new LLM provider work, and unrelated platform changes are out of scope" line. The current PROJECT.md v1030 entry already lists architecture rewrites, LLM providers, marketing, connectors, enterprise, large new features — keep this list visible at every phase entry.
- Any plan that proposes touching `builder-action-contract.ts` (renaming variants, splitting handlers, etc.) MUST be flagged at audit time as architecture work and either scoped explicitly or deferred to a v1031.
- Hard rule: no new files >500 LOC, no rename of >3 exported symbols, no `BuilderActionSource` widening without an explicit Future Requirement entry first.

**Warning signs:**
- A plan starts with "refactor X to make Y easier."
- A polish phase grows from "fix the X bug" to "refactor X subsystem."
- The roadmap adds a "Phase 113N — refactoring foundation" between polish phases.

**Phase to address:** Roadmapper. Polish phases must each be scoped to one user-visible surface, not a subsystem.

---

### Pitfall 13: "Easy-win" UX enhancements turn out hard

**What goes wrong:**
Several items in `todo.md:138-150` look like easy wins but have hidden complexity:
- "delete layer does not work" — may root-cause to v1027 action-dispatch routing, not a UI fix.
- "regular layer toggle does not work for map X" — already names a specific map ID; may be a per-map data issue, not a builder bug.
- "rename group does not focus appropriately on text field" — Radix DropdownMenu + focus management is the v1011 BUG-03 pattern (rAF-deferred focus + drop `onSelect` preventDefault).
- "Basemap should be draggable in layer order" — v1011 RESP-03 + Plan 06 sortable-disabled-droppable contract. Touching it WILL re-surface the dnd-kit collision regression (`useSortable` collision target during catalog drags).
- "DETAIL LEVEL toggle — what is the point?" — v1011 INV-01 ALREADY removed this. If todo.md still references it, the todo is stale OR a regression.

**Why it happens:**
- Easy-win labels are user-facing; the implementation paths are NOT.
- todo.md was written before v1011 closed several of these items.
- The cost of "discovery is the work" is invisible until a plan starts.

**How to avoid:**
- Phase 1133 audit MUST cross-reference EACH todo.md easy-win against the v1011/v1028 milestone records:
  - "DETAIL LEVEL toggle" → already removed in v1011 INV-01 (commit `6078b82a`). VERIFY the todo is stale; if it's a regression, that's a separate bug.
  - "Basemap draggable" → shipped in v1011 RESP-03. VERIFY it works; if not, it's a regression of the v1011 contract.
  - "Layer toggle for map X" → reproduce on the actual map ID before scheduling.
  - "Rename group focus" → known Radix pattern (`feedback_dndkit_listener_jsx_spread.md` for the spread-order rule; rAF-deferred focus for the parent close timing).
- Each easy-win must have a 15-minute spike attached to the audit BEFORE plan-01 lands. If the spike exceeds 15 min, the item is NOT an easy win — promote to its own phase or defer.

**Warning signs:**
- A plan for "easy-win delete layer fix" runs >2 hours.
- A polish PR touches more than the named surface.
- An item closed in a prior milestone is being re-opened.

**Phase to address:** Phase 1133 audit. Cross-reference every todo.md item against the milestone history before scheduling.

---

### Pitfall 14: Live MCP verification skipped because "it's small"

**What goes wrong:**
v1009 / v1009.1 / v1010 / v1010.2 / v1011 ALL had post-shipping code review catch secondary findings the planner missed. `feedback_review_findings_inline.md` is now the canonical pattern (default to fixing inline). A polish change skips Playwright MCP re-verify because "it's just a CSS tweak" — and ships a regression that only shows up live.

Recent specific examples from MEMORY.md:
- v1011 RESP-02-FOLLOWUP: 20×16 px NavigationControl ↔ MapCoordReadout overlap discovered LIVE during MCP re-verify at 800px. Headless vitest + e2e missed it.
- v1010.2: SF-04 dedupe contract leaked outside `map-sync.ts` to 3 callers. Only post-shipping code review caught it.
- v1011: 21 inline code-review fixes across 2 iterations. Without iter-2, would've been v1011.1.

**Why it happens:**
- Polish work feels low-risk per-item.
- Live MCP is slow vs vitest (minutes vs seconds).
- The "let's just ship" pressure peaks at end-of-milestone.

**How to avoid:**
- v1030 CONTEXT.md MUST state: Playwright MCP is the canonical close-gate (already stated, but reinforce per phase). No phase ships without a live MCP re-verify checklist in CHECKPOINT.md.
- Every polish phase exits with a 1-paragraph live MCP summary: "verified at 1440px desktop AND 800px tablet-narrow AND 414px mobile."
- Post-shipping code review per `feedback_review_findings_inline.md` is mandatory. Default to fixing inline.

**Warning signs:**
- A phase's CHECKPOINT.md says "live MCP skipped — vitest covers it."
- A phase shipped without re-running the 800px screenshot.
- A "small" PR diff touches more than its named surface.

**Phase to address:** Every phase. Roadmap CONTEXT.md must include the MCP requirement.

---

### Pitfall 15: CHANGELOG misses behavior changes because "they're invisible"

**What goes wrong:**
A polish change adjusts (a) the AI snapshot/undo contract (`isUndoSafeAction` set in `ChatPanel.tsx:107`), (b) the embed-token expiration messaging (clear vs update), (c) the allowed-origins normalization (trailing-slash strip behavior), or (d) the layer adapter `addLayers` initial-visibility honoring. CHANGELOG `[Unreleased]` is updated for the user-facing UI bug fix but NOT for the contract change. Downstream code (CLI, SDK consumers, tests) breaks silently on upgrade because they relied on the old behavior.

**Why it happens:**
- Polish work is framed as "user-facing fixes."
- Contract changes inside `BuilderActionSource`, `ChatAction`, `SharedMapResponse`, `EmbedToken.allowed_origins` are easy to update without touching CHANGELOG.
- The current milestone shape doesn't have a "behavior-change checklist" gate.

**How to avoid:**
- Every phase's CHECKPOINT.md must include a "Behavior changes" line: any change to the v1027 action contract, v1026 reconciler owned-set, AI action shape, share/embed token shape, or backend response shape is logged.
- A grep at close-gate: if `backend/openapi.json` diff is non-empty AND CHANGELOG `[Unreleased]` doesn't reference the changed routes, that's a blocker.
- If `frontend/src/types/api.ts` diff is non-empty AND CHANGELOG doesn't reference the type change, that's a blocker.

**Warning signs:**
- A polish phase ships with a non-empty OpenAPI diff but no CHANGELOG entry.
- A user reports "thing X changed silently after upgrade" — that should have been a CHANGELOG line.

**Phase to address:** Close-gate phase. Add CHANGELOG audit step.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Direct `map.setPaintProperty()` in an editor "for snappiness" | One slider feels faster | Layer JSON divergence; save/reload loses user input; v1010 PERF-02 budget broken | Never — use `setPaint` via the action boundary + reconciler |
| Bypass `BuilderLayerAction` for a "compound" AI action | Ship the new action in 1 plan instead of 2 | Provenance lost, undo snapshot misses it, dirty-state breaks | Never — add the new action variant first |
| Auto-clear `rawShareToken` on dialog close "to keep state clean" | Cleaner state machine | User loses just-created token; can't copy share URL on re-open | Never — raw token must survive session |
| Skip Playwright MCP for "CSS-only" changes | Faster phase close | Live regression slips past headless tests (v1011 RESP-02-FOLLOWUP precedent) | Never on builder/viewer canvas changes |
| Cache AI prompt schema by `dataset_id` only (not `(map_id, dataset_id)`) | Higher cache hit rate | Cross-map leakage (PERF-04 / Phase 274 reverse) | Only on global, public-visibility-only metadata (never columns) |
| Skip CHANGELOG for "internal" contract changes | Faster ship | Downstream consumers break silently on upgrade | Only when OpenAPI diff is empty AND no TS types changed |
| `null` vs `[]` for `allowed_origins` "to be expressive" | Cleaner API shape | CSP semantics diverge between defaults | Never — settle on `[]`-as-default-self everywhere |
| Use `useSortable` for a row that should only be a drop target | Less boilerplate | Re-introduces dnd-kit collision regression (v1011 Plan 06 / CTRL-01) | Never — use `useDroppable` for drop-only |

---

## Integration Gotchas

Common mistakes when connecting to existing GeoLens subsystems.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| v1027 action boundary | Direct call to handler bypassing `dispatchBuilderLayerAction` | Always go through `BuilderLayerAction` dispatch |
| v1026 reconciler | Mutating `paint` object in-place and expecting `paintValueChanged` to detect | Pass new object; `paintValueChanged` uses JSON.stringify for arrays/objects |
| v1008 unified stack | New `<SheetContent>` without `showCloseButton={false}` inside builder canvas | All overlay sheets opt-out of duplicate X |
| v1011 sortable contract | Add `useSortable` to a basemap-or-group row without `disabled: { droppable }` gating | Use `useDndContext()` + per-drag-source droppable gate (CTRL-01 fix `befe6a3b`) |
| AI chat layer validation | Trust client-supplied `dataset_table_name` | Always overwrite from DB via `_validate_chat_layers` |
| AI rate limiting | Add new `/ai/*` endpoint without `@limiter.limit(_AI_GENERATE_LIMIT)` | All AI endpoints share the `10/minute` budget unless documented otherwise |
| Embed-token CSP | Build `frame-ancestors` from un-normalized origins | Use `_build_csp_frame_ancestors` which does CRLF + parse validation |
| Share-token rotation | Don't revoke old token when regenerating | `handleRegenerateShareLink` revokes first (`SharePanel.tsx:423`) — preserve this |
| Layer adapter `addLayers` | Ignore `input.visible` at initial add | All adapters now honor `input.visible` (BUG-01 fix from v1011) — preserve |
| Map source dedupe | Key vector source by `layer.id` instead of `dataset_table_name` | Use `getSourceIdForLayer` (v1010.2 SF-04 contract) for non-cluster sources |

---

## Performance Traps

Patterns that work at small scale but fail as polish surfaces multiply.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| AI tool-loop with no token budget | Single chat blows quota | Reuse `_AI_GENERATE_LIMIT` 10/min AND server-side tool-loop step cap | After 1 user issues 20 prompts/min |
| Embed-token list query firing on every keystroke in domain input | Backend hammered with list calls | Debounce or only refetch on dialog open | After 1 enterprise user types a long origin list |
| New AI action that fetches DB metadata per-call (not cached) | Each prompt slows linearly with layer count | Use existing per-map cached schema context (PERF-04) | After 10+ layers in one map |
| Save-on-every-slider-tick | Backend overwhelmed during slider drag | v1010 200ms color+filter debounce — apply to all editors | Already a known v1010 perf budget |
| Style JSON export rebuilds on every render | UI lag in StyleJsonDialog | useMemo with stable deps | After 50+ layers |
| `useMapEmbedTokens` enabled unconditionally | Network noise + token-list refetch on every dialog open | Gated on `open && hasShareToken` (existing pattern at `SharePanel.tsx:340`) — preserve | Always preserve this gate |
| Direct map mutation skipping `coalesceFrame` | dropped frames during continuous slider drag | All animation-shape mutations use `coalesceFrame` rAF utility (v1010) | After 1 fast slider drag |

---

## Security Mistakes

Domain-specific security issues beyond general web security.

| Mistake | Risk | Prevention |
|---------|------|------------|
| AI prompt includes server-side `ANTHROPIC_API_KEY` in error detail | Key exfil via 500 response | Never interpolate `settings.*_api_key` into HTTPException; ESLint ban + grep gate |
| Embed CSP `frame-ancestors` set from un-validated input | XSS via iframe parent injection | `_build_csp_frame_ancestors` CRLF + parse validation at `router.py:111` — never bypass |
| Share-token endpoint returns the raw token on EVERY GET (not just create) | Token leaks to anyone with read access | `get_active_share_token` returns `token=None` on subsequent GETs (`SharePanel.tsx:335` pattern) — preserve |
| AI chat `_validate_chat_layers` doesn't enforce per-user dataset allowlist | Cross-tenant column-name leak | `build_table_allowlist(db, user)` — already enforced at `router.py:136`, NEVER bypass |
| Embed iframe sandbox includes `allow-same-origin` with `allow-scripts` | Sandbox-escape (SEC-07 / M-70 — already documented at `SharePanel.tsx:36`) | Keep `sandbox="allow-scripts"` only |
| Public-map endpoint accepts API key as query param without rate limit | Anonymous brute force | Existing rate limits on `/datasets/` + `/search/` — extend to any new `/ai/*` GET |
| AI analyze leaks visibility-off layer columns | Hidden-layer schema disclosure | Filter `layer.visible` BEFORE `_validate_chat_layers`, OR document that "analyze sees hidden layers" |
| OG/social-card endpoint serves private map thumbnails | Private map preview leaks | Verify visibility check on every OG endpoint; non-public 404s |
| `frame-ancestors 'self' *` from a wildcard accidentally accepted | Embed anywhere | Backend pin: assert `*` never appears in directive |
| New `/ai/analyze/` endpoint forgets `require_permission("use_ai_chat")` | Anonymous LLM cost burn | Every `/ai/*` endpoint MUST be permission-gated |

---

## UX Pitfalls

Common user experience mistakes during a polish sweep.

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Pre-applying AI suggestions then asking confirm | User sees changes they didn't ask for; rejecting leaves partial state | Two-phase staging OR force-undo-on-reject — pick one upfront |
| Closing share dialog clears raw token | User can't copy share URL after dialog reopen | Keep `rawShareToken` survival contract |
| Generic "AI failed" toast on all error classes | User can't distinguish "no API key" from "rate limited" from "auth expired" | Existing `mapApiErrorToMessage` at `ChatPanel.tsx:199` — extend, don't generalize |
| Suggestion chips visible when AI is disabled | User confused why nothing happens | Gate chips on `aiEnabled` (v1010.2 SF-06 pattern) |
| "Save" indicator turns dirty on AI preview before user accepts | User saves a preview they were rejecting | Pending actions must not flip dirty state |
| Removing X close button without alternative dismiss | User trapped in sheet on mobile | Provide back-button OR backdrop-click dismiss explicitly |
| Polish "fixes" the basemap selector double-X by adding nav-position back to top-right | Re-creates v1011 RESP-02 800px overlap | Fix the right-sidebar overlap instead; keep nav `top-left` in builder |
| Editor slider commits on every tick | Janky save indicator flicker | v1010 200ms debounce + dirty-state-only-after-commit |
| Allowed-origins input auto-https'd silently | User confused why `http://localhost:3000` becomes `https://localhost:3000` | Show normalized form in the chip list before submit |
| Embed code copied but user doesn't realize CSP'd | Embed fails in test page, blame copy button | Embed code preview includes the iframe sandbox attribute visibly |

---

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **New AI action type:** Often missing the `BuilderLayerAction` variant — verify the action is in `builder-action-contract.ts` AND `dispatchBuilderLayerAction` switch
- [ ] **Paint mutation polish:** Often missing the save/reload symmetry test — verify a vitest exercises save → reload → assert paint matches
- [ ] **`clear_paint` in chat action:** Often missing — verify `buildChatActionPaint` test table includes a clear case
- [ ] **AI confirm-before-apply:** Often missing the "reject leaves layers byte-equal" pin — add explicit regression test
- [ ] **AI provider gating on new feature:** Often missing — verify `_check_ai_available(db)` AND consumer-side `enabled: !!token && aiEnabled` (mirror v1010.2 SF-06)
- [ ] **AI analyze:** Often missing visibility filter — verify hidden layers excluded OR document
- [ ] **SharePanel polish:** Often missing the raw-token-survives-rerender pin — extend SharePanel.test.tsx
- [ ] **Embed token race:** Often missing the in-flight ref — verify `inflightEmbedCreate.current` mirrors ChatPanel's pattern
- [ ] **Allowed-origins polish:** Often missing the round-trip canonical-form test — verify on create AND update
- [ ] **Per-render-mode editor polish:** Often missing the direct-mutation grep guard — verify no `map.setPaintProperty` outside adapters
- [ ] **Smaller-screen layout fix:** Often missing the 800px Playwright MCP screenshot — required gate
- [ ] **`<SheetContent>` new sheet:** Often missing `showCloseButton={false}` — verify no double-X
- [ ] **Polish phase scope:** Often missing the "out of scope" list — verify CONTEXT.md restates non-goals
- [ ] **Easy-win item:** Often missing the 15-min spike — verify item didn't already ship in a prior milestone
- [ ] **CHANGELOG entry:** Often missing for "internal" contract changes — verify OpenAPI/TS-types diff matches CHANGELOG
- [ ] **Disabled-AI UAT:** Often missing — verify the close-gate runs with `AI_ENABLED=false`
- [ ] **Code-review iter-2:** Often skipped — per `feedback_review_findings_inline.md`, run review even after iter-1 GREEN

---

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Direct `map.setPaintProperty` shipped in editor | LOW | Replace with `setPaint` via action handler; add save/reload symmetry test; grep guard |
| New AI action bypasses action boundary | MEDIUM | Add the `BuilderLayerAction` variant retroactively; thread `BuilderActionSource`; backfill provenance |
| AI confirm-before-apply leaves partial state | MEDIUM | Add atomic-undo OR snapshot-and-restore on reject; pin "byte-equal" regression test |
| Raw share token cleared on dialog close | LOW | Revert the cleanup; pin survival test |
| Embed token race created duplicates | MEDIUM | Backend dedup + admin cleanup endpoint; add inflight ref; pin race regression |
| Allowed-origins normalization broken | LOW | Round-trip vitest + canonical-form documentation; backfill `parseOrigins` calls on update path |
| Per-render-mode editor save/reload divergence | LOW | Symmetry test + grep guard; revert direct mutation |
| Smaller-screen NavigationControl move regression | LOW | Revert to v1011 `top-left` placement; fix the sidebar overlap differently |
| Double-X sheet regression | LOW | Add `showCloseButton={false}`; extend negative-control pin |
| Polish scope creep into architecture | HIGH | Defer the architecture work to v1031; revert mid-phase refactors; ship the polish that was scoped |
| Easy-win turned hard | MEDIUM | Promote to its own phase OR defer; document in CARRYFORWARD |
| CHANGELOG miss | LOW | Backfill `[Unreleased]` with the contract change; tag a `v1030.x` if user-facing |
| AI provider key leak in error | HIGH | Rotate the leaked key immediately; backfill ESLint ban; audit logs for exfil |
| AI cross-map cache leak | HIGH | Clear the cache; re-key on `(map_id, dataset_id)`; audit access logs |

---

## Pitfall-to-Phase Mapping

How v1030 roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 1 — Bypass v1027 action boundary | Phase 1133 audit + every AI phase | grep guard for direct `map.*` outside adapters |
| 2 — Collapse v1026 patch/replace/clear | Per-render-mode editor phases + AI phase | `buildChatActionPaint` test table + save/reload symmetry vitest |
| 3 — AI confirm collapses snapshot/undo | AI chat phase | "Reject leaves layers byte-equal" regression test |
| 4 — AI provider-disabled regression | Phase 1133 audit + close-gate phase | `AI_ENABLED=false` Playwright MCP smoke |
| 5 — AI analyze leaks columns / cache | AI data-analysis phase | Visibility filter test + cache-key pin + grep ban on key strings |
| 6 — SharePanel raw-token cleared | Sharing polish phase | Raw-token-survival vitest |
| 7 — Embed-token race | Sharing polish phase | Inflight-ref + race regression vitest |
| 8 — Allowed-origins UX regression | Sharing polish phase | Round-trip + CSP no-wildcard backend pin |
| 9 — Editor direct `setPaintProperty` | Per-render-mode editor phase | grep guard + save/reload symmetry |
| 10 — NavigationControl smaller-screen move | Smaller-screen layout phase | 800px Playwright MCP screenshot + RESP-01/RESP-02 readme |
| 11 — `<SheetContent>` double-X regression | Smaller-screen layout phase | Generalized negative-control pin |
| 12 — Polish scope creep | Roadmapper + every phase | Out-of-scope list in CONTEXT.md; deferred-architecture register |
| 13 — Easy-wins turn hard | Phase 1133 audit | 15-min spike + cross-ref milestone history |
| 14 — Skip live MCP | Every phase + close-gate | Mandatory MCP screenshot per phase |
| 15 — Missed CHANGELOG | Close-gate phase | OpenAPI/types diff vs CHANGELOG diff check |

---

## Sources

- **`builder-action-contract.ts`** — v1027 typed action boundary; discriminated-union of `BuilderLayerAction` + `BuilderBasemapAction` + `BuilderSettingsAction` + `BuilderLayerActionHandlers`. `BuilderActionSource = 'manual' | 'ai' | 'system'` is the provenance contract.
- **`layer-adapters/shared.ts`** — v1026 reconciler primitives: `syncOwnedPaintProperties`, `syncOwnedLayoutProperties`, `paintValueChanged`, `syncSingleLayerVisibility`, `CUSTOM_PAINT_PROPS`, `setLayerProperty`. The canonical owned-set contract.
- **`ChatPanel.tsx`** — current chat action dispatch (`handleChatAction`), `buildChatActionPaint` patch/replace/clear encoder, `lastSnapshotRef` undo pattern (`BLD-20260526-04`), `inflightRef` synchronous lock pattern (`ChatPanel.tsx:165`).
- **`SharePanel.tsx`** — `rawShareToken` vs `persistedShareTokenHint` separation (post-`3ed5ceb3`), `parseOrigins` normalization (`SharePanel.tsx:24`), embed iframe sandbox contract (SEC-07 / M-70 at line 36), `handleRegenerateShareLink` revoke-first pattern.
- **`backend/app/processing/ai/router.py`** — `_check_ai_available` 403/503 distinction, `_validate_chat_layers` per-dataset allowlist enforcement, `@limiter.limit(_AI_GENERATE_LIMIT)` `10/minute` rate limit, `require_permission("use_ai_chat")` gate on every AI endpoint.
- **`backend/app/processing/ai/chat_actions.py`** — `_handle_query_data` cache-key-per-map note (PERF-04 / Phase 274).
- **`backend/app/modules/catalog/maps/router.py`** — `_build_csp_frame_ancestors` CRLF validation (line 111), `get_shared_map_endpoint` CSP emission (line 473), share-token revocation on visibility change (line 863).
- **`frontend/src/components/map/MapCoordReadout.tsx`** — Builder-vs-Viewer NavigationControl asymmetry contract (line 26-37); load-bearing `right-14` offset documented.
- **`.planning/PROJECT.md`** — Prior-milestone post-mortems:
  - **v1009.1 SP-09 (`inflightRefresh`)** — synchronous in-flight ref pattern.
  - **v1010 PERF baseline** — `coalesceFrame` rAF + 200ms debounce contract.
  - **v1010.2 SF-04** — vector-tile source dedupe via `getSourceIdForLayer`.
  - **v1010.2 SF-06** — consumer-side `enabled: !!token && aiEnabled` gating; `useEmbeddingStats` was missed by plan naming only `useAIStatus`.
  - **v1011 RESP-01/RESP-02** — NavigationControl `top-left` in builder vs `top-right` in viewer; `data-builder-canvas="true"` scoped CSS.
  - **v1011 RESP-03** — `<SheetContent showCloseButton={false}>` + negative-control regression pin.
  - **v1011 INV-01** — DETAIL LEVEL remove (commit `6078b82a`).
  - **v1011 BUG-01** — adapter-contract honor `input.visible` at initial add; defense-in-depth `syncVisibility`.
  - **v1011 CTRL-01** — dnd-kit `disabled: { droppable }` per-drag-source contract; sortable-row-not-collision-target during catalog drags.
  - **v1028** — AI feature polish + actionable AI-unavailable state.
- **`feedback_review_findings_inline.md`** — Default-to-fixing-all-inline policy after post-shipping code review.
- **`feedback_hygiene_milestone_pattern.md`** — Hygiene-shape milestone close pattern (v1009.1 / v1010.1 / v1010.2 / v1011 / v1011.1).
- **`project_maplibre_idle_retry_pattern.md`** — `map.once('idle', retry)` recovery pattern for `isStyleLoaded` race (v1011 SP-03 B-01-followup).
- **`todo.md:138-150`** — Current polish backlog covering carrot expand, sublayer indication, basemap drag, layer toggle for specific map, Map Settings widgets necessity, rename group focus, delete layer, smaller-screen overlays (3 separate items), and export-map watermark.
- **MEMORY.md** — Live MCP precedent for builder milestones; FastAPI trailing-slash dual-shape ROUTE-01 ALREADY-LANDED context for any new route additions.

---

*Pitfalls research for: v1030 Map Builder Polish Sweep — pitfalls of ADDING polish features to an existing v1026 reconciler + v1027 action boundary + v1008 unified stack substrate, with AI chat integrated via the same boundary and sharing/embed in flight.*
*Researched: 2026-05-27*
