# Quick Task 260326: Search page UI/UX assessment - Research

**Researched:** 2026-03-25
**Domain:** Search page (`/`) in desktop and mobile states
**Confidence:** HIGH

## Summary

The current search page has a solid base: search-first framing is clear, result cards are generally readable, and the mobile filters sheet is easier to understand than the previous dense inline toolbar. It is not yet fully aligned with UI/UX best practice, though, because the live page still has several concrete issues:

1. The spatial search dialog remains mounted as a visible off-canvas dialog with focusable controls even when closed.
2. Landing and browse states diverge in a way that removes filter access from the sticky header while scrolling the default result set.
3. Type counts and filter affordances do not accurately represent the records the page is actually showing.
4. Mobile shows a low-value Save Search CTA in the default state and the pagination layout breaks at narrow widths.
5. Table cards still trigger failing quicklook requests, producing console noise and an avoidable degraded first impression.

## Live Playwright Audit Coverage

- Desktop landing state on `http://localhost:8080/`
- Desktop browse state on `http://localhost:8080/?q=Zoning`
- Desktop filtered browse state on `http://localhost:8080/?record_type=vector_dataset`
- Mobile landing state at `390x844`
- Mobile browse state at `390x844`
- Mobile filters sheet

## Strengths

### Strength 1: Search-first structure is easy to understand

The page still communicates the core workflow immediately: search at the top, refine with filters, then scan results. The redesigned cards remain materially easier to parse than the pre-`260324` dense version.

### Strength 2: Result cards hold up reasonably well on mobile

The mobile browse view avoids horizontal overflow and keeps the title/spec/tag hierarchy intact. Hiding the preview image on small widths was a pragmatic choice.

### Strength 3: Desktop browse state has better control grouping than a typical faceted search toolbar

The browse shell meaningfully groups query, primary filters, secondary filters, result count, and save action. It looks intentional rather than purely utilitarian.

## Findings

### Finding 1: Closed spatial search dialog remains an exposed, focusable dialog off-canvas (HIGH confidence)

**Live evidence:** In Playwright, a `role="dialog"` labeled `Search area` is present even when the panel is visually closed. Runtime inspection showed:
- `display: block`
- `visibility: visible`
- `opacity: 1`
- bounding rect at `x=1280`, `width=400` on desktop
- 9 focusable descendants

This is an accessibility issue, not a cosmetic one. Off-screen but visible dialogs can still enter the accessibility tree and keyboard path.

**Source cause:** `SpatialFilterPanel` is always portaled and only moved with `translate-x-full`; it is not unmounted and is not hidden from assistive tech when closed.

**Source refs:** `frontend/src/components/search/SpatialFilterPanel.tsx:279-288`, `frontend/src/components/search/SpatialFilterPanel.tsx:296-304`

### Finding 2: Sticky behavior is inconsistent between landing and browse, so filters disappear while browsing default results (HIGH confidence)

**Live evidence:** On the landing page, scrolling past the hero replaces the full hero/filter surface with a sticky bar that only keeps the search input. The default result list remains visible below, so users are still browsing results but lose immediate access to filters until they scroll back up.

This is a workflow mismatch:
- landing state still shows default results
- sticky browse affordances are withheld because `isLanding` is still true

That behavior is surprising and weaker than best practice for a search catalog where “default browse” is still a browse mode.

**Source cause:** `showStickyBar` activates on scroll, but `FilterPanel` is only rendered inside the sticky shell when `!isLanding`.

**Source refs:** `frontend/src/pages/SearchPage.tsx:35-36`, `frontend/src/pages/SearchPage.tsx:53-67`, `frontend/src/pages/SearchPage.tsx:73-89`

### Finding 3: Type counts and type affordances do not match the records being shown (HIGH confidence)

**Live evidence:** On the live landing page the toolbar reads `All (59)` and `Vector (59)` while the page simultaneously shows `60 results` and includes a `Table` card (`sample-nonspatial`) in the result list.

This creates two UX problems:
- the count signal is visibly inconsistent
- the type model is incomplete for what the page actually contains

Even if tables are intentionally folded into the dataset search, the UI currently tells users a narrower story than the content below it.

**Source cause:** The `All` count is calculated by summing only `vector_dataset`, `raster_dataset`, and `vrt_dataset`, with no table contribution.

**Source refs:** `frontend/src/components/search/FilterPanel.tsx:372-386`, `frontend/src/components/search/FilterPanel.tsx:680-698`

### Finding 4: Mobile default state is cluttered by an always-on Save Search CTA, and pagination breaks at narrow widths (MEDIUM confidence)

**Live evidence:** On mobile landing, the hero action row shows `Filters` and `Save` even before the user has entered a query or selected filters. That makes the hero busier and promotes a low-value action too early. In the same mobile view, the pagination center label wraps vertically (`1 / 6` stacking into separate lines), which looks broken.

Best practice would be:
- hide or defer Save Search until the user has meaningful search state
- make pagination stack or compress intentionally on small widths

**Source cause:**
- mobile renders `SaveSearchButton` whenever a token exists
- pagination uses a single-row flex layout without a small-screen fallback

**Source refs:** `frontend/src/components/search/FilterPanel.tsx:253-280`, `frontend/src/components/search/FilterPanel.tsx:520-529`, `frontend/src/components/layout/Pagination.tsx:23-53`

### Finding 5: Table results still trigger failing quicklook requests, creating avoidable console noise (MEDIUM confidence)

**Live evidence:** The landing page logs repeated failed requests for the first table card’s quicklook endpoint. A direct Playwright fetch of `/api/datasets/97fafb8a-8eaa-4a70-a46b-3193bca792fd/quicklook?size=256` returned `404 Dataset not found`.

The UI degrades gracefully to `Preview unavailable`, but the network/console noise is still a UX quality issue and makes the page feel less trustworthy in dev/staging.

**Source cause:** `SearchResultCard` requests a quicklook for every non-collection result, and `useQuicklook` treats any failure as an error after making the request.

**Source refs:** `frontend/src/components/search/SearchResultCard.tsx:86-89`, `frontend/src/components/search/SearchResultCard.tsx:264-287`, `frontend/src/hooks/use-quicklook.ts:20-47`

### Finding 6: The browse sticky header is still visually heavy and implementation-heavy (LOW confidence)

**Live evidence:** In filtered browse mode, the sticky shell occupies substantial vertical space before the next result card is visible. It works, but the interaction feels closer to a floating control dashboard than a lightweight sticky browse bar.

This is not broken, but it is a simplification opportunity:
- fewer persistent controls at once
- progressive disclosure for secondary filters
- less duplicated shell markup between hero and sticky states

**Source refs:** `frontend/src/pages/SearchPage.tsx:58-89`, `frontend/src/components/search/FilterPanel.tsx:361-536`

## Cleanup / Simplification Opportunities

1. Extract a shared `SearchControlsShell` or similar from the duplicated hero/sticky layout in `SearchPage.tsx`.
2. Replace the custom off-canvas spatial panel with the same dialog/sheet primitives already used elsewhere in search.
3. Use one save-search gating rule on all breakpoints instead of desktop/mobile divergence.
4. Derive type totals from the same source of truth as `numberMatched`, or explicitly include/exclude table/collection types in the visible model.
5. Gate quicklook fetching by supported record types or by an explicit quicklook capability flag instead of optimistic fetch-then-fail.

## Sources

### Primary
- Live Playwright inspection of the running app on `http://localhost:8080`
- `frontend/src/pages/SearchPage.tsx`
- `frontend/src/components/search/FilterPanel.tsx`
- `frontend/src/components/search/SpatialFilterPanel.tsx`
- `frontend/src/components/search/SearchResultCard.tsx`
- `frontend/src/components/layout/Pagination.tsx`
- `frontend/src/hooks/use-quicklook.ts`
