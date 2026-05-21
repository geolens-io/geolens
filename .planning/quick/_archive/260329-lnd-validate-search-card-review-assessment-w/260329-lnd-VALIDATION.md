# Search Card Review — Playwright Validation Report

**Validated:** 2026-03-29
**Review under test:** 260330-REVIEW.md
**Method:** Live Playwright MCP inspection at http://localhost:8080

---

## Summary

| # | Finding | Review Severity | Validated Severity | Verdict |
|---|---------|----------------|-------------------|---------|
| 1 | Empty state and collection card shown simultaneously | HIGH | HIGH | confirmed |
| 2 | max-w-3xl creates dead gutter on desktop | MEDIUM-HIGH | MEDIUM-HIGH | confirmed |
| 3 | Tags visually heavier than specs/facts | MEDIUM | MEDIUM | confirmed |
| 4 | Preview failure shows weak icon-only fallback | MEDIUM | LOW-MEDIUM | revised |
| 5 | Collection card sparse, not intentionally designed | LOW-MEDIUM | LOW-MEDIUM | confirmed |

---

## Finding 1: Empty state and collection card shown simultaneously

### Review Claim

Searching `Natural Earth Cultural` renders both `No results found` empty state and a valid collection card in the same viewport. The API returns `numberMatched: 0` but also `numberReturned: 1` with one `collection` feature. The page shows the empty state from `numberMatched === 0` and the card from `features.length > 0` — two independent conditionals that are not mutually exclusive.

### Playwright Evidence

Navigated to `http://localhost:8080/?q=Natural+Earth+Cultural` (viewport 1440x900). Network response intercepted from `/api/search/datasets/?q=Natural+Earth+Cultural`:

```
numberMatched: 0
numberReturned: 1
features.length: 1
features[0].record_type: "collection"
```

DOM state after render:

```
page.locator('text=No results found').count() → 1   (EmptyState rendered)
page.locator('[data-testid="search-result-card"]').count() → 1   (Card rendered)
```

Body text confirmed both elements simultaneously:

```
"0 results ... No results found ... Try adjusting your search query or filters
Collection  71 datasets  Natural Earth Cultural (10m) ..."
```

The filter bar also showed `All (0)` which makes the single card visible below it feel like a ghost.

### Verdict: confirmed

### Severity Assessment

HIGH is correct. This is a logic bug that makes the card surface feel untrustworthy. The user sees a count of 0 results and a "no results" message while a card is clearly rendered below. This actively contradicts itself and damages confidence in the search feature. Severity is not overstated.

---

## Finding 2: Desktop cards waste horizontal space, preview feels detached

### Review Claim

At 1440px viewport, cards are 1104px wide with 120px preview. Source and description text are capped at `max-w-3xl` (768px), leaving unused space between the text block and the preview tile. The preview reads as a floating ornament rather than part of the card.

### Playwright Evidence

Measured at 1440x900 viewport on a `?q=land` search result (first card):

```
Card width:           1104px
Card left (x):         168px
Source text width:     768px  (maxWidth computed: 768px)
Source text height:     40px  (two-line wrap)
Description width:     768px  (maxWidth computed: 768px)
Preview img x:        1133px  (absolute)
Preview img width:     118px
```

Dead gutter calculation:
- Text column right edge: 168 (card x) + 20 (padding estimate) + 768 (text) = ~956px absolute
- Preview left edge: 1133px absolute
- Dead gutter: **197px** between text right edge and preview left edge

This was reproduced on the Riparian Integrity Score card (long source case) with identical measurements: 768px text block, 197px dead space, 118px preview.

Tablet (900px viewport) was also measured:
```
Card width:    852px
Source width:  680px  (constrained by column, not by max-w-3xl cap)
Preview x:     737px absolute
```
At tablet width the text column is naturally constrained (~680px) so the dead gutter is smaller but still present.

### Verdict: confirmed

### Severity Assessment

MEDIUM-HIGH is correct. This is not broken functionality, but the dead horizontal band makes cards feel airy in the wrong place. At 1440px, 197px of dead gutter between text and preview is visually conspicuous. The review's characterization of the preview feeling "detached" matches the measured geometry.

---

## Finding 3: Information hierarchy is flatter than it should be

### Review Claim

Source, description, facts, and keywords do not form a clear visual priority order. Keyword pills have more visual weight than the facts row even though facts are more important for quick scanning. In long-source cases, source and description collapse into one indistinct muted block.

### Playwright Evidence

Computed styles extracted from a card with both specs and tags (`?q=land`, first result):

```
Source element:
  fontSize: 13px  fontWeight: 400  color: oklab(0.556 0 0 / 0.9)  border: none  background: none

Description element:
  fontSize: 13px  fontWeight: 400  color: oklab(0.556 0 0 / 0.8)  border: none  background: none

Spec span (inside dataset-card-specs):
  fontSize: 12px  fontWeight: 400  border: none  background: transparent  padding: 0

Tag pill (keyword):
  fontSize: 12px  fontWeight: 500  border: 1px solid oklab(0.922 0 0 / 0.5)
  background: oklab(0.97 0 0 / 0.3)  padding: 4px 10px
```

The contrast between specs and tags is measurable:
- Specs: plain text, weight 400, no border, no background, no padding
- Tags: weight **500**, **1px border**, colored background, **10px horizontal padding**

Additionally, source and description share identical font size (13px) and weight (400), differing only in a small color opacity difference (0.9 vs 0.8). In the Riparian card the source was 250 characters with a 40px two-line block, matching the description height — confirming the review's "two same-weight muted text blocks" observation.

Multiple cards with both specs and tags were confirmed (all 11 visible cards on the `?q=land` search had both spec rows and tag pills).

### Verdict: confirmed

### Severity Assessment

MEDIUM is correct. This is a hierarchy design issue, not a functional bug. The visual weight imbalance between specs and tags is real and measurable (font-weight 400 vs 500, no decoration vs border+background). However, it does not break usability — users can still read the card. The severity aligns with the scope of work needed: CSS changes only, no logic changes.

---

## Finding 4: Preview failure states feel accidental

### Review Claim

Live Playwright inspection produced quicklook 404s for some cards. The error fallback is a muted container with a small `ImageOff` icon but no explanatory label or alternate content. The `BBoxPreview` fallback only handles the case where quicklook is disabled/null, not error cases.

### Playwright Evidence

Intercepted all quicklook requests via `page.route('**/api/datasets/**quicklook**', ...)` returning 404 for all requests, then measured the resulting state:

```
Cards found: 11
Per card (with forced 404s):
  imgCount: 0   (no images loaded, as expected)
  svgCount: 5   (4 icon SVGs + 1 ImageOff fallback SVG)
  innerText: no "Preview unavailable" or similar text
```

Preview container dimensions (120x120px box with 1 child SVG, no text):

```
previewContainers[0]:
  width:  120px
  height: 120px
  innerText: ""   (empty)
  childCount: 1
  svgCount: 1
  imgCount: 0
```

Fallback text search across all visible text:
```
"Preview unavailable" → not found
"No preview"          → not found
"Image unavailable"   → not found
"No image"            → not found
```

The finding is technically confirmed: the error state renders as an empty 120x120 square with a single small icon, no text label, and no alternate content.

**However**, on natural page load (no interception), all 11 cards in the `?q=land` search had images loading from blob URLs successfully. The review claimed "Playwright logged live quicklook 404s for some results" — this was not reproduced during this validation pass. The quicklook endpoint returned 200 for multiple tested datasets.

The finding is confirmed by code path verification and forced 404 interception, but the natural occurrence of quicklook failures appears rare or absent in the current dataset population.

### Verdict: revised

The code path for a weak fallback is real and confirmed by interception testing. However, the review's severity rating of MEDIUM implies this is a frequent visible issue. In practice, no natural quicklook failures were observed during validation. The weak fallback is a latent quality issue, not a routinely visible problem.

**Revised severity: LOW-MEDIUM** — the code path exists and should be improved, but it does not currently affect most users' experience. The review's MEDIUM rating slightly overstates the visibility of this issue in the current dataset.

---

## Finding 5: Collection card is sparse, not intentionally designed

### Review Claim

The collection card uses the same `SearchResultCard` component as datasets, with `isCollection` guards removing preview, specs, and tags. This leaves a wide sparse card that feels like a dataset card with sections removed, not an intentionally designed variant.

### Playwright Evidence

Collection card measured at 1440x900 (query: `?q=Natural+Earth+Cultural`):

```
Collection card:
  width:    1104px
  height:    148.5px
  hasSpecs: false
  hasTags:  false (no keyword pills — "Collection" badge is a RecordTypeBadge, not a tag)
  hasImg:   false
  hasSvg:   true  (RecordTypeBadge icon)
```

Card inner text:
```
"Collection
71 datasets
Natural Earth Cultural (10m)

Natural Earth 1:10m cultural vector datasets

Updated yesterday"
```

Comparison with dataset cards from the same viewport:
```
Dataset card heights: 270.5px, 250.5px, 208px
Collection card height: 148.5px
```

The collection card is 44% the height of a full dataset card (148.5 vs 270.5). At 1104px wide with only a title, one-line description, and timestamp, the card has a pronounced horizontal spread relative to its content density.

The card does render all the content described in the review — badge, count, title, description, footer. But there are no structural design decisions that make the spare layout feel intentional (e.g., no visual differentiation, no different padding rhythm, no alternative layout for the missing preview space).

### Verdict: confirmed

### Severity Assessment

LOW-MEDIUM is correct. Collections render correctly and are not confusing. The issue is purely about visual design quality: the card looks like a dataset card with pieces removed rather than a purposefully compact card. This is the lowest-priority item in the set and the severity matches that priority.

---

## Overall Assessment

The review is **highly accurate**. All 5 findings are confirmed against live evidence, with one severity revision:

- **Findings 1, 2, 3, 5:** Exactly as described. Line references correct, severity ratings appropriate.
- **Finding 4:** The code path for weak fallback is real, but natural quicklook failures were not observed in the current dataset. Severity revised down from MEDIUM to LOW-MEDIUM.

**Pattern:** The review does not over-claim. Findings 1 through 3 are clearly observable, and finding 4 is a latent defect rather than an actively broken state. The line references in the review were checked in the research phase and all matched the source code. This review is trustworthy and the recommendations are actionable.

**Fix priority order (unchanged from review):**
1. Fix the empty state / collection card contradiction (Finding 1) — logic bug
2. Remove max-w-3xl dead gutter in header (Finding 2) — CSS change
3. Rebalance spec vs tag visual weight (Finding 3) — CSS change
4. Create intentional collection card variant (Finding 5) — component design
5. Improve preview fallback label/content (Finding 4) — low priority, latent issue
