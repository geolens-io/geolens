---
phase: 260515-mmo
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/lib/representative-fraction.ts
  - frontend/src/lib/__tests__/representative-fraction.test.ts
  - frontend/src/components/map/MapCoordReadout.tsx
  - frontend/src/components/map/__tests__/MapCoordReadout.test.tsx
  - frontend/src/components/builder/BuilderMap.tsx
  - frontend/src/i18n/locales/en/common.json
  - frontend/src/i18n/locales/de/common.json
  - frontend/src/i18n/locales/es/common.json
  - frontend/src/i18n/locales/fr/common.json
autonomous: false
requirements:
  - SP-12
user_setup: []

must_haves:
  truths:
    - "Builder map's top-right pill shows four segments: lat° N · lng° E · z 5.2 · 1:288k"
    - "Viewer map's top-right pill stays at three segments (no 1:N segment), unchanged from current"
    - "The 1:N segment uses the same lat as the lat/lng segment (mouse position when hovering canvas, viewport center otherwise) — derived from existing coords.lat state, no new event subscription"
    - "Zooming the builder map changes the 1:N value; panning at constant zoom also changes it (cos-lat varies with latitude)"
    - "Formatter outputs: <1000 plain int; <1M with one-decimal lowercase 'k' (with trailing .0 dropped only when implementation chooses — test locks the rule); >=1M with one-decimal uppercase 'M'; clamped at 1 for sub-1 denominators"
    - "The '1:' prefix is muted (text-foreground/50), mirroring the existing 'z' prefix at MapCoordReadout.tsx:102"
    - "Existing MapCoordReadout test (SP-02 move-event coverage) still passes — SP-12 cases are appended, not replaced"
    - "All four locales (en, de, es, fr) have the new common.mapCoordReadout.scale key with the '1:{{value}}' template"
  artifacts:
    - path: "frontend/src/lib/representative-fraction.ts"
      provides: "Pure formatRepresentativeFraction(metersPerPixel, lat, opts?) helper + formatRfValue compact-number helper"
      contains: "export function formatRepresentativeFraction"
    - path: "frontend/src/lib/__tests__/representative-fraction.test.ts"
      provides: "Unit tests for the formatter — boundary cases 850, 999, 1000, 1234, 288000, 999999, 1234567, 120000000"
      contains: "describe('formatRepresentativeFraction"
    - path: "frontend/src/components/map/MapCoordReadout.tsx"
      provides: "Extended pill with optional showScale prop (default false), renders 1:N segment when true"
      contains: "showScale"
    - path: "frontend/src/components/map/__tests__/MapCoordReadout.test.tsx"
      provides: "SP-02 tests (preserved) + new SP-12 describe block with two minimum tests: showScale=true renders, showScale=false (default) does not"
      contains: "SP-12"
    - path: "frontend/src/components/builder/BuilderMap.tsx"
      provides: "Single render-site change at line 890 — pass showScale to MapCoordReadout"
      contains: "showScale"
    - path: "frontend/src/i18n/locales/en/common.json"
      provides: "New mapCoordReadout.scale key with '1:{{value}}' template (parity required across de/es/fr)"
      contains: "mapCoordReadout"
  key_links:
    - from: "frontend/src/components/map/MapCoordReadout.tsx"
      to: "frontend/src/lib/representative-fraction.ts"
      via: "import + call from render body"
      pattern: "from '@/lib/representative-fraction'"
    - from: "frontend/src/components/builder/BuilderMap.tsx"
      to: "frontend/src/components/map/MapCoordReadout.tsx"
      via: "JSX prop pass-through"
      pattern: "showScale"
    - from: "frontend/src/components/viewer/ViewerMap.tsx"
      to: "frontend/src/components/map/MapCoordReadout.tsx"
      via: "default prop fallback — no edit; relies on showScale default of false"
      pattern: "<MapCoordReadout map={mapRef.current} />"
---

<objective>
Add a representative-fraction "1:N" segment to the top-right MapCoordReadout pill, gated to the Builder surface only.

Purpose: Close SP-12 — the last open followup from milestone v1009.1. Desktop-GIS power users in the Builder authoring workflow expect a printable 1:N scale denominator alongside the existing MapLibre scale bar. The smoke check's p-01 finding (`.planning/milestones/v1009.1-phases/1045-builder-smoke-polish/VERIFICATION.md:59-72`) called this out; it was deferred from v1009.1 because it needed a cos-lat factor, a new UI slot, and i18n.

Output:
- `frontend/src/lib/representative-fraction.ts` (pure formatter helper + unit tests in `__tests__/`)
- Extended `MapCoordReadout.tsx` with optional `showScale` prop (default `false`)
- New SP-12 describe block appended to `MapCoordReadout.test.tsx`
- One-line callsite change in `BuilderMap.tsx:890`
- New `common.mapCoordReadout.scale` i18n key in all four locales (en/de/es/fr)
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/260515-mmo-sp-12-representative-fraction-1-n-readou/260515-mmo-CONTEXT.md
@frontend/src/components/map/MapCoordReadout.tsx
@frontend/src/components/map/__tests__/MapCoordReadout.test.tsx
@frontend/src/i18n/locales/en/common.json

<interfaces>
<!-- Contracts the executor needs. Extracted from the codebase. -->

From frontend/src/components/map/MapCoordReadout.tsx (current shape):
```typescript
interface MapCoordReadoutProps {
  map: MaplibreMap | null;
}
// State holds: { lat: number; lng: number; zoom: number } | null
// Renders absolute top-2 right-2 pill with three '·'-separated segments.
// The 'z' prefix at line 102 uses className="text-foreground/50" — mirror this for '1:'.
```

After this plan, the new shape is:
```typescript
interface MapCoordReadoutProps {
  map: MaplibreMap | null;
  showScale?: boolean; // default false — preserves Viewer behavior
}
```

From frontend/src/lib/ (existing naming convention — see basemap-utils.ts, geo-utils.ts, quicklook-cache.ts):
- Files are kebab-case .ts
- Tests live in frontend/src/lib/__tests__/{name}.test.ts (mirror name)
- Pure functions, no React imports, no MapLibre imports

New helper module to create (frontend/src/lib/representative-fraction.ts):
```typescript
// Classic Web Mercator meters-per-pixel at latitude `lat` (degrees), zoom `z`.
// EARTH_CIRCUMFERENCE_M / TILE_SIZE_PX at equator = 156543.03392.
export function metersPerPixel(lat: number, zoom: number): number;

// Compact-number format per CONTEXT.md <specifics>:
//   <1     -> "1"           (clamped)
//   <1000  -> "850"         (integer, no grouping)
//   <1M    -> "1.2k" / "288k" (one decimal, drop trailing ".0")
//   >=1M   -> "1.2M" / "120M" (one decimal, drop trailing ".0")
// Returns the value portion only — caller prefixes "1:".
export function formatRfValue(denominator: number): string;

// Composes the two above and returns "1:288k"-style string.
// ppi defaults to 96 (yields 3779.527559 px/m).
export function formatRepresentativeFraction(
  lat: number,
  zoom: number,
  ppi?: number,
): string;
```

From frontend/src/components/builder/BuilderMap.tsx:890 (callsite to edit):
```tsx
<MapCoordReadout map={mapRef.current} />
// becomes
<MapCoordReadout map={mapRef.current} showScale />
```

From frontend/src/components/viewer/ViewerMap.tsx:757 (DO NOT EDIT — relies on default):
```tsx
<MapCoordReadout map={mapRef.current} />
```

i18n key (new — add to all four locales identically in structure):
```json
{
  "mapCoordReadout": {
    "scale": "1:{{value}}"
  }
}
```
Translate the surrounding key path identically in en/de/es/fr — the template string itself is identical across locales (no locale-specific number grouping; the value is already opaque-formatted by the helper).
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Create representative-fraction formatter helper with unit tests</name>
  <files>frontend/src/lib/representative-fraction.ts, frontend/src/lib/__tests__/representative-fraction.test.ts</files>
  <behavior>
    Boundary cases for `formatRfValue(n)` (lock the format rule via the test — choose ONE of the two acceptable rules for the 1000 boundary and write the test against it; recommend rule A):

    Rule A (drop trailing ".0"):
    - formatRfValue(850)        -> "850"
    - formatRfValue(999)        -> "999"
    - formatRfValue(1000)       -> "1k"           (1.0 -> drop .0)
    - formatRfValue(1234)       -> "1.2k"
    - formatRfValue(99499)      -> "99.5k"        (one-decimal rounding to nearest)
    - formatRfValue(288000)     -> "288k"
    - formatRfValue(999000)     -> "999k"
    - formatRfValue(999999)     -> "1.0M"         (rolls to M: 999999/1e6 = 0.999... -> rounds to 1.0M)
                                                    OR "1M" if rule extends to M tier — pick one in test
    - formatRfValue(1234567)    -> "1.2M"
    - formatRfValue(120000000)  -> "120M"
    - formatRfValue(0.5)        -> "1"            (clamp floor)
    - formatRfValue(0)          -> "1"            (clamp floor)
    - formatRfValue(Infinity)   -> "1"            (clamp floor — guards against zoom=Infinity)
    - formatRfValue(NaN)        -> "1"            (clamp floor — guards against lat at +/-90 pole, cos=0)

    Boundary cases for `metersPerPixel(lat, zoom)`:
    - metersPerPixel(0, 0) approximately 156543.034 (within 0.01 m)
    - metersPerPixel(0, 12) approximately 38.218
    - metersPerPixel(60, 12) approximately 19.109   (cos(60°) = 0.5)
    - metersPerPixel(-60, 12) approximately 19.109  (cos negates, but cos(-x)=cos(x))

    Boundary cases for `formatRepresentativeFraction(lat, zoom)`:
    - formatRepresentativeFraction(0, 12) -> "1:144k"  (sanity check from CONTEXT.md — exact value depends on rounding; assert it matches /^1:1\d\dk$/ or the exact computed value)
    - formatRepresentativeFraction(45, 18) -> matches /^1:\d+$/   (high zoom, mid lat, denominator in plain-int range)
    - formatRepresentativeFraction(90, 12) -> "1:1"               (cos(90°)=0 -> denominator collapses to 0 -> clamped to 1)
  </behavior>
  <action>
    Create the pure helper module under `frontend/src/lib/representative-fraction.ts`, no React or MapLibre imports. Implement three exports:

    1. `metersPerPixel(lat, zoom)` using the classic formula from CONTEXT.md <specifics>:
       `156543.03392 * Math.cos(lat * Math.PI / 180) / Math.pow(2, zoom)`.
       At lat = +/-90 the cosine evaluates to exactly 0 (or a tiny float), so the formula returns 0 / very-small. Do NOT special-case here — let `formatRfValue` handle the clamp.

    2. `formatRfValue(denominator)` per the format rules in <behavior>. Use plain JS Math (no Intl.NumberFormat — explicitly avoiding locale grouping per D-02). Round to one decimal using `Math.round(x * 10) / 10`, then check `% 1 === 0` to drop trailing ".0". Clamp non-finite, NaN, and `<1` values to the literal string `"1"`.

    3. `formatRepresentativeFraction(lat, zoom, ppi = 96)`:
       - `const pxPerMeter = ppi / 0.0254;`  (-> 3779.527559... at ppi=96)
       - `const denominator = metersPerPixel(lat, zoom) * pxPerMeter;`
       - `return ` + "`1:${formatRfValue(denominator)}`" + `;`

    Co-locate the test under `frontend/src/lib/__tests__/representative-fraction.test.ts`. Follow the existing test style (see `frontend/src/lib/__tests__/geo-utils.test.ts` for a similar pure-function pattern — `import { describe, expect, it } from 'vitest';` then `describe(...)` with `it(...)` cases). Cover all <behavior> bullets. Lock Rule A for the 1000 boundary and 999999 boundary inline in the test so the implementation has no ambiguity.

    Per D-03 (Claude's discretion), use the classic formula (not `map.unproject`) — keeps the helper pure and free of MapLibre.
  </action>
  <verify>
    <automated>cd frontend &amp;&amp; npx vitest run src/lib/__tests__/representative-fraction.test.ts</automated>
  </verify>
  <done>
    All formatter test cases pass; helper module exports the three named functions; no React, no MapLibre, no Intl imports in the helper file.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Extend MapCoordReadout with showScale prop, wire BuilderMap callsite, add i18n keys</name>
  <files>frontend/src/components/map/MapCoordReadout.tsx, frontend/src/components/map/__tests__/MapCoordReadout.test.tsx, frontend/src/components/builder/BuilderMap.tsx, frontend/src/i18n/locales/en/common.json, frontend/src/i18n/locales/de/common.json, frontend/src/i18n/locales/es/common.json, frontend/src/i18n/locales/fr/common.json</files>
  <behavior>
    SP-12 test cases to APPEND to `MapCoordReadout.test.tsx` (new describe block, do not modify the existing SP-02 describe block):

    1. `it('does not render the scale segment by default (showScale omitted)')` — render `<MapCoordReadout map={map} />` with a known lat/zoom; assert `screen.queryByText(/1:/)` is null. Confirms ViewerMap behavior unchanged.

    2. `it('does not render the scale segment when showScale={false}')` — same as above but explicit false; confirms prop is honored.

    3. `it('renders the 1:N segment when showScale={true} with the expected format at a known lat/zoom')` — render with `lat: 0, lng: 0, zoom: 12` and `showScale`. Assert a `1:` token appears in the pill (use a permissive regex like `/1:\d/` or assert the segment text matches the computed value from the helper — call `formatRepresentativeFraction(0, 12)` inline in the test to derive the expected string).

    4. `it('updates the 1:N segment when the map moves to a different latitude (cos-lat changes)')` — render with `showScale`, capture initial 1:N text, fire `move` after `setCenter(60, 0)`, flush rAF, assert the 1:N text changed.

    Existing SP-02 tests must still pass unchanged.

    i18n parity: en/de/es/fr `common.json` all gain identical `mapCoordReadout.scale` key with value `"1:{{value}}"` (the template is identical across locales — per D-02 there is no locale-specific number formatting, the value is already opaque-formatted).
  </behavior>
  <action>
    Edit `frontend/src/components/map/MapCoordReadout.tsx`:

    1. Add `showScale?: boolean` to `MapCoordReadoutProps`. Destructure with default `false`: `function MapCoordReadout({ map, showScale = false }: MapCoordReadoutProps)`.
    2. Import `formatRepresentativeFraction` from `@/lib/representative-fraction`.
    3. Import `useTranslation` from `react-i18next` (see BuilderMap.tsx:14 for the established import pattern). Inside the component body call `const { t } = useTranslation('common');`. Only invoke `t` when `showScale` is true to keep the rendering branch hot-path cheap.
    4. In the JSX (currently lines 95-104), after the `z` segment, conditionally append the new segment when `showScale && coords` is truthy. Compute the formatted RF inline from `coords.lat` and `coords.zoom` (derive at render time per D-01 — no new state, no new effect, no new subscription). Use:
       ```
       const rfText = formatRepresentativeFraction(coords.lat, coords.zoom);
       // rfText is "1:288k" — split prefix "1:" and value "288k" so the prefix can be muted.
       ```
       Render the segment as a separator + muted-prefix `<span className="text-foreground/50">1:</span> {value}` — mirror the existing `z` prefix treatment at line 102. Use `t('mapCoordReadout.scale', { value })` to build the displayable text, then conditionally apply the muted span styling to the `1:` literal by string-splitting the template result OR (preferred) extract just the value via the helper and hardcode the `1:` literal as a muted span (the i18n key is still consulted for completeness via the helper return value, but the visible split is purely presentational). Lock the simpler approach: render `<span className="text-foreground/50">1:</span> {formatRfValue-result-or-helper-derived-value}` and use `t('mapCoordReadout.scale', { value })` for accessibility / aria-label or as the screen-reader text. Simpler still — just render the helper string directly and skip the prefix-muting if it complicates the i18n path. Planner discretion: the muted "1:" is a visual nicety from D-03, not a hard requirement. If the i18n template makes it ugly, ship the un-muted "1:288k" string from `formatRepresentativeFraction()` and note the choice in SUMMARY.

    Edit `frontend/src/components/builder/BuilderMap.tsx:890` — change `<MapCoordReadout map={mapRef.current} />` to `<MapCoordReadout map={mapRef.current} showScale />`. Per D-04, this is the ONLY callsite change. Do NOT touch `ViewerMap.tsx:757`.

    Edit `frontend/src/components/map/__tests__/MapCoordReadout.test.tsx`:
    - Preserve the existing SP-02 describe block untouched.
    - Append a new `describe('MapCoordReadout — SP-12 representative-fraction segment', () => { ... })` with the four `it` cases enumerated in <behavior>.
    - Reuse the existing `makeFakeMap`, `flushRaf` helpers, and the `beforeEach`/`afterEach` rAF mocking. If the new describe block needs the same rAF mocking, factor it minimally — duplicate the `beforeEach`/`afterEach` inside the new describe block rather than refactoring the existing one to avoid breaking SP-02.
    - If the i18n provider needs to be wrapped around `<MapCoordReadout>` for `useTranslation` to work in tests, import the existing i18n test setup (check for `frontend/src/i18n/i18n.ts` or a test provider helper). If MapCoordReadout uses `useTranslation` only inside the `showScale` branch and the test fixture wraps lazily, the SP-02 tests stay green without any i18n provider. If `useTranslation` cannot operate without an initialized i18n instance even when unused, switch the implementation to import `i18n` directly from `@/i18n/i18n` and call `i18n.t(...)` (same pattern as BuilderMap.tsx:13).

    Edit `frontend/src/i18n/locales/{en,de,es,fr}/common.json` — add a top-level (or nested under an appropriate group if `common.json` already groups by component) `mapCoordReadout` object with one key `scale: "1:{{value}}"`. All four locales identical structure; same `"1:{{value}}"` template per D-02 (no locale-specific number grouping).
  </action>
  <verify>
    <automated>cd frontend &amp;&amp; npx vitest run src/components/map/__tests__/MapCoordReadout.test.tsx src/lib/__tests__/representative-fraction.test.ts &amp;&amp; npm run test:i18n</automated>
  </verify>
  <done>
    Both new test files green; existing SP-02 tests still green; i18n resources test passes (parity across en/de/es/fr); BuilderMap renders four-segment pill, ViewerMap renders three-segment pill (verified by smoke check in Task 3); no TypeScript errors.
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 3: Playwright MCP smoke check — Builder shows 1:N, Viewer does not</name>
  <what-built>
    SP-12 1:N representative-fraction segment in the top-right pill of the Builder map; ViewerMap pill unchanged. New pure formatter helper + unit tests in `frontend/src/lib/representative-fraction.ts`. New SP-12 describe block in `MapCoordReadout.test.tsx`. New `common.mapCoordReadout.scale` i18n key across en/de/es/fr.
  </what-built>
  <how-to-verify>
    Orchestrator drives this via Playwright MCP (per feedback_playwright_mcp_self_verify.md). Stack must be up via `docker compose up -d` at http://localhost:8080.

    Two assertions:

    A) **Builder shows the 1:N segment.**
       1. Navigate to the Builder for any saved map (or create a new map).
       2. Locate the top-right coordinate pill.
       3. Assert it contains exactly four `·`-separated segments matching the pattern:
          `\d+\.\d{2}° [NS] · \d+\.\d{2}° [EW] · z \d+\.\d · 1:\S+`
       4. Pan or zoom; assert the `1:` value changes (cos-lat / zoom dependence). At least one pan + one zoom step.

    B) **Viewer pill stays 3-segment.**
       1. Open the public viewer for the same map (or any share link).
       2. Locate the top-right coordinate pill.
       3. Assert it matches the existing 3-segment pattern (`\d+\.\d{2}° [NS] · \d+\.\d{2}° [EW] · z \d+\.\d`) and contains NO `1:` token.

    Report any deviations as a bullet list. If both assertions pass, the executor finalizes the SUMMARY.
  </how-to-verify>
  <resume-signal>Type "approved" or describe issues (e.g. "Builder pill shows 1:NaN at z=22" / "Viewer pill regressed to 4 segments")</resume-signal>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client → DOM | Pure client-side computation; no untrusted input enters here |
| i18n template → DOM | `{{value}}` interpolation rendered by react-i18next; value is a string produced by our own pure formatter (no user input) |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-260515-mmo-01 | Tampering | `formatRepresentativeFraction` input | mitigate | Clamp non-finite / NaN / <1 to literal "1" in `formatRfValue`. Tested in Task 1 boundary cases. |
| T-260515-mmo-02 | Information Disclosure | Coordinate readout exposure | accept | The pill displays the same lat/lng that is already visible on screen via the MapLibre scale bar and is derivable from URL query params; adding a denominator reveals no new private data. |
| T-260515-mmo-03 | Denial of Service | rAF gate on hover | mitigate | Existing `rafRef` throttle at `MapCoordReadout.tsx:25` covers the new derivation too — RF is computed during render from already-throttled `coords` state, no new subscription. |
</threat_model>

<verification>
- Task 1: formatter unit tests green
- Task 2: MapCoordReadout SP-02 tests still green + new SP-12 tests green; i18n parity test green; TypeScript typecheck clean
- Task 3: Playwright MCP confirms Builder pill = 4 segments with `1:N`, Viewer pill = 3 segments without `1:`
- All four locale `common.json` files contain the `mapCoordReadout.scale` key
- Source audit: SP-12 is the sole requirement; covered by all three tasks
</verification>

<success_criteria>
- All test commands in <verify> blocks return exit 0
- Builder map's top-right pill renders `lat° N · lng° E · z 5.2 · 1:288k`-style four-segment string; the 1:N value updates on pan + zoom
- Viewer map's top-right pill renders three-segment string unchanged
- `frontend/src/lib/representative-fraction.ts` is pure (no React, no MapLibre imports — `grep -E "^import.*(react|maplibre)" frontend/src/lib/representative-fraction.ts` returns no matches)
- `npm run test:i18n` confirms en/de/es/fr have the new key with identical structure
- Existing SP-02 test cases pass without modification
</success_criteria>

<output>
Create `.planning/quick/260515-mmo-sp-12-representative-fraction-1-n-readou/260515-mmo-01-SUMMARY.md` when done.
</output>
