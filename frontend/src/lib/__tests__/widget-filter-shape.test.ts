import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { layerFilterToServerCql2, maplibreFilterToCql2, validateRawFilter } from '@/lib/maplibre-filter-utils';
import { widgetFilterShape } from '@/lib/widget-filter-shape';

interface ShapeCase {
  name: string;
  filter: unknown;
  typed?: boolean;
  columns: string[] | null;
  cql2?: unknown;
  values?: number;
  depth?: number;
}

const shapes = JSON.parse(
  readFileSync(resolve(__dirname, '../../../../backend/tests/fixtures/widget_filter_shapes.json'), 'utf-8'),
) as { types: Record<string, string>; cases: ShapeCase[] };
const { cases } = shapes;
// The layer's columns as the viewer has them, for the cases that check literals against their types.
const typedColumns = Object.entries(shapes.types).map(([name, type]) => ({ name, type }));

function normalized(filter: unknown): unknown {
  try {
    return validateRawFilter(filter);
  } catch {
    return undefined;
  }
}

// The aggregate's counts: every value but a property name or operator, and every level.
function values(node: unknown, key?: string): number {
  if (Array.isArray(node)) return node.reduce((sum: number, child) => sum + values(child), 0);
  if (node && typeof node === 'object') {
    return Object.entries(node).reduce((sum, [name, child]) => sum + values(child, name), 0);
  }
  return key === 'property' || key === 'op' ? 0 : 1;
}

function depth(node: unknown): number {
  const children = Array.isArray(node) ? node : node && typeof node === 'object' ? Object.values(node) : null;
  return children ? 1 + Math.max(0, ...children.map(depth)) : 1;
}

describe('the widget filter shapes the server takes', () => {
  it.each(cases.map((shape) => [shape.name, shape] as const))('%s', (_name, shape) => {
    const filter = normalized(shape.filter);
    const columns = shape.typed ? typedColumns : undefined;
    const read = filter === undefined ? null : widgetFilterShape(filter, columns);
    // With the column types, the viewer's converter must agree on refusals too.
    const sent = columns ? layerFilterToServerCql2(filter as never, columns) : maplibreFilterToCql2(filter as never);
    if (shape.columns === null) {
      expect(read).toBeNull();
      if (columns) expect(sent).toBe('unsupported');
      return;
    }
    expect(read).toEqual({ cql2: shape.cql2, columns: shape.columns });
    expect(sent).toEqual(shape.cql2);
    expect(sent ? [values(sent), depth(sent)] : [0, 0]).toEqual([shape.values, shape.depth]);
  });
});

describe('a malformed widget filter', () => {
  const tokens: unknown[] = [
    'all', 'any', '!', 'in', '!in', 'has', '!has', 'none', 'get', 'literal', '==', '!=', '<', '>=',
    'to-number', 'typeof', 'match', '$type', 'kind', 'null', null, true, 0, -1e12, 3.5, '', {}, [],
  ];
  let seed = 3688;
  const next = () => {
    seed = (seed * 1103515245 + 12345) % 2 ** 31;
    return seed / 2 ** 31;
  };
  const node = (depth: number): unknown =>
    depth > 6 || next() < 0.3
      ? tokens[Math.floor(next() * tokens.length)]
      : Array.from({ length: Math.floor(next() * 5) }, () => node(depth + 1));

  it('is refused as null and never throws', () => {
    for (let i = 0; i < 5000; i += 1) {
      const candidate = node(0);
      expect(() => widgetFilterShape(candidate)).not.toThrow();
      const filter = normalized(candidate);
      if (filter !== undefined) expect(() => widgetFilterShape(filter)).not.toThrow();
    }
  });
});
