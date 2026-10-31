import type { FilterSpecification } from 'maplibre-gl';
import { featureFilter } from '@maplibre/maplibre-gl-style-spec';
import type { SelectionValue, WidgetSelection } from '@/components/widgets/contract';
import { serverClusterFilter } from '@/components/builder/cluster-source';
import { layerFilterToServerCql2 } from '@/lib/maplibre-filter-utils';
import type { SharedLayerResponse } from '@/types/api';
import { linkMapLayers, selectionCql2, selectionFilter, widgetFilter, type LinkedPick } from '../linked-filters';

const columns = [
  { name: 'land_use', type: 'text' },
  { name: 'floors', type: 'integer' },
  { name: 'height', type: 'double precision' },
  { name: 'zone', type: 'text' },
];

function layer(id: string, filter: FilterSpecification | null = null): SharedLayerResponse {
  return { id, dataset_id: `ds-${id}`, filter, column_info: columns } as SharedLayerResponse;
}

const pick = (values: SelectionValue[], column = 'land_use'): WidgetSelection => ({ column, label: 'x', values });
const range = (column: string, lower: number, upper: number, includeUpper = false): WidgetSelection => ({
  column,
  label: 'x',
  range: { lower, upper, includeUpper },
});
const cql2 = (filter: FilterSpecification) => layerFilterToServerCql2(filter, columns);
const linkedPick = (widgetId: string, layerId: string, selection: WidgetSelection): LinkedPick => ({
  widgetId,
  layerId,
  selection,
  cql2: selectionCql2(layer(layerId), selection)!,
});

describe('selectionFilter', () => {
  it('keeps the picked text values, numbers and empty values, as the server reads them too', () => {
    expect(cql2(selectionFilter(pick(['Residential', 'Commercial'])))).toEqual({
      op: 'in',
      args: [{ property: 'land_use' }, ['Residential', 'Commercial']],
    });
    expect(cql2(selectionFilter(pick([3], 'floors'), 'integer'))).toEqual({
      op: '=',
      args: [{ property: 'floors' }, 3],
    });
    expect(cql2(selectionFilter(pick(['Residential', null])))).toEqual({
      op: 'or',
      args: [
        { op: 'in', args: [{ property: 'land_use' }, ['Residential']] },
        { op: 'isNull', args: [{ property: 'land_use' }] },
      ],
    });
  });

  it('keeps a range with its lower edge, and its upper edge only for the last bin', () => {
    expect(cql2(selectionFilter(range('height', 2.5, 5), 'double precision'))).toEqual({
      op: 'and',
      args: [
        { op: '>=', args: [{ property: 'height' }, 2.5] },
        { op: '<', args: [{ property: 'height' }, 5] },
      ],
    });
    expect(cql2(selectionFilter(range('height', 5, 7.5, true), 'double precision'))).toEqual({
      op: 'and',
      args: [
        { op: '>=', args: [{ property: 'height' }, 5] },
        { op: '<=', args: [{ property: 'height' }, 7.5] },
      ],
    });
  });

  it('moves a range on whole numbers in to the whole numbers it holds', () => {
    // Fractional edges on an integer column are refused by the server's literal check.
    expect(cql2(selectionFilter(range('floors', 1.4, 2.8), 'integer'))).toEqual({
      op: 'and',
      args: [
        { op: '>=', args: [{ property: 'floors' }, 2] },
        { op: '<', args: [{ property: 'floors' }, 3] },
      ],
    });
    expect(cql2(selectionFilter(range('floors', 2.8, 4.2, true), 'integer'))).toEqual({
      op: 'and',
      args: [
        { op: '>=', args: [{ property: 'floors' }, 3] },
        { op: '<=', args: [{ property: 'floors' }, 4] },
      ],
    });
  });

  it('draws the same rows on the map: null-safe numbers and a literal list', () => {
    expect(selectionFilter(pick(['Residential']))).toEqual(['in', ['get', 'land_use'], ['literal', ['Residential']]]);
    const [, guard] = selectionFilter(range('height', 0, 1), 'double precision') as unknown[];
    expect(guard).toEqual(['all', ['!=', ['typeof', ['get', 'height']], 'null'], expect.anything()]);
  });
});

describe('linkMapLayers', () => {
  const saved: FilterSpecification = ['==', ['get', 'zone'], 'A'];
  const layers = [layer('a', saved), layer('b')];

  it('hands back the saved layers while nothing is picked', () => {
    expect(linkMapLayers(layers, [])).toBe(layers);
  });

  it('adds each pick to its own layer, after the saved filter, without changing the saved layers', () => {
    const linked = linkMapLayers(layers, [
      linkedPick('w1', 'a', pick(['Residential'])),
      linkedPick('w2', 'a', range('height', 1, 2)),
    ]);
    expect(linked[1]).toBe(layers[1]);
    expect(layers[0].filter).toBe(saved);
    expect(linked[0].filter).toEqual([
      'all',
      saved,
      ['in', ['get', 'land_use'], ['literal', ['Residential']]],
      selectionFilter(range('height', 1, 2), 'double precision'),
    ]);
    // Still a filter the CQL2 converter reads, as server-clustered layers need.
    expect(cql2(linked[0].filter!)).toEqual({
      op: 'and',
      args: [
        { op: '=', args: [{ property: 'zone' }, 'A'] },
        { op: 'in', args: [{ property: 'land_use' }, ['Residential']] },
        {
          op: 'and',
          args: [
            { op: '>=', args: [{ property: 'height' }, 1] },
            { op: '<', args: [{ property: 'height' }, 2] },
          ],
        },
      ],
    });
  });

  it('keeps a saved `any` filter and a pick of a value and no value both readable as CQL2', () => {
    const anyZone: FilterSpecification = ['any', ['==', ['get', 'zone'], 'A'], ['==', ['get', 'zone'], 'B']];
    const [linked] = linkMapLayers([layer('a', anyZone)], [linkedPick('w1', 'a', pick(['Residential', null]))]);
    expect(cql2(linked.filter!)).toEqual({
      op: 'and',
      args: [
        {
          op: 'or',
          args: [
            { op: '=', args: [{ property: 'zone' }, 'A'] },
            { op: '=', args: [{ property: 'zone' }, 'B'] },
          ],
        },
        {
          op: 'or',
          args: [
            { op: 'in', args: [{ property: 'land_use' }, ['Residential']] },
            { op: 'isNull', args: [{ property: 'land_use' }] },
          ],
        },
      ],
    });
  });

  it('keeps a saved filter the converter cannot read, alongside the pick', () => {
    const opaque: FilterSpecification = ['>', ['length', ['get', 'zone']], 3];
    const [linked] = linkMapLayers([layer('a', opaque)], [
      linkedPick('w1', 'a', pick(['Residential'])),
    ]);
    expect(linked.filter).toEqual(['all', opaque, ['in', ['get', 'land_use'], ['literal', ['Residential']]]]);
  });

  it('keeps a legacy saved filter working once a pick joins it', () => {
    const matches = (filter: FilterSpecification | null | undefined, properties: Record<string, unknown>) =>
      featureFilter(filter!, 'filter').filter({ zoom: 10 }, { type: 1, properties } as never);
    const zoneA = { zone: 'A', land_use: 'Residential' };
    const zoneB = { zone: 'B', land_use: 'Residential' };
    for (const legacy of [
      ['==', 'zone', 'A'],
      ['in', 'zone', 'A', 'C'],
      ['all', ['==', 'zone', 'A'], ['has', 'land_use']],
    ] as FilterSpecification[]) {
      expect(matches(legacy, zoneA)).toBe(true);
      const [linked] = linkMapLayers([layer('a', legacy)], [linkedPick('w1', 'a', pick(['Residential']))]);
      expect(matches(linked.filter, zoneA)).toBe(true);
      expect(matches(linked.filter, zoneB)).toBe(false);
      expect(matches(linked.filter, { zone: 'A', land_use: 'Commercial' })).toBe(false);
    }
  });
});

describe('linkMapLayers with a legacy saved filter', () => {
  it('writes it in forms the cluster tiles can send as CQL2', () => {
    const [linked] = linkMapLayers(
      [layer('a', ['!in', 'zone', 'B'] as FilterSpecification)],
      [linkedPick('w1', 'a', pick(['Residential']))],
    );
    expect(serverClusterFilter(linked.filter, columns, null)).toEqual({
      json: JSON.stringify({
        op: 'and',
        args: [
          {
            op: 'or',
            args: [
              { op: 'isNull', args: [{ property: 'zone' }] },
              { op: 'not', args: [{ op: 'in', args: [{ property: 'zone' }, ['B']] }] },
            ],
          },
          { op: 'in', args: [{ property: 'land_use' }, ['Residential']] },
        ],
      }),
    });
  });
});

describe('layerFilterToServerCql2', () => {
  it('refuses a literal its column cannot hold at any depth', () => {
    // 'two' can't be compared with an integer column, so the server would refuse the whole filter.
    const nested: FilterSpecification = ['all', ['==', ['get', 'zone'], 'A'], ['any', ['==', ['get', 'floors'], 'two'], ['has', 'zone']]];
    expect(cql2(nested)).toBe('unsupported');
    expect(cql2(['all', ['==', ['get', 'zone'], 'A'], ['any', ['==', ['get', 'floors'], 2], ['has', 'zone']]])).toMatchObject({ op: 'and' });
  });
});

describe('selectionCql2', () => {
  it('is null for a value the server cannot compare as the map does', () => {
    const opened = [...columns, { name: 'opened', type: 'timestamp with time zone' }];
    const withTimestamps = { ...layer('a'), column_info: opened } as SharedLayerResponse;
    expect(selectionCql2(withTimestamps, pick(['2024-03-01 17:00:00+00'], 'opened'))).toBeNull();
  });
});

describe('linkMapLayers on a bounded cluster', () => {
  const matches = (filter: FilterSpecification | null | undefined, properties: Record<string, unknown>) =>
    featureFilter(filter!, 'filter').filter({ zoom: 10 }, { type: 1, properties } as never);
  const pointLayer = (cluster: boolean, column: string, type: string) =>
    ({
      id: 'a',
      dataset_id: 'ds-a',
      filter: null,
      layer_type: 'vector_geolens',
      geometry_type: 'POINT',
      feature_count: cluster ? 100 : 20_000,
      style_config: { render_mode: 'cluster' },
      column_info: [{ name: column, type }],
    }) as unknown as SharedLayerResponse;
  const linkedFilter = (target: SharedLayerResponse, selection: WidgetSelection) =>
    linkMapLayers([target], [{ widgetId: 'w1', layerId: 'a', selection, cql2: selectionCql2(target, selection)! }])[0].filter;

  it('keeps a picked timestamp\'s feature in the GeoJSON spelling as well as the tiles\'', () => {
    // The aggregate endpoint and the tiles write PostgreSQL text; to_jsonb puts a T in.
    const filter = linkedFilter(pointLayer(true, 'seen', 'timestamp without time zone'), pick(['2024-03-01 17:00:00.25'], 'seen'));
    expect(matches(filter, { seen: '2024-03-01T17:00:00.25' })).toBe(true);
    expect(matches(filter, { seen: '2024-03-01 17:00:00.25' })).toBe(true);
    expect(matches(filter, { seen: '2024-03-02T17:00:00.25' })).toBe(false);
  });

  it('keeps a picked timestamptz, which the endpoint, the tiles and to_jsonb in UTC all write alike', () => {
    const filter = linkedFilter(pointLayer(true, 'at', 'timestamp with time zone'), pick(['2024-03-01T17:00:00.25+00:00'], 'at'));
    expect(matches(filter, { at: '2024-03-01T17:00:00.25+00:00' })).toBe(true);
  });

  it('keeps a picked real in the shortest decimal to_jsonb writes', () => {
    const float4 = Math.fround(0.1);
    const filter = linkedFilter(pointLayer(true, 'r', 'real'), pick([float4], 'r'));
    expect(matches(filter, { r: 0.1 })).toBe(true);
    expect(matches(filter, { r: float4 })).toBe(true);
    expect(matches(filter, { r: 0.2 })).toBe(false);
  });

  it('keeps a real column\'s GeoJSON points in the histogram bin they belong to', () => {
    const target = pointLayer(true, 'r', 'real');
    const f = Math.fround;
    // Every value is 0.1: one bin with no width, whose edges are the float4 at double precision.
    const single = linkedFilter(target, range('r', f(0.1), f(0.1), true));
    expect(matches(single, { r: 0.1 })).toBe(true);
    // A point at a bin's open upper edge belongs to the next bin, in either spelling.
    const lowerBin = linkedFilter(target, range('r', f(0.1), f(0.2)));
    expect(matches(lowerBin, { r: 0.1 })).toBe(true);
    expect(matches(lowerBin, { r: 0.15 })).toBe(true);
    expect(matches(lowerBin, { r: 0.2 })).toBe(false);
    expect(matches(lowerBin, { r: f(0.2) })).toBe(false);
  });

  it('sends a real column\'s range as float4 edges, so the server\'s rounding keeps the bin\'s own values', () => {
    const f = Math.fround;
    // 0.35 as a float4 sits just below 0.35, so a plain 0.35 edge rounds to it and drops the point from [0.3, 0.35).
    const bin = range('r', 0.3, 0.35);
    const edges = JSON.stringify(selectionCql2(pointLayer(false, 'r', 'real'), bin)).match(/-?\d[\d.e-]*/g)!.map(Number);
    expect(edges.length).toBeGreaterThan(0);
    for (const edge of edges) expect(f(edge)).toBe(edge);
    const [lower, upper] = edges;
    // Server: the column's float4 value against the rounded edges.
    const serverKeeps = (value: number) => value >= f(lower) && value < f(upper);
    expect(serverKeeps(f(0.35))).toBe(true);
    expect(serverKeeps(f(0.3))).toBe(true);
    // The point belongs to this bin on the map too, and the next bin starts where this one ends.
    expect(matches(linkedFilter(pointLayer(false, 'r', 'real'), bin), { r: f(0.35) })).toBe(true);
    const next = linkedFilter(pointLayer(false, 'r', 'real'), range('r', 0.35, 0.4));
    expect(matches(next, { r: f(0.35) })).toBe(false);
  });

  it('keeps the same real values as the float8 range at every edge, just below and just above it', () => {
    const f = Math.fround;
    const view = new DataView(new ArrayBuffer(4));
    const step = (value: number, by: number) => {
      view.setFloat32(0, value);
      view.setInt32(0, view.getInt32(0) + by * (value >= 0 ? 1 : -1));
      return view.getFloat32(0);
    };
    const target = pointLayer(false, 'r', 'real');
    const edgesOf = (bin: ReturnType<typeof range>) =>
      JSON.stringify(selectionCql2(target, bin)).match(/-?\d[\d.e-]*/g)!.map(Number);
    const edgePairs = [
      [0.3, 0.35],
      [0.1, 0.2],
      [0, 0.05],
      [0.95, 1],
      [12.34, 56.78],
      [1e-7, 3e-7],
      [0.7, 0.7000000001],
    ];
    for (const [lo, hi] of edgePairs) {
      for (const includeUpper of [false, true]) {
        const [lower, upper] = edgesOf(range('r', lo, hi, includeUpper));
        // The server rounds every bind it gets to the column's float4.
        const serverKeeps = (v: number) => v >= f(lower) && (includeUpper ? v <= f(upper) : v < f(upper));
        const mapKeeps = (v: number) => v >= lo && (includeUpper ? v <= hi : v < hi);
        for (const edge of [lo, hi]) {
          for (let by = -3; by <= 3; by += 1) {
            const value = step(f(edge), by);
            expect(serverKeeps(value), `${value} in [${lo}, ${hi}${includeUpper ? ']' : ')'}`).toBe(mapKeeps(value));
          }
        }
      }
    }
  });

  it('sends a server-clustered layer only the spelling the server compares', () => {
    const target = pointLayer(false, 'seen', 'timestamp without time zone');
    expect(linkedFilter(target, pick(['2024-03-01 17:00:00'], 'seen'))).toEqual([
      'in',
      ['get', 'seen'],
      ['literal', ['2024-03-01 17:00:00']],
    ]);
  });
});

describe('widgetFilter', () => {
  it('joins the saved filter and the other widgets’ picks', () => {
    const residential = selectionCql2(layer('a'), pick(['Residential']))!;
    const result = widgetFilter(layer('a', ['==', ['get', 'zone'], 'A']), [residential]);
    expect(result).toEqual({
      savedIgnored: false,
      filter: {
        op: 'and',
        args: [
          { op: '=', args: [{ property: 'zone' }, 'A'] },
          { op: 'in', args: [{ property: 'land_use' }, ['Residential']] },
        ],
      },
    });
    expect(widgetFilter(layer('a'), [])).toEqual({ savedIgnored: false, filter: null });
  });

  it('sends a legacy saved filter with the picks', () => {
    const residential = selectionCql2(layer('a'), pick(['Residential']))!;
    expect(widgetFilter(layer('a', ['in', 'zone', 'A', 'C'] as FilterSpecification), [residential])).toEqual({
      savedIgnored: false,
      filter: {
        op: 'and',
        args: [
          { op: 'in', args: [{ property: 'zone' }, ['A', 'C']] },
          { op: 'in', args: [{ property: 'land_use' }, ['Residential']] },
        ],
      },
    });
  });

  it('applies the picks when the saved filter cannot be sent, and says so', () => {
    const residential = selectionCql2(layer('a'), pick(['Residential']))!;
    const result = widgetFilter(layer('a', ['>', ['length', ['get', 'zone']], 3]), [residential]);
    expect(result).toEqual({
      savedIgnored: true,
      filter: { op: 'in', args: [{ property: 'land_use' }, ['Residential']] },
    });
  });
});
