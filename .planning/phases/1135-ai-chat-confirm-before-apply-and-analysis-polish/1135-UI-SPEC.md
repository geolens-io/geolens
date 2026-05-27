---
phase: 1135
slug: ai-chat-confirm-before-apply-and-analysis-polish
status: draft
shadcn_initialized: true
preset: not applicable (existing project — components.json present)
created: 2026-05-27
---

# Phase 1135 — UI Design Contract

> Visual and interaction contract for Phase 1135: AI Chat Confirm-Before-Apply and Analysis Polish.
> Shape B (`pendingLayers` staging buffer) is locked by CONTEXT.md — no re-discussion.
> This phase introduces 5 new surfaces inside `ChatPanel` / `BuilderRail`. No new design tokens,
> no new typographic sizes, no new color tokens. All design decisions derive from existing
> `frontend/src/index.css` tokens and the 1134-UI-SPEC precedent.

---

## Design System

| Property | Value | Source |
|----------|-------|--------|
| Tool | shadcn (via Radix primitives) | components.json present |
| Preset | existing project — no init required | components.json |
| Component library | Radix UI (via shadcn) | frontend/src/components/ui/ |
| Icon library | Lucide React | existing |
| Font (sans) | IBM Plex Sans Variable | frontend/src/index.css line 262 |
| Font (mono) | IBM Plex Mono | frontend/src/index.css line 263 |

---

## Spacing Scale

Standard 8-point scale in use project-wide. Inherited from 1134-UI-SPEC; no new values.

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | Icon gaps, chip internal padding minimum |
| sm | 8px | Chip gap, banner padding, table cell padding |
| md | 16px | Panel section padding, card padding |
| lg | 24px | Empty-state body vertical rhythm |
| xl | 32px | Disabled-state vertical centering padding |
| 2xl | 48px | Not used in this phase |
| 3xl | 64px | Not used in this phase |

**Exceptions for this phase:**

- **Action preview chip:** `px-2.5 py-1` (10px / 4px) — matches the existing suggestion chip shape in `ChatPanel.tsx:539`. This is a sub-8px vertical exception already established by the suggestion chip; reusing it keeps visual consistency rather than introducing a second chip variant.
- **Inline data table max-height:** `max-h-48` (192px = 48 × 4px). This is a non-scale value chosen to show ~5–6 rows before scrolling. 192 is divisible by 4; acceptable per project convention.

---

## Typography

No new sizes or weights. All type from the existing scale in `frontend/src/index.css`.
Inherited from 1134-UI-SPEC verbatim.

| Role | Size | Weight | Line Height | Usage |
|------|------|--------|-------------|-------|
| Body / label | 14px (`text-sm`) | 400 | 1.43 | Chat messages, chip text, table cell text, disabled-state body |
| Micro / caption | 12px (`text-xs`) | 400 | 1.33 | Table column headers, chip count label, banner helper text, "applied N changes" line |
| Instrument (mono) | 10px (`text-2xs` + `font-mono`) | 400 | 0.875rem | Not used in this phase (coord readout only) |
| Section heading | 14px (`text-sm`) | 500 | 1.43 | Disabled-state title, staging tray header label, inline card heading |

**Rule:** No new `text-*` class beyond this set is introduced in this phase.

---

## Color

All tokens from `frontend/src/index.css`. No new tokens.

| Role | Token | Value (light mode) | Usage |
|------|-------|--------------------|-------|
| Dominant (60%) | `--background` | `oklch(0.985 0.003 85)` | ChatPanel background, staging tray background |
| Secondary (30%) | `--muted` / `--card` | `oklch(0.97 0.003 85)` | Assistant message bubbles, inline data card bg, disabled-state container |
| Accent (10%) | `--primary` | `oklch(0.55 0.18 250)` | See reserved-for list below |
| Destructive | `--destructive` | `oklch(0.577 0.245 27.325)` | Error banner border + icon; reject button (outline-destructive) |
| Muted foreground | `--muted-foreground` | `oklch(0.45 0.005 250)` | Chip text at rest, table header text, disabled-state body text |
| Warning | `--warning` | `oklch(0.75 0.15 85)` | Not used in this phase |
| Success | `--success` | `oklch(0.53 0.19 145)` | Not used in this phase |

**Accent (`--primary` OKLCH blue) reserved for (exhaustive list, this phase):**
1. Accept button in action preview chip tray (`bg-primary text-primary-foreground`)
2. User message bubble background (`bg-primary text-primary-foreground`) — existing
3. Suggestion chip hover border (`hover:border-primary/30`) — existing
4. Focus ring (`--ring`) — existing

**Accent NOT used for:** the staging chip pill background (use `bg-muted`), table headers (use `bg-muted/50`), disabled-state copy (use `text-muted-foreground`), error banner (use `--destructive`).

---

## Surface 1: Action Preview Chip Tray (AI-01 / AI-09)

The staging tray renders between the last assistant message and the compose area when `pendingActions.length > 0`. It is gated on Shape B — the tray only appears when the `chat-action-staging.ts` buffer holds at least one destructive action.

### Layout

- The tray is a full-width block in the message log scroll area, rendered as the last item before `messagesEndRef`.
- Outer container: `border border-border rounded-lg bg-muted/30 p-2 space-y-1.5`
- Header row: `flex items-center justify-between mb-1`
  - Left: label `text-xs font-medium text-muted-foreground` — "N pending change(s) — review before applying"
  - Right: two buttons — "Accept all" (primary, `h-7 text-xs`) and "Reject all" (outline-destructive, `h-7 text-xs`)

### Individual Action Chip

Each pending action renders as one chip row:

```
[ verb-icon ] [ chip text ]                  [ Accept ] [ Reject ]
```

| Property | Value | Rationale |
|----------|-------|-----------|
| Container | `flex items-center gap-2 rounded-md bg-background px-2 py-1.5` | Matches existing `bg-muted` message bubble family but lighter surface |
| Verb icon | Lucide `Plus` (add_layer) or `Trash2` (remove_layer), 14px, `text-muted-foreground` | Consistent with Lucide icon vocabulary in the builder |
| Chip text | `text-sm text-foreground` | Full sentence format: see copywriting section |
| Accept button | `Button size="sm" variant="default"` with `h-7 text-xs` override | OKLCH blue — confirms action |
| Reject button | `Button size="sm" variant="outline"` with `h-7 text-xs border-destructive/50 text-destructive hover:bg-destructive/10` | Destructive-tinted outline — rejects without full red fill |
| Max visible chips before scroll | 4 chips | After 4, the chip list gets `max-h-40 overflow-y-auto` |

### Chip Text Format

Chip text is verb + entity + optional relative position. Format rules:

| Action | Format | Example |
|--------|--------|---------|
| `add_layer` | `Add "{display_name}"` or `Add "{display_name}" below "{reference_layer}"` | `Add "NYC Subway" below "Counties"` |
| `remove_layer` | `Remove "{display_name}"` or `Remove "{display_name}" (N features)` if feature count is available | `Remove "Boroughs" (5 features)` |

- Display name is taken from `MapLayerResponse.display_name ?? MapLayerResponse.dataset_name`.
- "Below" reference is the layer immediately above in the MapLibre stack at staging time.
- If no reference layer can be determined, omit the relative position clause.
- Text is truncated at 60 characters with `truncate` class; full text in `title` attribute.

### Interaction Contract

- **Accept one:** dispatches `acceptOne(index)` from `ChatActionStaging`, which calls `dispatchLayerAction` for that single action. Chip disappears from tray.
- **Reject one:** calls `rejectOne(index)`. Map state unchanged. Chip disappears.
- **Accept all:** calls `acceptAll()`. All chips dispatched in order. Tray disappears.
- **Reject all:** calls `rejectAll()`. Buffer cleared. Tray disappears. Map state is byte-equal to pre-prompt.
- If tray is visible and user sends another message, the old pending actions are auto-rejected (buffer cleared before new staging begins).
- The existing Undo button (single-level undo for safe actions) is suppressed while the staging tray is visible — they are mutually exclusive undo affordances.

### Accessibility

- Tray container: `role="region" aria-label="Pending AI actions"` — screen reader announces region entry.
- Each chip: `role="listitem"` inside a `role="list"` container.
- Accept/Reject buttons have `aria-label` including the action text: `aria-label={t('chat.staging.accept', { action: chipText })}`.

---

## Surface 2: Inline Data-Analysis Card (AI-08)

When `show_query_result` returns rows (not just a spatial bbox for map flyover), the result renders as an inline table card inside the assistant message bubble. This is a read-only display; no new `BuilderLayerAction` variant.

### When to Render

- `show_query_result` action with `rows: Row[]` present (non-empty array) → render inline card below the assistant text.
- `show_query_result` with only `geojson` + `bbox` (spatial result) → existing `onQueryResult` flyover path, no inline card.
- Empty `rows: []` → render the empty-state variant (see below).

### Card Shape

The card is appended as a sibling to the assistant message `<p>` inside the same `bg-muted` bubble:

```
┌─────────────────────────────────────┐
│ col1 header  col2 header  col3 hdr  │  ← text-xs font-medium text-muted-foreground, bg-muted/50
│─────────────────────────────────────│  ← border-b border-border
│ row 1 val    row 1 val    row 1 val │  ← text-sm text-foreground
│ row 2 val    …                      │
│ (scrollable after 5 rows)           │
└─────────────────────────────────────┘
│ N rows                              │  ← text-xs text-muted-foreground, below card
```

| Property | Value |
|----------|-------|
| Card container | `mt-2 rounded-md border border-border overflow-hidden` |
| Table element | `w-full text-sm` with `table-fixed` |
| Column header row | `bg-muted/50`, cell padding `px-2 py-1`, `text-xs font-medium text-muted-foreground uppercase tracking-wide` |
| Data row | `border-b border-border last:border-0`, cell padding `px-2 py-1`, `text-sm text-foreground` |
| Data row hover | `hover:bg-muted/40` |
| Max visible height | `max-h-48` (192px) with `overflow-y-auto` on a scroll wrapper around the `<tbody>` equivalent |
| Column count | Render all columns returned by the API; cap at 5 columns displayed (hide excess with `…` indicator in header) |
| Cell value truncation | `max-w-[8rem] truncate` per cell; full value in `title` attribute |
| Footer row count | `mt-1 text-xs text-muted-foreground` — "{N} row(s)" |

### Empty State (0 rows)

```
┌────────────────────────────┐
│  No results returned       │
└────────────────────────────┘
```

- Container: `mt-2 rounded-md border border-border px-3 py-2`
- Text: `text-sm text-muted-foreground` — "No results returned."

### Accessibility

- Table has `role="table"` with `aria-label` from the assistant message context (not a separate label needed — the surrounding message provides context).
- Column headers use `scope="col"`.
- Scroll wrapper: `role="region" aria-label={t('chat.queryResult.tableLabel', { defaultValue: 'Query result table' })}`.

---

## Surface 3: Disabled-State ChatPanel (AI-02)

When `isAIAvailable === false`, `BuilderRail.tsx:170-181` renders a placeholder. The current implementation renders plain text with no actionable affordance. This phase replaces it with a structured disabled state.

### Existing State (v1028 — to be replaced)

```tsx
<div className="flex h-full flex-col justify-center gap-2 p-4 text-sm" role="status" aria-live="polite">
  <p className="font-medium text-foreground">AI is unavailable</p>
  <p className="text-muted-foreground">An administrator needs to enable an AI provider...</p>
</div>
```

### Target State (this phase)

The disabled state distinguishes two reasons from `useAIAvailability()`:

| Reason | Condition | Copy | CTA |
|--------|-----------|------|-----|
| `env_disabled` | `!aiStatus.data?.enabled` (AI_ENABLED=false) | "AI is disabled" + "An administrator has disabled AI for this instance." | "Go to Settings" link (admin only) |
| `no_key` | `aiStatus.data?.enabled && !aiStatus.data?.configured` | "AI not configured" + "A provider API key is required." | "Configure in Settings" link (admin only) |
| `permission` | `!can('use_ai_chat')` | "AI unavailable" + "You don't have permission to use AI chat." | No CTA |
| Loading | `aiStatus.isLoading` | Spinner only | — |

**Note:** the `reason` field must be derived in `useAIAvailability()` (already planned in CONTEXT.md) — this spec defines what the UI renders per reason.

### Visual Spec

```
┌─────────────────────────────┐
│  [icon]  {title}            │
│          {body}             │
│          [{CTA link}]       │  ← only for admin + env_disabled/no_key
└─────────────────────────────┘
```

| Property | Value |
|----------|-------|
| Container | `flex h-full flex-col items-center justify-center gap-3 p-6 text-sm` |
| Icon | Lucide `BotOff`, `h-8 w-8 text-muted-foreground` |
| Title | `text-sm font-medium text-foreground` |
| Body | `text-sm text-muted-foreground text-center max-w-[18rem]` |
| CTA link | `Button variant="outline" size="sm"` — "Go to Settings" or "Configure in Settings"; routes to `/admin/settings?tab=ai` via `Link` component |
| CTA visibility | Only rendered when `isAdmin === true` AND reason is `env_disabled` or `no_key` |
| `role` attribute | `role="status" aria-live="polite"` — preserves existing screen reader contract |

### i18n Keys Required (new)

| Key | Default (en) |
|-----|-------------|
| `builder:rail.aiDisabledTitle` | `"AI is disabled"` |
| `builder:rail.aiDisabledBody` | `"An administrator has disabled AI for this instance."` |
| `builder:rail.aiNoKeyTitle` | `"AI not configured"` |
| `builder:rail.aiNoKeyBody` | `"A provider API key is required before AI chat can be used."` |
| `builder:rail.aiPermissionTitle` | `"AI unavailable"` |
| `builder:rail.aiPermissionBody` | `"You don't have permission to use AI chat."` |
| `builder:rail.aiGoToSettings` | `"Go to Settings"` |
| `builder:rail.aiConfigureSettings` | `"Configure in Settings"` |

Required in: en, de, es, fr (i18n parity — same 4-language requirement as all builder strings).

---

## Surface 4: Recoverable Error Banner (AI-03)

The existing `ChatPanel` surfaces errors as inline error bubbles inside the message log (`role="error"` ChatMessage with `bg-destructive/10` + `AlertCircle` icon + Retry button). This is the correct pattern for transient per-message errors.

Phase 1135 adds a **persistent inline banner** for errors that indicate the AI service has become unavailable mid-session (401, 403, 503). This is distinct from per-message errors.

### When to Show the Banner vs. the Existing Error Bubble

| Error Type | Trigger | Surface |
|-----------|---------|---------|
| 401 session expired | `err.status === 401` | Existing error bubble (single message). Copy: `t('chat.errorSessionExpired')`. No retry — session must be refreshed at page level |
| 403 forbidden | `err.status === 403` | **Persistent banner** (AI disabled or permission revoked mid-session). No retry. CTA: "Contact your administrator" or dismiss |
| 503 AI unavailable | `err.status === 503` | **Persistent banner** with retry. CTA: "Retry" re-fires the last user message |
| Network error / unknown | Other `ApiError` or raw `Error` | Existing error bubble with Retry button |

### Banner Visual Spec

The banner renders at the TOP of the ChatPanel message log (not below the compose area). It is sticky within the message scroll area via `sticky top-0 z-10`.

```
┌──────────────────────────────────────────┐
│ [AlertCircle] {title}  {body}  [Retry/×] │
└──────────────────────────────────────────┘
```

| Property | Value |
|----------|-------|
| Container | `flex items-start gap-2 rounded-md border border-destructive/20 bg-destructive/8 px-3 py-2 mb-2 sticky top-0 z-10` |
| Icon | Lucide `AlertCircle`, `h-4 w-4 text-destructive shrink-0 mt-0.5` |
| Title | `text-sm font-medium text-foreground` — brief label |
| Body | `text-xs text-muted-foreground` — one-line explanation |
| Retry button (503) | `Button size="sm" variant="outline" className="h-7 text-xs gap-1"` — `RotateCcw` icon + "Retry" |
| Dismiss button (403) | Plain `×` button `Button size="icon-xs" variant="ghost"` — no retry offered for permission errors |
| Retry behavior | Re-fires the last user message (existing `handleRetry` pattern from `ChatPanel:517-519`) |
| Banner persistence | Remains visible until user dismisses (×) OR a successful response replaces it. Sending a new message does NOT auto-clear the banner — it persists until the retry succeeds |
| `role` | `role="alert" aria-live="assertive"` — announces immediately to screen readers |

### i18n Keys Required (new)

| Key | Default (en) |
|-----|-------------|
| `builder:chat.bannerForbiddenTitle` | `"AI access lost"` |
| `builder:chat.bannerForbiddenBody` | `"You no longer have permission to use AI chat."` |
| `builder:chat.bannerUnavailableTitle` | `"AI is unavailable"` |
| `builder:chat.bannerUnavailableBody` | `"The AI service is temporarily unavailable. Try again in a moment."` |
| `builder:chat.bannerRetry` | `"Retry"` |
| `builder:chat.bannerDismiss` | `"Dismiss"` |

Required in: en, de, es, fr.

### What Changes from the Existing Error Bubble

The existing `role: 'error'` ChatMessage with `bg-destructive/10` inside the message log is preserved for network errors and 401. Only 403 and 503 elevate to the sticky banner. This keeps the message log clean for per-message errors while surfacing service-level problems at the panel level.

---

## Surface 5: Viewport-Aware Suggestion Chips (AI-05)

The existing `getSmartSuggestions()` in `chat-suggestions.ts` generates up to 4 suggestions based on layer geometry type. Phase 1135 adds viewport context (current map bounds + zoom) and selected-layer context to the suggestion list.

### Chip Shape (unchanged)

Existing chips at `ChatPanel.tsx:539`:
```tsx
className="cursor-pointer text-xs px-2.5 py-1 rounded-full border border-border
           hover:bg-accent hover:border-primary/30 text-muted-foreground
           hover:text-foreground transition-colors"
```

No changes to chip visual shape. The chip count limit remains 4. No new chip variant.

### Viewport-Aware Augmentation

The suggestion function signature expands to accept optional viewport context:

```typescript
interface ViewportContext {
  zoom: number;               // current map zoom level
  bounds: [number, number, number, number]; // [west, south, east, north] WGS84
  selectedLayerName?: string; // display_name of currently selected layer, if any
}

export function getSmartSuggestions(
  layers: MapLayerResponse[],
  t: AnyTFunction,
  viewport?: ViewportContext,
): string[]
```

### Suggestion Priority Order (with viewport)

1. If `selectedLayerName` is set: lead with a layer-specific suggestion referencing `@[{selectedLayerName}]`.
2. If `zoom >= 12` and at least one vector layer exists: add "Show attributes near this area" type suggestion.
3. Existing geometry-type suggestions (fallback).
4. "Add dataset" fallback if count < 4.

The chip list still caps at 4. The `getSmartSuggestions` function still returns `string[]`.

### Refresh Trigger

Chips are re-evaluated when:
- The user sends a message (chips show on the new empty-state after the conversation is cleared, or on the empty initial state).
- The selected layer changes.
- The map idle event fires (debounced — 500ms after idle).

The chip list is NOT re-rendered mid-conversation. Chips only appear on the initial empty state or after all messages are cleared.

### Viewport Hook Wiring

`ChatPanel` receives an optional `viewport?: ViewportContext` prop. The caller (`BuilderRail.tsx`) provides this from the existing `useBuilderViewport` / `useMapRef` pattern already in `MapBuilderPage.tsx`. No new state management; viewport is passed down as a prop.

---

## Interaction Contracts Summary

| Surface | Trigger | Response | Timing |
|---------|---------|----------|--------|
| Action chip tray | `pendingActions.length > 0` after AI response | Tray appears below last message before compose area | Synchronous — no animation; follows existing `motion-fast` (150ms) CSS transition if entry animation is desired |
| Accept one chip | Button click | Dispatches single action, chip removed | `motion-fast` (150ms) chip fade-out |
| Reject one chip | Button click | Chip removed, map unchanged | `motion-fast` (150ms) chip fade-out |
| Reject all | Button click | Tray removed, `pendingActions = []` | Immediate |
| Inline table card | `show_query_result` with rows | Appears in assistant bubble | Synchronous |
| Disabled state | `!aiAvailable` | Full-panel placeholder, no compose area shown | Static — no transition |
| Error banner | 403 or 503 during active session | Sticky banner at top of message log | `motion-fast` (150ms) slide-in from top |
| Error banner dismiss | `×` click | Banner removed | `motion-fast` (150ms) fade-out |
| Error banner retry | Retry click | Re-fires last user message | Calls existing `handleRetry` |
| Viewport chip refresh | Map idle + 500ms debounce | Chip list recalculated | Only visible on empty state; no visible change mid-conversation |

---

## Copywriting Contract

| Element | Copy | i18n Key |
|---------|------|----------|
| Staging tray header | "N pending change(s) — review before applying" | `chat.staging.header` (pluralized) |
| Accept all button | "Accept all" | `chat.staging.acceptAll` |
| Reject all button | "Reject all" | `chat.staging.rejectAll` |
| Accept one button | "Accept" | `chat.staging.accept` |
| Reject one button | "Reject" | `chat.staging.reject` |
| Add layer chip | `Add "{name}"` or `Add "{name}" below "{ref}"` | `chat.staging.chipAdd` / `chat.staging.chipAddBelow` |
| Remove layer chip | `Remove "{name}"` or `Remove "{name}" (N features)` | `chat.staging.chipRemove` / `chat.staging.chipRemoveFeatures` |
| Empty query table | "No results returned." | `chat.queryResult.empty` |
| Table scroll region aria-label | "Query result table" | `chat.queryResult.tableLabel` |
| Row count footer | "N row(s)" | `chat.queryResult.rowCount` |
| Disabled: env_disabled title | "AI is disabled" | `rail.aiDisabledTitle` |
| Disabled: env_disabled body | "An administrator has disabled AI for this instance." | `rail.aiDisabledBody` |
| Disabled: no_key title | "AI not configured" | `rail.aiNoKeyTitle` |
| Disabled: no_key body | "A provider API key is required before AI chat can be used." | `rail.aiNoKeyBody` |
| Disabled: permission title | "AI unavailable" | `rail.aiPermissionTitle` |
| Disabled: permission body | "You don't have permission to use AI chat." | `rail.aiPermissionBody` |
| Disabled: settings CTA (env/key) | "Go to Settings" or "Configure in Settings" | `rail.aiGoToSettings` / `rail.aiConfigureSettings` |
| Error banner: 403 title | "AI access lost" | `chat.bannerForbiddenTitle` |
| Error banner: 403 body | "You no longer have permission to use AI chat." | `chat.bannerForbiddenBody` |
| Error banner: 503 title | "AI is unavailable" | `chat.bannerUnavailableTitle` |
| Error banner: 503 body | "The AI service is temporarily unavailable. Try again in a moment." | `chat.bannerUnavailableBody` |
| Error banner retry | "Retry" | `chat.bannerRetry` |
| Error banner dismiss | "Dismiss" | `chat.bannerDismiss` |
| Suggestion (no layers) | "Search for a dataset" | `chat.suggestions.searchDatasets` — existing |
| Suggestion (selected layer context) | "Summarize @[{name}] attributes" | `chat.suggestions.summarizeLayer` — new |
| Suggestion (zoom ≥ 12 + vector) | "Show nearby features in this area" | `chat.suggestions.nearbyFeatures` — new |

**Destructive actions in this phase:**

| Action | Confirmation approach |
|--------|----------------------|
| Reject all pending AI actions | Immediate — no modal. The staging tray replaces the confirm-before-apply dialog; a second confirmation inside the tray would be redundant. The button label "Reject all" is explicit enough. |
| Remove layer (via AI staging) | Staged in tray — user sees the remove chip before committing. No additional modal. After Accept, the existing optimistic + rollback pattern from v1011 BUG-02 handles server errors. |

---

## Component Inventory

New and modified components.

| Component | File | Type | Modification |
|-----------|------|------|-------------|
| `ChatPanel` | `frontend/src/components/builder/ChatPanel.tsx` | Modify | Add staging tray render, error banner, updated empty state chips with viewport |
| `ChatPanel` props | same | Modify | Add `viewport?: ViewportContext` prop |
| `chat-action-staging.ts` | `frontend/src/builder/ai/chat-action-staging.ts` | NEW | Shape B staging buffer module (~150 LOC per CONTEXT.md) |
| `chat-suggestions.ts` | `frontend/src/components/builder/chat-suggestions.ts` | Modify | Add `viewport?: ViewportContext` param; add 2 new suggestion types |
| `BuilderRail` | `frontend/src/components/builder/BuilderRail.tsx` | Modify | Replace disabled-state UI (lines 170-181) with structured disabled-state component |
| `use-ai-availability.ts` | `frontend/src/hooks/use-ai-availability.ts` | Modify | Add `reason` field to return type: `'env_disabled' | 'no_key' | 'permission' | null` |

Components that are **read-only** in this phase (verified, not modified):
- `ChatInput.tsx` — compose area unchanged.
- `sheet.tsx` — no new Sheet instances in AI rail.
- `chat-suggestions.ts` function signature extension preserves all existing call sites via optional `viewport` param.

---

## Regression Test Contracts

| Test File | Requirement | What to Pin |
|-----------|-------------|-------------|
| `frontend/src/components/builder/__tests__/ChatPanel.test.tsx` | AI-01 | Staging: reject-all leaves `layers` byte-equal to pre-prompt snapshot; accept-one dispatches exactly one action |
| `frontend/src/components/builder/__tests__/ChatPanel.test.tsx` | AI-02 | With `isAIAvailable=false` + reason `env_disabled`: disabled-state renders `rail.aiDisabledTitle`, no compose area, no console error |
| `frontend/src/components/builder/__tests__/ChatPanel.test.tsx` | AI-02 | With `isAIAvailable=false` + reason `permission`: disabled-state renders `rail.aiPermissionTitle`, no settings CTA button |
| `frontend/src/components/builder/__tests__/ChatPanel.test.tsx` | AI-03 | 503 response: error banner renders with `bannerUnavailableTitle` and Retry button; Retry re-fires last user message |
| `frontend/src/components/builder/__tests__/ChatPanel.test.tsx` | AI-03 | 403 response: error banner renders with `bannerForbiddenTitle` and Dismiss button, no Retry |
| `frontend/src/components/builder/__tests__/ChatPanel.test.tsx` | AI-09 | Staging tray renders for `add_layer` + `remove_layer` actions; chip text matches `chip{Add,Remove}` format; tray absent for `set_style` actions |
| `frontend/src/components/builder/__tests__/chat-suggestions.test.ts` | AI-05 | With `viewport.zoom >= 12` + vector layer: `nearbyFeatures` suggestion appears; with `selectedLayerName` set: layer-specific suggestion leads |
| `frontend/src/builder/ai/__tests__/chat-action-staging.test.ts` | AI-01 | `rejectAll()` returns `pendingActions.length === 0`; `acceptAll()` calls `dispatchLayerAction` N times in order |

---

## Layout Invariants Inherited from 1134-UI-SPEC (unchanged)

These are locked by 1134-UI-SPEC and must not be touched by Phase 1135:

| Invariant | Contract |
|-----------|----------|
| INV-01 | NavigationControl stays `top-left`. |
| INV-02 | MapCoordReadout `top-2 right-14`. |
| INV-03 | Every `<SheetContent>` in builder canvas uses `showCloseButton={false}`. |

Phase 1135 does not introduce new `<SheetContent>` instances (AI chat is in the `<aside>` panel, not a Sheet).

---

## Registry Safety

No new shadcn blocks or third-party registries introduced in this phase.

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn official | Button, existing primitives | not required — no new blocks |
| Third-party | none | not applicable |

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS
- [ ] Dimension 2 Visuals: PASS
- [ ] Dimension 3 Color: PASS
- [ ] Dimension 4 Typography: PASS
- [ ] Dimension 5 Spacing: PASS
- [ ] Dimension 6 Registry Safety: PASS

**Approval:** pending

---

## Pre-Populated From

| Source | Decisions Used |
|--------|---------------|
| 1135-CONTEXT.md | 6 (Shape B lock, module shape, wiring point, PendingAction union, Pitfall #4 gating, disabled-state reason taxonomy) |
| 1134-UI-SPEC.md | 8 (design system, spacing scale, typography table, color table + accent reserved-for, layout invariants INV-01..03, notes dot precedent, SheetContent invariant) |
| 1133-BUILDER-WALKTHROUGH-AUDIT.md | 4 (AI consumer-gating matrix, disabled-state existing impl lines 170-181, ChatPanel error bubble pattern, `mapApiErrorToMessage` 403/503 distinction) |
| REQUIREMENTS.md | 7 (AI-01..05, AI-08, AI-09 descriptions and success criteria) |
| frontend/src/components/builder/ChatPanel.tsx | 9 (existing chip shape, error bubble shape, message bubble shape, `role:error` pattern, `handleRetry` pattern, `inflightRef` pattern, `role="log"` on message area, `getSmartSuggestions` call, compose area layout) |
| frontend/src/components/builder/chat-suggestions.ts | 2 (function signature, 4-chip limit, geometry dispatch logic) |
| frontend/src/components/builder/BuilderRail.tsx | 3 (disabled-state container lines 170-181, ChatPanel lazy mount lines 183-198, `aiAvailable` prop name) |
| frontend/src/hooks/use-ai-availability.ts | 2 (return shape, `isAIAvailable` composite gate) |
| frontend/src/index.css | 5 (all color tokens used, `--destructive` for error, `--warning` not used, motion tokens) |
| User input | 0 (discuss phase skipped; all decisions from upstream artifacts) |
