import type { FilterSpecification } from 'maplibre-gl';
import { featureFilter } from '@maplibre/maplibre-gl-style-spec';
import type { SelectionValue, WidgetSelection } from '@/components/widgets/contract';
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

  it('applies the picks when the saved filter cannot be sent, and says so', () => {
    const residential = selectionCql2(layer('a'), pick(['Residential']))!;
    const result = widgetFilter(layer('a', ['>', ['length', ['get', 'zone']], 3]), [residential]);
    expect(result).toEqual({
      savedIgnored: true,
      filter: { op: 'in', args: [{ property: 'land_use' }, ['Residential']] },
    });
  });
});
