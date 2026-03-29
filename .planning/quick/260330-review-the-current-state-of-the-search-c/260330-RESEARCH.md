# Quick Task 260330: Search Card Layout + Style Review - Research

**Researched:** 2026-03-29
**Domain:** Search result cards on the live local GeoLens app
**Confidence:** HIGH

## Summary

The current search cards are directionally good, but they are not yet optimized for “simple, elegant, intuitive” scanning. The layout is cleaner than the older dense card design, but the live page still shows four concrete problems:

1. A collection query can show an empty state and a valid collection card at the same time.
2. Desktop cards create an avoidable dead middle gutter, so the preview feels detached from the content.
3. The typography hierarchy is flatter than it should be: source, summary, facts, and tags do not read in a clear priority order.
4. Preview fallbacks are technically handled, but visually they still read as broken or decorative emptiness.

The live cards are close. The next pass should be a tightening and hierarchy pass, not another wholesale redesign.

## Live Audit Coverage

- Desktop landing/search results at `1440x1400`
- Tablet landing/search results at `900x1280`
- Long-source dataset search: `?q=Riparian+Integrity+Score`
- Collection search: `?q=Natural+Earth+Cultural`
- Supporting API checks against `/api/search/datasets/`

## Live Evidence

### Desktop default result stack

Playwright measurement of the first four cards at `1440px` showed:

- Card width: `1104px`
- Card height: `251px` for richer cards, `208px` for simpler cards
- Preview size: ~`120px`
- Description block height: `20px` to `40px`

This confirms the cards are not cramped. The current issue is not density; it is where the whitespace lands and which elements receive emphasis.

### Tablet default result stack

At `900px`, the first cards measured:

- Card width: `852px`
- Card height: `251px`
- Preview size: `120px`

The preview remains the same physical size on tablet as desktop. That keeps it visible, but it also makes the right rail feel heavier relative to the available text width.

### Long-source dataset case

For `Riparian Integrity Score`:

- Card height: `271px`
- Source text length: `250` characters
- Source block height: `40px`
- Description block height: `40px`

The source and summary become two same-weight muted text blocks stacked together. The card stays readable, but the provenance line and the explanatory summary visually collapse into one layer.

### Collection search case

For `Natural Earth Cultural`:

- API response returned `numberMatched: 0`
- The same response also returned `numberReturned: 1` and one `collection` feature
- The UI showed `No results found` and a valid collection card simultaneously

This is a real state bug, not a design preference. It makes the card surface feel unreliable even before styling is discussed.

## Strengths

### Strength 1: The card structure is calmer than the older dense search cards

The title-first structure, reduced chrome, and clear vertical banding are improvements. The cards no longer feel overloaded.

### Strength 2: Hiding previews below mobile is still the right move

On desktop/tablet, previews help orientation. On smaller widths they would cost too much. The current responsive decision remains sound.

### Strength 3: The current band ordering is conceptually correct

Header -> facts -> tags -> footer is the right general mental model. The remaining work is mostly about emphasis and breakpoint tuning.

## Findings

### Finding 1: Collection queries can show “No results found” while also rendering a collection card

**Severity:** High

**Live evidence:** Searching `Natural Earth Cultural` produced a visible `No results found` empty state, a `0 results` label, and a valid collection card for `Natural Earth Cultural (10m)` in the same viewport. The backing API response confirmed the inconsistency:

- `numberMatched: 0`
- `numberReturned: 1`
- `features.length: 1`
- `features[0].properties.record_type: "collection"`

**Why it matters for card UX:** This makes the card feel untrustworthy. Users are told there are no results while a card is clearly present.

**Source cause:** `SearchPage` renders the empty state from `data.numberMatched === 0`, but renders cards from `data.features.length > 0`, so contradictory upstream counts surface directly in the UI.

**Source refs:** `frontend/src/pages/SearchPage.tsx:163-189`

### Finding 2: The header text column is artificially capped, creating a dead middle gutter and a detached preview

**Severity:** Medium-High

**Live evidence:** On desktop, cards are `1104px` wide but the preview is only `120px`. Source and description text are capped at `max-w-3xl`, which leaves a large unused middle strip before the preview. In the live screenshot this makes the preview feel like a floating tile instead of part of the same information block.

**Why it matters:** The layout feels airy in the wrong place. The card looks bigger than the information it contains.

**Source cause:** The header grid uses `md:grid-cols-[1fr_120px]`, but both the source and description are capped with `max-w-3xl`, so the text column never fully uses the space that the grid gives it.

**Source refs:** `frontend/src/components/search/SearchResultCard.tsx:193-245`
**Specific refs:** `frontend/src/components/search/SearchResultCard.tsx:218-235`

### Finding 3: Source, description, facts, and tags are not visually prioritized in the right order

**Severity:** Medium

**Live evidence:** In the long-source `Riparian Integrity Score` card, the source block and the description are both two-line muted text blocks with nearly identical size and tone. Meanwhile, the keyword pills draw more visual attention than the facts row (`MultiPolygon`, `187 features`, `EPSG:4326`), even though the facts are more important for scanning.

**Why it matters:** The card is readable, but not intuitive at a glance. Users have to work to separate provenance, summary, essential facts, and optional tags.

**Source cause:**

- source: `text-[13px] leading-5 text-muted-foreground/90`
- description: `text-[13px] leading-5 text-muted-foreground/80`
- facts: plain `text-xs`
- tags: bordered rounded pills

That makes the secondary keyword row feel stronger than the primary facts row.

**Source refs:** `frontend/src/components/search/SearchResultCard.tsx:216-304`

### Finding 4: Preview fallbacks are technically present, but visually they still read as broken or empty

**Severity:** Medium

**Live evidence:** Playwright logged live quicklook 404s for some results, and the corresponding cards showed preview boxes that read more like empty placeholders than confident fallbacks. The UI does not catastrophically fail, but the state still feels degraded.

**Why it matters:** When previews fail, the card loses one of its strongest orientation cues. The fallback should feel deliberate, not accidental.

**Source cause:** `useQuicklook` throws on any non-OK response, and the card’s fallback state renders a muted square with a small `ImageOff` icon but no explanatory label or alternate content unless the `BBoxPreview` path is reached.

**Source refs:** `frontend/src/hooks/use-quicklook.ts:26-40`
**Source refs:** `frontend/src/components/search/SearchResultCard.tsx:245-266`

### Finding 5: The collection-card variant is structurally correct but visually under-resolved

**Severity:** Low-Medium

**Live evidence:** The collection card measured `1104px x 149px` on desktop and presents as a sparse left-aligned content block inside a wide card. Once the dataset-specific bands are removed, the component still functions, but it no longer feels intentionally composed.

**Why it matters:** Collections are meaningfully different objects. They should feel intentionally simpler, not like a dataset card with missing pieces.

**Source cause:** `SearchResultCard` uses the same component for collections and datasets, then removes preview/spec/tag behavior with `isCollection` guards.

**Source refs:** `frontend/src/components/search/SearchResultCard.tsx:127-170`
**Source refs:** `frontend/src/components/search/SearchResultCard.tsx:199-230`
**Source refs:** `frontend/src/components/search/SearchResultCard.tsx:272-346`

## Recommended Card Direction

The next implementation pass should aim for this target:

### 1. Keep the four-band model, but tighten and rebalance it

- Keep: header -> facts -> tags -> footer
- Tighten: less dead horizontal space, slightly smaller vertical footprint
- Prioritize: facts above tags in visual importance

### 2. Use breakpoint-specific preview sizing

- Tablet: `96px`
- Desktop: `112px` or `120px`

The current fixed `120px` preview is acceptable on desktop but too stubborn at tablet widths.

### 3. Remove the artificial text-width cap in the header

- Let the source and description use the true text column width
- Keep clamping, but avoid the wide empty gutter between text and preview

### 4. Create a stronger text hierarchy

- Source: smaller, quieter, but clearly separate from the description
- Description: slightly darker and more readable than source
- Facts: stronger than tags
- Tags: quieter and clearly optional

### 5. Give collections their own intentionally simple variant

- Collection badge + dataset count
- Title
- One-line description
- Footer timestamp

No empty space that implies a missing preview rail or missing metadata row.

## Sources

### Primary
- Live Playwright inspection of `http://localhost:8080`
- `frontend/src/components/search/SearchResultCard.tsx`
- `frontend/src/pages/SearchPage.tsx`
- `frontend/src/hooks/use-quicklook.ts`

### Supporting
- `.planning/quick/260329-ga7-search-results-card-ui-ux-restructure-st/260329-ga7-PLAN.md`
- `.planning/quick/260329-kq7-enhance-dataset-cards-with-quick-actions/260329-kq7-SUMMARY.md`
