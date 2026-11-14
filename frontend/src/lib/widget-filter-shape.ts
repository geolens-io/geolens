import type { Cql2Expression } from './maplibre-filter-utils';

/**
 * The filter shapes a dashboard widget takes, mirroring
 * `backend/app/modules/catalog/widgets/filter_shapes.py`: the conditions the
 * filter editor writes, joined by `all` and `any`, and the legacy forms
 * `maplibreFilterToCql2` translates. `widgetFilterShape` returns the CQL2 the
 * viewer sends for such a filter and the columns it reads, or null for any
 * other shape. `backend/tests/fixtures/widget_filter_shapes.json` holds the
 * cases both copies and the converter are checked against.
 */

const COLUMN = /^[A-Za-z][A-Za-z0-9_]{0,62}$/;
const CQL2_OPS: Record<string, string> = { '==': '=', '!=': '<>', '<': '<', '>': '>', '<=': '<=', '>=': '>=' };
const ORDER = new Set(['<', '>', '<=', '>=']);
const LEGACY_NEGATIONS: Record<string, string> = { '!in': 'in', '!=': '==', '!has': 'has' };
const PSEUDO = new Set(['$type', '$id']);
const LOW = -1_000_000_000_000;
const HIGH = 1_000_000_000_000;

class Refused extends Error {}

type Node = unknown[];

const op = (node: unknown): string | null =>
  Array.isArray(node) && node.length > 0 && typeof node[0] === 'string' ? node[0] : null;
// An integer past the safe range reached the browser rounded, so the server refuses it too.
const isNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value) && (!Number.isInteger(value) || Number.isSafeInteger(value));
const isScalar = (value: unknown) => typeof value === 'string' || typeof value === 'boolean' || isNumber(value);
const hasOp = (table: Record<string, string>, name: string | null): name is string =>
  name !== null && Object.hasOwn(table, name);
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

function get(node: unknown): string | null {
  return op(node) === 'get' && (node as Node).length === 2 && typeof (node as Node)[1] === 'string'
    ? ((node as Node)[1] as string)
    : null;
}

const typeOf = (field: string, kind: string, comparison: string) => [comparison, ['typeof', ['get', field]], kind];
const scalarGuard = (field: string) => ['any', ...['null', 'boolean', 'number', 'string'].map((kind) => typeOf(field, kind, '=='))];

function fallback(operator: string, value: number): number {
  if (operator === '<' || operator === '<=') return HIGH;
  return value === LOW ? HIGH : LOW;
}

function compareNumbers(a: number, operator: string, b: number): boolean {
  switch (operator) {
    case '==':
      return a === b;
    case '!=':
      return a !== b;
    case '<':
      return a < b;
    case '>':
      return a > b;
    case '<=':
      return a <= b;
    default:
      return a >= b;
  }
}

function isComparison(node: unknown): node is Node {
  return hasOp(CQL2_OPS, op(node)) && (node as Node).length === 3 && get((node as Node)[1]) !== null;
}

function toNumber(node: unknown): [string, number] | null {
  if (!hasOp(CQL2_OPS, op(node)) || (node as Node).length !== 3 || !isNumber((node as Node)[2])) return null;
  const accessor = (node as Node)[1];
  if (op(accessor) !== 'to-number' || (accessor as Node).length !== 3) return null;
  const field = get((accessor as Node)[1]);
  const fb = (accessor as Node)[2];
  return field !== null && isNumber(fb) ? [field, fb] : null;
}

function guarded(node: unknown): [string, string, number] | null {
  if (op(node) !== 'all' || (node as Node).length !== 3) return null;
  const [, guard, test] = node as Node;
  const inner = guarded(test);
  if (inner && same(guard, typeOf(inner[0], 'number', '=='))) return inner;
  if (op(guard) !== '!=' || (guard as Node).length !== 3 || (guard as Node)[2] !== 'null') return null;
  const typeofNode = (guard as Node)[1];
  const field = op(typeofNode) === 'typeof' && (typeofNode as Node).length === 2 ? get((typeofNode as Node)[1]) : null;
  const accessor = toNumber(test);
  if (field === null || accessor === null || accessor[0] !== field) return null;
  const [operator, , value] = test as [string, unknown, number];
  return accessor[1] === fallback(operator, value) ? [field, operator, value] : null;
}

function members(node: unknown): [string, unknown[]] | null {
  if (op(node) !== 'in' || (node as Node).length !== 3) return null;
  const field = get((node as Node)[1]);
  const listed = (node as Node)[2];
  if (field === null || op(listed) !== 'literal' || (listed as Node).length !== 2) return null;
  const values = (listed as Node)[1];
  return Array.isArray(values) ? [field, values] : null;
}

function withoutScalarGuard(node: unknown): unknown {
  if (op(node) === 'all' && (node as Node).length === 3) {
    const found = members((node as Node)[2]);
    if (found && same((node as Node)[1], scalarGuard(found[0]))) return (node as Node)[2];
  }
  return node;
}

class Builder {
  readonly columns = new Set<string>();

  prop(field: string) {
    if (!COLUMN.test(field)) throw new Refused();
    this.columns.add(field);
    return { property: field };
  }

  isNull(field: string): Cql2Expression {
    return { op: 'isNull', args: [this.prop(field)] };
  }

  orNull(field: string, expr: Cql2Expression): Cql2Expression {
    return { op: 'or', args: [this.isNull(field), expr] };
  }

  compare(operator: string, field: string, value: unknown): Cql2Expression {
    return { op: CQL2_OPS[operator], args: [this.prop(field), value] };
  }

  members(field: string, values: unknown[]): Cql2Expression {
    if (values.length === 0 || !values.every(isScalar)) throw new Refused();
    return { op: 'in', args: [this.prop(field), values] };
  }

  comparison(operator: string, field: string, value: unknown): Cql2Expression {
    // A bare number is drawn null-safe, as sanitizeNullableNumericFilter does.
    if (isNumber(value)) return this.compare(operator, field, value);
    if (value === null) {
      if (operator === '==') return this.isNull(field);
      if (operator === '!=') return { op: 'not', args: [this.isNull(field)] };
      throw new Refused();
    }
    if (!isScalar(value)) throw new Refused();
    const comparison = this.compare(operator, field, value);
    return operator === '!=' ? this.orNull(field, comparison) : comparison;
  }

  condition(node: unknown): Cql2Expression | null {
    const negated = op(node) === '!' && (node as Node).length === 2;
    const e = negated ? ['!', withoutScalarGuard((node as Node)[1])] : withoutScalarGuard(node);
    const name = op(e);
    const n = e as Node;
    if (name === 'any' && n.length === 3 && isComparison(n[2]) && (n[2] as Node)[0] === '==') {
      const field = get((n[2] as Node)[1]) as string;
      if ((n[2] as Node)[2] === null && same(n[1], ['!', ['has', field]])) return this.isNull(field);
    }
    if (name === '!') {
      const inner = n[1];
      if (op(inner) === 'has' && (inner as Node).length === 2 && typeof (inner as Node)[1] === 'string') {
        return this.isNull((inner as Node)[1] as string);
      }
      const found = members(inner);
      if (!found) return null;
      return this.orNull(found[0], { op: 'not', args: [this.members(...found)] });
    }
    const found = members(e);
    if (found) return this.members(...found);
    if (name === 'in' && n.length === 3 && get(n[2]) !== null) {
      if (typeof n[1] !== 'string') throw new Refused();
      const pattern = n[1].replace(/[\\%_]/g, '\\$&');
      return { op: 'like', args: [this.prop(get(n[2]) as string), `%${pattern}%`] };
    }
    if (name === 'has' && n.length === 2 && typeof n[1] === 'string') {
      return { op: 'not', args: [this.isNull(n[1])] };
    }
    const guard = guarded(e);
    if (guard) return this.compare(guard[1], guard[0], guard[2]);
    if (isComparison(e)) return this.comparison(name as string, get(n[1]) as string, n[2]);
    const accessor = toNumber(e);
    if (!accessor) return null;
    const [field, fb] = accessor;
    const value = n[2] as number;
    const comparison = this.compare(name as string, field, value);
    return fb === fallback(name as string, value) || !compareNumbers(0, name as string, value)
      ? comparison
      : this.orNull(field, comparison);
  }

  tree(node: unknown): Cql2Expression | null {
    const condition = this.condition(node);
    if (condition) return condition;
    const name = op(node);
    if (name !== 'all' && name !== 'any') throw new Refused();
    const parts: Cql2Expression[] = [];
    let keepsAll = false;
    for (const child of (node as Node).slice(1)) {
      if (!Array.isArray(child)) throw new Refused();
      // Every branch is read, after one that keeps every feature too.
      const part = this.tree(child);
      if (part === null) keepsAll = true;
      else parts.push(part);
    }
    if (name === 'any' && keepsAll) return null;
    if (parts.length === 0) {
      if (name === 'any') throw new Refused();
      return null;
    }
    if (parts.length === 1) return parts[0];
    return { op: name === 'all' ? 'and' : 'or', args: parts };
  }
}

/** MapLibre's `classifyFilter`. */
function classify(node: unknown): 'legacy' | 'expression' | 'neutral' {
  if (typeof node === 'boolean') return 'neutral';
  if (!Array.isArray(node) || node.length === 0) return 'legacy';
  const name = op(node);
  if (name === 'has') {
    if (node.length < 2 || PSEUDO.has(node[1] as string)) return 'legacy';
    return node.length === 2 ? 'neutral' : 'expression';
  }
  if (name === 'in') {
    return node.length >= 3 && (typeof node[1] !== 'string' || Array.isArray(node[2])) ? 'expression' : 'legacy';
  }
  if (name === '!in' || name === '!has' || name === 'none') return 'legacy';
  if (hasOp(CQL2_OPS, name)) {
    return node.length !== 3 || Array.isArray(node[1]) || Array.isArray(node[2]) ? 'expression' : 'legacy';
  }
  if (name === 'any' || name === 'all') {
    let sawLegacy = false;
    for (const child of node.slice(1)) {
      const kind = classify(child);
      if (kind === 'expression') return 'expression';
      if (kind === 'legacy') sawLegacy = true;
    }
    return sawLegacy ? 'legacy' : 'neutral';
  }
  return 'expression';
}

function legacy(node: unknown): unknown[] {
  const name = op(node);
  if (name === null) throw new Refused();
  const n = node as Node;
  const key = n[1];
  const values = n.slice(2);
  if (name === 'all' || name === 'any') return [name, ...n.slice(1).map(legacy)];
  if (hasOp(LEGACY_NEGATIONS, name)) return ['!', legacy([LEGACY_NEGATIONS[name], ...n.slice(1)])];
  if (typeof key !== 'string' || PSEUDO.has(key)) throw new Refused();
  if (name === 'in') return ['in', ['get', key], ['literal', values]];
  if (name === 'has') {
    if (values.length > 0) throw new Refused();
    return ['has', key];
  }
  if (values.length !== 1 || !isScalar(values[0])) throw new Refused();
  const [value] = values;
  if (name === '==') return ['in', ['get', key], ['literal', [value]]];
  if (!ORDER.has(name) || !isNumber(value)) throw new Refused();
  const comparison = [name, ['to-number', ['get', key], fallback(name, value)], value];
  return ['all', typeOf(key, 'number', '=='), ['all', typeOf(key, 'null', '!='), comparison]];
}

/** The CQL2 the viewer sends for a normalized widget filter and the columns it reads, or null for another shape. */
export function widgetFilterShape(filter: unknown): { cql2: Cql2Expression | null; columns: string[] } | null {
  if (filter === null || filter === undefined) return { cql2: null, columns: [] };
  const builder = new Builder();
  try {
    const expression = classify(filter) === 'legacy' ? legacy(filter) : filter;
    const cql2 = builder.tree(expression);
    return { cql2, columns: [...builder.columns].sort() };
  } catch (error) {
    if (error instanceof Refused) return null;
    throw error;
  }
}
