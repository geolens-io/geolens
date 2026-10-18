/**
 * Read-only helpers for inspecting MapLibre style expressions.
 *
 * Separate from `maplibre-filter-utils.ts`, which several hook suites mock
 * wholesale and would stub these helpers to undefined.
 */

/**
 * Does this expression read `column` anywhere inside it?
 *
 * Deliberately asks only whether the column is referenced AT ALL — never which `get` is
 * the "real" one. A hand-authored expression can read several columns, and guessing which
 * one a classification describes would delete hand-authored category colours on a wrong
 * guess (#461).
 */
export function expressionReadsColumn(value: unknown, column: string): boolean {
  if (!Array.isArray(value)) return false;
  if (value[0] === 'get' && value[1] === column) return true;
  return value.some((entry) => expressionReadsColumn(entry, column));
}
