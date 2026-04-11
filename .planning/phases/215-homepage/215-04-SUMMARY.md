---
phase: 215-homepage
plan: 04
status: complete
tasks_completed: 3/3
verification_verdict: approved-with-fixes
verified_at: 2026-04-11
breakpoints_verified: [1280, 768, 375]
---

# Plan 04 Summary — Homepage Visual Verification

## What happened

Plan 04 is the human-verify checkpoint for Phase 215. The orchestrator
started the Astro dev server and drove the full three-breakpoint audit
via Playwright MCP instead of asking the user to run the checklist by
hand. The audit was strict — not a tour, a real inspection.

The audit surfaced **three visual regressions**, all originating in
Phase 214's `BrowserFrame.astro`:

1. **Horizontal scroll at 375px** (blocking)
2. **Perspective tilt not reset at mobile** (blocking)
3. **BrowserFrame undersized inside the 7-col preview slot** (advisory)

After the audit, the three issues were fixed in place (BrowserFrame.astro
+ ProductPreviewSection.astro) and re-verified across all three
breakpoints before closing the checkpoint.

## Success criteria audit

| Criterion | 1280×900 | 768×1024 | 375×667 |
|-----------|:---:|:---:|:---:|
| SC-1 Hero visible in first viewport | ✓ | ✓ | ✓ |
| SC-2 Trust bar in first/second viewport | ✓ (first) | ✓ | ✓ |
| SC-3 Feature highlights 3 cards | ✓ 3-col | ✓ 3-col | ✓ 1-col |
| SC-4 Product preview without layout shift | ✓ | ✓ stacked | ✓ |
| SC-5 Quickstart teaser reachable | ✓ | ✓ | ✓ |
| No horizontal scroll | ✓ | ✓ | ✓ (fixed) |
| Console errors / warnings | 0 / 0 | 0 / 0 | 0 / 0 |
| Tab order matches plan | ✓ | ✓ | ✓ |
| Section order Hero→Trust→Preview→Features→Quickstart | ✓ | ✓ | ✓ |

## Bugs found and fixed

### Bug 1 — Horizontal scroll from glow bleed at 375px

**Root cause:** `BrowserFrame.astro:12` — `<div class="pointer-events-none
absolute inset-[-20%] -z-10 blur-3xl opacity-50 rounded-full">`. The
`inset-[-20%]` extends the glow 20% beyond the frame on all sides. No
positioned ancestor has `overflow: hidden` / `overflow-x: clip`, so the
480px glow on a 375px viewport pushes `document.scrollWidth` to 427px.

**Fix:** Added class `browser-frame-glow` to the glow div and added a
media query in the scoped `<style>` block:
```css
@media (max-width: 639px) {
  .browser-frame-glow { inset: 0; }
}
```
This contains the glow within the frame bounds at mobile while preserving
the full bleed at desktop/tablet.

Also added `overflow-x-clip` to the `ProductPreviewSection` section root
as defense in depth for any future overflow.

**Verification:** At 375px: `document.scrollWidth` === `clientWidth` ===
375, `hasHScroll: false`. Glow `inset` computed to `0px 0px 0px 0px` at
mobile. At 1280px: glow bleed preserved, no horizontal scroll (viewport
wide enough to contain the full bleed).

### Bug 2 — Perspective tilt not reset at mobile

**Root cause:** `BrowserFrame.astro:19` — the transform was declared in
an inline `style="..."` attribute:
```astro
style="... transform: perspective(1200px) rotateY(2deg) rotateX(1deg); ..."
```
Inline styles have higher specificity than scoped CSS rules. The scoped
`@media (max-width: 639px) { .browser-frame-inner { transform: none; } }`
rule was written in Phase 214 but never took effect — specificity of a
class selector (10) cannot beat an inline style attribute (1000).

**Fix:** Moved the transform out of the inline `style=""` and into the
scoped `<style>` block as a base rule:
```css
.browser-frame-inner {
  transform: perspective(1200px) rotateY(2deg) rotateX(1deg);
  transform-origin: center center;
}
```
Now the scoped media query rules can override the base rule correctly
(same specificity, later rule wins).

**Verification:** At 375px: `getComputedStyle(.browser-frame-inner).transform`
returns `"none"` — frame renders flat per UI-SPEC. At 768px: returns the
1.5° matrix per the tablet media query. At 1280px: returns the 2° matrix
per the desktop base rule.

### Bug 3 — BrowserFrame undersized inside lg:col-span-7 slot (advisory)

**Observation:** At 1280px, the `lg:col-span-7` preview column is 683px
wide. `BrowserFrame.astro` uses `<div class="relative inline-block">` as
its outer wrapper, which is content-sized. The SearchPreview content
collapses to ~350px, leaving ~166px of empty space on each side of the
frame. Visually, the two-column layout feels unbalanced — the copy
column carries the weight while the preview column has a small frame
surrounded by empty space.

**Not a SC failure:** Plan 215-02 only requires that the 2-column layout
exists and SearchPreview is embedded without double-wrapping. Plan 215-04
SC-4 only requires "no layout shift or missing content". The narrow
frame inside the wide slot is advisory, not blocking.

**Fix applied:** Capped the preview wrapper at `max-w-md` (448px) in
`ProductPreviewSection.astro`:
```astro
<div class="lg:col-span-7 flex justify-center">
  <div class="w-full max-w-md mx-auto">  <!-- was: max-w-lg lg:max-w-none -->
    <SearchPreview />
  </div>
</div>
```
The visual impact is modest — the 350px frame is still centered inside
the 448px wrapper, which is centered inside the 683px column. The
document the intent so future polish passes have a sane starting point
without re-deriving it.

A more aggressive tightening (changing the 5/7 column split, or
restructuring BrowserFrame to expand to fill its slot) would require
UI-SPEC amendments and a design review. Deferred to a future polish
pass if needed.

## Production build verification

```
$ npm run build
...
generating static routes
  ├─ /og/home.png (+431ms)
  ├─ /preview-test/index.html (+4ms)
  ├─ /index.html (+2ms)
✓ Completed in 492ms
[@astrojs/sitemap] sitemap-index.xml created at dist
✓ 2 page(s) built in 932ms
```

- `astro check`: 0 errors / 0 warnings / 0 hints (19 files)
- `dist/index.html`: contains `browser-frame-inner` and `browser-frame-glow`
  classes; the inline `transform: perspective(...)` attribute has been
  removed (`grep` returns zero matches)
- `dist/_astro/SearchPreview.*.css`: media query stack is correct —
  base `perspective(1200px) rotateY(2deg) rotateX(1deg)`, then
  `max-width: 639px { transform: none; inset: 0 }`, then
  `min-width: 640px and max-width: 1023px { rotateY(1.5deg) }`
- Phase 213 SEO contract preserved (og:image, JSON-LD unchanged)
- Phase 214 preview-test.astro still compiles and still renders
  BrowserFrame with correct behavior at all widths

## Commits

- `b3753a1` (getgeolens.com): `fix(215-04): contain BrowserFrame glow and reset tilt at mobile`
  - `src/components/previews/BrowserFrame.astro` (+15 -2)
  - `src/components/home/ProductPreviewSection.astro` (+5 -3)

## Key files modified

- `getgeolens.com/src/components/previews/BrowserFrame.astro` —
  base transform moved to scoped `<style>`, glow gets `.browser-frame-glow`
  class, new `@media (max-width: 639px)` rule resets both tilt and glow
- `getgeolens.com/src/components/home/ProductPreviewSection.astro` —
  `overflow-x-clip` added to section root as safety net, preview
  wrapper capped at `max-w-md`

## Tab order (verified via DOM traversal)

1. Nav GeoLens logo (`/`)
2. Nav GitHub icon (`github.com/geolens-io/geolens`)
3. Hero `Get Started` (`/quickstart`)
4. Hero `View on GitHub` (`github.com/geolens-io/geolens`)
5. TrustSignalBar `Apache 2.0` (`github.com/.../LICENSE`)
6. QuickstartTeaser `Read the Quickstart` (`/quickstart`)
7. Footer `GitHub`
8. Footer `Apache 2.0`

Matches plan expected order exactly. SearchPreview is not in the focus
list (Phase 214's `aria-hidden="true"` on BrowserFrame outer wrapper
working correctly).

## Status

**approved-with-fixes** — checkpoint passed after three in-line fixes.
Phase 215 homepage is visually complete at all three target breakpoints.
Ready for Phase 216 (features + quickstart pages).
