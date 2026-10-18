/**
 * HTML-escaping for dataset credit lines on their way into MapLibre.
 *
 * MapLibre assigns the joined attribution string to `innerHTML`
 * (`AttributionControl._updateAttributions`). Its sanitizer removes `<script>`,
 * `on*` handlers and `javascript:`/`data:` URLs but leaves `<img src>`,
 * `<iframe src>` and inline `style`, so an editor-supplied credit could beacon a
 * viewer's IP or lay a fixed-position overlay across every public, shared and
 * embedded map showing that dataset.
 *
 * The backend rejects `<` and `>` on both write paths
 * (`core.text.reject_html_markup`), so in practice this escapes only the
 * ampersand in a name like "Rand & McNally". It exists so a value that predates
 * that guard, or arrives by a direct database write, renders as inert text.
 *
 * Escape only. Don't use this for values rendered through React, which escapes
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
