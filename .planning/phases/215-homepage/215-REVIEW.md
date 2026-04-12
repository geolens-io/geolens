---
phase: 215-homepage
reviewed: 2026-04-11T00:00:00Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - /Users/ishiland/Code/getgeolens.com/src/components/home/HeroSection.astro
  - /Users/ishiland/Code/getgeolens.com/src/components/home/TrustSignalBar.astro
  - /Users/ishiland/Code/getgeolens.com/src/components/home/QuickstartTeaser.astro
  - /Users/ishiland/Code/getgeolens.com/src/components/home/ProductPreviewSection.astro
  - /Users/ishiland/Code/getgeolens.com/src/components/home/FeatureHighlightsSection.astro
  - /Users/ishiland/Code/getgeolens.com/src/pages/index.astro
  - /Users/ishiland/Code/getgeolens.com/src/components/previews/BrowserFrame.astro
findings:
  critical: 0
  warning: 1
  info: 4
  total: 5
status: issues_found
---

# Phase 215: Code Review Report

**Reviewed:** 2026-04-11
**Depth:** standard
**Files Reviewed:** 7
**Status:** issues_found

## Summary

All seven files are structurally correct Astro components. No client directives, no JS runtime, no raw hex in brand color paths, no missing `rel="noopener noreferrer"` on external links in the reviewed files. The Phase 214 BrowserFrame fixes (specificity correction + glow containment at mobile) are correctly implemented and the specificity analysis in 215-04-SUMMARY is accurate. No critical issues found.

One warning: the JSON-LD `softwareVersion` field in `index.astro` is a factual error — it says `14.0` while the project shipped publicly at `1.0.0` (versions were reset at the 1.0.0 Public Release milestone per MEMORY.md). Four info-level items cover an accessibility inconsistency on the TrustSignalBar external link, a spec deviation on the FeatureHighlightsSection `<h2>` class, a known dead link, and a hardcoded version maintenance note.

---

## Warnings

### WR-01: JSON-LD `softwareVersion` contradicts the public release version

**File:** `/Users/ishiland/Code/getgeolens.com/src/pages/index.astro:22`

**Issue:** The `SoftwareApplication` structured data object sets `softwareVersion: '14.0'`. Per project MEMORY.md, backend/frontend versions were reset from the pre-public `13.x`/`14.x` numbering to `1.0.0` at the 1.0.0 Public Release milestone (2026-04-01). Search engines (Google, Bing) index `softwareVersion` from JSON-LD and surface it in rich results. The value `14.0` is factually incorrect and could confuse users comparing the structured data version to the actual release tag.

**Fix:**
```astro
// Option A: correct the literal value
softwareVersion: '1.0.0',

// Option B: derive from a shared constant so it stays in sync
// In src/lib/links.ts (or a new src/lib/constants.ts):
export const GEOLENS_VERSION = '1.0.0';

// In index.astro:
import { GEOLENS_VERSION } from '../lib/constants.ts';
// ...
softwareVersion: GEOLENS_VERSION,
```

---

## Info

### IN-01: TrustSignalBar external link missing "opens in new tab" accessible label

**File:** `/Users/ishiland/Code/getgeolens.com/src/components/home/TrustSignalBar.astro:27-33`

**Issue:** The Apache 2.0 `<a>` opens with `target="_blank"` but has no `aria-label` announcing the new-tab behavior. The Hero section's GitHub CTA — an analogous external link — explicitly includes `aria-label="GeoLens on GitHub (opens in new tab)"`. The inconsistency means screen reader users get a new-tab warning for GitHub but not for the license link. WCAG 2.4.4 (Link Purpose) is technically met since "Apache 2.0" is unambiguous, but the UX is inconsistent with the pattern already established in this same phase.

**Fix:**
```astro
<a
  href={GEOLENS_LICENSE_URL}
  target="_blank"
  rel="noopener noreferrer"
  aria-label="Apache 2.0 License (opens in new tab)"
  class="text-base font-semibold hover:underline trust-badge-link"
  style="color: var(--foreground);"
>Apache 2.0</a>
```

---

### IN-02: FeatureHighlightsSection `<h2>` missing `text-center` class required by UI-SPEC

**File:** `/Users/ishiland/Code/getgeolens.com/src/components/home/FeatureHighlightsSection.astro:17`

**Issue:** The UI-SPEC (215-UI-SPEC.md §FeatureHighlightsSection) specifies `"text-3xl font-semibold leading-[1.2] text-center"` for the section `<h2>`. The implementation omits `text-center` from the heading element itself:

```astro
<!-- current -->
<h2
  class="mt-3 text-3xl font-semibold leading-[1.2]"
  ...
>Everything your team needs...</h2>
```

The heading is visually centered today because its parent div carries `text-center max-w-3xl mx-auto`. However, the centering is implicit and fragile — if that parent class is ever changed (e.g., left-aligning the eyebrow label), the heading will silently shift left while the intent was to keep it centered.

**Fix:**
```astro
<h2
  class="mt-3 text-3xl font-semibold leading-[1.2] text-center"
  style="color: var(--foreground);"
>Everything your team needs to work with geospatial data</h2>
```

---

### IN-03: `/quickstart` CTA links to a page that does not yet exist

**File:** `/Users/ishiland/Code/getgeolens.com/src/components/home/QuickstartTeaser.astro:20`
**Also:** `/Users/ishiland/Code/getgeolens.com/src/components/home/HeroSection.astro:23`

**Issue:** Both the Hero "Get Started" CTA and the QuickstartTeaser "Read the Quickstart" CTA link to `/quickstart`. Phase 216 has not shipped yet, so this route currently 404s. The 215-UI-SPEC acknowledges this: "If it 404s before Phase 216 ships, this is acceptable for the development period." Flagged here as a reminder to verify both links are live before Phase 215 is promoted to production.

**Fix:** No code change needed now. When Phase 216 ships and `/quickstart` is built, verify both CTAs resolve correctly. If there is any risk of Phase 215 going live before Phase 216, add a temporary redirect or placeholder page.

---

### IN-04: BrowserFrame `inset-[-20%]` class and scoped override coexist without explanation on the element

**File:** `/Users/ishiland/Code/getgeolens.com/src/components/previews/BrowserFrame.astro:12`

**Issue:** The glow div carries the Tailwind utility `inset-[-20%]` in its class list, while the scoped `<style>` block overrides it with `inset: 0` at `max-width: 639px`. The specificity logic is correct (Astro-scoped class + data-attribute selector = 0,2,0 beats Tailwind's single-class utility at 0,1,0), and the fix is sound. However, the HTML element itself has no comment explaining why a negative inset class is intentionally present when there is a zero-inset override. A future developer could remove `inset-[-20%]` as "dead code" or try moving the override back inline, reintroducing the bug.

**Fix:** Add a brief inline comment on the glow element:
```astro
<!-- Glow layer: -20% bleed at desktop/tablet; scoped CSS resets to inset:0 at mobile
     (max-width:639px) to prevent horizontal scroll. Do NOT move the override inline —
     inline style specificity (1,0,0,0) would defeat the scoped media query. -->
<div
  class="browser-frame-glow pointer-events-none absolute inset-[-20%] -z-10 blur-3xl opacity-50 rounded-full"
  ...
></div>
```

---

## BrowserFrame Specificity Analysis — Correctness Assessment

The approach taken in 215-04 is correct. The root cause (inline `style=""` at specificity 1,0,0,0 defeating a scoped class rule at 0,1,0 or 0,2,0) was properly diagnosed. The fix — moving the base transform into the scoped `<style>` block — gives both the base rule and the mobile override the same selector type (Astro-scoped class), so cascade order determines the winner. The mobile override appears later in the stylesheet and wins. No regression risk exists for the Phase 214 `/preview-test` page: any existing consumer of `BrowserFrame` that was receiving the inline transform now receives the same transform from the CSS rule, producing an identical visual result.

---

_Reviewed: 2026-04-11_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
