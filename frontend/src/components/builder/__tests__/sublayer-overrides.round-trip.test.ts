/**
 * Round-trip parity tests for `sublayer_overrides` (Phase 1059 BSE-01).
 *
 * Verifies that:
 *   1. A MapBasemapConfig with sublayer_overrides survives JSON.parse(JSON.stringify())
 *      without losing fields (numbers preserved, hex strings preserved, nulls preserved).
 *   2. The helper's call trace is identical for direct input vs round-tripped input —
 *      proving serialize→deserialize produces semantically identical mutations.
 *   3. Edge cases: null values, partial overrides, multi-sublayer dicts, legacy payloads
 *      without the field, and unknown sublayer IDs are all handled gracefully.
 *
 * This test covers ROADMAP.md Phase 1059 Acceptance Criteria:
 *   - AC3: cross-context round-trip parity (payload survives the save→load cycle)
 *   - AC4: zero-migration backward compat (legacy maps without sublayer_overrides render safely)
 *
 * Uses a fake MapLibre map identical to the factory in basemap-style-mutation.test.ts.
 * Inline boilerplate is intentional (no shared test-utils for this pattern yet).
 */
import { describe, it, expect, vi } from 'vitest';
import { applySublayerOverrides } from '@/lib/builder/basemap-style-mutation';
import type { MapBasemapConfig, MapSublayerOverride } from '@/types/api';

// ---------------------------------------------------------------------------
// Fake MapLibre map factory
// ---------------------------------------------------------------------------

function makeFakeMap(
  layers: Array<{
    id: string;
    type: string;
    source?: string;
    'source-layer'?: string;
    layout?: Record<string, unknown>;
    paint?: Record<string, unknown>;
  }>,
) {
  const setPaintProperty = vi.fn();
  const setLayerZoomRange = vi.fn();
  const setLayoutProperty = vi.fn();
  const map = {
    isStyleLoaded: vi.fn(() => true),
    getStyle: vi.fn(() => ({ layers })),
    // getLayer returns truthy (layer object) for any id in the style so safeSetPaint
    // and safeSetZoomRange proceed with mutations.
    getLayer: vi.fn((id: string) => layers.find((l) => l.id === id) ?? null),
    setPaintProperty,
    setLayerZoomRange,
    setLayoutProperty,
    once: vi.fn(),
  };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return { map: map as any, setPaintProperty, setLayerZoomRange };
}

// ---------------------------------------------------------------------------
// Fake style layers
// ---------------------------------------------------------------------------
// Layer IDs and source-layer values are chosen so the SUBLAYER_CLASSIFIERS in
// basemap-utils.ts classify them correctly:
//   - 'road' id token  → isRoadLayer (type='line', matches ROAD_PATTERNS)
//   - 'boundary' id token → isBoundaryLayer (type='line', matches BOUNDARY_PATTERNS)
//   - 'building' type='fill-extrusion' → isBuildingLayer
//   - 'label' id token + layout['text-field'] → isTextLabelLayer (type='symbol')
const FAKE_STYLE_LAYERS = [
  {
    id: 'road-primary',
    type: 'line',
    source: 'openmaptiles',
    'source-layer': 'transportation',
    layout: {},
    paint: {},
  },
  {
    id: 'road-primary-casing',
    type: 'line',
    source: 'openmaptiles',
    'source-layer': 'transportation',
    layout: {},
    paint: {},
  },
  {
    id: 'boundary-country',
    type: 'line',
    source: 'openmaptiles',
    'source-layer': 'boundary',
    layout: {},
    paint: {},
  },
  {
    id: 'building-3d',
    type: 'fill-extrusion',
    source: 'openmaptiles',
    'source-layer': 'building',
    layout: {},
    paint: {},
  },
  {
    id: 'road-label',
    type: 'symbol',
    source: 'openmaptiles',
    'source-layer': 'transportation_name',
    layout: { 'text-field': '{name}' },
    paint: {},
  },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('sublayer_overrides round-trip parity (Phase 1059 BSE-01)', () => {
  it('payload survives JSON.parse(JSON.stringify())', () => {
    const cfg: MapBasemapConfig = {
      label_mode: 'full',
      road_visibility: 'full',
      boundary_visibility: 'full',
      building_visibility: true,
      land_water_tone: 'default',
      sublayer_overrides: {
        road: { stroke_color: '#ff0000', stroke_width: 2.5, min_zoom: 5, max_zoom: 18 },
        boundary: { casing_color: '#000000', casing_width: 1 },
        building: { opacity: 0.5 },
      },
    };
    const roundTripped = JSON.parse(JSON.stringify(cfg)) as MapBasemapConfig;
    expect(roundTripped.sublayer_overrides).toEqual(cfg.sublayer_overrides);
    // Floating-point precision preserved
    expect(roundTripped.sublayer_overrides!.road.stroke_width).toBe(2.5);
    // Hex strings preserved
    expect(roundTripped.sublayer_overrides!.road.stroke_color).toBe('#ff0000');
    // Integer zoom values preserved as numbers
    expect(roundTripped.sublayer_overrides!.road.min_zoom).toBe(5);
    expect(roundTripped.sublayer_overrides!.road.max_zoom).toBe(18);
  });

  it('helper apply yields identical call trace for direct vs round-tripped input', () => {
    const overrides: Record<string, MapSublayerOverride> = {
      road: { stroke_color: '#ff0000', stroke_width: 2 },
    };

    const direct = makeFakeMap(FAKE_STYLE_LAYERS);
    applySublayerOverrides(direct.map, overrides);

    const roundTripped = makeFakeMap(FAKE_STYLE_LAYERS);
    const overridesRT = JSON.parse(JSON.stringify(overrides)) as typeof overrides;
    applySublayerOverrides(roundTripped.map, overridesRT);

    // setPaintProperty call traces must be identical
    expect(direct.setPaintProperty.mock.calls).toEqual(roundTripped.setPaintProperty.mock.calls);
    // setLayerZoomRange call traces must be identical
    expect(direct.setLayerZoomRange.mock.calls).toEqual(roundTripped.setLayerZoomRange.mock.calls);
  });

  it('null values survive round-trip (not coerced to undefined or 0)', () => {
    const overrides = { road: { stroke_color: null, stroke_width: 2 } };
    const roundTripped = JSON.parse(JSON.stringify(overrides)) as typeof overrides;
    // null survives JSON round-trip (unlike undefined which is stripped)
    expect(roundTripped.road.stroke_color).toBeNull();
    // Non-null numeric value preserved
    expect(roundTripped.road.stroke_width).toBe(2);
  });

  it('partial overrides produce no phantom mutation calls', () => {
    const { map, setPaintProperty } = makeFakeMap(FAKE_STYLE_LAYERS);
    // Only stroke_color provided — width, casing, zoom, opacity absent
    applySublayerOverrides(map, { road: { stroke_color: '#ff0000' } });

    const calls = setPaintProperty.mock.calls;
    const propsCalled = new Set((calls as [string, string, unknown][]).map((c) => c[1]));
    // stroke_color → line-color IS expected
    expect(propsCalled.has('line-color')).toBe(true);
    // stroke_width → line-width NOT expected (field absent)
    expect(propsCalled.has('line-width')).toBe(false);
    // casing_width → line-gap-width NOT expected (field absent)
    expect(propsCalled.has('line-gap-width')).toBe(false);
    // opacity → line-opacity NOT expected (field absent)
    expect(propsCalled.has('line-opacity')).toBe(false);
  });

  it('multi-sublayer dict applies to all known sublayer IDs', () => {
    const { map, setPaintProperty } = makeFakeMap(FAKE_STYLE_LAYERS);
    applySublayerOverrides(map, {
      road: { stroke_color: '#ff0000' },
      boundary: { stroke_color: '#0000ff' },
      building: { opacity: 0.5 },
      label: { opacity: 0.3 },
    });

    const calls = setPaintProperty.mock.calls as Array<[string, string, unknown]>;
    // road: road-primary + road-primary-casing get line-color
    expect(calls.some((c) => c[0] === 'road-primary' && c[1] === 'line-color')).toBe(true);
    // boundary: boundary-country gets line-color (boundary has stroke_color)
    expect(calls.some((c) => c[0] === 'boundary-country' && c[1] === 'line-color')).toBe(true);
    // building: building-3d gets fill-extrusion-opacity
    expect(calls.some((c) => c[0] === 'building-3d' && c[1] === 'fill-extrusion-opacity')).toBe(true);
    // label: road-label (symbol with text-field) gets text-opacity and icon-opacity
    expect(calls.some((c) => c[0] === 'road-label' && c[1] === 'text-opacity')).toBe(true);
    expect(calls.some((c) => c[0] === 'road-label' && c[1] === 'icon-opacity')).toBe(true);
  });

  it('legacy payload without sublayer_overrides renders without crashing (ROADMAP AC4)', () => {
    const { map, setPaintProperty } = makeFakeMap(FAKE_STYLE_LAYERS);
    // ROADMAP.md Phase 1059 Acceptance Criterion 4: legacy saved maps must render
    // safely without any sublayer_overrides field present.
    expect(() => applySublayerOverrides(map, undefined)).not.toThrow();
    expect(() => applySublayerOverrides(map, null)).not.toThrow();
    expect(() => applySublayerOverrides(map, {})).not.toThrow();
    // None of the three calls above should mutate any MapLibre properties
    expect(setPaintProperty).not.toHaveBeenCalled();
  });

  it('unknown sublayer ID is silently ignored (forward-compat D-01)', () => {
    const { map, setPaintProperty } = makeFakeMap(FAKE_STYLE_LAYERS);
    applySublayerOverrides(map, {
      some_brand_new_provider_sublayer: { stroke_color: '#ff0000', opacity: 0.5 },
    } as Record<string, MapSublayerOverride>);
    // Unknown key → no classifier found → zero mutations
    expect(setPaintProperty).not.toHaveBeenCalled();
  });
});
