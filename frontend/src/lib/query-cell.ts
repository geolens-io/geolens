/** Display text for one cell of an AI chat query result. */
export function formatQueryCell(raw: unknown): string {
  if (raw == null) return '';
  // A SUM or AVG over a double carries binary rounding noise past 15 significant
  // digits. Integers stay exact, since large IDs can need more digits than that.
  if (typeof raw === 'number' && !Number.isInteger(raw)) return String(Number(raw.toPrecision(15)));
  return String(raw);
}
