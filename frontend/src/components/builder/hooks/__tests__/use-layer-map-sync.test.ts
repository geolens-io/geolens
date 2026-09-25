// useLayerMapSync commits each handler's change to builder state: composition, the
// EDIT-05 fill exclusions and the fill-colour stash. The map writes are in the .writes suite.
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useLayerMapSync } from '../use-layer-map-sync';
import { fillPatternTint } from '@/lib/fill-pattern-preview';
import type { MapLayerResponse, StyleConfig } from '@/types/api';
import type { Map as MaplibreMap } from 'maplibre-gl';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------
const LAYER_ID = 'layer-uuid-123';
const makeLayer = (overrides: Partial<MapLayerResponse> = {}): MapLayerResponse => ({
  id: LAYER_ID,
  dataset_id: 'ds-1',
  dataset_name: 'Test',
  dataset_geometry_type: 'Polygon',
  dataset_table_name: 'test_table',
  dataset_extent_bbox: null,
  dataset_column_info: null,
  dataset_feature_count: null,
  dataset_sample_values: null,
  display_name: 'Test Layer',
  sort_order: 0,
  visible: true,
  opacity: 1,
  paint: {},
  layout: {},
  filter: null,
  label_config: null,
  style_config: null,
  ...overrides,
});

/** A map no sync pass has drawn, so the handlers write nothing to it. */
function makeMapStub() {
  return { isStyleLoaded: () => true } as unknown as MaplibreMap;
}

// Every adapter's addLayers honours input.visible, so a layer added outside a
// sync pass starts in the right visibility.
describe('adapter.addLayers respects input.visible (BUG-01 root cause)', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
  });

  function makeAddLayerMap() {
    const layerSpecs = new Map<string, { layout?: Record<string, unknown> }>();
    const sources = new Map<string, unknown>();
    const layoutProps = new Map<string, Record<string, unknown>>();
    return {
      addLayer: vi.fn((layer: { id: string; layout?: Record<string, unknown> }) => {
        layerSpecs.set(layer.id, { layout: layer.layout });
        if (layer.layout) layoutProps.set(layer.id, { ...layer.layout });
      }),
      getLayer: vi.fn((id: string) => (layerSpecs.has(id) ? { id } : null)),
      addSource: vi.fn((id: string, spec: unknown) => { sources.set(id, spec); }),
      getSource: vi.fn((id: string) => sources.get(id) ?? null),
      removeLayer: vi.fn(),
      removeSource: vi.fn(),
      setPaintProperty: vi.fn(),
      setLayoutProperty: vi.fn((id: string, prop: string, value: unknown) => {
        const props = layoutProps.get(id) ?? {};
        props[prop] = value;
        layoutProps.set(id, props);
      }),
      getLayoutProperty: vi.fn((id: string, prop: string) => layoutProps.get(id)?.[prop]),
      setFilter: vi.fn(),
      setLayerZoomRange: vi.fn(),
      hasImage: vi.fn(() => false),
      addImage: vi.fn(),
      getSprite: vi.fn(() => []),
      addSprite: vi.fn(),
      isStyleLoaded: vi.fn(() => true),
      __layerSpecs: layerSpecs,
      __layoutProps: layoutProps,
    } as unknown as MaplibreMap & {
      __layerSpecs: Map<string, { layout?: Record<string, unknown> }>;
      __layoutProps: Map<string, Record<string, unknown>>;
    };
  }

  function commonInput(layerId: string, visible: boolean) {
    return {
      id: layerId,
      dataset_table_name: 'shared',
      dataset_geometry_type: 'Polygon',
      opacity: 1,
      visible,
      paint: {},
      layout: {},
      filter: null,
      sourceId: `source-${layerId}`,
      layerId: `layer-${layerId}`,
      sourceLayer: 'data.shared',
      tileUrl: '/tiles/shared/{z}/{x}/{y}.pbf',
    };
  }

  it('fillAdapter.addLayers with visible=false ends with main layer visibility "none"', async () => {
    const { fillAdapter } = await import('@/components/builder/layer-adapters/fill-adapter');
    const map = makeAddLayerMap();
    const input = commonInput('hidden-fill', false);

    fillAdapter.addLayers(map as unknown as MaplibreMap, input as never);

    const vis = (map as unknown as { getLayoutProperty: (id: string, prop: string) => unknown })
      .getLayoutProperty('layer-hidden-fill', 'visibility');
    expect(vis).toBe('none');

    // Outline companion must also be hidden (it shares the parent's visibility).
    const outlineVis = (map as unknown as { getLayoutProperty: (id: string, prop: string) => unknown })
      .getLayoutProperty('layer-hidden-fill-outline', 'visibility');
    expect(outlineVis).toBe('none');
  });

  it('fillAdapter.addLayers with visible=true ends with main layer visibility "visible"', async () => {
    const { fillAdapter } = await import('@/components/builder/layer-adapters/fill-adapter');
    const map = makeAddLayerMap();
    const input = commonInput('shown-fill', true);

    fillAdapter.addLayers(map as unknown as MaplibreMap, input as never);

    const vis = (map as unknown as { getLayoutProperty: (id: string, prop: string) => unknown })
      .getLayoutProperty('layer-shown-fill', 'visibility');
    // Either explicit 'visible' or undefined (MapLibre default) is acceptable.
    expect(vis === 'visible' || vis === undefined).toBe(true);
  });

  it('lineAdapter.addLayers with visible=false ends with main layer visibility "none"', async () => {
    const { lineAdapter } = await import('@/components/builder/layer-adapters/line-adapter');
    const map = makeAddLayerMap();
    const input = { ...commonInput('hidden-line', false), dataset_geometry_type: 'LineString' };

    lineAdapter.addLayers(map as unknown as MaplibreMap, input as never);

    const vis = (map as unknown as { getLayoutProperty: (id: string, prop: string) => unknown })
      .getLayoutProperty('layer-hidden-line', 'visibility');
    expect(vis).toBe('none');
  });

  it('circleAdapter.addLayers with visible=false ends with main layer visibility "none"', async () => {
    const { circleAdapter } = await import('@/components/builder/layer-adapters/circle-adapter');
    const map = makeAddLayerMap();
    const input = { ...commonInput('hidden-circle', false), dataset_geometry_type: 'Point' };

    circleAdapter.addLayers(map as unknown as MaplibreMap, input as never);

    const vis = (map as unknown as { getLayoutProperty: (id: string, prop: string) => unknown })
      .getLayoutProperty('layer-hidden-circle', 'visibility');
    expect(vis).toBe('none');
  });

  it('heatmapAdapter.addLayers with visible=false ends with main layer visibility "none"', async () => {
    const { heatmapAdapter } = await import('@/components/builder/layer-adapters/heatmap-adapter');
    const map = makeAddLayerMap();
    const input = { ...commonInput('hidden-heatmap', false), dataset_geometry_type: 'Point' };

    heatmapAdapter.addLayers(map as unknown as MaplibreMap, input as never);

    const vis = (map as unknown as { getLayoutProperty: (id: string, prop: string) => unknown })
      .getLayoutProperty('layer-hidden-heatmap', 'visibility');
    expect(vis).toBe('none');
  });
});

// ---------------------------------------------------------------------------
// BUG-019 regression: applyLayerUpdate composes multi-field updates inside
// functional setState.
//
// Pre-fix: `const updated = updater(layersRef.current.find(...))` captured the
// stale ref snapshot OUTSIDE the functional setState. Two synchronous
// applyLayerUpdate calls for different fields both captured from the same stale
// ref, so the second call's setState clobbered the first call's paint changes.
//
// Post-fix: the updater is applied INSIDE prev.map() so React's functional
// update composition applies each updater against the latest prev, not the
// stale ref snapshot. Both field changes land in the final state.
//
// The test uses a wrapper hook that owns real useState so we can assert the
// accumulated state (not just spy calls). The wrapper mirrors the pattern
// used throughout this file but adds a `getCurrentLayer()` helper so the
// test can inspect state after act().
// ---------------------------------------------------------------------------

describe('applyLayerUpdate — multi-field composition (BUG-019)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('Test 1 (BUG-019): two synchronous applyLayerUpdate calls compose — both fields land in final state', () => {
    /**
     * Setup: layer with paint={} and opacity=1.
     * Two synchronous handlePaintChange + handleOpacityChange calls inside
     * one act().
     *
     * Pre-fix: both calls captured from the same stale layersRef snapshot.
     *   After act(): paint={} (lost!), opacity=0.5 — only the LAST field wins.
     * Post-fix: updater() runs inside prev.map() so React's queue applies
     *   paint update, then opacity update against that result.
     *   After act(): paint={'fill-color':'red'}, opacity=0.5 — BOTH fields land.
     */
    const initialLayer = makeLayer({ paint: {}, opacity: 1 });
    let finalLayers: MapLayerResponse[] = [initialLayer];

    // Wrapper hook that owns real React state and exposes the accumulated result.
    const { result } = renderHook(() => {
      const [layers, setLayers] = React.useState([initialLayer]);
      finalLayers = layers;
      return useLayerMapSync(
        layers,
        setLayers as React.Dispatch<React.SetStateAction<MapLayerResponse[]>>,
        vi.fn(),
        { current: null } as unknown as React.RefObject<import('maplibre-gl').Map | null>,
      );
    });

    act(() => {
      // Two synchronous calls with different fields — must both apply
      result.current.handlePaintChange(LAYER_ID, { 'fill-color': '#ff0000' });
      result.current.handleOpacityChange(LAYER_ID, 0.5);
    });

    const finalLayer = finalLayers.find((l) => l.id === LAYER_ID);
    // Both fields must be present in the final state
    expect(finalLayer?.paint).toEqual({ 'fill-color': '#ff0000' });
    expect(finalLayer?.opacity).toBe(0.5);
  });

  it('Test 2 (BUG-019): non-matching layerId early-exits without state mutation (existence gate still works)', () => {
    const initialLayer = makeLayer({ paint: {}, opacity: 1 });
    let finalLayers: MapLayerResponse[] = [initialLayer];
    const setHasUnsavedChanges = vi.fn();

    const { result } = renderHook(() => {
      const [layers, setLayers] = React.useState([initialLayer]);
      finalLayers = layers;
      return useLayerMapSync(
        layers,
        setLayers as React.Dispatch<React.SetStateAction<MapLayerResponse[]>>,
        setHasUnsavedChanges,
        { current: null } as unknown as React.RefObject<import('maplibre-gl').Map | null>,
      );
    });

    act(() => {
      result.current.handlePaintChange('no-such-layer', { 'fill-color': '#ff0000' });
    });

    // Existence gate: no state mutation, no dirty flag
    expect(setHasUnsavedChanges).not.toHaveBeenCalled();
    const layer = finalLayers.find((l) => l.id === LAYER_ID);
    expect(layer?.paint).toEqual({});
  });
});

describe('useLayerMapSync — handleStyleConfigChange line-gradient cleanup (P1-07)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('drops line-gradient paint + builder.lineGradient when switching to data-driven solid color', () => {
    const initialLayer = makeLayer({
      dataset_geometry_type: 'LineString',
      paint: {
        'line-color': '#888888',
        'line-gradient': ['interpolate', ['linear'], ['line-progress'], 0, '#000000', 1, '#ffffff'],
      },
      style_config: {
        builder: { lineGradient: { stops: [{ position: 0, color: '#000000' }] } },
      } as MapLayerResponse['style_config'],
    });
    let finalLayers: MapLayerResponse[] = [initialLayer];

    const { result } = renderHook(() => {
      const [layers, setLayers] = React.useState([initialLayer]);
      finalLayers = layers;
      return useLayerMapSync(
        layers,
        setLayers as React.Dispatch<React.SetStateAction<MapLayerResponse[]>>,
        vi.fn(),
        { current: makeMapStub() } as unknown as React.RefObject<import('maplibre-gl').Map | null>,
      );
    });

    act(() => {
      result.current.handleStyleConfigChange(
        LAYER_ID,
        { mode: 'categorical', column: 'kind', ramp: 'Set2' },
        {
          'line-color': ['match', ['get', 'kind'], 'a', '#ff0000', '#00ff00'],
          'line-gradient': ['interpolate', ['linear'], ['line-progress'], 0, '#000000', 1, '#ffffff'],
        },
      );
    });

    const updated = finalLayers.find((l) => l.id === LAYER_ID)!;
    expect('line-gradient' in (updated.paint ?? {})).toBe(false);
    const builder = (updated.style_config as { builder?: { lineGradient?: unknown } } | null)?.builder;
    expect(builder?.lineGradient).toBeUndefined();
  });

  it('preserves line-gradient when switching a graduated SIZE target (not color)', () => {
    const initialLayer = makeLayer({
      dataset_geometry_type: 'LineString',
      paint: {
        'line-gradient': ['interpolate', ['linear'], ['line-progress'], 0, '#000000', 1, '#ffffff'],
      },
      style_config: {
        builder: { lineGradient: { stops: [{ position: 0, color: '#000000' }] } },
      } as MapLayerResponse['style_config'],
    });
    let finalLayers: MapLayerResponse[] = [initialLayer];

    const { result } = renderHook(() => {
      const [layers, setLayers] = React.useState([initialLayer]);
      finalLayers = layers;
      return useLayerMapSync(
        layers,
        setLayers as React.Dispatch<React.SetStateAction<MapLayerResponse[]>>,
        vi.fn(),
        { current: makeMapStub() } as unknown as React.RefObject<import('maplibre-gl').Map | null>,
      );
    });

    act(() => {
      result.current.handleStyleConfigChange(
        LAYER_ID,
        { mode: 'graduated', column: 'len', ramp: 'YlOrRd', target: 'width' },
        { 'line-gradient': ['interpolate', ['linear'], ['line-progress'], 0, '#000000', 1, '#ffffff'], 'line-width': 3 },
      );
    });

    const updated = finalLayers.find((l) => l.id === LAYER_ID)!;
    // A size-target change must NOT clear the gradient.
    expect('line-gradient' in (updated.paint ?? {})).toBe(true);
  });
});

// fix(#918): fill-color / fill-pattern is the same exclusion shape. MapLibre gives
// the pattern precedence, so a ramp applied over a pattern rendered the pattern
// while the appearance section, the legend and saved paint all claimed the ramp.
describe('useLayerMapSync — handleStyleConfigChange fill-pattern cleanup (#918)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function renderWith(initialLayer: MapLayerResponse, mapStub = makeMapStub()) {
    let finalLayers: MapLayerResponse[] = [initialLayer];
    const { result } = renderHook(() => {
      const [layers, setLayers] = React.useState([initialLayer]);
      finalLayers = layers;
      return useLayerMapSync(
        layers,
        setLayers as React.Dispatch<React.SetStateAction<MapLayerResponse[]>>,
        vi.fn(),
        { current: mapStub } as unknown as React.RefObject<import('maplibre-gl').Map | null>,
      );
    });
    return { result, mapStub, layers: () => finalLayers };
  }

  const RAMP = ['match', ['get', 'era'], 'pre-war', '#ff0000', '#00ff00'];

  it('drops fill-pattern paint + the stale fillColorSaved stash when a ramp takes the fill color', () => {
    const { result, layers } = renderWith(
      makeLayer({
        dataset_geometry_type: 'Polygon',
        paint: { 'fill-pattern': 'geolens-fill-hatch', 'fill-opacity': 0.3 },
        style_config: {
          builder: { fillColorSaved: '#ff0000', outlineWidth: 2 },
        } as MapLayerResponse['style_config'],
      }),
    );

    act(() => {
      result.current.handleStyleConfigChange(
        LAYER_ID,
        { mode: 'categorical', column: 'era', ramp: 'Set2' },
        { 'fill-pattern': 'geolens-fill-hatch', 'fill-opacity': 0.3, 'fill-color': RAMP },
      );
    });

    const updated = layers().find((l) => l.id === LAYER_ID)!;
    expect('fill-pattern' in (updated.paint ?? {})).toBe(false);
    expect(updated.paint?.['fill-color']).toEqual(RAMP);
    const builder = (updated.style_config as { builder?: Record<string, unknown> } | null)?.builder;
    expect(builder?.fillColorSaved).toBeUndefined();
    // Unrelated builder fields survive.
    expect(builder?.outlineWidth).toBe(2);
  });

  it('preserves fill-pattern when the write is not a data-driven color', () => {
    const { result, layers } = renderWith(
      makeLayer({
        dataset_geometry_type: 'Polygon',
        paint: { 'fill-pattern': 'geolens-fill-hatch' },
      }),
    );

    act(() => {
      result.current.handleStyleConfigChange(
        LAYER_ID,
        { builder: { outlineWidth: 3 } },
        { 'fill-pattern': 'geolens-fill-hatch' },
      );
    });

    const updated = layers().find((l) => l.id === LAYER_ID)!;
    expect(updated.paint?.['fill-pattern']).toBe('geolens-fill-hatch');
  });

  it('preserves fill-pattern when a graduated SIZE target changes', () => {
    const { result, layers } = renderWith(
      makeLayer({
        dataset_geometry_type: 'Polygon',
        paint: { 'fill-pattern': 'geolens-fill-hatch', 'fill-color': RAMP },
      }),
    );

    act(() => {
      result.current.handleStyleConfigChange(
        LAYER_ID,
        { mode: 'graduated', column: 'len', ramp: 'YlOrRd', target: 'width' },
        { 'fill-pattern': 'geolens-fill-hatch', 'fill-color': RAMP, 'line-width': 3 },
      );
    });

    expect('fill-pattern' in (layers().find((l) => l.id === LAYER_ID)!.paint ?? {})).toBe(true);
  });

  // fix(#910, codex P2): the funnel half of the stash clear. A config that collapsed
  // to null because fillColorSaved was its only field hits the "keep the existing
  // builder" branch, which resurrects the stash — `replace` is what makes it stick.
  it('wipes the builder when a replace write clears its last field', () => {
    const { result, layers } = renderWith(
      makeLayer({
        dataset_geometry_type: 'Polygon',
        paint: { 'fill-pattern': 'geolens-fill-hatch' },
        style_config: { builder: { fillColorSaved: '#ff0000' } } as MapLayerResponse['style_config'],
      }),
    );

    act(() => {
      result.current.handleStyleConfigChange(
        LAYER_ID,
        null,
        { 'fill-color': '#ff0000' },
        { replace: true },
      );
    });

    expect(layers().find((l) => l.id === LAYER_ID)!.style_config).toBeNull();
  });

  it('without replace, a null config still preserves the builder (revert contract)', () => {
    const { result, layers } = renderWith(
      makeLayer({
        dataset_geometry_type: 'Polygon',
        style_config: { builder: { outlineWidth: 3 } } as MapLayerResponse['style_config'],
      }),
    );

    act(() => {
      result.current.handleStyleConfigChange(LAYER_ID, null, { 'fill-color': '#ff0000' });
    });

    const builder = (layers().find((l) => l.id === LAYER_ID)!.style_config as
      { builder?: Record<string, unknown> } | null)?.builder;
    expect(builder?.outlineWidth).toBe(3);
  });

  // fix(#910, codex P2): the both-keys collision also arrives with NO data-driven
  // config. Paste-style merges a copied fill-pattern onto a target that kept its own
  // fill-color, so this is the shape handlePasteStyle actually sends.
  it('drops the target fill-color when a pasted pattern arrives beside it', () => {
    const { result, layers } = renderWith(
      makeLayer({
        dataset_geometry_type: 'Polygon',
        paint: { 'fill-color': '#0000ff', 'fill-opacity': 0.3 },
      }),
    );

    act(() => {
      // What applyCopiedStyleToLayer produces: copied pattern over the target's colour,
      // with the SOURCE layer's colour already stashed in the copied builder.
      result.current.handleStyleConfigChange(
        LAYER_ID,
        { builder: { fillColorSaved: '#ff0000' } } as StyleConfig,
        { 'fill-color': '#0000ff', 'fill-pattern': 'geolens-fill-hatch', 'fill-opacity': 0.3 },
      );
    });

    const updated = layers().find((l) => l.id === LAYER_ID)!;
    expect('fill-color' in (updated.paint ?? {})).toBe(false);
    expect(updated.paint?.['fill-pattern']).toBe('geolens-fill-hatch');
    // The copied source colour wins — that is the one None has to restore, not the
    // target's old blue.
    const builder = (updated.style_config as { builder?: Record<string, unknown> } | null)?.builder;
    expect(builder?.fillColorSaved).toBe('#ff0000');
  });

  it('stashes the dropped colour when the incoming config has no stash of its own', () => {
    const { result, layers } = renderWith(
      makeLayer({ dataset_geometry_type: 'Polygon', paint: { 'fill-color': '#0000ff' } }),
    );

    act(() => {
      result.current.handleStyleConfigChange(
        LAYER_ID,
        { builder: { outlineWidth: 2 } } as StyleConfig,
        { 'fill-color': '#0000ff', 'fill-pattern': 'geolens-fill-dots' },
      );
    });

    const builder = (layers().find((l) => l.id === LAYER_ID)!.style_config as
      { builder?: Record<string, unknown> } | null)?.builder;
    expect(builder?.fillColorSaved).toBe('#0000ff');
    expect(builder?.outlineWidth).toBe(2);
  });

  // fix(#910, codex P2): this asserted the drop and the drop was wrong. An expression
  // has no stashable form, so removing it is unrecoverable — and it does not take a
  // pattern click to get here: an Advanced-JSON layer carrying both keys re-sends
  // that paint through the funnel on ANY later builder edit, so an outline-width
  // change silently destroyed the classification. LayerStyleEditor already emits the
  // expression untouched when a pattern is applied; the funnel now agrees.
  it('keeps an expression-valued fill-color rather than dropping what it cannot stash', () => {
    const { result, layers } = renderWith(
      makeLayer({ dataset_geometry_type: 'Polygon', paint: { 'fill-color': RAMP } }),
    );

    act(() => {
      result.current.handleStyleConfigChange(
        LAYER_ID,
        { builder: { outlineWidth: 2 } } as StyleConfig,
        { 'fill-color': RAMP, 'fill-pattern': 'geolens-fill-hatch' },
      );
    });

    const updated = layers().find((l) => l.id === LAYER_ID)!;
    expect(updated.paint?.['fill-color']).toEqual(RAMP);
    expect(updated.paint?.['fill-pattern']).toBe('geolens-fill-hatch');
    const builder = (updated.style_config as { builder?: Record<string, unknown> } | null)?.builder;
    expect(builder?.fillColorSaved).toBeUndefined();
  });

  // fix(#914): the drop above is what makes the tint correct, so pin the two
  // together. `fillPatternTint` prefers a string `fill-color` in paint over the
  // stash, so leaving the target's colour there — which is what MapLibre would
  // tolerate, since the pattern wins visually either way — tints the pasted
  // pattern the TARGET's blue on the map and all three legend surfaces instead of
  // the red the user copied. Nothing else would catch that: both halves pass
  // their own tests, and only the composition is wrong.
  it('leaves a pasted pattern tinting the copied colour, not the target one', () => {
    const { result, layers } = renderWith(
      makeLayer({ dataset_geometry_type: 'Polygon', paint: { 'fill-color': '#0000ff' } }),
    );

    act(() => {
      result.current.handleStyleConfigChange(
        LAYER_ID,
        { builder: { fillColorSaved: '#ff0000' } } as StyleConfig,
        { 'fill-color': '#0000ff', 'fill-pattern': 'geolens-fill-hatch' },
      );
    });

    const updated = layers().find((l) => l.id === LAYER_ID)!;
    const builder = (updated.style_config as { builder?: { fillColorSaved?: string } } | null)
      ?.builder;
    expect(fillPatternTint(updated.paint, builder)).toBe('#ff0000');
  });
});

// fix(#461, codex P2): Revert-to-saved passes { replace: true } so the saved
// config is restored verbatim. Without it, the default builder-preserve would
// strand a discarded builder-only edit (e.g. outline width) and keep the layer dirty.
describe('useLayerMapSync — handleStyleConfigChange replace mode (revert)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function runWith(opts?: { replace?: boolean }) {
    const draftLayer = makeLayer({
      dataset_geometry_type: 'LineString',
      paint: { 'line-color': '#123456' },
      // draft carries a builder-only edit the saved baseline never had
      style_config: { builder: { outlineWidth: 4 } } as MapLayerResponse['style_config'],
    });
    let finalLayers: MapLayerResponse[] = [draftLayer];
    const { result } = renderHook(() => {
      const [layers, setLayers] = React.useState([draftLayer]);
      finalLayers = layers;
      return useLayerMapSync(
        layers,
        setLayers as React.Dispatch<React.SetStateAction<MapLayerResponse[]>>,
        vi.fn(),
        { current: makeMapStub() } as unknown as React.RefObject<import('maplibre-gl').Map | null>,
      );
    });
    act(() => {
      // saved baseline had no style_config → restore null
      result.current.handleStyleConfigChange(LAYER_ID, null, { 'line-color': '#000000' }, opts);
    });
    return finalLayers.find((l) => l.id === LAYER_ID)!;
  }

  it('replace:true drops the draft builder (restores null verbatim)', () => {
    expect(runWith({ replace: true }).style_config).toBeNull();
  });

  it('default (no opts) preserves the draft builder — the behavior revert must bypass', () => {
    const updated = runWith();
    const builder = (updated.style_config as { builder?: { outlineWidth?: number } } | null)?.builder;
    expect(builder?.outlineWidth).toBe(4);
  });
});

// fix(#910/#918, codex P2): the EDIT-05 rule is enforced at applyLayerUpdate, the one
// boundary every handler in this hook commits through, so it holds on paths that never
// touch handleStyleConfigChange. The provenance rule is read off the paint diff: the key
// the write INTRODUCED is the one the user asked for.
describe('useLayerMapSync — EDIT-05 at the commit boundary', () => {
  const LID = 'layer-uuid-123';

  function renderBoundary(initialLayer: MapLayerResponse, mapStub = makeMapStub()) {
    let finalLayers: MapLayerResponse[] = [initialLayer];
    const { result } = renderHook(() => {
      const [layers, setLayers] = React.useState([initialLayer]);
      finalLayers = layers;
      return useLayerMapSync(
        layers,
        setLayers as React.Dispatch<React.SetStateAction<MapLayerResponse[]>>,
        vi.fn(),
        { current: mapStub } as unknown as React.RefObject<import('maplibre-gl').Map | null>,
      );
    });
    return { result, mapStub, layers: () => finalLayers };
  }

  // The AI `set_style` action and the Advanced JSON editor both write through
  // onPaintChange, never the style-config funnel. Adding a colour to a patterned layer
  // reported success while MapLibre kept drawing the old pattern.
  it('a paint-only write that adds fill-color displaces the pattern', () => {
    const { result, layers } = renderBoundary(
      makeLayer({
        dataset_geometry_type: 'Polygon',
        paint: { 'fill-pattern': 'geolens-fill-hatch', 'fill-opacity': 0.3 },
      }),
    );

    act(() => {
      result.current.handlePaintChange(LID, {
        'fill-pattern': 'geolens-fill-hatch',
        'fill-color': '#abc',
        'fill-opacity': 0.3,
      });
    });

    const updated = layers().find((l) => l.id === LID)!;
    expect('fill-pattern' in (updated.paint ?? {})).toBe(false);
    expect(updated.paint?.['fill-color']).toBe('#abc');
  });

  // The mirror direction on the same path: a pattern added over a solid colour.
  it('a paint-only write that adds fill-pattern displaces and stashes the colour', () => {
    const { result, layers } = renderBoundary(
      makeLayer({ dataset_geometry_type: 'Polygon', paint: { 'fill-color': '#0000ff' } }),
    );

    act(() => {
      result.current.handlePaintChange(LID, {
        'fill-color': '#0000ff',
        'fill-pattern': 'geolens-fill-dots',
      });
    });

    const updated = layers().find((l) => l.id === LID)!;
    expect('fill-color' in (updated.paint ?? {})).toBe(false);
    const builder = (updated.style_config as { builder?: Record<string, unknown> } | null)?.builder;
    expect(builder?.fillColorSaved).toBe('#0000ff');
  });

  // A write that does not touch paint expresses no new intent, so a layer that already
  // carries the forbidden pair is left exactly as it was.
  it('leaves a pre-existing collision alone when the write does not touch paint', () => {
    const { result, layers } = renderBoundary(
      makeLayer({
        dataset_geometry_type: 'Polygon',
        paint: { 'fill-color': '#0000ff', 'fill-pattern': 'geolens-fill-hatch' },
      }),
    );

    act(() => {
      result.current.handleToggleVisibility(LID);
    });

    const updated = layers().find((l) => l.id === LID)!;
    expect(updated.paint?.['fill-color']).toBe('#0000ff');
    expect(updated.paint?.['fill-pattern']).toBe('geolens-fill-hatch');
    expect(updated.visible).toBe(false);
  });

  // Revert-to-saved must reproduce the baseline byte-for-byte: the dirty check diffs
  // against that same baseline, so a normalized restore never returns to clean.
  it('restores a both-keys baseline verbatim instead of normalizing it', () => {
    const savedPaint = { 'fill-color': '#0000ff', 'fill-pattern': 'geolens-fill-hatch' };
    const { result, layers } = renderBoundary(
      makeLayer({ dataset_geometry_type: 'Polygon', paint: { 'fill-color': '#ff0000' } }),
    );

    act(() => {
      result.current.handleStyleConfigChange(LID, null, savedPaint, { replace: true, restore: true });
    });

    expect(layers().find((l) => l.id === LID)!.paint).toEqual(savedPaint);
  });

  it('still normalizes a replace that is NOT a restore', () => {
    const { result, layers } = renderBoundary(
      makeLayer({ dataset_geometry_type: 'Polygon', paint: { 'fill-pattern': 'geolens-fill-hatch' } }),
    );

    act(() => {
      result.current.handleStyleConfigChange(
        LID,
        null,
        { 'fill-pattern': 'geolens-fill-hatch', 'fill-color': '#abc' },
        { replace: true },
      );
    });

    const updated = layers().find((l) => l.id === LID)!;
    expect('fill-pattern' in (updated.paint ?? {})).toBe(false);
    expect(updated.paint?.['fill-color']).toBe('#abc');
  });
});

// fix(#910, codex P2): the stash has to track WHO owns the fill across a sequence of
// writes, not just the write in front of it. A solid colour taking the fill leaves any
// previous stash stale; keeping it meant the next pattern write found the slot occupied
// and None restored a colour from two edits back.
describe('useLayerMapSync — the fill-colour stash across successive writes', () => {
  const LID = 'layer-uuid-123';

  function renderSeq(initialLayer: MapLayerResponse) {
    let finalLayers: MapLayerResponse[] = [initialLayer];
    const { result } = renderHook(() => {
      const [layers, setLayers] = React.useState([initialLayer]);
      finalLayers = layers;
      return useLayerMapSync(
        layers,
        setLayers as React.Dispatch<React.SetStateAction<MapLayerResponse[]>>,
        vi.fn(),
        { current: makeMapStub() } as unknown as React.RefObject<import('maplibre-gl').Map | null>,
      );
    });
    return { result, layers: () => finalLayers };
  }

  const builderOf = (l: MapLayerResponse) =>
    (l.style_config as { builder?: Record<string, unknown> } | null)?.builder;

  it('a solid colour taking the fill clears the stale stash', () => {
    const { result, layers } = renderSeq(
      makeLayer({
        dataset_geometry_type: 'Polygon',
        paint: { 'fill-pattern': 'geolens-fill-hatch' },
        style_config: { builder: { fillColorSaved: '#111111' } } as MapLayerResponse['style_config'],
      }),
    );

    act(() => {
      result.current.handlePaintChange(LID, {
        'fill-pattern': 'geolens-fill-hatch',
        'fill-color': '#222222',
      });
    });

    expect(builderOf(layers().find((l) => l.id === LID)!)?.fillColorSaved).toBeUndefined();
  });

  it('so a later pattern write stashes the CURRENT colour, not the two-edits-ago one', () => {
    const { result, layers } = renderSeq(
      makeLayer({
        dataset_geometry_type: 'Polygon',
        paint: { 'fill-pattern': 'geolens-fill-hatch' },
        style_config: { builder: { fillColorSaved: '#111111' } } as MapLayerResponse['style_config'],
      }),
    );

    // 1: a solid colour takes the fill (AI set_style / Advanced JSON).
    act(() => {
      result.current.handlePaintChange(LID, {
        'fill-pattern': 'geolens-fill-hatch',
        'fill-color': '#222222',
      });
    });
    // 2: a pattern takes it back. The colour it displaces is #222222.
    act(() => {
      result.current.handlePaintChange(LID, {
        'fill-color': '#222222',
        'fill-pattern': 'geolens-fill-dots',
      });
    });

    const updated = layers().find((l) => l.id === LID)!;
    expect(updated.paint?.['fill-pattern']).toBe('geolens-fill-dots');
    expect('fill-color' in (updated.paint ?? {})).toBe(false);
    expect(builderOf(updated)?.fillColorSaved).toBe('#222222');
  });

  it('keeps the stash while the pattern still owns the fill', () => {
    const { result, layers } = renderSeq(
      makeLayer({
        dataset_geometry_type: 'Polygon',
        paint: { 'fill-pattern': 'geolens-fill-hatch', 'fill-opacity': 0.5 },
        style_config: { builder: { fillColorSaved: '#111111' } } as MapLayerResponse['style_config'],
      }),
    );

    act(() => {
      result.current.handlePaintChange(LID, {
        'fill-pattern': 'geolens-fill-hatch',
        'fill-opacity': 0.9,
      });
    });

    expect(builderOf(layers().find((l) => l.id === LID)!)?.fillColorSaved).toBe('#111111');
  });
});

// fix(#910, codex P2): presence is not intent. On a layer that already carried BOTH fill
// keys, editing the colour left both "added" checks false, so pattern-wins fired and the
// edit the user just made was deleted. The diff compares values now.
describe('useLayerMapSync — a CHANGED fill key counts as intent, not just a new one', () => {
  const LID = 'layer-uuid-123';

  function renderPrev(paint: Record<string, unknown>) {
    const initialLayer = makeLayer({ dataset_geometry_type: 'Polygon', paint });
    let finalLayers: MapLayerResponse[] = [initialLayer];
    const { result } = renderHook(() => {
      const [layers, setLayers] = React.useState([initialLayer]);
      finalLayers = layers;
      return useLayerMapSync(
        layers,
        setLayers as React.Dispatch<React.SetStateAction<MapLayerResponse[]>>,
        vi.fn(),
        { current: makeMapStub() } as unknown as React.RefObject<import('maplibre-gl').Map | null>,
      );
    });
    return { result, layers: () => finalLayers };
  }

  it('editing the colour on a both-keys layer keeps the edit and drops the pattern', () => {
    const { result, layers } = renderPrev({
      'fill-color': '#111111',
      'fill-pattern': 'geolens-fill-hatch',
    });

    act(() => {
      result.current.handlePaintChange(LID, {
        'fill-color': '#222222',
        'fill-pattern': 'geolens-fill-hatch',
      });
    });

    const updated = layers().find((l) => l.id === LID)!;
    expect(updated.paint?.['fill-color']).toBe('#222222');
    expect('fill-pattern' in (updated.paint ?? {})).toBe(false);
  });

  it('editing the pattern on a both-keys layer keeps the pattern and stashes the colour', () => {
    const { result, layers } = renderPrev({
      'fill-color': '#111111',
      'fill-pattern': 'geolens-fill-hatch',
    });

    act(() => {
      result.current.handlePaintChange(LID, {
        'fill-color': '#111111',
        'fill-pattern': 'geolens-fill-dots',
      });
    });

    const updated = layers().find((l) => l.id === LID)!;
    expect(updated.paint?.['fill-pattern']).toBe('geolens-fill-dots');
    expect('fill-color' in (updated.paint ?? {})).toBe(false);
    const builder = (updated.style_config as { builder?: Record<string, unknown> } | null)?.builder;
    expect(builder?.fillColorSaved).toBe('#111111');
  });

  // Both touched at once is genuinely ambiguous — no rule can read intent out of it — so
  // it takes the documented fallback rather than guessing. Pinned so the fallback is a
  // decision and not an accident.
  it('falls back to pattern-wins when the write touched both keys', () => {
    const { result, layers } = renderPrev({
      'fill-color': '#111111',
      'fill-pattern': 'geolens-fill-hatch',
    });

    act(() => {
      result.current.handlePaintChange(LID, {
        'fill-color': '#222222',
        'fill-pattern': 'geolens-fill-dots',
      });
    });

    const updated = layers().find((l) => l.id === LID)!;
    expect(updated.paint?.['fill-pattern']).toBe('geolens-fill-dots');
    expect('fill-color' in (updated.paint ?? {})).toBe(false);
  });
});

// fix(#910, codex P2): the displacement is a TRANSITION to a pattern-owned fill, not
// necessarily a collision. Advanced JSON replacing paint wholesale, or an AI set_style
// with replace_paint, hands over a pattern-only object that already dropped the colour —
// so nothing collided, nothing was stashed, and None fell back to default blue.
describe('useLayerMapSync — a replacement paint still stashes the colour it displaced', () => {
  const LID = 'layer-uuid-123';
  const RAMP_SEQ = ['match', ['get', 'era'], 'pre-war', '#ff0000', '#00ff00'];

  function renderPrev(paint: Record<string, unknown>, styleConfig: MapLayerResponse['style_config'] = null) {
    const initialLayer = makeLayer({ dataset_geometry_type: 'Polygon', paint, style_config: styleConfig });
    let finalLayers: MapLayerResponse[] = [initialLayer];
    const { result } = renderHook(() => {
      const [layers, setLayers] = React.useState([initialLayer]);
      finalLayers = layers;
      return useLayerMapSync(
        layers,
        setLayers as React.Dispatch<React.SetStateAction<MapLayerResponse[]>>,
        vi.fn(),
        { current: makeMapStub() } as unknown as React.RefObject<import('maplibre-gl').Map | null>,
      );
    });
    return { result, layers: () => finalLayers };
  }

  const builderOf = (l: MapLayerResponse) =>
    (l.style_config as { builder?: Record<string, unknown> } | null)?.builder;

  it('stashes the previous colour when the replacement dropped it', () => {
    const { result, layers } = renderPrev({ 'fill-color': '#ff0000', 'fill-opacity': 0.4 });

    act(() => {
      // Wholesale replacement: no fill-color at all, so nothing collides.
      result.current.handlePaintChange(LID, { 'fill-pattern': 'geolens-fill-hatch' });
    });

    const updated = layers().find((l) => l.id === LID)!;
    expect(updated.paint?.['fill-pattern']).toBe('geolens-fill-hatch');
    expect(builderOf(updated)?.fillColorSaved).toBe('#ff0000');
  });

  it('does not stash a previous expression colour, which has no solid form', () => {
    const { result, layers } = renderPrev({ 'fill-color': RAMP_SEQ });

    act(() => {
      result.current.handlePaintChange(LID, { 'fill-pattern': 'geolens-fill-hatch' });
    });

    expect(builderOf(layers().find((l) => l.id === LID)!)?.fillColorSaved).toBeUndefined();
  });

  it('leaves an existing stash alone when the replacement had no colour to displace', () => {
    const { result, layers } = renderPrev(
      { 'fill-pattern': 'geolens-fill-hatch' },
      { builder: { fillColorSaved: '#0000ff' } } as MapLayerResponse['style_config'],
    );

    act(() => {
      result.current.handlePaintChange(LID, { 'fill-pattern': 'geolens-fill-dots' });
    });

    expect(builderOf(layers().find((l) => l.id === LID)!)?.fillColorSaved).toBe('#0000ff');
  });
});

// fix(#910, codex P2): style_config and paint are two records of one fact, and the
// surfaces split between them — the map draws the expression, the legend and the style
// editor read the config. A paint replacement (Advanced JSON, an AI `replace_paint`) can
// drop the expression and leave the config behind, and every reader downstream then
// reports styling the map is not doing. The reconciliation is at this boundary, keyed
// off the RESOLVED paint, because the writers are an open set and the None click was
// merely the first control to trip over the disagreement.
describe('useLayerMapSync — an orphaned colour classification is reconciled at the boundary', () => {
  const LID = 'layer-uuid-123';
  const RAMP_CLS = ['match', ['get', 'era'], 'pre-war', '#ff0000', '#00ff00'];
  const CATEGORICAL = {
    mode: 'categorical',
    column: 'era',
    ramp: 'Set2',
    categories: [{ value: 'pre-war', color: '#ff0000' }],
  } as StyleConfig;

  function renderBoundary(initialLayer: MapLayerResponse) {
    let finalLayers: MapLayerResponse[] = [initialLayer];
    const { result } = renderHook(() => {
      const [layers, setLayers] = React.useState([initialLayer]);
      finalLayers = layers;
      return useLayerMapSync(
        layers,
        setLayers as React.Dispatch<React.SetStateAction<MapLayerResponse[]>>,
        vi.fn(),
        { current: makeMapStub() } as unknown as React.RefObject<import('maplibre-gl').Map | null>,
      );
    });
    return { result, layers: () => finalLayers };
  }

  const configOf = (layer: MapLayerResponse) =>
    layer.style_config as Record<string, unknown> | null;

  it('drops the claim when a paint replacement leaves no expression behind', () => {
    const { result, layers } = renderBoundary(
      makeLayer({
        dataset_geometry_type: 'Polygon',
        paint: { 'fill-color': RAMP_CLS },
        style_config: CATEGORICAL,
      }),
    );

    act(() => {
      result.current.handlePaintChange(LID, { 'fill-color': '#3b82f6' });
    });

    const config = configOf(layers().find((l) => l.id === LID)!);
    expect(config?.mode).toBeUndefined();
    expect(config?.categories).toBeUndefined();
    // fix(#910, codex P2): and `column` goes with them. Keeping it as "the user's
    // selection" re-applied the classification the next time the editor mounted, because
    // a config with a column and no mode reads to a fresh DataDrivenStyleEditor as a live
    // categorical classification.
    expect(config?.column).toBeUndefined();
    expect(config?.ramp).toBeUndefined();
  });

  // The same shape a pattern write produces: no fill-color in the resolved paint at all.
  it('drops the claim when the resolved paint has no colour key at all', () => {
    const { result, layers } = renderBoundary(
      makeLayer({
        dataset_geometry_type: 'Polygon',
        paint: { 'fill-color': RAMP_CLS },
        style_config: CATEGORICAL,
      }),
    );

    act(() => {
      result.current.handlePaintChange(LID, { 'fill-pattern': 'geolens-fill-hatch' });
    });

    expect(configOf(layers().find((l) => l.id === LID)!)?.mode).toBeUndefined();
  });

  it('keeps the claim when the expression survives the write', () => {
    const { result, layers } = renderBoundary(
      makeLayer({
        dataset_geometry_type: 'Polygon',
        paint: { 'fill-color': RAMP_CLS },
        style_config: CATEGORICAL,
      }),
    );

    act(() => {
      result.current.handlePaintChange(LID, { 'fill-color': RAMP_CLS, 'fill-opacity': 0.7 });
    });

    const config = configOf(layers().find((l) => l.id === LID)!);
    expect(config?.mode).toBe('categorical');
    expect(config?.categories).toHaveLength(1);
  });

  // A point layer's classification lives in circle-color. Reading fill-color for every
  // geometry would delete every point and line classification on any paint edit.
  it('reads the colour key this geometry actually uses', () => {
    const { result, layers } = renderBoundary(
      makeLayer({
        dataset_geometry_type: 'MultiPoint',
        paint: { 'circle-color': RAMP_CLS },
        style_config: CATEGORICAL,
      }),
    );

    act(() => {
      result.current.handlePaintChange(LID, { 'circle-color': RAMP_CLS, 'circle-radius': 8 });
    });

    expect(configOf(layers().find((l) => l.id === LID)!)?.mode).toBe('categorical');
  });

  // A size classification describes circle-radius; a colour write is none of its
  // business. The `colors` here are the stale leftovers of an earlier colour session,
  // which StyleConfig's open bag makes routine (#392) — without the target check they
  // read as a colour claim and a colour edit would delete the size styling.
  it('leaves a size-target classification alone', () => {
    const { result, layers } = renderBoundary(
      makeLayer({
        dataset_geometry_type: 'MultiPoint',
        paint: { 'circle-color': '#3b82f6', 'circle-radius': ['step', ['get', 'pop'], 2, 20, 8] },
        style_config: {
          mode: 'graduated',
          column: 'pop',
          target: 'radius',
          sizes: [2, 8],
          colors: ['#fee8c8', '#fdbb84'],
          breaks: [20],
        } as MapLayerResponse['style_config'],
      }),
    );

    act(() => {
      result.current.handlePaintChange(LID, {
        'circle-color': '#ff0000',
        'circle-radius': ['step', ['get', 'pop'], 2, 20, 8],
      });
    });

    const config = configOf(layers().find((l) => l.id === LID)!);
    expect(config?.mode).toBe('graduated');
    expect(config?.target).toBe('radius');
  });

  // Everything that is not the claim survives the strip. render_mode selects the
  // RENDERER, so folding an orphaned classification into a builder-only config would
  // silently un-cluster the layer.
  it('preserves render_mode and the builder block when it drops the claim', () => {
    const { result, layers } = renderBoundary(
      makeLayer({
        dataset_geometry_type: 'MultiPoint',
        paint: { 'circle-color': RAMP_CLS },
        style_config: {
          ...CATEGORICAL,
          render_mode: 'cluster',
          builder: { outlineWidth: 3 },
        } as MapLayerResponse['style_config'],
      }),
    );

    act(() => {
      result.current.handlePaintChange(LID, { 'circle-color': '#3b82f6' });
    });

    const config = configOf(layers().find((l) => l.id === LID)!);
    expect(config?.mode).toBeUndefined();
    expect(config?.render_mode).toBe('cluster');
    expect((config?.builder as { outlineWidth?: number } | undefined)?.outlineWidth).toBe(3);
  });

  // Revert restores the saved baseline verbatim; reconciling it would leave the layer
  // permanently dirty against the very baseline it just restored.
  it('does not reconcile a verbatim restore', () => {
    const { result, layers } = renderBoundary(
      makeLayer({
        dataset_geometry_type: 'Polygon',
        paint: { 'fill-color': RAMP_CLS },
        style_config: null,
      }),
    );

    act(() => {
      result.current.handleStyleConfigChange(
        LID,
        CATEGORICAL,
        { 'fill-color': '#3b82f6' },
        { replace: true, restore: true },
      );
    });

    expect(configOf(layers().find((l) => l.id === LID)!)?.mode).toBe('categorical');
  });
});

// fix(#910, codex P2): the provenance diff has to compare expression VALUES. The
// Advanced JSON editor applies `JSON.parse` of the whole block, so every array-valued
// key comes back as a fresh object even when its text never changed — and a reference
// comparison read that as "the user asked for this colour" and deleted the pattern.
describe('useLayerMapSync — provenance survives a JSON round-trip of an untouched expression', () => {
  const LID = 'layer-uuid-123';
  const RAMP_JSON = ['match', ['get', 'era'], 'pre-war', '#ff0000', '#00ff00'];

  function renderBoundary(initialLayer: MapLayerResponse) {
    let finalLayers: MapLayerResponse[] = [initialLayer];
    const { result } = renderHook(() => {
      const [layers, setLayers] = React.useState([initialLayer]);
      finalLayers = layers;
      return useLayerMapSync(
        layers,
        setLayers as React.Dispatch<React.SetStateAction<MapLayerResponse[]>>,
        vi.fn(),
        { current: makeMapStub() } as unknown as React.RefObject<import('maplibre-gl').Map | null>,
      );
    });
    return { result, layers: () => finalLayers };
  }

  it('keeps the pattern when an unrelated Advanced JSON edit reparses the colour', () => {
    const savedPaint = {
      'fill-color': RAMP_JSON,
      'fill-pattern': 'geolens-fill-hatch',
      'fill-opacity': 0.3,
    };
    const { result, layers } = renderBoundary(
      makeLayer({ dataset_geometry_type: 'Polygon', paint: savedPaint }),
    );

    act(() => {
      // Exactly what AdvancedJsonEditor.handleApply hands over: a parse of the edited
      // text, so `fill-color` is a NEW array holding the same expression.
      const reparsed = JSON.parse(JSON.stringify(savedPaint)) as Record<string, unknown>;
      reparsed['fill-opacity'] = 0.6;
      result.current.handlePaintChange(LID, reparsed);
    });

    const updated = layers().find((l) => l.id === LID)!;
    expect(updated.paint?.['fill-pattern']).toBe('geolens-fill-hatch');
    expect(updated.paint?.['fill-color']).toEqual(RAMP_JSON);
    expect(updated.paint?.['fill-opacity']).toBe(0.6);
  });

  // The mirror: a genuine edit to the expression still reads as intent, so the pattern
  // goes. Otherwise the fix above would just disable provenance for expressions.
  it('still drops the pattern when the reparsed colour actually differs', () => {
    const savedPaint = {
      'fill-color': RAMP_JSON,
      'fill-pattern': 'geolens-fill-hatch',
      'fill-opacity': 0.3,
    };
    const { result, layers } = renderBoundary(
      makeLayer({ dataset_geometry_type: 'Polygon', paint: savedPaint }),
    );

    act(() => {
      const reparsed = JSON.parse(JSON.stringify(savedPaint)) as Record<string, unknown>;
      reparsed['fill-color'] = ['match', ['get', 'era'], 'pre-war', '#0000ff', '#00ff00'];
      result.current.handlePaintChange(LID, reparsed);
    });

    const updated = layers().find((l) => l.id === LID)!;
    expect('fill-pattern' in (updated.paint ?? {})).toBe(false);
  });
});

// fix(#910, codex P2): `fill-pattern: null` means NO pattern — MapLibre reads it as unset,
// and `FillEditor` already tests `!= null`. A presence-only collision test read it as a
// live pattern, so an unrelated edit fell through to pattern-wins and deleted the only
// colour the layer had. Reachable from an imported or API-authored style, which gets
// serialized-size validation and not much else.
describe('useLayerMapSync — a null fill key is not an active one', () => {
  const LID = 'layer-uuid-123';

  function renderBoundary(initialLayer: MapLayerResponse) {
    let finalLayers: MapLayerResponse[] = [initialLayer];
    const { result } = renderHook(() => {
      const [layers, setLayers] = React.useState([initialLayer]);
      finalLayers = layers;
      return useLayerMapSync(
        layers,
        setLayers as React.Dispatch<React.SetStateAction<MapLayerResponse[]>>,
        vi.fn(),
        { current: makeMapStub() } as unknown as React.RefObject<import('maplibre-gl').Map | null>,
      );
    });
    return { result, layers: () => finalLayers };
  }

  it('keeps the solid colour when the pattern is null and an unrelated key changes', () => {
    const { result, layers } = renderBoundary(
      makeLayer({
        dataset_geometry_type: 'Polygon',
        paint: { 'fill-color': '#ff0000', 'fill-pattern': null, 'fill-opacity': 0.3 },
      }),
    );

    act(() => {
      result.current.handlePaintChange(LID, {
        'fill-color': '#ff0000',
        'fill-pattern': null,
        'fill-opacity': 0.7,
      });
    });

    const updated = layers().find((l) => l.id === LID)!;
    expect(updated.paint?.['fill-color']).toBe('#ff0000');
    expect(updated.paint?.['fill-opacity']).toBe(0.7);
    // Nothing was displaced, so nothing was stashed either.
    const builder = (updated.style_config as { builder?: Record<string, unknown> } | null)?.builder;
    expect(builder?.fillColorSaved).toBeUndefined();
  });

  it('treats a null pattern as no pattern when clearing a stale stash', () => {
    const { result, layers } = renderBoundary(
      makeLayer({
        dataset_geometry_type: 'Polygon',
        paint: { 'fill-color': '#ff0000', 'fill-pattern': null },
        style_config: { builder: { fillColorSaved: '#0000ff' } } as MapLayerResponse['style_config'],
      }),
    );

    act(() => {
      result.current.handlePaintChange(LID, { 'fill-color': '#00ff00', 'fill-pattern': null });
    });

    const updated = layers().find((l) => l.id === LID)!;
    const builder = (updated.style_config as { builder?: Record<string, unknown> } | null)?.builder;
    expect(builder?.fillColorSaved).toBeUndefined();
    expect(updated.paint?.['fill-color']).toBe('#00ff00');
  });
});
