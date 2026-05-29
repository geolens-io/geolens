---
phase: 1138-easy-win-sweep
fixed_at: 2026-05-28T06:38:00Z
review_path: .planning/phases/1138-easy-win-sweep/1138-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 1138: Code Review Fix Report

**Fixed at:** 2026-05-28T06:38:00Z
**Source review:** .planning/phases/1138-easy-win-sweep/1138-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 4 (3 Warning + 1 Info; IN-02 is no-fix-required per review)
- Fixed: 4
- Skipped: 0

## Fixed Issues

### WR-01 + IN-01: URL_RE consumes trailing punctuation / youtube-nocookie.com not recognized

**Files modified:** `frontend/src/lib/popup-rich-text.ts`, `frontend/src/lib/__tests__/popup-rich-text.test.ts`
**Commit:** 5f5ec533
**Applied fix:**
- Added `trimTrailingPunctuation(url)` helper exported from `popup-rich-text.ts`. Uses CommonMark/Slack approach: strips trailing `.,;:!?"')` from each URL match unless `)` is balanced by `(` in the URL body (preserves Wikipedia-style `/wiki/Foo_(bar)` links).
- Applied in `splitTextWithUrls`: raw match is trimmed; stripped punctuation is re-injected as a `text` segment so displayed text is visually unchanged.
- Applied in `detectUrls`: maps each match through `trimTrailingPunctuation` before returning.
- Extended `YT_HOSTS` to include `youtube-nocookie.com` (IN-01), enabling recognition and embedding of YouTube privacy-enhanced URLs.
- Updated test file: replaced the outdated "trailing dot consumed — documented trade-off" test with two new WR-01 tests (trailing comma stripped cleanly, trailing period stripped); added WR-01 classification test (img.jpg. → image after trim); added two IN-01 tests (classifyUrl + normalizeYouTubeEmbed for nocookie domain).
- Test results: 40/40 pass (6 new cases).

### WR-02: layer object in useEffect deps causes queryRenderedFeatures at 60fps

**Files modified:** `frontend/src/components/builder/hooks/use-filtered-feature-count.ts`
**Commit:** 2f5bb0dd
**Applied fix:**
Removed the trailing `layer` entry from the `useEffect` dependency array. The dep array is now `[map, layer?.id, layer?.filter]`. Added a comment explaining the omission so future maintainers do not re-add the full object. The closure still captures the current `layer` reference at each effect run; `id` and `filter` are the only fields that require a recount.

### WR-03: img lacks crossOrigin="anonymous"

**Files modified:** `frontend/src/components/map/FeaturePopup.tsx`
**Commit:** 4b2e6039
**Applied fix:**
Added `crossOrigin="anonymous"` to the `<img>` element in `ValueDisplay` that renders classified image URLs. This forces uncredentialed CORS requests, preventing Referer/cookie leakage to external image hosts and blocking secondary credential-bearing requests from SVG images that reference external resources.

---

_Fixed: 2026-05-28T06:38:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
