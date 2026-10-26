import type { FilterSpecification } from 'maplibre-gl';

/**
 * Single source of truth for the *editable* MapLibre filter-expression subset
 * the map builder authors and recognizes.
 *
 * Supported grammar subset (deliberate scope — anything else round-trips as an
 * opaque, uneditable filter):
 *   - comparisons:        ==, !=, >, <, >=, <=   over ["get", field], or the
 *                         null-safe pair this module emits for numeric columns,
 *                         ["all", ["!=", ["typeof", ["get", field]], "null"],
 *                         [op, ["to-number", ["get", field], fallback], n]], and
 *                         the bare ["to-number", ["get", field], fallback] accessor.
 *   - membership:         ["in", ["get", field], ["literal", [...]]]   (in_list)
 *                         ["!", ["in", ["get", field], ["literal", [...]]]] (not_in_list)
 *   - substring/contains: ["in", <scalar>, ["get", field]]
 *   - existence:          ["has", field]
 *   - null test:          ["any", ["!", ["has", f]], ["==", ["get", f], null]]
 *                         (and the legacy short form ["!", ["has", f]])
 *   - combinators:        single-level ["all", ...] / ["any", ...]
 *
 * Both the structured editor (LayerFilterEditor) and the chip summarizer
 * (ActiveFilterChips) consume `parseCanonicalFilter` so the two recognizers
 * cannot drift.
 */

// The canonical comparison-operator set, shared by LayerFilterEditor and
// ActiveFilterChips.
export const NUMERIC_COMPARISON_OPERATORS = new Set(['==', '!=', '>', '<', '>=', '<=']);

function isGetExpression(value: unknown): value is ['get', string] {
  return Array.isArray(value) && value[0] === 'get' && typeof value[1] === 'string';
}

const NUMERIC_LOW_SENTINEL = -1_000_000_000_000;
const NUMERIC_HIGH_SENTINEL = 1_000_000_000_000;

function numericFallbackForOperator(operator: string, comparisonValue: number) {
  if (operator === '<' || operator === '<=') return NUMERIC_HIGH_SENTINEL;
  if (comparisonValue === NUMERIC_LOW_SENTINEL) return NUMERIC_HIGH_SENTINEL;
  return NUMERIC_LOW_SENTINEL;
}

/**
 * A numeric comparison that a null or missing value never satisfies, as in SQL.
 * `to-number` still reads a numeric string, but it turns null into 0, so the
 * value's type is checked for null first.
 */
export function buildNullSafeNumericComparison(
  field: string,
  operator: string,
  comparisonValue: number,
  negated = false,
) {
  const comparison = [
    operator,
    ['to-number', ['get', field], numericFallbackForOperator(operator, comparisonValue)],
    comparisonValue,
  ];
  // The guard stays outside a negation, or `!` would turn a null into a match.
  return ['all', ['!=', ['typeof', ['get', field]], 'null'], negated ? ['!', comparison] : comparison];
}

/** A `buildNullSafeNumericComparison(..., true)` result, else false. */
function guardedNegation(node: unknown): boolean {
  if (!Array.isArray(node) || node.length !== 3 || node[0] !== 'all') return false;
  const field = nullGuardField(node[1]);
  const negation = node[2];
  const inner = Array.isArray(negation) && negation[0] === '!' ? bareNumericComparison(negation[1]) : null;
  return field !== null && inner !== null && inner.field === field;
}

/** `[op, ["get", f] | ["to-number", ["get", f], ...], n]` as its parts, else null. */
function bareNumericComparison(
  node: unknown,
): { field: string; operator: string; value: number } | null {
  if (!Array.isArray(node) || node.length < 3) return null;
  const [operator, left, right] = node;
  if (
    typeof operator !== 'string' ||
    !NUMERIC_COMPARISON_OPERATORS.has(operator) ||
    typeof right !== 'number'
  ) {
    return null;
  }
  if (isGetExpression(left)) return { field: left[1], operator, value: right };
  if (Array.isArray(left) && left[0] === 'to-number' && isGetExpression(left[1])) {
    return { field: left[1][1], operator, value: right };
  }
  return null;
}

/** The field of `["!=", ["typeof", ["get", field]], "null"]`, else null. */
function nullGuardField(node: unknown): string | null {
  return Array.isArray(node) &&
    node.length === 3 &&
    node[0] === '!=' &&
    Array.isArray(node[1]) &&
    node[1][0] === 'typeof' &&
    isGetExpression(node[1][1]) &&
    node[2] === 'null'
    ? node[1][1][1]
    : null;
}

/** The comparison of a `buildNullSafeNumericComparison` pair, else null. */
function guardedComparison(node: unknown): unknown[] | null {
  if (!Array.isArray(node) || node.length !== 3 || node[0] !== 'all') return null;
  const field = nullGuardField(node[1]);
  const comparison = node[2];
  return field !== null &&
    Array.isArray(comparison) &&
    comparison.length === 3 &&
    typeof comparison[0] === 'string' &&
    NUMERIC_COMPARISON_OPERATORS.has(comparison[0]) &&
    Array.isArray(comparison[1]) &&
    comparison[1][0] === 'to-number' &&
    isGetExpression(comparison[1][1]) &&
    comparison[1][1][1] === field &&
    typeof comparison[2] === 'number'
    ? comparison
    : null;
}

export interface CanonicalFilterCondition {
  field: string;
  operator: string;
  /** Editor string form: comma-joined for lists, '' for is_null / has. */
  value: string;
  /** Raw right-hand-side for comparison / contains ops (used for chip display). */
  rawValue?: unknown;
  /** Parsed literal values for in_list / not_in_list (used for chip preview). */
  listValues?: unknown[];
  /** A numeric comparison a null value never satisfies. */
  toNumber?: true;
}

type CanonicalFilter =
  | { kind: 'editable'; combinator: 'all' | 'any'; conditions: CanonicalFilterCondition[] }
  | { kind: 'opaque'; raw: FilterSpecification };

/** Recognize a single (non-combinator) filter node. Returns null if unsupported. */
function parseSingleCondition(e: unknown): CanonicalFilterCondition | null {
  if (!Array.isArray(e) || e.length === 0) return null;

  // is_null full pattern: ["any", ["!", ["has", f]], ["==", ["get", f], null]]
  if (
    e[0] === 'any' &&
    e.length === 3 &&
    Array.isArray(e[1]) && e[1][0] === '!' && Array.isArray(e[1][1]) && e[1][1][0] === 'has' &&
    Array.isArray(e[2]) && e[2][0] === '==' && Array.isArray(e[2][1]) && e[2][1][0] === 'get' && e[2][2] === null &&
    e[1][1][1] === e[2][1][1]
  ) {
    return { field: e[1][1][1] as string, operator: 'is_null', value: '' };
  }

  // is_null legacy short form: ["!", ["has", f]]
  if (e[0] === '!' && Array.isArray(e[1]) && e[1][0] === 'has') {
    return { field: e[1][1] as string, operator: 'is_null', value: '' };
  }

  // not_in_list: ["!", ["in", ["get", f], ["literal", [...]]]]
  if (
    e[0] === '!' &&
    Array.isArray(e[1]) && e[1][0] === 'in' &&
    Array.isArray(e[1][1]) && e[1][1][0] === 'get' &&
    Array.isArray(e[1][2]) && e[1][2][0] === 'literal' && Array.isArray(e[1][2][1])
  ) {
    const list = e[1][2][1] as unknown[];
    return { field: e[1][1][1] as string, operator: 'not_in_list', value: list.join(', '), listValues: list };
  }

  // in_list: ["in", ["get", f], ["literal", [...]]]
  if (
    e[0] === 'in' &&
    Array.isArray(e[1]) && e[1][0] === 'get' &&
    Array.isArray(e[2]) && e[2][0] === 'literal' && Array.isArray(e[2][1])
  ) {
    const list = e[2][1] as unknown[];
    return { field: e[1][1] as string, operator: 'in_list', value: list.join(', '), listValues: list };
  }

  // contains (substring): ["in", value, ["get", f]]
  if (e[0] === 'in' && Array.isArray(e[2]) && e[2][0] === 'get') {
    return { field: e[2][1] as string, operator: 'contains', value: String(e[1]), rawValue: e[1] };
  }

  // has: ["has", f]
  if (e[0] === 'has' && typeof e[1] === 'string') {
    return { field: e[1], operator: 'has', value: '' };
  }

  // null-safe numeric comparison: ["all", ["!=", ["typeof", ["get", f]], "null"], [op, ["to-number", ["get", f], fb], n]]
  const guarded = guardedComparison(e);
  if (guarded) {
    return {
      field: ((guarded[1] as unknown[])[1] as ['get', string])[1],
      operator: guarded[0] as string,
      value: String(guarded[2]),
      rawValue: guarded[2],
      toNumber: true,
    };
  }

  // standard comparison: [op, ["get", f], value]
  if (Array.isArray(e[1]) && e[1][0] === 'get') {
    return { field: e[1][1] as string, operator: e[0] as string, value: String(e[2] ?? ''), rawValue: e[2] };
  }

  // numeric-safe comparison: [op, ["to-number", ["get", f], fallback], value]
  if (
    Array.isArray(e[1]) &&
    e[1][0] === 'to-number' &&
    Array.isArray(e[1][1]) &&
    e[1][1][0] === 'get'
  ) {
    return {
      field: e[1][1][1] as string,
      operator: e[0] as string,
      value: String(e[2] ?? ''),
      rawValue: e[2],
      toNumber: true,
    };
  }

  return null;
}

/**
 * Parse a MapLibre filter into the canonical editable structure (condition list
 * + combinator) or an opaque passthrough. The exact `raw` reference is
 * preserved for opaque filters so callers can round-trip them untouched.
 */
export function parseCanonicalFilter(expr: FilterSpecification | null | undefined): CanonicalFilter {
  if (!expr || !Array.isArray(expr) || expr.length === 0) {
    return { kind: 'editable', combinator: 'all', conditions: [] };
  }

  // Try the whole expression as a single condition first (covers the is_null
  // "any" compound, which must not be mistaken for a generic "any" combinator).
  const single = parseSingleCondition(expr);
  if (single) {
    return { kind: 'editable', combinator: 'all', conditions: [single] };
  }

  if (expr[0] === 'all' || expr[0] === 'any') {
    const combinator = expr[0] as 'all' | 'any';
    const conditions: CanonicalFilterCondition[] = [];
    for (let i = 1; i < expr.length; i++) {
      if (!Array.isArray(expr[i])) return { kind: 'opaque', raw: expr };
      const parsed = parseSingleCondition(expr[i]);
      if (parsed === null) return { kind: 'opaque', raw: expr };
      conditions.push(parsed);
    }
    return { kind: 'editable', combinator, conditions };
  }

  return { kind: 'opaque', raw: expr };
}

// Mirrors backend/app/modules/catalog/maps/filter_grammar.py:validate_filter so
// a filter accepted in the raw-JSON editor is accepted, stored, exported, and
// replayed identically. Accepts None/[] as "clear", normalizes the legacy
// bare-field comparison form into expression form, rejects malformed recognized
// forms (wrong arity, non-string operator, legacy bare-field `in`), and
// explicitly PRESERVES structurally-valid opaque filters (match/step/case/...).

const RAW_COMBINATORS = new Set(['all', 'any']);
// Legacy MapLibre pseudo-fields resolved by the renderer, NOT feature props —
// they must NOT be rewritten to ["get", ...].
const RAW_LEGACY_PSEUDO_FIELDS = new Set(['$type', '$id']);

export class FilterValidationError extends Error {}

function isGetNode(node: unknown): boolean {
  return Array.isArray(node) && node.length >= 2 && node[0] === 'get';
}

function normalizeFilterNode(node: unknown): unknown {
  if (!Array.isArray(node)) {
    throw new FilterValidationError(`filter expression must be a JSON array, got ${typeof node}`);
  }
  if (node.length === 0) {
    throw new FilterValidationError('filter expression must not be an empty array');
  }

  const op = node[0];
  if (typeof op !== 'string') {
    throw new FilterValidationError('filter expression operator (first element) must be a string');
  }

  if (RAW_COMBINATORS.has(op)) {
    return [
      op,
      ...node.slice(1).map((child) => (Array.isArray(child) ? normalizeFilterNode(child) : child)),
    ];
  }

  if (op === '!') {
    if (node.length !== 2) {
      throw new FilterValidationError("'!' filter takes exactly one operand: ['!', <expression>]");
    }
    const inner = node[1];
    return Array.isArray(inner) ? ['!', normalizeFilterNode(inner)] : node;
  }

  if (op === 'has') {
    if (node.length !== 2 || typeof node[1] !== 'string') {
      throw new FilterValidationError("'has' filter takes a single field name: ['has', <field>]");
    }
    return node;
  }

  if (op === 'in') {
    // in_list:  ["in", ["get", f], ["literal", [...]]]
    if (
      node.length === 3 &&
      isGetNode(node[1]) &&
      Array.isArray(node[2]) &&
      node[2].length > 0 &&
      node[2][0] === 'literal'
    ) {
      return node;
    }
    // contains: ["in", <scalar>, ["get", f]]
    if (node.length === 3 && isGetNode(node[2])) return node;
    // Legacy bare-field "in" (["in", "field", v0, ...]) is rejected with guidance.
    if (node.length >= 2 && typeof node[1] === 'string') {
      throw new FilterValidationError(
        "legacy 'in' filter form is not supported; use ['in', ['get', <field>], ['literal', [...]]]",
      );
    }
    return node;
  }

  if (NUMERIC_COMPARISON_OPERATORS.has(op)) {
    if (node.length !== 3) {
      throw new FilterValidationError(
        `comparison filter '${op}' takes exactly two operands: ['${op}', <field-expression>, <value>]`,
      );
    }
    const operand = node[1];
    if (Array.isArray(operand)) return node;
    if (typeof operand === 'string') {
      if (RAW_LEGACY_PSEUDO_FIELDS.has(operand)) return node;
      // Legacy bare-field comparison — normalize to expression form.
      return [op, ['get', operand], node[2]];
    }
    return node;
  }

  // Unknown / unsupported operator (match, step, case, coalesce, interpolate,
  // geometry-type, ...) — explicitly PRESERVE the opaque filter, do not crash.
  return node;
}

/**
 * Validate + normalize a raw-JSON MapLibre layer filter.
 * `null` and `[]` both clear the filter (return null). A recognized form with
 * invalid arity throws `FilterValidationError`; opaque unsupported filters are
 * preserved verbatim.
 */
export function validateRawFilter(value: unknown): FilterSpecification | null {
  if (value === null || value === undefined) return null;
  if (!Array.isArray(value)) {
    throw new FilterValidationError('filter must be a JSON array or null');
  }
  // An empty array is not a valid MapLibre filter; treat as clear.
  if (value.length === 0) return null;
  return normalizeFilterNode(value) as FilterSpecification;
}

function sanitizeFilterNode(node: unknown): unknown {
  if (!Array.isArray(node) || node.length === 0) return node;
  if (node[0] === 'literal' || guardedComparison(node) || guardedNegation(node)) return node;

  // The bare accessor reads null as 0; the guarded pair does not.
  const comparison = bareNumericComparison(node);
  if (comparison) {
    return buildNullSafeNumericComparison(comparison.field, comparison.operator, comparison.value);
  }
  const negated = node[0] === '!' && node.length === 2 ? bareNumericComparison(node[1]) : null;
  if (negated) {
    return buildNullSafeNumericComparison(negated.field, negated.operator, negated.value, true);
  }

  // Recurse only through combinator/negation wrappers: walking every child
  // would rewrite numeric comparisons nested in opaque expressions
  // (case/match/step/coalesce), breaking their verbatim round-trip.
  if (node[0] === 'all' || node[0] === 'any' || node[0] === '!') {
    return node.map((child, index) => (index === 0 ? child : sanitizeFilterNode(child)));
  }
  return node;
}

export function sanitizeNullableNumericFilter(
  filter: FilterSpecification | null | undefined,
): FilterSpecification | null {
  if (!filter) return null;
  // An empty array is not a valid maplibre filter — `map.setFilter(id, [])`
  // throws ("filter property expected at least 1 element"). Treat it as "no filter"
  // so it can never be persisted nor reach setFilter via any caller.
  if (Array.isArray(filter) && filter.length === 0) return null;
  const sanitized = sanitizeFilterNode(filter);
  // Preserve input reference when structurally unchanged so the filter editor re-emit guard holds
  if (JSON.stringify(sanitized) === JSON.stringify(filter)) return filter;
  return sanitized as FilterSpecification;
}

/** A CQL2-JSON expression, as the analysis endpoints and OGC items accept it. */
export type Cql2Expression = {
  op: string;
  args: unknown[];
};

const CQL2_COMPARISON: Record<string, string> = {
  '==': '=',
  '!=': '<>',
  '<': '<',
  '>': '>',
  '<=': '<=',
  '>=': '>=',
};

/** A dataset column as the catalog lists it, typed by its information_schema name. */
interface FilterColumn {
  name: string;
  type?: string | null;
}

// Mirrors _FEATURE_QUERYABLE_NAME_RE and _PG_TYPE_TO_SCHEMA in
// backend/app/standards/ogc/filtering.py: the columns a CQL2 filter can read.
const CQL2_COLUMN_NAME_RE = /^[A-Za-z][A-Za-z0-9_]{0,62}$/;
const CQL2_STRING_TYPES = new Set(['text', 'character varying', 'character']);
const CQL2_QUERYABLE_TYPES = new Set([
  ...CQL2_STRING_TYPES,
  'smallint',
  'integer',
  'bigint',
  'real',
  'double precision',
  'numeric',
  'boolean',
  'date',
  'timestamp without time zone',
  'timestamp with time zone',
  'uuid',
]);
// The map compares a date or timestamp as the text PostgreSQL wrote into the
// tile, so only a value in that exact form compares the same way in SQL.
const DATE_TEXT_RE = /^\d{4}-\d{2}-\d{2}$/;
// No trailing zeros in the fraction: PostgreSQL drops them.
const TIMESTAMP_TEXT_RE = /^(\d{4}-\d{2}-\d{2}) ((?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{0,5}[1-9])?)$/;
// Mirrors _utc_timestamptz_text in backend/app/processing/tiles/service.py.
const UTC_TIMESTAMP_TEXT_RE =
  /^(\d{4}-\d{2}-\d{2})T((?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{0,5}[1-9])?)\+00:00$/;
const TYPED_TIMESTAMP_RE =
  /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?\s*(Z|[+-](?:0\d|1[0-5])(?::?[0-5]\d)?)?$/i;
// PostgreSQL writes a uuid in lowercase, and the map compares case-sensitively.
const UUID_TEXT_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function isCalendarDate(day: string): boolean {
  const parsed = new Date(`${day}T00:00:00Z`);
  return (
    !Number.isNaN(parsed.getTime()) &&
    parsed.getUTCFullYear() >= 1 &&
    parsed.toISOString().slice(0, 10) === day
  );
}

const pad = (n: number, width = 2) => String(n).padStart(width, '0');

/**
 * A typed timestamp as the UTC text vector tiles carry for a timestamp with
 * time zone, e.g. `2024-03-01T17:00:00+00:00`, or null when `value` is not a
 * date and time. A value without an offset is read as UTC, the zone the map
 * shows these values in.
 */
export function utcTimestampText(value: string): string | null {
  const m = TYPED_TIMESTAMP_RE.exec(value.trim());
  if (!m) return null;
  const [, y, mo, d, h, mi, s = '00', fraction = '', zone = 'Z'] = m;
  const at = new Date(0);
  at.setUTCFullYear(Number(y), Number(mo) - 1, Number(d));
  at.setUTCHours(Number(h), Number(mi), Number(s));
  if (
    at.getUTCFullYear() !== Number(y) ||
    at.getUTCMonth() !== Number(mo) - 1 ||
    at.getUTCDate() !== Number(d) ||
    at.getUTCHours() !== Number(h) ||
    at.getUTCMinutes() !== Number(mi) ||
    at.getUTCSeconds() !== Number(s)
  ) {
    return null;
  }
  if (zone.toUpperCase() !== 'Z') {
    const digits = zone.slice(1).replace(':', '');
    const minutes = Number(digits.slice(0, 2)) * 60 + Number(digits.slice(2) || 0);
    at.setTime(at.getTime() - (zone[0] === '-' ? -minutes : minutes) * 60_000);
  }
  const year = at.getUTCFullYear();
  if (year < 1 || year > 9999) return null;
  const trimmed = fraction.replace(/0+$/, '');
  return (
    `${pad(year, 4)}-${pad(at.getUTCMonth() + 1)}-${pad(at.getUTCDate())}` +
    `T${pad(at.getUTCHours())}:${pad(at.getUTCMinutes())}:${pad(at.getUTCSeconds())}` +
    `${trimmed ? `.${trimmed}` : ''}+00:00`
  );
}

/**
 * The CQL2 literal for a value compared with a column of `pgType`, or null when
 * SQL can't compare it the way the map does.
 */
function cql2Literal(value: string | number | boolean, pgType: string | undefined): unknown {
  if (pgType === 'date') {
    return typeof value === 'string' && DATE_TEXT_RE.test(value) && isCalendarDate(value)
      ? { date: value }
      : null;
  }
  if (pgType === 'timestamp without time zone') {
    const m = typeof value === 'string' ? TIMESTAMP_TEXT_RE.exec(value) : null;
    return m && isCalendarDate(m[1]) ? { timestamp: `${m[1]}T${m[2]}Z` } : null;
  }
  if (pgType === 'timestamp with time zone') {
    const m = typeof value === 'string' ? UTC_TIMESTAMP_TEXT_RE.exec(value) : null;
    return m && isCalendarDate(m[1]) ? { timestamp: `${m[1]}T${m[2]}Z` } : null;
  }
  if (pgType === 'uuid') {
    return typeof value === 'string' && UUID_TEXT_RE.test(value) ? value : null;
  }
  return value;
}

function isCql2Scalar(value: unknown): value is string | number | boolean {
  return (
    typeof value === 'string' ||
    typeof value === 'boolean' ||
    (typeof value === 'number' && Number.isFinite(value))
  );
}

// Inclusive bounds from backend/app/core/db/pg_ranges.py; BigInt keeps int8 endpoints exact.
const CQL2_PG_INTEGER_RANGES = new Map<string, readonly [bigint, bigint]>([
  ['smallint', [-32768n, 32767n]],
  ['integer', [-2147483648n, 2147483647n]],
  ['bigint', [-(2n ** 63n), 2n ** 63n - 1n]],
]);
const CQL2_FLOAT4_MAX = 3.4028234663852886e38;

/** Check scalar types and numeric ranges using the converter's temporal/UUID rules too. */
export function isCql2LiteralCompatible(value: unknown, pgType: string | undefined): boolean {
  if (!isCql2Scalar(value) || cql2Literal(value, pgType) === null) return false;
  if (CQL2_STRING_TYPES.has(pgType ?? '')) return typeof value === 'string';
  const bounds = CQL2_PG_INTEGER_RANGES.get(pgType ?? '');
  if (bounds) {
    // Unsafe integers may already have rounded before the filter is serialized.
    if (typeof value !== 'number' || !Number.isSafeInteger(value)) return false;
    const integer = BigInt(value);
    return integer >= bounds[0] && integer <= bounds[1];
  }
  if (pgType === 'real') return typeof value === 'number' && Math.abs(value) <= CQL2_FLOAT4_MAX;
  if (['double precision', 'numeric'].includes(pgType ?? '')) return typeof value === 'number';
  if (pgType === 'boolean') return typeof value === 'boolean';
  return true;
}

const cql2Property = (field: string) => ({ property: field });
const cql2IsNull = (field: string): Cql2Expression => ({
  op: 'isNull',
  args: [cql2Property(field)],
});
const cql2Not = (expr: Cql2Expression): Cql2Expression => ({ op: 'not', args: [expr] });
// Tiles omit null properties, so MapLibre's negative tests (`!=`, not-in) keep
// features with no value where SQL's three-valued logic would drop them.
const cql2OrNull = (field: string, expr: Cql2Expression): Cql2Expression => ({
  op: 'or',
  args: [cql2IsNull(field), expr],
});

function conditionToCql2(
  c: CanonicalFilterCondition,
  pgType: string | undefined,
): Cql2Expression | null {
  if (!CQL2_COLUMN_NAME_RE.test(c.field)) return null;
  // An unlisted column is left to the server, which reads the live table.
  if (pgType !== undefined && !CQL2_QUERYABLE_TYPES.has(pgType)) return null;
  if (c.operator === 'is_null') return cql2IsNull(c.field);
  if (c.operator === 'has') return cql2Not(cql2IsNull(c.field));
  if (c.operator === 'in_list' || c.operator === 'not_in_list') {
    const values = c.listValues ?? [];
    if (values.length === 0 || !values.every(isCql2Scalar)) return null;
    const literals = values.map((v) => cql2Literal(v, pgType));
    if (literals.includes(null)) return null;
    const inList: Cql2Expression = { op: 'in', args: [cql2Property(c.field), literals] };
    return c.operator === 'in_list' ? inList : cql2OrNull(c.field, cql2Not(inList));
  }
  if (c.operator === 'contains') {
    if (typeof c.rawValue !== 'string') return null;
    if (pgType !== undefined && !CQL2_STRING_TYPES.has(pgType)) return null;
    // MapLibre's `in` is a literal, case-sensitive substring test.
    const literal = c.rawValue.replace(/[\\%_]/g, '\\$&');
    return { op: 'like', args: [cql2Property(c.field), `%${literal}%`] };
  }
  const op = CQL2_COMPARISON[c.operator];
  if (!op) return null;
  if (c.toNumber) {
    if (typeof c.rawValue !== 'number' || !Number.isFinite(c.rawValue)) return null;
    // SQL drops a null from any comparison, as the guarded map filter does.
    return { op, args: [cql2Property(c.field), c.rawValue] };
  }
  if (c.rawValue === null) {
    if (c.operator === '==') return cql2IsNull(c.field);
    if (c.operator === '!=') return cql2Not(cql2IsNull(c.field));
    return null;
  }
  if (!isCql2Scalar(c.rawValue)) return null;
  const literal = cql2Literal(c.rawValue, pgType);
  if (literal === null) return null;
  const comparison: Cql2Expression = { op, args: [cql2Property(c.field), literal] };
  return c.operator === '!=' ? cql2OrNull(c.field, comparison) : comparison;
}

/**
 * Translate a layer's MapLibre filter into CQL2-JSON that keeps the same
 * features. Returns null when the layer has no filter, and 'unsupported' when
 * the filter uses a form outside the structured editor's subset or reads a
 * column CQL2 cannot filter. `columns` types the literals; a filter on a
 * column it does not list is sent untyped.
 */
export function maplibreFilterToCql2(
  filter: FilterSpecification | null | undefined,
  columns?: readonly FilterColumn[] | null,
  opts?: { requireKnownFields?: boolean },
): Cql2Expression | null | 'unsupported' {
  const canonical = parseCanonicalFilter(filter);
  if (canonical.kind === 'opaque') return 'unsupported';
  const types = new Map(
    (columns ?? []).filter((col) => col.type).map((col) => [col.name, String(col.type).toLowerCase()]),
  );
  // Without column metadata the server reads the live table, but WITH it an
  // unknown field converts to a filter the rows endpoint must reject — the
  // drawer asks for this stricter mode so a stale field name falls back to
  // the all-rows notice instead of a table that cannot load.
  if (opts?.requireKnownFields && columns) {
    const known = new Set(columns.map((col) => col.name));
    for (const condition of canonical.conditions) {
      if (!known.has(condition.field)) return 'unsupported';
    }
  }
  const parts: Cql2Expression[] = [];
  for (const condition of canonical.conditions) {
    const part = conditionToCql2(condition, types.get(condition.field));
    if (part === null) return 'unsupported';
    parts.push(part);
  }
  // An empty `any` matches nothing on the map, and CQL2 here has no false literal.
  if (parts.length === 0) return canonical.combinator === 'any' ? 'unsupported' : null;
  if (parts.length === 1) return parts[0];
  return { op: canonical.combinator === 'all' ? 'and' : 'or', args: parts };
}
