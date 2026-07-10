/**
 * Canonical "eyebrow" treatment for sidebar/section card titles on the dataset
 * detail page — the single source of truth for the mono-caps section marker.
 *
 * This is the strong tier of the page's two-tier label system: mono-caps section
 * *markers* (this style) vs. quiet sans field *labels* (see SideKV). Heading
 * semantics are applied at each call site via `<CardTitle level={n}>` — the page
 * gives every section card an h2/h3 for a valid outline; this constant owns only
 * the visual treatment, so the tier can evolve in one place.
 */
export const SECTION_EYEBROW =
  'text-mini font-mono font-semibold uppercase tracking-[0.1em] text-foreground/70';
