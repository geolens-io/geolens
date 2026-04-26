/**
 * Popup template helpers — extract, validate, and substitute `{column_name}`
 * placeholders for the per-layer popup expression.
 *
 * No escape syntax: `\{` becomes literal text. `{}` (empty) and identifiers
 * starting with a digit (e.g. `{1bad}`) are never matched and are left
 * unchanged. React JSX text-node rendering is the only XSS gate — never
 * pass substituted output through `dangerouslySetInnerHTML`.
 */

const PLACEHOLDER_RE = /\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g;

/** Extract the unique, ordered list of placeholder keys from a template. */
export function extractPlaceholders(template: string): string[] {
  if (!template) return [];
  const out: string[] = [];
  for (const m of template.matchAll(PLACEHOLDER_RE)) {
    const key = m[1];
    if (!out.includes(key)) out.push(key);
  }
  return out;
}

/** Validate that every placeholder maps to a known column name. */
export function validatePlaceholders(
  placeholders: string[],
  knownColumns: string[],
): { ok: boolean; unknown: string[] } {
  const known = new Set(knownColumns);
  const unknown = placeholders.filter((k) => !known.has(k));
  return { ok: unknown.length === 0, unknown };
}

/**
 * Substitute placeholders against a feature property bag.
 * Missing / null / undefined values resolve to the empty string per the
 * locked spec. Other values are coerced to strings.
 */
export function substitutePopupTemplate(
  template: string,
  properties: Record<string, unknown> | null | undefined,
): string {
  if (!properties) return template.replace(PLACEHOLDER_RE, () => '');
  return template.replace(PLACEHOLDER_RE, (_match, key: string) => {
    const v = properties[key];
    if (v === null || v === undefined) return '';
    return String(v);
  });
}
