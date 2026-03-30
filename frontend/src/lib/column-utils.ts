/** Canonical set of Postgres numeric column types for data-driven styling.
 *  Covers standard types plus common aliases (int4, float8, serial, etc.). */
const NUMERIC_TYPES = new Set([
  'integer', 'numeric', 'real', 'double', 'float',
  'bigint', 'smallint', 'int4', 'int8', 'int2', 'float4', 'float8',
  'double precision', 'int', 'serial', 'bigserial',
]);

/** Check if a column type string represents a numeric Postgres type. */
export function isNumericColumn(type: string): boolean {
  const t = type.toLowerCase();
  // Use Set.has for exact match, then fall back to includes for compound types
  return NUMERIC_TYPES.has(t) || [...NUMERIC_TYPES].some((nt) => t.includes(nt));
}
