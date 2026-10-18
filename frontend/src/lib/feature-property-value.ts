/**
 * Shared value formatter for feature/record properties, used by the map popup
 * (`FeaturePopup`) and the accessible data panel (`AccessibleMapDataPanel`) so
 * the same value renders the same way in both. Objects and arrays are
 * `JSON.stringify`d, since `String(value)` would render `[object Object]`.
 *
 * `null`/`undefined` return `null`: callers render their own empty text (the
 * popup uses "--", the panel "—").
 */
export function formatFeaturePropertyValue(
  value: unknown,
  locale: string,
  booleanTrue: string,
  booleanFalse: string,
  // Each caller states its own precision: the data panel renders raw feature
  // coordinates at 5 fraction digits, and the popup's 4-digit default dropped one.
  maxFractionDigits = 4,
): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'boolean') return value ? booleanTrue : booleanFalse;
  if (typeof value === 'number') {
    return Number.isInteger(value)
      ? value.toLocaleString(locale)
      : value.toLocaleString(locale, { maximumFractionDigits: maxFractionDigits });
  }
  if (typeof value === 'object') {
    // Circular structures throw in JSON.stringify; fall back to String()
    // rather than letting the popup/panel crash on a pathological value.
    try {
      return JSON.stringify(value) ?? String(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}
