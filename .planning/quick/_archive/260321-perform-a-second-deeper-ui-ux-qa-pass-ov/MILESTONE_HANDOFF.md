# Milestone Handoff: Record Detail UI/UX Stabilization

## Executive Summary

The second-pass QA shows that desktop vector and raster detail pages are directionally solid, but the overall record-detail experience is not milestone-ready yet.

The two biggest user-facing problems are:
- the mobile dataset header shell collapses under the current action load; and
- the VRT preview still fails as a silent broken hero instead of a resilient product state.

The collection page adds a separate problem set: it still feels structurally different from the dataset detail family and now has confirmed accessibility defects in its metadata card.

Recommended milestone framing:
- Ship the next milestone as a focused record-detail stabilization cycle.
- Prioritize user-visible containment and failure handling before visual polish.
- Treat the collection semantics and mobile table accessibility issues as mandatory cleanup in the same milestone because they are low-effort, high-signal wins.

## Workstream A: Preview Resilience And Hero Composition

Why first:
- `F-001` is still a `P0`.
- The current VRT hero communicates backend failure only through console noise.
- Raster desktop still spends a large hero canvas on a small centered preview.

Acceptance criteria:
- VRT preview failures stop after a bounded retry budget and switch to an explicit in-UI error/fallback state.
- The VRT hero always shows one of:
  - a loaded preview,
  - a loading state,
  - a failure state with a retry affordance and explanatory copy.
- Raster desktop uses the hero intentionally:
  - either the preview occupies the canvas more effectively; or
  - the hero is restructured into preview plus quick facts so the whitespace feels deliberate.

Implementation guidance:
- Start in [`frontend/src/components/dataset/DatasetMap.tsx`](/Users/ishiland/Code/geolens/frontend/src/components/dataset/DatasetMap.tsx).
- Add raster/VRT tile-source error tracking and surface that state to the parent shell.
- Use [`frontend/src/pages/DatasetPage.tsx`](/Users/ishiland/Code/geolens/frontend/src/pages/DatasetPage.tsx) to swap in an error/empty-state overlay or a non-map fallback block for raster/VRT records.
- For a lightweight fallback, reuse the visual language from [`frontend/src/components/layout/BBoxPreview.tsx`](/Users/ishiland/Code/geolens/frontend/src/components/layout/BBoxPreview.tsx) and the existing quick-facts strip rather than inventing a new visual system.

Avoid:
- infinite tile retry loops;
- blank hero surfaces with no copy;
- desktop-only fixes that leave mobile VRT equally opaque.

How to verify:
- Re-run `npm run e2e -- e2e/record-detail-ux-audit.spec.ts --project=chromium`.
- Repeat a live Playwright browser pass on the VRT dataset.
- Success means:
  - the VRT manual screenshot is no longer visually blank;
  - console/network evidence no longer shows uncontrolled retry spam;
  - raster desktop feels intentionally composed.

## Workstream B: Responsive Header And Action Containment

Why second:
- This is the main day-to-day usability failure on mobile.
- Vector and VRT collapse into a `31px` title lane.
- Raster mobile overflows the viewport to `472px` and hides the H1 entirely.

Acceptance criteria:
- At `375x812`, dataset pages have no horizontal page overflow.
- The page title keeps a readable lane and never collapses below a practical width.
- The raster mobile header no longer hides the H1 when `Download COG` is present.
- Secondary actions collapse behind overflow or into a lower-priority row at the mobile breakpoint.

Implementation guidance:
- Primary touchpoints:
  - [`frontend/src/components/dataset/DatasetDetailHeader.tsx`](/Users/ishiland/Code/geolens/frontend/src/components/dataset/DatasetDetailHeader.tsx)
  - [`frontend/src/pages/DatasetPage.tsx`](/Users/ishiland/Code/geolens/frontend/src/pages/DatasetPage.tsx)
  - [`frontend/src/components/layout/PageHeader.tsx`](/Users/ishiland/Code/geolens/frontend/src/components/layout/PageHeader.tsx)
- The structural problem is not just the overflow menu. The `leadingContent` action group still occupies the same row as the title.
- The cleanest direction is usually:
  - title and metadata in a dedicated top block;
  - primary action(s) in a responsive row below;
  - overflow for everything else.
- Special-case raster mobile if needed so `Download COG` does not remain inline with `Add to Map` and `Connect`.

Avoid:
- solving this only by shrinking the H1 font;
- leaving all three CTAs inline and hoping truncation becomes acceptable;
- making desktop worse by forcing all actions into overflow.

How to verify:
- Re-run the audit spec and confirm the mobile failures disappear for vector, raster, and VRT.
- In a live browser pass:
  - vector title no longer stacks into seven short lines;
  - raster page does not scroll horizontally;
  - VRT title keeps a visible lane beside or above actions.

## Workstream C: Mobile Navigation And A11y Hardening

Why third:
- The detail shell is close enough that this is now a high-value polish pass.
- Several items are small code changes with meaningful UX payoff.

Acceptance criteria:
- Mobile tab triggers meet a practical touch target size.
- Tab overflow remains discoverable and usable on small screens.
- The shared scrollable table container is keyboard focusable.
- The VRT status badge passes color-contrast checks on desktop and mobile.

Implementation guidance:
- Touchpoints:
  - [`frontend/src/components/ui/tabs.tsx`](/Users/ishiland/Code/geolens/frontend/src/components/ui/tabs.tsx)
  - [`frontend/src/components/ui/table.tsx`](/Users/ishiland/Code/geolens/frontend/src/components/ui/table.tsx)
  - [`frontend/src/components/dataset/tabs/OverviewTab.tsx`](/Users/ishiland/Code/geolens/frontend/src/components/dataset/tabs/OverviewTab.tsx)
  - [`frontend/src/lib/status-colors.ts`](/Users/ishiland/Code/geolens/frontend/src/lib/status-colors.ts)
- Increase mobile tab height from the current `28px` to a real touch target and keep the row horizontally scrollable.
- Add focusability and a visible focus ring to the shared table container so overflow tables are reachable without a mouse.
- Replace the low-contrast VRT status badge styling with the existing semantic success token set.

Avoid:
- patching only one page; these are shared primitives;
- increasing tab width without increasing height;
- inventing a one-off VRT badge style when shared status tokens already exist.

How to verify:
- Audit run should go green for:
  - `raster_dataset mobile` axe;
  - `vrt_dataset desktop` axe;
  - `vrt_dataset mobile` axe.
- Manual mobile screenshots should show roomier tabs and clearer focus behavior during keyboard checks.

## Workstream D: Collection Shell Alignment And Semantics

Why fourth:
- Collection is not broken in the same way as VRT/mobile headers, but it still weakens the family-level UX.
- It also carries a confirmed serious semantics defect that is easy to fix while this surface is open.

Acceptance criteria:
- The collection metadata card uses valid semantics.
- The collection detail header remains readable on mobile without a four-line title squeeze.
- The page has an intentional secondary information architecture:
  - either aligned with dataset-detail wayfinding; or
  - clearly framed as a collection-first experience with equally deliberate section hierarchy.

Implementation guidance:
- Touchpoints:
  - [`frontend/src/pages/CollectionDetailPage.tsx`](/Users/ishiland/Code/geolens/frontend/src/pages/CollectionDetailPage.tsx)
  - [`frontend/src/components/collections/CollectionDatasetList.tsx`](/Users/ishiland/Code/geolens/frontend/src/components/collections/CollectionDatasetList.tsx)
  - [`frontend/src/components/layout/PageHeader.tsx`](/Users/ishiland/Code/geolens/frontend/src/components/layout/PageHeader.tsx)
- First, fix the semantics debt by moving the metadata block into a proper `<dl>`.
- Then decide whether collection should gain lightweight secondary navigation or a more intentional section rhythm so it stops feeling like an unrelated admin page.
- If the shell stays distinct, use stronger section framing and mobile spacing so the distinction feels chosen rather than unfinished.

Avoid:
- leaving the metadata card as div-wrapped `dt/dd`;
- making the collection page mimic dataset detail mechanically without a product reason;
- preserving the current mobile heading/actions layout unchanged.

How to verify:
- Axe should pass on collection desktop and mobile.
- Manual screenshots should show cleaner header composition and a more intentional section rhythm.
- The resulting page should feel like a peer detail surface, not a one-off list view.

## Low-Risk Easy Wins

These can land early in the milestone or as a first PR:
- Fix collection metadata semantics in [`frontend/src/pages/CollectionDetailPage.tsx`](/Users/ishiland/Code/geolens/frontend/src/pages/CollectionDetailPage.tsx).
- Make the shared table container focusable in [`frontend/src/components/ui/table.tsx`](/Users/ishiland/Code/geolens/frontend/src/components/ui/table.tsx).
- Swap the VRT success badge to semantic success tokens in [`frontend/src/components/dataset/tabs/OverviewTab.tsx`](/Users/ishiland/Code/geolens/frontend/src/components/dataset/tabs/OverviewTab.tsx).
- Raise mobile tab trigger height in [`frontend/src/components/ui/tabs.tsx`](/Users/ishiland/Code/geolens/frontend/src/components/ui/tabs.tsx).

## Suggested Milestone Exit Bar

Do not close the milestone until:
- VRT preview failure is user-visible and bounded;
- dataset mobile headers no longer collapse or overflow;
- collection and raster mobile axe failures are resolved;
- mobile tabs are no longer undersized.

