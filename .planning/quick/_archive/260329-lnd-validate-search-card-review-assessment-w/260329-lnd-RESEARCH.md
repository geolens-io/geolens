# Quick Task 260329-lnd: Validate Search Card Review Assessment - Research

**Researched:** 2026-03-29
**Domain:** Source code verification of 5 review findings + Playwright validation strategy
**Confidence:** HIGH

## Summary

All 5 findings in the review are **confirmed by source code analysis**. The code matches what the review claims in every case. The line references are accurate, the logic descriptions are correct, and the severity ratings are reasonable. No discrepancies found.

The Playwright validation should focus on live reproduction of each finding with DOM measurements and API interception, not further code reading.

## Source Code Verification

### Finding 1: Empty state + collection card simultaneously

**Review claim:** `SearchPage.tsx:163-189` -- empty state renders from `numberMatched === 0` while cards render from `features.length > 0`, creating a contradictory display.

**Verified:** TRUE. Lines 164 and 183 are independent conditionals:
- Line 164: `data && data.numberMatched === 0` -- renders `EmptyState`
- Line 183: `data && data.features.length > 0` -- renders card list

These conditions are not mutually exclusive. If the API returns `numberMatched: 0` with a non-empty `features` array (which the review's research confirmed happens for collection results), both blocks render.

**Severity assessment:** HIGH is correct. This is a logic bug, not a style preference.

**Playwright checks needed:**
1. Navigate to `/search?q=Natural+Earth+Cultural`
2. Intercept `/api/search/datasets/` response and assert `numberMatched === 0` AND `features.length > 0`
3. Assert `EmptyState` (text "No results found") is visible
4. Assert at least one `[data-testid="search-result-card"]` is also visible
5. Screenshot the contradictory state

### Finding 2: max-w-3xl creates dead gutter on desktop

**Review claim:** Source and description text are capped at `max-w-3xl` inside a `1fr` grid column, creating unused space before the 120px preview.

**Verified:** TRUE.
- Line 193: `md:grid-cols-[1fr_120px]` -- grid gives text column all remaining width
- Line 218: source `<p>` has `max-w-3xl` (768px cap)
- Line 227: collection description has `max-w-3xl`
- Line 234: dataset description has `max-w-3xl`

At 1104px card width minus 120px preview minus padding, the text column is ~950px. Capping at 768px leaves ~180px of dead space.

**Severity assessment:** MEDIUM-HIGH is fair. Visual issue, not broken, but noticeable on wide viewports.

**Playwright checks needed:**
1. Set viewport to 1440x900
2. Measure card width via `boundingBox()` on first `[data-testid="search-result-card"]`
3. Measure `[data-testid="dataset-card-source"]` width
4. Measure `[data-testid="dataset-card-description"]` width
5. Calculate the gutter between text right edge and preview left edge
6. Assert gutter > 100px (confirming dead space exists)

### Finding 3: Flat information hierarchy (tags visually heavier than facts)

**Review claim:** Tags have more visual weight than the facts/specs row due to borders, backgrounds, and `font-medium`.

**Verified:** TRUE.
- Line 276 (specs): `text-xs text-muted-foreground` -- plain unstyled text
- Line 293 (tags): `rounded-full border border-border/50 bg-muted/30 px-2.5 py-1 text-xs font-medium text-muted-foreground/90` -- bordered pills with background and medium font weight

Tags have: border, background color, padding, border-radius, `font-medium`. Specs have: none of those. The visual weight difference is inherent in the CSS classes.

**Severity assessment:** MEDIUM is correct. Hierarchy issue, not a bug.

**Playwright checks needed:**
1. Find a card with both specs and tags (search for a dataset with keywords)
2. Measure computed styles on `[data-testid="dataset-card-specs"]` children vs tag elements
3. Compare: font-weight, border presence, background-color
4. Optionally screenshot and annotate the two rows for visual comparison

### Finding 4: Preview failure shows weak fallback

**Review claim:** `useQuicklook` throws on non-OK responses; the card's error fallback is just a muted `ImageOff` icon with no label or alternate content.

**Verified:** TRUE.
- `use-quicklook.ts` line 33: `if (!r.ok) throw new Error(String(r.status))` -- any non-200 triggers error state
- `use-quicklook.ts` line 39: `retry: false` -- no retry, error is immediate
- `SearchResultCard.tsx` lines 260-263: error state renders only `<ImageOff className="h-5 w-5 opacity-50" />` inside a muted container -- no text label, no "Preview unavailable" message
- The `BBoxPreview` fallback on line 265 is only reached in the final else branch (no src, not loading, no error), which means it handles the case where quicklook is disabled/null, NOT error cases

**Severity assessment:** MEDIUM is correct. Functional but visually weak.

**Playwright checks needed:**
1. Intercept quicklook requests: `page.route('**/api/datasets/*/quicklook*', route => route.fulfill({ status: 404 }))`
2. Navigate to search results
3. Assert the error fallback element exists (the `ImageOff` icon container)
4. Assert no text like "Preview unavailable" exists in the fallback
5. Measure the fallback container dimensions to confirm it renders as a 120x120 empty-looking box

### Finding 5: Collection card is sparse, not intentionally designed

**Review claim:** Collections use the same `SearchResultCard` component with `isCollection` guards that remove preview, specs, and tags, leaving a wide sparse card.

**Verified:** TRUE. The `isCollection` flag (line 128) gates:
- Preview tile: line 243 `!isCollection &&` -- hidden for collections
- Specs row: line 273 `!isCollection &&` -- hidden for collections
- Tags row: line 288 `!isCollection &&` -- hidden for collections
- Source org: line 216 `!isCollection &&` -- hidden for collections

Collections render only: RecordTypeBadge + dataset count badge (lines 197-209), title (line 212), description (line 226-229), footer timestamp (line 309-319). All inside the same full-width card shell with identical padding.

**Severity assessment:** LOW-MEDIUM is correct. Functional but under-designed.

**Playwright checks needed:**
1. Search for a collection (e.g., `?q=Natural+Earth+Cultural`)
2. Measure collection card dimensions (expect full width ~1104px but short height ~149px)
3. Assert preview area is NOT present (no `img` or `ImageOff` inside the card)
4. Assert specs row `[data-testid="dataset-card-specs"]` is NOT present
5. Assert no tag pills exist inside the card
6. Compare card height to a dataset card in the same viewport

## Playwright Infrastructure

**Config:** `playwright.config.ts` at project root
- Base URL: `http://localhost:8080`
- Auth setup: `e2e/auth.setup.ts` creates `playwright/.auth/user.json`
- Chromium project uses stored auth state
- Timeout: 60s test / 10s expect

**Existing specs:** `e2e/collections.spec.ts`, `e2e/admin.spec.ts`, etc. exist and can serve as patterns.

**Key test IDs available in SearchResultCard:**
- `search-result-card` (the card link wrapper)
- `dataset-card-source`
- `dataset-card-description`
- `dataset-card-specs`
- `dataset-card-updated-attribution`

**Key test IDs in SearchPage:**
- `search-sticky-shell`

## Validation Strategy

Run a single Playwright spec file with 5 test blocks, one per finding. Each test should:

1. Set viewport appropriately (1440x900 for desktop findings)
2. Use `page.route()` to intercept API calls where needed (findings 1, 4)
3. Collect DOM measurements via `locator.boundingBox()` and `locator.evaluate()`
4. Produce a per-finding verdict: confirmed / disputed / revised
5. Capture screenshots as evidence

The spec does not need to fix anything -- it is a validation-only artifact.

## Sources

### Primary
- `frontend/src/components/search/SearchResultCard.tsx` -- all 5 findings verified against source
- `frontend/src/pages/SearchPage.tsx` -- finding 1 verified
- `frontend/src/hooks/use-quicklook.ts` -- finding 4 verified
- `playwright.config.ts` -- infrastructure confirmed
