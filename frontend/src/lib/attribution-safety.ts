/**
 * fix(#1472 review): HTML-escaping for dataset credit lines on their way into
 * MapLibre.
 *
 * MapLibre renders attribution as HTML — `AttributionControl._updateAttributions`
 * assigns the joined string to `innerHTML`. Its own sanitizer is not a defense
 * for us: it removes `<script>` elements, `on*` handlers, and
 * `javascript:`/`data:` URLs, and leaves everything else standing, so
 * `<img src>`, `<iframe src>`, and inline `style` all survive it. A credit line
 * supplied by a dataset editor could otherwise beacon a viewer's IP or lay a
 * fixed-position overlay across every public, shared, and embedded map showing
 * that dataset — an anonymous-facing surface the editor cannot otherwise put
 * markup on.
 *
 * The backend rejects `<` and `>` on both write paths
 * (`core.text.reject_html_markup`), so in practice this escapes only the
 * ampersand in a name like "Rand & McNally" — which is the correct rendering
 * for an HTML target anyway. It is here so a value that predates that guard, or
 * arrives by a direct database write, renders as inert text rather than markup.
 *
 * Escape only. Do NOT use this for values rendered through React, which escapes
 * already and would show the entities literally.
 */
export function escapeAttributionHtml(credit: string): string {
  return credit
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

/**
 * Trim a credit line and escape it for MapLibre, or return null when the
 * dataset requires no credit. The single normalization every MapLibre
 * attribution boundary runs, so none of them can drift from the others.
 */
export function toMapLibreAttribution(
  credit: string | null | undefined,
): string | null {
  const trimmed = credit?.trim();
  if (!trimmed) return null;
  return escapeAttributionHtml(trimmed);
}
