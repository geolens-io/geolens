---
name: 260515-mmo-CONTEXT
description: Decisions locked during the discussion phase for the SP-12 representative-fraction "1:N" readout
type: project
---

# Quick Task 260515-mmo: SP-12 1:N readout — Context

**Gathered:** 2026-05-15
**Status:** Ready for planning

<domain>
## Task Boundary

Close v1009.1's SP-12 ("representative-fraction pane next to MapCoordReadout") — the last open followup from milestone v1009.1.

**Background (from `.planning/milestones/v1009.1-phases/1045-builder-smoke-polish/VERIFICATION.md:59-72`):** The smoke check's `p-01` finding asked for a *representative-fraction* readout (e.g. "1:288k") in the top-right area next to the existing coordinate pill. MapLibre's `ScaleControl` bar is already on screen at `bottom-left` of both `BuilderMap.tsx:854` and `ViewerMap.tsx:746`, so the **bar** is satisfied; what's missing is the **1:N denominator readout** that desktop-GIS users expect. SP-12 was SKIPPED during v1009.1 closeout because it required:
- a meters-per-pixel calculation with a cosine-of-latitude meridian factor
- a new UI slot inside MapCoordReadout
- i18n / locale-aware number formatting

This task delivers exactly that, scoped per the discussion decisions below.

**Existing surface to extend:** `frontend/src/components/map/MapCoordReadout.tsx` (107 lines). Currently renders a single top-right pill: `lat° N · lng° E · z 5.2`. Updates on `move` + `mousemove` + canvas-leave (SP-02 added the `move` subscription). Uses rAF gate. Memoized component.

**Out of scope:**
- The MapLibre `ScaleControl` bar (already present).
- Any change to the existing lat/lng/z segments of MapCoordReadout — only adding a new segment.
- Any backend changes — purely client-side computation.

</domain>

<decisions>
## Implementation Decisions

### Latitude reference for cos-lat factor

**Locked:** Mouse position whenever available; fall back to viewport center when the cursor is outside the canvas.

- Echoes MapCoordReadout's existing behavior: lat/lng segments already track mouse during hover and fall back to center on `mouseleave`. The 1:N segment must use the **same lat** the rest of the pill is currently showing, so the readout stays internally consistent ("here's the lat/lng I'm hovering, and here's the scale at that lat").
- Implementation tie-in: the existing `coords.lat` state in `MapCoordReadout.tsx:24` already encodes this behavior. Compute the RF as a derived value from `coords.lat` + `coords.zoom`; no new event subscription needed.
- Rationale for accepting the flicker: the lat/lng segments already flicker the same way during hover, so a flickering scale segment is a feature (consistency), not a bug.

### Number formatting

**Locked:** Mixed compact form.

- **<1000:** `1:850` (plain integer, no grouping)
- **<1,000,000:** `1:1.2k` ... `1:288k` (one decimal where it adds info, otherwise dropped — i.e. `1:850k` not `1:850.0k`)
- **≥1,000,000:** `1:1.2M` ... `1:120M` (same one-decimal rule)
- **<1:** edge case — if the user zooms in so far that the denominator drops below 1 (only theoretically possible on indoor maps at z~22+), display as `1:1` clamped at the floor. Document the clamp but don't optimize beyond.
- **Lowercase `k`, uppercase `M`** — matches the convention already in the repo (e.g. `feature_count: 12.3k` in record summaries; verify during planning that this is consistent).
- No locale digit grouping. The compact format sidesteps the `1,000` vs `1.000` vs `1 000` locale question entirely. i18n only needs an opaque `"1:{value}"` template string per locale, not number-formatting logic.

### Layout placement

**Locked:** Append as one more `·`-separated segment inside the existing top-right pill.

- Final segment order: `lat° N · lng° E · z 5.2 · 1:288k`
- Single component (`MapCoordReadout.tsx`), single DOM node, single `bg-background/60` + `backdrop-blur-sm` styling pass. No new component, no new layout container.
- Visual treatment: same `font-mono text-2xs tracking-wide` for the value; the "1:" prefix could be muted (`text-foreground/50`) mirroring how the existing "z" prefix is muted at `MapCoordReadout.tsx:102`. Planner's call.

### Surfaces

**Locked:** Builder only. Gate inside `MapCoordReadout` via a prop.

- Add an optional prop to `MapCoordReadout`: `showScale?: boolean` (default `false`).
- `BuilderMap.tsx:25` callsite passes `showScale={true}`.
- `ViewerMap.tsx:25` callsite stays at the default (no scale segment).
- Rationale for narrower scope than the recommendation: keeps the public/share/embed viewer pill identical to its current 3-segment form. The 1:N readout is a power-user / authoring-workflow affordance — Builder users want to know the printable scale; public viewer users are exploring the map, not preparing for export. Smaller blast radius for v1009.1 closeout.
- The prop is *opt-in*, so future surfaces can enable it by flipping a flag without re-architecting.

### Claude's Discretion

- Exact pixel-distance source for meters-per-pixel: either `map.unproject(point1)` + `map.unproject(point2)` to measure a known canvas pixel span (most accurate, uses MapLibre's projection), OR the classic formula `metersPerPixel = 156543.03392 * cos(lat * π/180) / 2^zoom`. The classic formula is simpler and well-known; the `unproject` approach is more accurate near map edges. Planner's choice.
- Whether to add a small `formatRepresentativeFraction(meters_per_pixel, ppi=96)` helper in `frontend/src/lib/` (so it can be unit-tested in isolation and reused) or inline it in `MapCoordReadout.tsx`. Recommend the helper for testability.
- Whether to add an i18n key (e.g. `mapCoordReadout.scale: "1:{value}"`) or just hardcode `"1:" + formatted` inline. Recommend i18n key for parity with the rest of the pill.
- Update throttling: reuse the existing rAF gate already in `MapCoordReadout.tsx:25` (`rafRef`). No new subscriptions needed.
- Test coverage: minimum is a unit test for the formatter (boundary values: 999, 1000, 9999, 999999, 1000000, 1234567), plus a render test confirming the new segment appears when `showScale=true` and is absent when `showScale=false`.
- Playwright MCP UAT: visit Builder, confirm `1:N` appears in top-right pill, zoom in/out and confirm the value changes; visit a public viewer and confirm the pill remains 3-segment (no scale).

</decisions>

<specifics>
## Specific Ideas

- **Existing rAF + throttle plumbing** is at `MapCoordReadout.tsx:25` (`rafRef`). New derivation from `coords` happens during render, not in an effect, so no new subscriptions are needed.
- **i18n locale files** live in `frontend/src/i18n/locales/{en,de,es,fr}/builder.json` (per v1009.1 work). For MapCoordReadout, the right namespace is `frontend/src/i18n/locales/{lang}/map.json` if it exists, otherwise add a key under whatever namespace MapCoordReadout's existing strings (if any) live in — planner confirms during the file scan. Worst case: no existing strings, add a small new key.
- **Reference formula** (classic Web Mercator meters-per-pixel at latitude `lat`, zoom `z`):
  ```
  M_PER_PX = 156543.03392 * cos(lat * π / 180) / 2^z
  ```
  Multiply by a screen-pixels-per-meter constant (96 DPI / 0.0254 m/in = ~3779.527559 px/m) to get the RF denominator: `denominator = M_PER_PX * 3779.527559`.
  Sanity check: at lat=0, z=12, M_PER_PX ≈ 38.22, denominator ≈ 144,478 → `1:144k`. Reasonable for a city-level zoom near the equator.
- **Test boundary cases** for the formatter:
  - `formatRF(850)` → `"1:850"`
  - `formatRF(999)` → `"1:999"`
  - `formatRF(1000)` → `"1:1.0k"` (or `"1:1k"` — pick a rule and lock it in the test)
  - `formatRF(1234)` → `"1:1.2k"`
  - `formatRF(288000)` → `"1:288k"`
  - `formatRF(999999)` → `"1:1.0M"` (rolls to M at the 1M threshold)
  - `formatRF(1234567)` → `"1:1.2M"`
  - `formatRF(120000000)` → `"1:120M"`
- **MapCoordReadout consumers** — only two: `BuilderMap.tsx:25` and `ViewerMap.tsx:25`. Adding a default-false prop is fully backward compatible; only BuilderMap callsite changes.

</specifics>

<canonical_refs>
## Canonical References

- v1009.1 VERIFICATION.md: `.planning/milestones/v1009.1-phases/1045-builder-smoke-polish/VERIFICATION.md:59-72` — original SP-12 skip rationale describing exactly this work.
- v1009.1 REQUIREMENTS.md SP-12: `.planning/milestones/v1009.1-REQUIREMENTS.md:99-103`.
- v1009.1 ROADMAP.md remediation list: `.planning/milestones/v1009.1-ROADMAP.md:95-96` ("SP-12 feature ticket — representative-fraction '1:N' pane next to MapCoordReadout (requires cos-lat factor + i18n)").
- Existing MapCoordReadout: `frontend/src/components/map/MapCoordReadout.tsx` (107 lines).
- Existing MapCoordReadout test: `frontend/src/components/map/__tests__/MapCoordReadout.test.tsx` (SP-02 move-event coverage; extend with SP-12 cases).

</canonical_refs>
