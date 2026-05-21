# Quick Task: Hero Collapse, Card Density, Create vs Import IA - Research

**Researched:** 2026-03-18
**Domain:** React UI/UX patterns, search page layout
**Confidence:** HIGH

## Summary

Three targeted improvements to the search page and navigation. All changes are localized to a small set of files with clear boundaries. No new dependencies needed -- all patterns use existing Tailwind classes and React state.

## 1. Hero Collapse on Scroll

### Current State

**File:** `frontend/src/pages/SearchPage.tsx` (lines 31-38)

The hero is a simple static block inside `<PageShell maxWidth="wide">`:
```tsx
<div className="text-center space-y-2">
  <h1 className="text-2xl font-semibold tracking-tight">{t('title')}</h1>
  <p className="text-muted-foreground text-sm">{t('subtitle')}</p>
</div>
<SearchBar />
```

**SearchBar** (`frontend/src/components/search/SearchBar.tsx`) is a self-contained component at `max-w-2xl mx-auto` with a rounded pill input (`h-12 pl-12 pr-10 text-lg rounded-full`). It manages its own state via `useSearchStore` and includes typeahead. It can render in any container without modification.

**PageShell** (`frontend/src/components/layout/PageShell.tsx`) applies `px-6 py-6 space-y-6` -- all children get 24px vertical gap via space-y-6.

**FilterPanel** (`frontend/src/components/search/FilterPanel.tsx`) is NOT sticky. It scrolls with the page content.

**No IntersectionObserver or scroll-based behavior exists** anywhere in the frontend codebase.

### Implementation Approach

Use a `useState` boolean (`collapsed`) toggled by an `IntersectionObserver` on a sentinel element at the top of the page. When the hero scrolls out of view:

1. Hide the h1 + subtitle (already gone from viewport)
2. Show a compact sticky header with just the SearchBar at a smaller size
3. The SearchBar component itself needs NO changes -- just render it twice (hero + sticky) or use CSS to reposition

**Recommended pattern:** Render a sentinel `<div ref={sentinelRef} />` above the hero. When it leaves the viewport, show a sticky compact bar. This avoids scroll event listeners and is performant.

```tsx
const [heroVisible, setHeroVisible] = useState(true);
const sentinelRef = useRef<HTMLDivElement>(null);

useEffect(() => {
  const el = sentinelRef.current;
  if (!el) return;
  const observer = new IntersectionObserver(
    ([entry]) => setHeroVisible(entry.isIntersecting),
    { threshold: 0 }
  );
  observer.observe(el);
  return () => observer.disconnect();
}, []);
```

**Sticky bar placement:** Render OUTSIDE the `<PageShell>` (before it) or use `sticky top-0 z-10` within the page. Since the Navbar is `border-b bg-background` with no sticky positioning (`frontend/src/components/layout/Navbar.tsx` line 282), the sticky search bar should go directly below the navbar area OR make the whole header area sticky.

**Key decision:** The sticky bar should sit just below the navbar (which is already static at top). Use `sticky top-[57px]` (navbar is `h-14` = 56px + 1px border) on the compact search wrapper.

### Files to Modify
- `frontend/src/pages/SearchPage.tsx` -- add sentinel, IntersectionObserver, conditional sticky bar
- No changes needed to `SearchBar.tsx` -- render it as-is in both contexts
- Consider adding `compact` className variant to SearchBar for smaller height in sticky mode

## 2. Card Density

### Current State

**File:** `frontend/src/components/search/DatasetCard.tsx`

Card structure (line 79):
```
Card (flex-col sm:flex-row, py-0, gap-0)
  Metadata section (flex-1, p-4)
    Title (text-lg font-semibold, line-clamp-2 sm:line-clamp-1)
    Description (mt-1.5, text-sm, line-clamp-2)
    Badges row (mt-2, flex-wrap, gap-2) -- record type, geometry, feature count, CRS, org, quality
    Keywords row (mt-2, flex-wrap, gap-1) -- up to 3 tags
    Provenance row (mt-2.5, text-xs) -- "Updated by X - time ago"
  Preview section (hidden sm:block, sm:w-48, sm:p-4)
    BBoxPreview or quicklook image
```

**Gap between cards:** Results list uses `space-y-4` (line 89 of SearchPage.tsx) = 16px gap between cards.

**Card padding:** `p-4` on metadata section = 16px all sides. Preview section also `sm:p-4`.

### Density Improvements

The card is already fairly lean. Specific tightening opportunities:

1. **Reduce inter-card gap:** `space-y-4` -> `space-y-3` (16px -> 12px)
2. **Reduce card padding:** `p-4` -> `p-3` on metadata section (16px -> 12px)
3. **Tighten internal spacing:** `mt-2` gaps between sections -> `mt-1.5`, `mt-2.5` -> `mt-2`
4. **Preview width:** `sm:w-48` (192px) is generous. Could reduce to `sm:w-40` (160px) or `sm:w-36` (144px)
5. **Preview padding:** `sm:p-4` -> `sm:p-3`
6. **Skeleton should match** (`frontend/src/components/search/DatasetCardSkeleton.tsx`)

### What's Already Good
- Description is already `line-clamp-2` (capped)
- Keywords limited to 3 + overflow count
- Badges are compact (`text-xs`)
- Title is `line-clamp-1` on desktop

### Files to Modify
- `frontend/src/components/search/DatasetCard.tsx` -- tighten padding/margins
- `frontend/src/components/search/DatasetCardSkeleton.tsx` -- match new sizing
- `frontend/src/pages/SearchPage.tsx` -- reduce `space-y-4` on results list

## 3. Create vs Import IA

### Current State

**"Import" nav link** in `frontend/src/components/layout/Navbar.tsx`:
- Desktop: line 302-304 -- `<NavLink to="/import">` shown to users with `can('upload')` permission
- Mobile: line 219-222 -- same NavLink in mobile drawer

**Import page** (`frontend/src/pages/ImportPage.tsx`):
- Three tabs: **Upload** (file upload), **Register** (register existing file path), **Service** (register URL)
- These are the primary ways to ADD DATA with files/paths to the system

**"Create" dropdown** in `frontend/src/components/layout/Navbar.tsx` (lines 42-92, `CreateMenu` component):
- **Dataset** -- `CreateDatasetDialog`: creates an EMPTY dataset with schema columns (no data upload)
- **Collection** -- `CollectionCreateDialog`: creates a collection (grouping container)
- **Map** -- `MapCreateDialog`: creates a map view
- **Virtual Raster** -- `VrtCreateDialog`: creates a VRT mosaic from existing rasters

### Analysis: Overlap and Distinction

| Action | Create Menu | Import Page | Overlap? |
|--------|------------|-------------|----------|
| Empty dataset (define schema) | Yes (CreateDatasetDialog) | No | No overlap |
| Upload file -> dataset | No | Yes (Upload tab) | No overlap |
| Register path -> dataset | No | Yes (Register tab) | No overlap |
| Register URL -> dataset | No | Yes (Service tab) | No overlap |
| Create collection | Yes | No | No overlap |
| Create map | Yes | No | No overlap |
| Create VRT | Yes | No | No overlap |

**Key finding:** There is NO functional overlap. "Create Dataset" makes an empty schema-defined dataset. "Import" brings in actual data files. They are complementary, not duplicative.

**The UX confusion** is purely nomenclature -- users think "Create" and "Import" both mean "add a dataset." The mental model is:
- "I want to add data" -> which one do I click?

### Recommendation

Fold Import into the Create menu as "Import Data" or "Upload Dataset":

1. Add an "Import Data" item to the Create dropdown that navigates to `/import`
2. Remove the top-level "Import" NavLink from the navbar
3. This reduces nav items and groups all "add stuff" actions under Create

The Import PAGE itself stays as-is -- it's a full page with tabs that makes sense for the upload workflow. Only the navigation entry point changes.

### Files to Modify
- `frontend/src/components/layout/Navbar.tsx`:
  - Remove `<NavLink to="/import">` from desktop nav (line 302-304) and mobile nav (line 219-222)
  - Add `<DropdownMenuItem>` with `<Link to="/import">` in CreateMenu (after Dataset item)
  - Add same in MobileNav create section
- Route definition stays the same (the page still exists at `/import`)

## Common Pitfalls

1. **Sticky z-index conflicts:** The FilterPanel popovers (bbox map, date picker) use `z-50`. The sticky search bar needs `z-30` or `z-40` to sit below popover content but above page content.

2. **Double SearchBar state:** If rendering two SearchBar instances (hero + sticky), they share the same zustand store, so they stay in sync. However, focus state and typeahead will be independent -- ensure the sticky bar's typeahead doesn't render behind the hero content.

3. **IntersectionObserver threshold:** Use `threshold: 0` (any pixel leaving viewport triggers). Using `threshold: 1` would only trigger when fully out of view, causing a jarring late transition.

4. **Card density and touch targets:** Don't reduce padding below `p-3` (12px) -- smaller makes touch targets too small on mobile.

5. **Import nav removal accessibility:** Ensure the Create dropdown is discoverable for keyboard users. The existing dropdown uses proper ARIA attributes via Radix UI, so this should be fine.

## Sources

All findings from direct codebase inspection (HIGH confidence):
- `frontend/src/pages/SearchPage.tsx`
- `frontend/src/components/search/SearchBar.tsx`
- `frontend/src/components/search/DatasetCard.tsx`
- `frontend/src/components/search/DatasetCardSkeleton.tsx`
- `frontend/src/components/search/FilterPanel.tsx`
- `frontend/src/components/layout/Navbar.tsx`
- `frontend/src/components/layout/PageShell.tsx`
- `frontend/src/pages/ImportPage.tsx`
- `frontend/src/components/create/CreateDatasetDialog.tsx`
