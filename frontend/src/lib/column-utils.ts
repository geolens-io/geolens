/** Canonical set of Postgres numeric column types for data-driven styling.
 *  Covers standard types plus common aliases (int4, float8, serial, etc.). */
const NUMERIC_TYPES = new Set([
  'integer', 'numeric', 'real', 'double', 'float',
  'bigint', 'smallint', 'int4', 'int8', 'int2', 'float4', 'float8',
  'double precision', 'int', 'serial', 'bigserial',
]);

/** Check if a column type string represents a numeric Postgres type. */
export function isNumericColumn(type: string): boolean {
  return NUMERIC_TYPES.has(type.toLowerCase());
}

// The column types the aggregate endpoint reads as numbers (column_stats._NUMERIC_TYPES),
// as information_schema names them.
const AGGREGATE_NUMERIC_TYPES = new Set([
  'smallint',
  'integer',
  'bigint',
  'decimal',
  'numeric',
  'real',
  'double precision',
  'money',
]);

/**
 * True for a column type the aggregate endpoint sums, averages and compares.
 * Unlike `isNumericColumn` it takes `money` and none of the aliases
 * information_schema never reports.
 */
export function isAggregateNumeric(type: string): boolean {
  return AGGREGATE_NUMERIC_TYPES.has(type.toLowerCase());
}

/** information_schema's names for PostgreSQL's text types. */
export const TEXT_COLUMN_TYPES: ReadonlySet<string> = new Set(['text', 'character varying', 'character']);

export function isTextColumn(type: string | null | undefined): boolean {
  return TEXT_COLUMN_TYPES.has((type ?? '').toLowerCase());
}

/** Check if a column type string represents a Postgres boolean. */
export function isBooleanColumn(type: string): boolean {
  const t = type.toLowerCase();
  return t === 'boolean' || t === 'bool';
}

const INTEGER_TYPES = new Set([
  'smallint', 'integer', 'bigint', 'int', 'int2', 'int4', 'int8',
  'serial', 'smallserial', 'bigserial',
]);

/** Check if a column type string represents a Postgres integer type. */
export function isIntegerColumn(type: string): boolean {
  return INTEGER_TYPES.has(type.toLowerCase());
}
