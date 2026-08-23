/**
 * Shared value formatter for feature/record properties, used by the map
 * popup (`FeaturePopup`) and the accessible data panel (`AccessibleMapDataPanel`)
 * so the same property value renders the same way in both places.
 *
 * fix(#1627): the two components had drifted apart — the popup had no
 * object/array branch and fell through to `String(value)`, which rendered
 * `[object Object]` for an object-valued property. The data panel already
 * `JSON.stringify`d objects. Centralizing avoids a third copy drifting too.
 *
 * `null`/`undefined` return `null` — callers render their own existing empty
 * text (the popup uses "--", the panel uses "—") rather than sharing one
 * placeholder string.
 */
export function formatFeaturePropertyValue(
  value: unknown,
  locale: string,
  booleanTrue: string,
  booleanFalse: string,
  // fix(#1629 codex P2): the data panel formatted non-integer numbers to 5
  // fraction digits (it renders raw feature coordinates on the accessibility
  // surface); collapsing both callers onto the popup's 4-digit default
  // silently dropped a digit of precision there. Each caller now states its
  // own precision explicitly instead of inheriting the popup's.
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
