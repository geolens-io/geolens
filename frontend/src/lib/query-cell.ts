// A SUM or AVG over doubles carries binary rounding error in its last digits
// (491.9000000000001, 7708611.570000037, 92.799999999999). Pattern checks on the
// digits miss some of it, so a non-integer shows at most 12 significant digits,
// about what a result cell fits before it truncates. The result tables keep the
// exact value in each cell's title.
const DISPLAY_DIGITS = 12;

/** Display text for one cell of an AI chat query result. */
export function formatQueryCell(raw: unknown): string {
  if (raw == null) return '';
  if (typeof raw === 'number' && !Number.isSafeInteger(raw)) {
    return String(Number(raw.toPrecision(DISPLAY_DIGITS)));
  }
  return String(raw);
}
