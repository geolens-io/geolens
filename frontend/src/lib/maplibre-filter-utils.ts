import type { FilterSpecification } from 'maplibre-gl';

/**
 * builder-audit #338 SPEC-09 / DRY-01 / DRY-02 / FILT-01 / FILT-02 / P1-04:
 * Single source of truth for the *editable* MapLibre filter-expression subset
 * the map builder authors and recognizes.
 *
 * Supported grammar subset (deliberate scope — anything else round-trips as an
 * opaque, uneditable filter, see SPEC-09):
 *   - comparisons:        ==, !=, >, <, >=, <=   over ["get", field] or the
 *                         nullable-safe ["to-number", ["get", field], fallback]
 *                         accessor this module emits for numeric columns.
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
 * cannot drift again (the FILT-01 to-number-unwrap and FILT-02 contains-label
 * bugs were direct consequences of two independent hand-rolled walkers).
 */

// builder-audit #338 DRY-02: the single canonical comparison-operator set. Imported
// by LayerFilterEditor and ActiveFilterChips instead of re-declared per file.
export const NUMERIC_COMPARISON_OPERATORS = new Set(['==', '!=', '>', '<', '>=', '<=']);

const NUMERIC_LOW_SENTINEL = -1_000_000_000_000;
const NUMERIC_HIGH_SENTINEL = 1_000_000_000_000;

function isGetExpression(value: unknown): value is ['get', string] {
  return Array.isArray(value) && value[0] === 'get' && typeof value[1] === 'string';
}

function numericFallbackForOperator(operator: string, comparisonValue: number) {
  if (operator === '<' || operator === '<=') return NUMERIC_HIGH_SENTINEL;
  if (comparisonValue === NUMERIC_LOW_SENTINEL) return NUMERIC_HIGH_SENTINEL;
  return NUMERIC_LOW_SENTINEL;
}

export function buildNullableSafeNumericAccessor(
  field: string,
  operator: string,
  comparisonValue: number,
) {
  return ['to-number', ['get', field], numericFallbackForOperator(operator, comparisonValue)];
}

// ---------------------------------------------------------------------------
// builder-audit #338 FILT-01 / DRY-01: one canonical field extractor + filter parser
// ---------------------------------------------------------------------------

/**
 * Extract the underlying property name a filter operand reads.
 *
 * builder-audit #338 FILT-01: also unwraps the ["to-number", ["get", field], _]
 * accessor the editor emits for every numeric-column comparison — the chip
 * summarizer previously only understood ["get", field] and bare strings, so
 * numeric filters silently produced no chip.
 */
export function extractFilterField(expr: unknown): string | null {
  if (Array.isArray(expr) && expr[0] === 'get' && typeof expr[1] === 'string') {
    return expr[1];
  }
  if (
    Array.isArray(expr) &&
    expr[0] === 'to-number' &&
    Array.isArray(expr[1]) &&
    expr[1][0] === 'get' &&
    typeof expr[1][1] === 'string'
  ) {
    return expr[1][1];
  }
  if (typeof expr === 'string') return expr;
  return null;
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
}

export type CanonicalFilter =
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

  // standard comparison: [op, ["get", f], value]
  if (Array.isArray(e[1]) && e[1][0] === 'get') {
    return { field: e[1][1] as string, operator: e[0] as string, value: String(e[2] ?? ''), rawValue: e[2] };
  }

  // numeric-safe comparison: [op, ["to-number", ["get", f], fallback], value]  (FILT-01)
  if (
    Array.isArray(e[1]) &&
    e[1][0] === 'to-number' &&
    Array.isArray(e[1][1]) &&
    e[1][1][0] === 'get'
  ) {
    return { field: e[1][1][1] as string, operator: e[0] as string, value: String(e[2] ?? ''), rawValue: e[2] };
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

// ---------------------------------------------------------------------------
// builder-audit #338 P1-04: raw-JSON filter validator/normalizer
// ---------------------------------------------------------------------------
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
 * Validate + normalize a raw-JSON MapLibre layer filter (builder-audit #338 P1-04).
 * `null` and `[]` both clear the filter (return null). A recognized form with
 * invalid arity throws `FilterValidationError`; opaque unsupported filters are
 * preserved verbatim.
 */
export function validateRawFilter(value: unknown): FilterSpecification | null {
  if (value === null || value === undefined) return null;
  if (!Array.isArray(value)) {
    throw new FilterValidationError('filter must be a JSON array or null');
  }
  // EDIT-03: an empty array is not a valid MapLibre filter; treat as clear.
  if (value.length === 0) return null;
  return normalizeFilterNode(value) as FilterSpecification;
}

function sanitizeFilterNode(node: unknown): unknown {
  if (!Array.isArray(node) || node.length === 0) return node;
  if (node[0] === 'literal') return node;

  const [operator, left, right] = node;
  if (
    typeof operator === 'string' &&
    NUMERIC_COMPARISON_OPERATORS.has(operator) &&
    typeof right === 'number' &&
    isGetExpression(left)
  ) {
    return [
      operator,
      buildNullableSafeNumericAccessor(left[1], operator, right),
      right,
    ];
  }

  // fix(#526 B-045): recurse only through combinator/negation wrappers. The
  // previous fallthrough walked EVERY child, so opaque out-of-subset
  // expressions (case/match/step/coalesce operands) had nested numeric
  // comparisons rewritten to the nullable-safe form — breaking the verbatim
  // round-trip contract for imported/hand-authored advanced filters.
  if (node[0] === 'all' || node[0] === 'any' || node[0] === '!') {
    return node.map((child, index) => (index === 0 ? child : sanitizeFilterNode(child)));
  }
  return node;
}

export function sanitizeNullableNumericFilter(
  filter: FilterSpecification | null | undefined,
): FilterSpecification | null {
  if (!filter) return null;
  // EDIT-03: an empty array is not a valid maplibre filter — `map.setFilter(id, [])`
  // throws ("filter property expected at least 1 element"). Treat it as "no filter"
  // so it can never be persisted nor reach setFilter via any caller.
  if (Array.isArray(filter) && filter.length === 0) return null;
  const sanitized = sanitizeFilterNode(filter);
  // fix(#392): preserve input reference when structurally unchanged so the filter editor re-emit guard holds (audit FL-01)
  if (JSON.stringify(sanitized) === JSON.stringify(filter)) return filter;
  return sanitized as FilterSpecification;
}
