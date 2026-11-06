import { vi } from 'vitest';
import { circleAdapter } from '@/components/builder/layer-adapters/circle-adapter';
import { columnsReadBy } from '@/components/builder/spec-columns';
import { describeLayers, getDataDrivenColumnsForLayer } from '@/components/builder/layer-description';
import { syncRenderContext, toSyncInput } from '@/components/builder/map-sync';
import { RENDER_CONTEXTS } from '@/test/fixtures/render-contexts';
import { SAVED_LAYERS } from '@/test/fixtures/saved-layers';

function tileUrl(colsOnly: boolean | undefined, layer = SAVED_LAYERS.polygon) {
  const { sources, layers } = describeLayers([toSyncInput(layer)], { ...RENDER_CONTEXTS.builder, colsOnly });
  const source = sources.get(layers[0].sourceId) as { tiles: string[] };
  return source.tiles[0];
}

describe('lean vector tiles', () => {
  it('adds cols_only to the source URL when the context asks for it', () => {
    expect(tileUrl(true)).toContain('cols_only=true');
  });

  it('keeps today\'s URL when the context does not ask', () => {
    expect(tileUrl(false)).not.toContain('cols_only');
    expect(tileUrl(undefined)).not.toContain('cols_only');
  });

  it('asks by default from the sync render context, and lets a caller opt out', () => {
    expect(syncRenderContext(new Map(), undefined, undefined, undefined).colsOnly).toBe(true);
    expect(syncRenderContext(new Map(), undefined, undefined, { colsOnly: false }).colsOnly).toBe(false);
  });
});

describe('columns named by legacy style forms', () => {
  it('reads the property of a paint function', () => {
    const paint = { 'circle-color': { property: 'kind', type: 'categorical', stops: [['a', '#f00']] } };
    expect(getDataDrivenColumnsForLayer({ paint })).toEqual(['kind']);
  });

  it('reads the field of a legacy comparison filter', () => {
    expect(getDataDrivenColumnsForLayer({ filter: ['==', 'status', 'open'] })).toEqual(['status']);
  });

  it('reads the field of a legacy in filter nested under all', () => {
    const filter = ['all', ['in', 'kind', 'a', 'b'], ['none', ['!in', 'size', 1]], ['==', '$type', 'Point']];
    expect(getDataDrivenColumnsForLayer({ filter }).sort()).toEqual(['kind', 'size']);
  });

  it('reads the field of a legacy has and !has', () => {
    expect(getDataDrivenColumnsForLayer({ filter: ['any', ['has', 'owner'], ['!has', 'name']] }).sort())
      .toEqual(['name', 'owner']);
  });
});

describe('columns the rendered layers read', () => {
  const colsOf = (overrides: Parameters<typeof toSyncInput>[0] extends infer L ? Partial<L> : never) => {
    const { sources, layers } = describeLayers(
      [toSyncInput({ ...SAVED_LAYERS.polygon, ...overrides })],
      { ...RENDER_CONTEXTS.builder, colsOnly: true },
    );
    const url = new URL((sources.get(layers[0].sourceId) as { tiles: string[] }).tiles[0], 'https://x.test');
    return (url.searchParams.get('cols') ?? '').split(',').filter(Boolean);
  };

  it('requests a text-field expression stored in the layout without a label column', () => {
    expect(colsOf({ layout: { 'text-field': ['get', 'name'] } })).toContain('name');
  });

  it('requests the fields of a text-field placeholder string', () => {
    expect(colsOf({ layout: { 'text-field': '{name} ({code})' } })).toEqual(expect.arrayContaining(['name', 'code']));
  });

  it('requests the property of a paint function', () => {
    const paint = { 'fill-color': { property: 'kind', type: 'categorical', stops: [['a', '#f00']] } };
    expect(colsOf({ paint })).toContain('kind');
  });

  it('requests the field of a legacy filter', () => {
    expect(colsOf({ filter: ['all', ['in', 'kind', 'a']] as never })).toContain('kind');
  });

  it('requests the height column of an extrusion', () => {
    expect(colsOf({ paint: { '_height_column': 'floors' } })).toContain('floors');
  });

  it('requests whatever the adapter output reads', () => {
    const describe = circleAdapter.describe!;
    const spy = vi.spyOn(circleAdapter, 'describe').mockImplementation((input) => {
      const drawing = describe(input);
      return {
        ...drawing,
        specs: drawing.specs.map((spec) => ({
          ...spec,
          layer: { ...spec.layer, paint: { ...spec.layer.paint, 'circle-opacity': ['get', 'injected'] } },
        })),
      };
    });
    try {
      expect(colsOf({ dataset_geometry_type: 'POINT' })).toContain('injected');
    } finally {
      spy.mockRestore();
    }
  });
});

describe('layers that read a column by a computed name', () => {
  const urlFor = (filter: unknown) => {
    const { sources, layers } = describeLayers(
      [toSyncInput({ ...SAVED_LAYERS.polygon, filter: filter as never })],
      { ...RENDER_CONTEXTS.builder, colsOnly: true },
    );
    return (sources.get(layers[0].sourceId) as { tiles: string[] }).tiles[0];
  };

  it('keeps the default projection so the computed column still reaches the map', () => {
    const url = urlFor(['==', ['get', ['concat', 'value_', ['get', 'year']]], 1]);
    expect(url).not.toContain('cols_only');
  });

  it('narrows the tile when every name is a literal', () => {
    expect(urlFor(['==', ['get', 'year'], 1])).toContain('cols_only=true');
  });
});

describe('columns the rows endpoint cannot return', () => {
  const colsFor = (columns: string[]) => {
    const layer = { ...SAVED_LAYERS.polygon, dataset_column_info: columns.map((name) => ({ name, type: 'text' })) };
    const { tileColumns, layers } = describeLayers([toSyncInput(layer)], { ...RENDER_CONTEXTS.builder, colsOnly: true });
    return tileColumns.get(layers[0].sourceId);
  };

  it('stay in the tile because a popup cannot fetch them', () => {
    expect(colsFor(['Zone', 'zone2'])).toEqual(['Zone']);
  });

  it('include an enum column, which the rows endpoint leaves out', () => {
    const layer = { ...SAVED_LAYERS.polygon, dataset_column_info: [{ name: 'status', type: 'USER-DEFINED' }, { name: 'name', type: 'text' }] };
    const { tileColumns, layers } = describeLayers([toSyncInput(layer)], { ...RENDER_CONTEXTS.builder, colsOnly: true });
    expect(tileColumns.get(layers[0].sourceId)).toEqual(['status']);
  });
});

describe('the object operand of get', () => {
  it('is read for the fields it uses', () => {
    const filter = ['==', ['get', 'color', ['case', ['==', ['get', 'kind'], 'a'], ['literal', { color: 1 }], ['literal', {}]]], 1];
    const { cols } = columnsReadBy({ id: 'l', type: 'fill', source: 's', paint: {}, layout: {}, filter: filter as never });
    expect(cols.sort()).toEqual(['color', 'kind']);
  });
});

describe('a projection too long for the request line', () => {
  const wide = Array.from({ length: 400 }, (_, index) => ({ name: `Mixed_Case_Column_${String(index).padStart(4, '0')}_x`, type: 'text' }));
  const urlFor = (layer: typeof SAVED_LAYERS.polygon, columns: typeof wide) => {
    const { sources, layers } = describeLayers(
      [toSyncInput({ ...layer, dataset_column_info: columns })],
      { ...RENDER_CONTEXTS.builder, colsOnly: true },
    );
    return (sources.get(layers[0].sourceId) as { tiles: string[] }).tiles[0];
  };

  it.each([
    ['plain', SAVED_LAYERS.polygon],
    ['cluster', SAVED_LAYERS.serverCluster],
  ])('falls back to full tiles on a %s source without the held columns', (_kind, layer) => {
    const url = urlFor(layer, wide);
    expect(url).not.toContain('cols_only');
    expect(url).not.toContain('Mixed_Case');
  });

  it('drops the held columns when the default projection is too long, too', () => {
    const { sources, layers } = describeLayers(
      [toSyncInput({ ...SAVED_LAYERS.polygon, dataset_column_info: wide })],
      { ...RENDER_CONTEXTS.builder, colsOnly: false },
    );
    expect((sources.get(layers[0].sourceId) as { tiles: string[] }).tiles[0]).not.toContain('Mixed_Case');
  });

  it('drops the held columns on a source that cannot be narrowed', () => {
    const computed = ['==', ['get', ['concat', 'a_', ['get', 'year']]], 1];
    const { sources, layers } = describeLayers(
      [toSyncInput({ ...SAVED_LAYERS.polygon, filter: computed as never, dataset_column_info: wide })],
      { ...RENDER_CONTEXTS.builder, colsOnly: true },
    );
    expect((sources.get(layers[0].sourceId) as { tiles: string[] }).tiles[0]).not.toContain('Mixed_Case');
  });

  it('keeps the held columns when they fit, with lean tiles off', () => {
    const { sources, layers } = describeLayers(
      [toSyncInput({ ...SAVED_LAYERS.polygon, dataset_column_info: wide.slice(0, 3) })],
      { ...RENDER_CONTEXTS.builder, colsOnly: false },
    );
    expect((sources.get(layers[0].sourceId) as { tiles: string[] }).tiles[0]).toContain('Mixed_Case');
  });

  it('stays lean when the held columns fit', () => {
    expect(urlFor(SAVED_LAYERS.polygon, wide.slice(0, 3))).toContain('cols_only=true');
  });
});
