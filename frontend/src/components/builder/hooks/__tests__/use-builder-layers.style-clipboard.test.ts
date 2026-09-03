/**
 * Phase 1201-01 (ENH-02 / ENH-03) — copy/paste/bulk-apply style handler tests.
 *
 * Asserts:
 *  - handleCopyStyle stashes the source style + exposes copiedStyleGeometryClass
 *  - handlePasteStyle round-trips style_config to a geometry-compatible target
 *  - handlePasteStyle no-ops on a geometry-incompatible target
 *  - handleBulkApplyStyle applies the source style to all OTHER compatible
 *    selected layers in ONE render pass, skipping incompatible geometries
 *
 * Harness mirrors use-builder-layers.bulk-ops.test.ts (QueryClientProvider +
 * MemoryRouter via shared renderHook; non-empty fixture; afterEach cleanup).
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import { act, cleanup } from '@testing-library/react';
import { renderHook } from '@/test/test-utils';
import { useBuilderLayers } from '@/components/builder/hooks/use-builder-layers';
import {
  makeBuilderLayer,
  makeBuilderMap,
} from '@/components/builder/__tests__/fixtures/map-builder-fixtures';
import type { MapLayerResponse, MapResponse, StyleConfig } from '@/types/api';

afterEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
  cleanup();
});

function makeMockLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return makeBuilderLayer(overrides);
}

function makeMapData(layers: MapLayerResponse[] = []): MapResponse {
  return makeBuilderMap(layers);
}

function makeMapRef() {
  const mapInstance = {
    isStyleLoaded: () => false,
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    getPaintProperty: vi.fn(),
    getLayoutProperty: vi.fn(),
    getLayer: vi.fn().mockReturnValue(null),
    getSource: vi.fn().mockReturnValue(null),
  };
  return { current: mapInstance } as unknown as React.RefObject<import('maplibre-gl').Map | null>;
}

const MAP_ID = 'map-1';

function renderBuilderLayers(mapData: MapResponse | undefined) {
  const addLayerMutation = { mutate: vi.fn(), mutateAsync: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[3];
  const removeLayerMutation = { mutate: vi.fn(), mutateAsync: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[4];
  // fix(#392): 6th positional param bridging into useBuilderSave's Save-diff baseline.
  const saveBaselineSyncRef = { current: { add: () => {}, remove: () => {} } } as unknown as Parameters<typeof useBuilderLayers>[5];
  return renderHook(() =>
    useBuilderLayers(mapData, makeMapRef(), MAP_ID, addLayerMutation, removeLayerMutation, saveBaselineSyncRef),
  );
}

async function waitForInit() {
  await act(async () => {});
}

// fix(#910, codex P2): the paint expression that a real categorical source carries — the
// config and the expression are written together and copied together. A source paired
// with a FLAT colour is an orphaned layer, and the paste now declines to propagate that
// claim to the target, so these fixtures need the pair to be testing the paste at all.
const POLY_RAMP = ['match', ['get', 'zone'], 'a', '#e41a1c', '#377eb8'];

const POLY_STYLE: StyleConfig = {
  mode: 'categorical',
  column: 'zone',
  ramp: 'Set2',
  categories: [
    { value: 'a', color: '#e41a1c' },
    { value: 'b', color: '#377eb8' },
  ],
};

describe('useBuilderLayers — handleCopyStyle / copiedStyleGeometryClass (ENH-02)', () => {
  it('stashes the source style and exposes its geometry class', async () => {
    const src = makeMockLayer({ id: 'src', dataset_geometry_type: 'Polygon', paint: { 'fill-color': '#fff' }, style_config: POLY_STYLE });
    const { result } = renderBuilderLayers(makeMapData([src]));
    await waitForInit();

    expect(result.current.copiedStyleGeometryClass).toBeNull();

    act(() => {
      result.current.handleCopyStyle('src');
    });

    expect(result.current.copiedStyleGeometryClass).toBe('polygon');
  });
});

describe('useBuilderLayers — handlePasteStyle (ENH-02)', () => {
  it('copy → paste round-trips style_config to a compatible target', async () => {
    const src = makeMockLayer({ id: 'src', dataset_geometry_type: 'Polygon', paint: { 'fill-color': POLY_RAMP }, style_config: POLY_STYLE, sort_order: 0 });
    const tgt = makeMockLayer({ id: 'tgt', dataset_geometry_type: 'MultiPolygon', paint: { 'fill-opacity': 0.2 }, style_config: null, sort_order: 1 });
    const { result } = renderBuilderLayers(makeMapData([src, tgt]));
    await waitForInit();

    act(() => {
      result.current.handleCopyStyle('src');
    });
    act(() => {
      result.current.handlePasteStyle('tgt');
    });

    const updated = result.current.localLayers.find((l) => l.id === 'tgt')!;
    expect(updated.style_config).toEqual(POLY_STYLE);
    expect(updated.paint['fill-color']).toEqual(POLY_RAMP);
    expect(updated.paint['fill-opacity']).toBe(0.2); // target's own paint key preserved
    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  it('no-ops on a geometry-incompatible target (line copied → polygon target)', async () => {
    const src = makeMockLayer({ id: 'src', dataset_geometry_type: 'LineString', paint: { 'line-color': '#111' }, style_config: { mode: 'categorical', column: 'k', ramp: 'X' }, sort_order: 0 });
    const tgt = makeMockLayer({ id: 'tgt', dataset_geometry_type: 'Polygon', paint: { 'fill-color': '#fff' }, style_config: null, sort_order: 1 });
    const { result } = renderBuilderLayers(makeMapData([src, tgt]));
    await waitForInit();

    act(() => {
      result.current.handleCopyStyle('src');
    });
    act(() => {
      result.current.handlePasteStyle('tgt');
    });

    const updated = result.current.localLayers.find((l) => l.id === 'tgt')!;
    expect(updated.style_config).toBeNull();
    expect(updated.paint['line-color']).toBeUndefined();
    expect(updated.paint['fill-color']).toBe('#fff');
  });

  it('no-ops when nothing has been copied', async () => {
    const tgt = makeMockLayer({ id: 'tgt', dataset_geometry_type: 'Polygon', style_config: null });
    const { result } = renderBuilderLayers(makeMapData([tgt]));
    await waitForInit();

    act(() => {
      result.current.handlePasteStyle('tgt');
    });

    expect(result.current.localLayers.find((l) => l.id === 'tgt')!.style_config).toBeNull();
    expect(result.current.hasUnsavedChanges).toBe(false);
  });
});

describe('useBuilderLayers — handleBulkApplyStyle (ENH-03)', () => {
  it('applies the first selected layer style to compatible peers, skipping incompatible ones', async () => {
    const src = makeMockLayer({ id: 'src', dataset_geometry_type: 'Polygon', paint: { 'fill-color': POLY_RAMP }, style_config: POLY_STYLE, sort_order: 0 });
    const peer = makeMockLayer({ id: 'peer', dataset_geometry_type: 'Polygon', paint: {}, style_config: null, sort_order: 1 });
    const incompatible = makeMockLayer({ id: 'line', dataset_geometry_type: 'LineString', paint: {}, style_config: null, sort_order: 2 });
    const { result } = renderBuilderLayers(makeMapData([src, peer, incompatible]));
    await waitForInit();

    act(() => {
      result.current.handleBulkApplyStyle(new Set(['src', 'peer', 'line']));
    });

    const layers = result.current.localLayers;
    // compatible peer gets the source style
    expect(layers.find((l) => l.id === 'peer')!.style_config).toEqual(POLY_STYLE);
    expect(layers.find((l) => l.id === 'peer')!.paint['fill-color']).toEqual(POLY_RAMP);
    // incompatible line is skipped
    expect(layers.find((l) => l.id === 'line')!.style_config).toBeNull();
    // source itself unchanged in identity (still has its own style)
    expect(layers.find((l) => l.id === 'src')!.style_config).toEqual(POLY_STYLE);
    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  it('applies all compatible peers within a SINGLE render (one setState pass)', async () => {
    const src = makeMockLayer({ id: 'src', dataset_geometry_type: 'Polygon', paint: { 'fill-color': POLY_RAMP }, style_config: POLY_STYLE, sort_order: 0 });
    const p1 = makeMockLayer({ id: 'p1', dataset_geometry_type: 'Polygon', sort_order: 1 });
    const p2 = makeMockLayer({ id: 'p2', dataset_geometry_type: 'MultiPolygon', sort_order: 2 });
    const { result } = renderBuilderLayers(makeMapData([src, p1, p2]));
    await waitForInit();

    const before = result.current.localLayers;

    act(() => {
      result.current.handleBulkApplyStyle(new Set(['src', 'p1', 'p2']));
    });

    const after = result.current.localLayers;
    // Both peers updated in the same commit (array reference changed exactly once).
    expect(after).not.toBe(before);
    expect(after.find((l) => l.id === 'p1')!.style_config).toEqual(POLY_STYLE);
    expect(after.find((l) => l.id === 'p2')!.style_config).toEqual(POLY_STYLE);
  });

  it('no-ops when fewer than 2 compatible layers are selected', async () => {
    const src = makeMockLayer({ id: 'src', dataset_geometry_type: 'Polygon', style_config: POLY_STYLE, sort_order: 0 });
    const line = makeMockLayer({ id: 'line', dataset_geometry_type: 'LineString', style_config: null, sort_order: 1 });
    const { result } = renderBuilderLayers(makeMapData([src, line]));
    await waitForInit();

    act(() => {
      result.current.handleBulkApplyStyle(new Set(['src', 'line']));
    });

    expect(result.current.localLayers.find((l) => l.id === 'line')!.style_config).toBeNull();
    expect(result.current.hasUnsavedChanges).toBe(false);
  });

  // fix(#910/#918, codex P2): bulk apply reaches neither handleStyleConfigChange nor
  // handlePasteStyle, so the EDIT-05 exclusions had to be shared with it explicitly.
  // applyCopiedStyleToLayer merges the copied paint OVER the target's, which is what
  // strands the loser of each incompatible pair on the layer.
  describe('EDIT-05 fill exclusions', () => {
    // fix(#910, codex P2): the pattern-wins tie-break is only correct when the pattern
    // is what was copied. Applying a SOLID style must displace the target's pattern, or
    // the operation silently keeps the old look and appears to do nothing.
    it('lets a copied solid colour displace the target pattern', async () => {
      const src = makeMockLayer({
        id: 'src', dataset_geometry_type: 'Polygon',
        paint: { 'fill-color': '#abc' }, style_config: null, sort_order: 0,
      });
      const patterned = makeMockLayer({
        id: 'patterned', dataset_geometry_type: 'Polygon',
        paint: { 'fill-pattern': 'geolens-fill-hatch' },
        style_config: { builder: { fillColorSaved: '#0f0' } } as StyleConfig, sort_order: 1,
      });
      const { result } = renderBuilderLayers(makeMapData([src, patterned]));
      await waitForInit();

      act(() => {
        result.current.handleBulkApplyStyle(new Set(['src', 'patterned']));
      });

      const updated = result.current.localLayers.find((l) => l.id === 'patterned')!;
      expect('fill-pattern' in updated.paint).toBe(false);
      expect(updated.paint['fill-color']).toBe('#abc');
    });

    it('lets a pasted solid colour displace the target pattern', async () => {
      const src = makeMockLayer({
        id: 'src', dataset_geometry_type: 'Polygon',
        paint: { 'fill-color': '#abc' }, style_config: null, sort_order: 0,
      });
      const patterned = makeMockLayer({
        id: 'patterned', dataset_geometry_type: 'Polygon',
        paint: { 'fill-pattern': 'geolens-fill-hatch' },
        style_config: { builder: { fillColorSaved: '#0f0' } } as StyleConfig, sort_order: 1,
      });
      const { result } = renderBuilderLayers(makeMapData([src, patterned]));
      await waitForInit();

      act(() => {
        result.current.handleCopyStyle('src');
      });
      act(() => {
        result.current.handlePasteStyle('patterned');
      });

      const updated = result.current.localLayers.find((l) => l.id === 'patterned')!;
      expect('fill-pattern' in updated.paint).toBe(false);
      expect(updated.paint['fill-color']).toBe('#abc');
    });

    // fix(#923): the other paste direction. The pair is symmetric, and the merge that
    // strands the loser is the same one, so both directions have to be pinned.
    it('lets a pasted pattern displace the target solid colour', async () => {
      const src = makeMockLayer({
        id: 'src', dataset_geometry_type: 'Polygon',
        paint: { 'fill-pattern': 'geolens-fill-dots' },
        style_config: { builder: { fillColorSaved: '#ff0000' } } as StyleConfig, sort_order: 0,
      });
      const solid = makeMockLayer({
        id: 'solid', dataset_geometry_type: 'Polygon',
        paint: { 'fill-color': '#0000ff' }, style_config: null, sort_order: 1,
      });
      const { result } = renderBuilderLayers(makeMapData([src, solid]));
      await waitForInit();

      act(() => {
        result.current.handleCopyStyle('src');
      });
      act(() => {
        result.current.handlePasteStyle('solid');
      });

      const updated = result.current.localLayers.find((l) => l.id === 'solid')!;
      expect('fill-color' in updated.paint).toBe(false);
      expect(updated.paint['fill-pattern']).toBe('geolens-fill-dots');
      // The copied source colour is the one None has to bring back, not the target's
      // displaced blue.
      expect(updated.style_config?.builder?.fillColorSaved).toBe('#ff0000');
    });

    it('drops the target pattern when a data-driven colour style is applied over it', async () => {
      const src = makeMockLayer({
        id: 'src', dataset_geometry_type: 'Polygon',
        paint: { 'fill-color': POLY_RAMP }, style_config: POLY_STYLE, sort_order: 0,
      });
      const patterned = makeMockLayer({
        id: 'patterned', dataset_geometry_type: 'Polygon',
        paint: { 'fill-pattern': 'geolens-fill-hatch' },
        style_config: { builder: { fillColorSaved: '#0f0' } } as StyleConfig, sort_order: 1,
      });
      const { result } = renderBuilderLayers(makeMapData([src, patterned]));
      await waitForInit();

      act(() => {
        result.current.handleBulkApplyStyle(new Set(['src', 'patterned']));
      });

      const updated = result.current.localLayers.find((l) => l.id === 'patterned')!;
      // The ramp is the explicit request, so it owns the fill and the pattern goes —
      // otherwise MapLibre keeps drawing hatch while the legend claims the ramp.
      expect('fill-pattern' in updated.paint).toBe(false);
      expect(updated.paint['fill-color']).toEqual(POLY_RAMP);
      // The old stash would restore a colour from before the ramp on a later None.
      expect(updated.style_config?.builder?.fillColorSaved).toBeUndefined();
    });

    it('drops the target colour when a patterned style is applied over it', async () => {
      const src = makeMockLayer({
        id: 'src', dataset_geometry_type: 'Polygon',
        paint: { 'fill-pattern': 'geolens-fill-dots' },
        style_config: { builder: { fillColorSaved: '#ff0000' } } as StyleConfig, sort_order: 0,
      });
      const solid = makeMockLayer({
        id: 'solid', dataset_geometry_type: 'Polygon',
        paint: { 'fill-color': '#0000ff' }, style_config: null, sort_order: 1,
      });
      const { result } = renderBuilderLayers(makeMapData([src, solid]));
      await waitForInit();

      act(() => {
        result.current.handleBulkApplyStyle(new Set(['src', 'solid']));
      });

      const updated = result.current.localLayers.find((l) => l.id === 'solid')!;
      expect('fill-color' in updated.paint).toBe(false);
      expect(updated.paint['fill-pattern']).toBe('geolens-fill-dots');
      // The copied source colour wins over the target's displaced blue: that is the
      // one the user copied, and the one None has to bring back.
      expect(updated.style_config?.builder?.fillColorSaved).toBe('#ff0000');
    });
  });
});
