import { vi } from 'vitest';
import { circleAdapter } from '@/components/builder/layer-adapters/circle-adapter';
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
