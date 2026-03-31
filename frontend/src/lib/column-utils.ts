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
  if (NUMERIC_TYPES.has(t)) return true;
  // Fall back to substring match for compound types (e.g. "double precision")
  for (const nt of NUMERIC_TYPES) {
    if (t.includes(nt)) return true;
  }
  return false;
}
