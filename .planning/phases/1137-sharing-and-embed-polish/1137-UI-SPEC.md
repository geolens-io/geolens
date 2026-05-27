---
phase: 1137
slug: sharing-and-embed-polish
status: draft
shadcn_initialized: true
preset: not applicable (existing project — components.json present)
created: 2026-05-27
---

# Phase 1137 — UI Design Contract

> Visual and interaction contract for Phase 1137: Sharing and Embed Polish.
> This phase introduces 5 new surfaces inside `SharePanel` / `ShareDialog` and `ViewerMap`.
> No new design tokens, no new component variants, no new typographic decisions.
> No new shadcn blocks. All design decisions derive from existing tokens in
> `frontend/src/index.css`, the shadcn Input + Badge + Select primitives already present,
> and the 1134-/1135-/1136-UI-SPEC precedent chain.

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

Standard 8-point scale in use project-wide. No new spacing values introduced in this phase.

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | Icon gaps, chip internal padding |
| sm | 8px | Chip gap, input row gap, field spacing |
| md | 16px | Dialog section padding, field label margin |
| lg | 24px | Not used in new surfaces |
| xl | 32px | Not used in new surfaces |
| 2xl | 48px | Not used in new surfaces |
| 3xl | 64px | Not used in new surfaces |

**Exceptions for this phase: none.** Every Tailwind value in new code MUST be a multiple of 4
(`px-2`, `px-3`, `px-4`, `py-1`, `py-2`, `gap-2`, `gap-4`). Prohibited: `*-0.5`, `*-1.5`,
`*-2.5`, `mt-0.5`, `space-y-1.5`.

The existing `ShareDialog` has several `space-y-1.5` and `py-2.5` instances from prior work.
These are **pre-existing** and must not be changed by Phase 1137 (they are outside the new
surface boundaries). New code written in Phase 1137 must follow the strict grid rule.

---

## Typography

No new sizes or weights introduced in this phase. All type from the existing scale.
Inherited from 1136-UI-SPEC verbatim.

| Role | Size | Weight | Line Height | Usage |
|------|------|--------|-------------|-------|
| Body / label | 14px (`text-sm`) | 400 | 1.43 | Expiration label, chip text, iframe pane header |
| Micro / caption | 12px (`text-xs`) | 400 | 1.33 | Chip input hint, iframe loading/error copy, branding footer |
| Section cap label | 10px (`text-[10px]`) | 600 | implicit | Not used in new surfaces |
| Muted hint | 12px (`text-xs`) | 400 | 1.33 | Origin input placeholder, iframe error body |

**Rule:** No new `text-*` class beyond this set is introduced in this phase.

---

## Color

All tokens from `frontend/src/index.css`. No new tokens.

| Role | Token | Value (light mode) | Usage |
|------|-------|--------------------|-------|
| Dominant (60%) | `--background` | `oklch(0.985 0.003 85)` | Dialog bg, iframe pane bg, chip bg |
| Secondary (30%) | `--muted` / `--card` | `oklch(0.97 0.003 85)` | Chip pill background, iframe container bg |
| Accent (10%) | `--primary` | `oklch(0.55 0.18 250)` | See reserved-for list below |
| Destructive | `--destructive` | `oklch(0.577 0.245 27.325)` | Chip remove X (hover state only) |
| Muted foreground | `--muted-foreground` | `oklch(0.45 0.005 250)` | Branding footer text, chip hint, iframe status text |

**Accent (`--primary` OKLCH blue) reserved for (exhaustive list, this phase):**

1. Chip input focus ring (`--ring` = `oklch(0.55 0.18 250)`) — inherited from `Input` component
2. Expiration preset Select trigger focus ring — inherited from `Select` component
3. Chip remove X hover background (`hover:bg-primary/10`) — only on focus/hover, not at rest

**Accent NOT used for:** chip pill background at rest (use `bg-muted`), chip text (use `text-foreground`), branding footer text (use `text-muted-foreground`), iframe pane border (use `border-border`).

---

## Surface 1: Allowed-Origins Chip Input (SHARE-02 / SHARE-06)

Replaces the existing comma-separated `Input` field in `ShareLinkSettings` with a chip-based
origin list. The comma-separated input is the ENTRY mechanism; chips are the DISPLAY mechanism
after save.

### Layout

The chip input block replaces the current `domainsValue` Input field inside the
`showDomainRestrict` branch of `ShareLinkSettings`. The outer `space-y-1.5` wrapper is
replaced by a `space-y-2` wrapper for this new block (strict-grid compliant).

```
┌──────────────────────────────────────────────────┐
│ [ https://example.com ×]  [ https://other.io ×]  │  ← chip list (chips = saved state)
│ ┌─────────────────────────────────────────┐ [+] │
│ │ Paste a URL like https://example.com    │     │
│ └─────────────────────────────────────────┘     │  ← text input for new entry
│ Press Enter or comma to add. Origins are         │
│ normalized before saving.                        │  ← hint text
└──────────────────────────────────────────────────┘
```

When `allowedOrigins` is empty and no input text:
```
┌──────────────────────────────────────────────────┐
│  ← empty chip area (no chips shown)              │
│ ┌─────────────────────────────────────────┐ [+] │
│ │ Paste a URL like https://example.com    │     │
│ └─────────────────────────────────────────┘     │
│ No origins yet — paste a URL like                │
│ https://example.com to allow embedding.          │  ← empty-state hint (solution path)
└──────────────────────────────────────────────────┘
```

### Chip Shape

Each chip is a `Badge` variant `outline` plus a remove button. Uses shadcn `Badge` with
`className` override — no new variant.

| Property | Value | Rationale |
|----------|-------|-----------|
| Container | `inline-flex items-center gap-1 rounded-full border border-border bg-muted px-3 py-1 text-xs` | On-grid (12px / 4px). Matches Phase 1135 chip precedent (`px-3 py-1`) |
| Text | `text-xs text-foreground font-mono truncate max-w-[16rem]` | Monospace for URLs; truncate at 16rem (256px) with `title` attribute showing full URL |
| Remove button | `Button size="icon-xs" variant="ghost" className="h-4 w-4 rounded-full -mr-1 hover:bg-destructive/10 hover:text-destructive"` | `-mr-1` is NOT a spacing-scale deviation — it is an overlap adjustment inside the chip's own padding boundary to tighten the pill; the chip `px-3` absorbs it |
| Remove icon | Lucide `X`, `h-3 w-3` | Standard close icon at smallest size |
| Remove aria-label | `t('share.removeOrigin', { origin })` → `"Remove {origin}"` | Per-chip accessible label |

**Note on `-mr-1`:** The `-mr-1` on the remove button is an overlap-within-chip adjustment,
not a new spacing token. The chip pill's `px-3` provides 12px right padding; `-mr-1` (−4px)
positions the X tighter within that padding. This is structurally equivalent to the badge
component's own `[&>svg]:-mr-1` convention for trailing icon trim.

### Input Field

The text input for adding origins:

| Property | Value |
|----------|-------|
| Element | shadcn `Input` with `className="h-8 text-sm font-mono flex-1"` |
| Placeholder | `"Paste a URL like https://example.com"` |
| Submit triggers | Enter key OR comma character in value (strip trailing comma) |
| Add button | Lucide `Plus` icon only, `Button size="icon" variant="outline" className="h-8 w-8 shrink-0"` |
| Add button aria | `t('share.addOrigin')` → `"Add origin"` |

### Normalization Contract (SHARE-06)

Normalization runs on submit (Enter / comma / Add button). Must be implemented in
`frontend/src/lib/builder/url-normalize.ts` (new helper) or extended from existing
`parseOrigins` in `SharePanel.tsx:24-31`.

Canonical form rules:
1. Add `https://` scheme if missing (no scheme → `https://`)
2. Lowercase scheme + host
3. Strip trailing slash from path
4. Preserve port if explicitly provided (`:3000`, `:8080`)
5. Deduplicate: if canonical form already exists in chip list, silently discard

**Examples:**
- `Example.com` → `https://example.com`
- `https://Example.com/` → `https://example.com`
- `http://localhost:3000/` → `http://localhost:3000`
- `https://example.com` (duplicate) → silently discarded

### Interaction Contract

- **Add:** User types URL, presses Enter or comma. Input clears. Chip appears immediately
  (optimistic UI). PATCH `allowed_origins` fires with the new full list.
- **Remove:** User clicks X on chip. Chip disappears immediately (optimistic UI). PATCH fires
  with updated list (chip removed).
- **PATCH error:** Toast `t('share.updateFailed')` (existing key). Chip re-appears (add
  rollback) or origin re-added (remove rollback).
- **Save button:** Removed from this block — each add/remove is a live PATCH. No "Save"
  button for origins.
- **CSP contract:** Backend must validate that no origin in the PATCH body is `*`. Frontend
  normalizer must also reject `*` with an inline error: `"Wildcard origin not allowed"` shown
  as a `text-xs text-destructive` message below the input.

### Accessibility

- Chip list: `role="list"` container, each chip: `role="listitem"`.
- Input: `aria-label={t('share.originsInputLabel')}` → `"Allowed origin URL"`.
- Input hint: `id="origins-hint"`, referenced by `aria-describedby="origins-hint"` on input.
- Remove button: `aria-label` includes the origin URL (see chip shape table above).

---

## Surface 2: Expiration Presets Select (SHARE-04)

Replaces (or augments) the free-text `<input type="date">` in `ShareLinkSettings` with a
`Select` offering 5 presets. The existing `DatePicker` (date input) is retained as the
"Custom" affordance revealed when the user picks "Custom" from the Select.

### Layout

The expiration block in `ShareLinkSettings` (currently a single row: date input + Save button)
becomes a two-row block:

```
Row 1:  [Select: "1 week"  ↓]        ← preset Select (full-width)
Row 2 (conditional on "Custom"):
        [Date input field    ] [Save] ← existing DatePicker + Save button
```

| Property | Value |
|----------|-------|
| Select trigger | `SelectTrigger size="sm" className="w-full h-8"` |
| Select default value | `"never"` (maps to `expiresAt: null`) |
| Preset options | See table below |
| Custom option label | `"Custom date…"` |
| Custom reveals | Existing `<Input type="date">` + Save button, visible only when `preset === 'custom'` |

### Preset Values

| Option label | `value` | `expiresAt` computation | i18n key |
|---|---|---|---|
| "Never" | `"never"` | `null` (no expiration) | `share.expirationNever` |
| "1 day" | `"1d"` | `now + 1 day` at `T23:59:59Z` | `share.expiration1Day` |
| "7 days" | `"7d"` | `now + 7 days` at `T23:59:59Z` | `share.expiration7Days` |
| "30 days" | `"30d"` | `now + 30 days` at `T23:59:59Z` | `share.expiration30Days` |
| "1 year" | `"1y"` | `now + 365 days` at `T23:59:59Z` | `share.expiration1Year` |
| "Custom date…" | `"custom"` | reveals DatePicker; user sets explicit date | `share.expirationCustom` |

### Preset Selection Interaction

- On Select change (non-Custom): immediately call `handleSaveExpiration` with the computed
  `expiresAt`. No extra "Save" button needed for presets — selection is a direct save.
- On Select change to `"custom"`: reveal the existing `<Input type="date">` and Save button.
  Do NOT auto-save; wait for explicit Save click (preserving existing `handleSaveExpiration`
  path).
- The Select shows the CURRENT expiration as a pre-selected value on dialog open:
  - If `shareExpires` is null → select `"never"`.
  - If `shareExpires` is a future date → compute which preset bucket it falls into; if it
    matches a preset window (±1 day tolerance), select that preset; otherwise select
    `"custom"` and pre-populate the DatePicker.
- `rawShareToken` survival (Pitfall #6): the preset Select does NOT touch `rawShareToken` or
  `embedTokenRaw` state. Expiration is updated on the share token only (via `updateShareToken`
  mutation). The docstring on `handleSaveExpiration` must assert: "Does not modify rawShareToken
  or embedTokenRaw — those survive independently per Pitfall #6 contract."

### Position Relative to Existing Fields

Inside `ShareLinkSettings` > `showSettings` accordion:
1. **Expiration** block (Select + optional DatePicker) — first
2. **Domain restriction** block (chip input, from Surface 1) — second
3. **Revoke** block — third (unchanged)

---

## Surface 3: "Powered by GeoLens" Branding (SHARE-07)

Two separate surfaces: (A) the shared/embed viewer overlay, and (B) the export PNG footer.
The export PNG footer is **already implemented** in `use-builder-save.ts:568-638` — it reads
`isEnterprise` from `useEdition()` and shows/suppresses branding correctly. Phase 1137 must
verify this path is live (SHARE-09 audit) and add `useEdition()` to `ViewerMap.tsx` for the
viewer/embed overlay.

### (A) Viewer / Embed Overlay (new surface)

The branding overlay is a small fixed text element anchored to the bottom-left of `ViewerMap`.
It renders inside the `ViewerMap` component's return JSX, below `<MapGL>` and siblings.

```
┌────────────────────────────────────────────────────────┐
│                                                        │
│  [MapLibre map canvas]                                 │
│                                                        │
│                                                        │
│  Powered by GeoLens                    [scale] [attr]  │
└────────────────────────────────────────────────────────┘
    ↑ bottom-left, above ScaleControl
```

| Property | Value | Rationale |
|----------|-------|-----------|
| Position | `absolute bottom-8 left-2 z-10` | `bottom-8` (32px from bottom) clears the MapLibre ScaleControl at `bottom-left` which occupies ~24px. `left-2` = 8px from left. `z-10` to float above the map canvas |
| Text | `"Powered by GeoLens"` | Same copy already used in export PNG (`t('export.poweredBy')`) — reuse key |
| Typography | `text-xs text-muted-foreground` | 12px / 400 weight / `oklch(0.45 0.005 250)`. Subdued — does not compete with map content |
| Background | `bg-background/70 rounded px-2 py-1` | Semi-transparent paper white, 8px h-padding, 4px v-padding; on-grid |
| Visibility | Only when `!isEnterprise` (from `useEdition().isEnterprise`) | Suppressed under enterprise edition |
| Suppression mechanism | `{!isEnterprise && <span>...</span>}` inside ViewerMap return JSX | Never renders the DOM node when enterprise |

**`useEdition()` integration in ViewerMap:** Add `const { isEnterprise } = useEdition()` inside
`ViewerMap`. The hook reads from `frontend/src/hooks/use-edition.ts` which fetches
`/api/edition/info` (TanStack Query, staleTime configured). ViewerMap has its own TanStack
Query context (viewer page mounts QueryClientProvider), so the query fires normally.

**Regression pin required:** `ViewerMap.branding.test.tsx` — with `useEdition` mocked to
`isEnterprise: false`, branding text renders; with `isEnterprise: true`, branding text absent.

### (B) Export PNG Footer (existing — verify only)

The export PNG footer at `use-builder-save.ts:568-638` already:
- Checks `showBranding = !isEnterprise` (line 568)
- Renders `t('export.poweredBy', { defaultValue: 'Powered by GeoLens' })` at bottom-right of
  the offscreen canvas (line 632-637)
- Uses `ctx.fillStyle = '#999999'` and 12px font (equivalent to `text-xs text-muted-foreground`)

Phase 1137 must verify this path is exercised by SHARE-09 success criteria (title + legend +
branding all render in the exported PNG). No code change to the export path itself unless the
SHARE-09 audit finds a gap.

**i18n key to add:** `export.poweredBy` with value `"Powered by GeoLens"` in en/de/es/fr if
not already present. (The existing `defaultValue: 'Powered by GeoLens'` in `use-builder-save.ts`
suggests the key may not yet be in the i18n files — verify and add.)

---

## Surface 4: Legend + Title in Shared / Embed / Export (SHARE-09)

The legend and title in the **export PNG** are already implemented in `use-builder-save.ts:534-665`.
Phase 1137's SHARE-09 work is:

1. **Export PNG — verify live:** Confirm that `handleExportPNG` renders title block (if name
   present), map canvas, legend block (if `legendLayers.length > 0`), and branding footer (if
   `!isEnterprise`) in the correct stacked order. Pin a vitest in `use-builder-save.test.ts`
   that asserts these sections compose correctly.

2. **Shared / embed view — legend overlay:** The shared viewer (`/m/{shareToken}`) and embed
   view do NOT currently render a legend overlay. SHARE-09 adds an optional `MapLegend` overlay
   to the viewer page. The overlay is a floating panel, NOT drawn on the canvas (unlike the
   export PNG which composites onto an offscreen canvas).

### MapLegend Overlay in Viewer (new)

The viewer page already has a `?legend=true|false` URL parameter documented in `SharePanel.tsx:769`.
Phase 1137 makes this parameter functional: when `legend=true` (the default for shared/embed
links), a `MapLegend` overlay renders inside the viewer.

| Property | Value |
|----------|-------|
| Default behavior | `legend=true` (shown unless explicitly `legend=false`) |
| Overlay position | `absolute bottom-8 left-2 z-10` (above ScaleControl, below branding) |
| Container | `rounded-lg border border-border bg-background/90 px-3 py-2 space-y-1 max-w-[200px]` |
| Header | `text-xs font-semibold text-foreground uppercase tracking-wide` — "Legend" |
| Legend row | `flex items-center gap-2` — color swatch + `text-xs text-foreground truncate` |
| Color swatch | `h-3 w-3 rounded-sm shrink-0` with `style={{ backgroundColor: layerColor }}` |
| Swatch size | 12px × 12px (`h-3 w-3`) — on-grid (12 = 3 × 4px) |
| Max rows before scroll | 8 rows; after 8 the container gets `max-h-48 overflow-y-auto` |
| Visibility | Only layers where `visible === true && show_in_legend !== false` |
| Map title | Rendered above the map as a `<h1>` or prominent text block; see below |

### Map Title in Viewer (new)

When the viewer URL has `title=true` (default for shared/embed), the map title renders as a
header above the map content.

| Property | Value |
|----------|-------|
| Default behavior | `title=true` (shown unless explicitly `title=false`) |
| Position | Static block above the `ViewerMap` container (not floating) |
| Container | `px-4 py-2 border-b border-border bg-background` |
| Title text | `text-base font-semibold text-foreground` (16px / 600 weight) |
| Description text | `text-sm text-muted-foreground` (14px / 400 weight) |
| Visibility | Only rendered when `map.name` is non-empty AND `?title=true` |

**Note:** The title and legend URL params are already documented in the embed code UI
(`SharePanel.tsx:768-770`) — Phase 1137 makes them functional in the viewer route.

---

## Surface 5: Embed Preview Iframe Pane (SHARE-03)

Per Phase 1133 WALK-05 audit ruling: **KEEP SHARE-03 in v1030**. The `sandbox="allow-scripts"` contract is fully preserved. The pane is a collapsible section inside `ShareDialog` — shown only when both `hasShareToken` AND `rawShareToken` are available (same gate as the embed code textarea currently).

### Layout

The iframe pane renders below the embed code textarea, replacing or extending the existing embed code section.

```
┌─────────────────────────────────────────────────┐
│  [Code icon]  Embed Code              ← header   │
│  ┌──────────────────────────────────────────┐   │
│  │ <iframe src="..." sandbox="allow-scripts" │   │
│  │  style="border:none;"></iframe>          │   │
│  │                                   [Copy] │   │
│  └──────────────────────────────────────────┘   │
│  ──────────────────────────────────────────      │
│  [Preview ▼] (collapsible)                       │
│  ┌─────────────────────────────────────────┐    │
│  │  [iframe src=live-embed-url             │    │
│  │   sandbox="allow-scripts"               │    │
│  │   width="100%"                          │    │
│  │   height="300"]                         │    │
│  │                                         │    │
│  │   [loading state / error state here]    │    │
│  └─────────────────────────────────────────┘    │
│  ⚠ sandbox="allow-scripts" only (SEC-07)         │
└─────────────────────────────────────────────────┘
```

### Iframe Pane Shape

| Property | Value | Rationale |
|----------|-------|-----------|
| Container | `rounded-lg border border-border overflow-hidden` | Matches `ShareDialog` card style |
| Iframe width | 100% of container | Fills the dialog max-width (`sm:max-w-md` = ~448px) |
| Iframe height | `300px` (`h-[300px]`) | Fixed height; 300 is divisible by 4; shows enough map to be useful |
| `src` | `/m/{shareToken}?embed=true&et={embedTokenRaw}` | Mirrors the embed snippet exactly |
| `sandbox` | `"allow-scripts"` | SEC-07 / M-70 contract. No `allow-same-origin` |
| `loading` | `"lazy"` | Defer iframe load until pane is expanded |
| `title` | `t('share.iframePreviewTitle')` → `"Map embed preview"` | Accessibility: `<iframe>` must have `title` |
| Border | `style={{ border: 'none' }}` | Matches the embed snippet output |
| Pane visibility | Collapsed by default; toggle via "Preview" disclosure button | Avoids auto-loading iframe on dialog open |
| Toggle button | `text-xs font-medium text-muted-foreground hover:text-foreground flex items-center gap-1` with Lucide `ChevronRight` rotating to `rotate-90` when expanded | Matches `ShareLinkSettings` toggle style for consistency |

### Loading State

While the iframe is loading (`onLoad` not yet fired):

| Property | Value |
|----------|-------|
| Container | `h-[300px] bg-muted flex items-center justify-center` |
| Content | Lucide `Loader2 className="h-5 w-5 animate-spin text-muted-foreground"` |
| Transition | Swap `animate-pulse bg-muted` placeholder for the real iframe on `onLoad` |

Implementation: render iframe with `opacity-0` + `h-0` until `onLoad`, then swap to
`opacity-100 h-[300px]` via `transition-opacity`. The loading placeholder is shown
simultaneously at `h-[300px]` until the iframe fires `onLoad`.

### Error State

If the iframe fires `onError` or the `src` resolves to a non-200:

| Property | Value |
|----------|-------|
| Container | `h-[300px] bg-muted flex flex-col items-center justify-center gap-2 px-4` |
| Icon | Lucide `AlertCircle className="h-5 w-5 text-muted-foreground"` |
| Primary text | `text-sm text-muted-foreground text-center` — `"Preview unavailable"` |
| Secondary text | `text-xs text-muted-foreground/80 text-center` — `"Check that the embed token is valid and the share link is active. Reload to retry."` (problem + solution path) |
| Retry | Inline link `text-xs text-primary underline` — `"Reload"` — increments a `key` prop on the iframe to force re-mount |

**Note:** Browsers do not reliably fire `onerror` on iframes for HTTP errors (cross-origin
sandbox limitation). The error state MUST also handle the case where the iframe loads but
renders an error page from the viewer. The implementation should rely on a timeout fallback:
if `onLoad` has not fired within 8000ms, show the error state. The timeout fires via
`useEffect` cleanup on unmount.

### Security Indicator

Below the preview container, always render:

```
<div className="flex items-center gap-1 px-3 py-2 text-xs text-muted-foreground">
  <Shield className="h-3 w-3" />
  sandbox="allow-scripts" only — SEC-07 contract
</div>
```

This is a READ-ONLY indicator, not a control. It documents the security contract inline for
any developer inspecting the share dialog. `aria-hidden="true"` on the icon.

### `inflightEmbedCreate` Race Guard (Pitfall #7)

The `inflightEmbedCreate` ref pattern must be added to `ShareDialog` to prevent a race where
two concurrent embed token creation requests overwrite each other:

```typescript
const inflightEmbedCreate = useRef<Promise<EmbedTokenResponse> | null>(null);

async function maybeCreateEmbedToken() {
  if (embedTokenRaw) return;
  if (activeEmbedToken) return;
  // Pitfall #7: deduplicate concurrent calls
  if (inflightEmbedCreate.current) {
    await inflightEmbedCreate.current;
    return;
  }
  const promise = createEmbedToken.mutateAsync({ ... });
  inflightEmbedCreate.current = promise;
  try {
    const tokenResult = await promise;
    setEmbedTokenRaw(tokenResult.raw_token);
  } finally {
    inflightEmbedCreate.current = null;
  }
}
```

Regression pin: `SharePanel.test.tsx` — two concurrent `maybeCreateEmbedToken()` calls result
in exactly ONE `createEmbedToken.mutateAsync` invocation.

---

## Interaction Contracts Summary

| Surface | Trigger | Response | Timing |
|---------|---------|----------|--------|
| Add origin chip | Enter / comma in input | Chip appears; PATCH fires | Optimistic — synchronous chip render |
| Remove origin chip | X button click | Chip removed; PATCH fires | Optimistic — synchronous chip remove |
| Expiration preset select | Select onChange (non-Custom) | PATCH fires; Select shows new value | Synchronous — no spinner shown |
| Expiration "Custom" select | Select onChange to custom | DatePicker + Save button appear | Synchronous reveal |
| Branding overlay | Page load (viewer/embed) | Static text; appears/disappears based on edition | No animation — static suppression |
| Preview pane toggle | Button click | Iframe pane expands; iframe begins loading | `motion-fast` (150ms) expand; no iframe load until expanded |
| Iframe onLoad | Iframe fires load event | Loading spinner replaced by live preview | Synchronous swap |
| Iframe error / timeout | 8000ms timeout or onError | Error state shown with Reload link | Synchronous swap on timeout |
| Reload iframe | "Reload" link click | `key` prop incremented → iframe re-mounts | Synchronous |

---

## Copywriting Contract

### Primary CTA

| Action | Label |
|--------|-------|
| Save expiration preset | Automatic (no button for presets; DatePicker path: "Save") |
| Add origin chip | `"Add origin"` (icon button aria-label) |

### Empty State

| Element | Copy | i18n Key |
|---------|------|----------|
| Origins empty hint | `"No origins yet — paste a URL like https://example.com to allow embedding."` | `share.originsEmptyHint` |
| Origins empty (secondary) | `"Each origin is normalized to scheme + host + port before saving."` | `share.originsNormHint` |
| Iframe loading | (spinner only — no text) | — |

### Error States (problem + solution path)

| Element | Copy | i18n Key |
|---------|------|----------|
| Iframe preview error primary | `"Preview unavailable"` | `share.iframeErrorTitle` |
| Iframe preview error secondary | `"Check that the embed token is valid and the share link is active. Reload to retry."` | `share.iframeErrorBody` |
| Iframe reload action | `"Reload"` | `share.iframeReload` |
| Origin wildcard rejected | `"Wildcard origin not allowed"` | `share.originWildcardError` |
| PATCH failed toast | Existing `t('share.updateFailed')` | pre-existing key |

### Destructive Actions

| Action | Confirmation approach |
|--------|----------------------|
| Remove origin chip | Immediate — no modal. The X is an explicit remove affordance; origin removal does not destroy data (it can be re-added). |
| Revoke share link | Pre-existing confirmation pattern in `ShareLinkSettings` — not changed in Phase 1137. |

### New i18n Keys Required

| Key | Default (en) |
|-----|-------------|
| `share.originsEmptyHint` | `"No origins yet — paste a URL like https://example.com to allow embedding."` |
| `share.originsNormHint` | `"Each origin is normalized to scheme + host + port before saving."` |
| `share.removeOrigin` | `"Remove {origin}"` (interpolated) |
| `share.addOrigin` | `"Add origin"` |
| `share.originsInputLabel` | `"Allowed origin URL"` |
| `share.expirationNever` | `"Never"` |
| `share.expiration1Day` | `"1 day"` |
| `share.expiration7Days` | `"7 days"` |
| `share.expiration30Days` | `"30 days"` |
| `share.expiration1Year` | `"1 year"` |
| `share.expirationCustom` | `"Custom date…"` |
| `share.iframePreviewTitle` | `"Map embed preview"` |
| `share.iframePreviewToggle` | `"Preview"` |
| `share.iframeErrorTitle` | `"Preview unavailable"` |
| `share.iframeErrorBody` | `"Check that the embed token is valid and the share link is active. Reload to retry."` |
| `share.iframeReload` | `"Reload"` |
| `share.iframeSandboxNote` | `"sandbox=\"allow-scripts\" only — SEC-07 contract"` |
| `share.originWildcardError` | `"Wildcard origin not allowed"` |
| `export.poweredBy` | `"Powered by GeoLens"` |

Required in: en, de, es, fr (i18n parity — same 4-language requirement as all builder strings).

---

## Component Inventory

New and modified components in this phase.

| Component | File | Type | Modification |
|-----------|------|------|-------------|
| `ShareDialog` / `ShareLinkSettings` | `frontend/src/components/builder/SharePanel.tsx` | Modify | Add chip input for origins (Surface 1); add expiration preset Select (Surface 2); add iframe preview pane (Surface 5); add `inflightEmbedCreate` ref (Pitfall #7) |
| `url-normalize.ts` | `frontend/src/lib/builder/url-normalize.ts` | NEW | Origin canonical-form normalization helper (scheme/host/port/slash strip/dedupe) |
| `ViewerMap` | `frontend/src/components/viewer/ViewerMap.tsx` | Modify | Add `useEdition()` + conditional branding overlay (Surface 3A); add `?legend=true` MapLegend overlay (Surface 4); add `?title=true` map title block (Surface 4) |

Components that are **read-only** in this phase (verified, not modified):
- `use-builder-save.ts` — export PNG title/legend/branding already implemented; verified only.
- `badge.tsx` — API is correct for chip pattern (use with className override, no new variant).
- `select.tsx` — API correct for expiration presets; `SelectTrigger size="sm"` available.
- `input.tsx` — API correct for origin input field.

---

## Layout Invariants Inherited (unchanged)

These are locked by 1134-UI-SPEC and must not be touched by Phase 1137:

| Invariant | Contract |
|-----------|----------|
| INV-01 | NavigationControl stays `top-left` in BuilderMap. |
| INV-02 | MapCoordReadout `top-2 right-14`. |
| INV-03 | Every `<SheetContent>` in builder canvas uses `showCloseButton={false}`. |

Phase 1137 does not introduce new `<SheetContent>` instances (share dialog is a Radix `Dialog`,
not a `Sheet`).

**ViewerMap layout note:** The branding overlay (`absolute bottom-8 left-2`) and the
MapLegend overlay (`absolute bottom-8 left-2`) share the same anchor. When both are present,
the legend sits at `bottom-8 left-2` and the branding sits at `bottom-2 left-2` (below the
legend). The legend occupies variable height based on layer count; the branding must always be
the lowest element. Implementation: render branding at `absolute bottom-2 left-2` and legend at
`absolute bottom-8 left-2` with `style={{ bottom: brandingHeight + 8 + 'px' }}` computed
dynamically — OR use a `flex-col` vertical stack with `absolute bottom-2 left-2` on the
container.

**Preferred approach:** Wrap both in a single `absolute bottom-2 left-2 flex flex-col-reverse gap-2` container so stacking order is automatic and neither element requires hardcoded pixel math.

---

## Regression Test Contracts

Named test files the executor MUST create or extend.

| Test File | Requirement | What to Pin |
|-----------|-------------|-------------|
| `frontend/src/components/builder/__tests__/SharePanel.test.tsx` | SHARE-02 | Chip input: adding URL → chip appears; removing chip → list updates; duplicate origin silently discarded; wildcard `*` origin shows inline error |
| `frontend/src/components/builder/__tests__/SharePanel.test.tsx` | SHARE-06 | Normalization: `Example.com` → `https://example.com`; `https://Example.com/` → `https://example.com`; `http://localhost:3000/` → `http://localhost:3000` |
| `frontend/src/components/builder/__tests__/SharePanel.test.tsx` | SHARE-04 | Expiration Select: selecting "7 days" fires `updateShareToken.mutateAsync` with computed date; selecting "Custom" reveals DatePicker; selecting "Never" sets `expiresAt: null` |
| `frontend/src/components/builder/__tests__/SharePanel.test.tsx` | Pitfall #7 | Two concurrent `maybeCreateEmbedToken()` calls invoke `createEmbedToken.mutateAsync` exactly once |
| `frontend/src/components/builder/__tests__/SharePanel.test.tsx` | SHARE-03 | Iframe pane: collapsed by default; toggle reveals iframe; `sandbox` attr = `"allow-scripts"` only (no `allow-same-origin`); `title` attr = `"Map embed preview"` |
| `frontend/src/lib/builder/__tests__/url-normalize.test.ts` | SHARE-06 | Unit tests covering all 5 normalization rules: scheme-add, lowercase, trailing-slash strip, port preserve, dedupe |
| `frontend/src/components/viewer/__tests__/ViewerMap.branding.test.tsx` | SHARE-07 | `isEnterprise: false` → branding text renders; `isEnterprise: true` → branding text absent |
| `frontend/src/components/builder/__tests__/use-builder-save.test.ts` | SHARE-09 | `handleExportPNG` composites title block + map canvas + legend block + branding footer in correct vertical order; branding absent when `isEnterprise: true` |

---

## Registry Safety

No new shadcn blocks or third-party registries introduced in this phase.

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn official | Input, Badge, Select, Button — all pre-existing | not required — no new blocks |
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
| 1137-CONTEXT.md | 7 (SHARE-03 KEEP ruling, rawShareToken Pitfall #6, inflightEmbedCreate Pitfall #7, origin normalization Pitfall #8, CSP frame-ancestors never-star, useEdition() integration paths, chip+Select+iframe primitive selection) |
| 1133-BUILDER-WALKTHROUGH-AUDIT.md | 4 (SHARE-03 sandbox feasibility verdict, SHARE-08 DEFER verdict, todo.md L151 SHARE-07+SHARE-09 routing, SEC-07/M-70 sandbox comment at SharePanel.tsx:36-46) |
| REQUIREMENTS.md | 6 (SHARE-02/03/04/06/07/09 descriptions and success criteria) |
| 1135-UI-SPEC.md | 3 (chip precedent px-3 py-1, motion-fast timing, spacing strict-grid rule from precedent chain) |
| 1136-UI-SPEC.md | 2 (strict spacing rule, prohibited micro-nudge list) |
| frontend/src/components/builder/SharePanel.tsx | 8 (existing VISIBILITY_OPTIONS shape, ShareLinkSettings layout, handleSaveExpiration/handleSaveDomains patterns, embed code textarea block, rawShareToken/persistedShareTokenHint separation, configDomains display, resolvedEmbedTokenId gate, parseOrigins existing helper) |
| frontend/src/components/builder/hooks/use-builder-save.ts | 4 (handleExportPNG compositing already implemented, isEnterprise check live at line 568, export.poweredBy i18n key, doCapture canvas pattern) |
| frontend/src/components/viewer/ViewerMap.tsx | 3 (no existing branding/edition code — new surface; ScaleControl at bottom-left position; NavigationControl at top-right in viewer context) |
| frontend/src/index.css | 4 (color tokens, muted-foreground for branding, motion tokens, border token for pane border) |
| frontend/src/components/ui/badge.tsx | 1 (outline variant API, className override pattern for chip) |
| frontend/src/components/ui/select.tsx | 1 (SelectTrigger size="sm" API) |
| User input | 0 (discuss phase skipped; all decisions from upstream artifacts) |
