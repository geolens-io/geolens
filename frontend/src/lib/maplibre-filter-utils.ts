import type { FilterSpecification } from 'maplibre-gl';

const NUMERIC_COMPARISON_OPERATORS = new Set(['==', '!=', '>', '<', '>=', '<=']);
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

  return node.map((child, index) => index === 0 ? child : sanitizeFilterNode(child));
}

export function sanitizeNullableNumericFilter(
  filter: FilterSpecification | null | undefined,
): FilterSpecification | null {
  if (!filter) return null;
  return sanitizeFilterNode(filter) as FilterSpecification;
}
