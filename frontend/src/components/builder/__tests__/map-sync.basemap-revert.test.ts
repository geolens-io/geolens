/**
 * fix(#1778): "applyBasemapConfigToMap's paint diff can never CLEAR a basemap
 * override" (codebase audit 2026-08-30).
 *
 * applyBasemapConfigToMap reads the LIVE style, so on a revert pass the value
 * `applyBasemapConfigToStyle` produced was the tint the PREVIOUS pass had
 * written; it compared equal and nothing was written back. The map stayed
 * tinted for the rest of the session while React state, the stack row and the
 * saved payload all said "default".
 *
 * Every test here therefore runs the helper TWICE against a map whose
 * `getStyle()` reflects the first pass's writes. The existing coverage in
 * BuilderMap.unit.test.ts uses a fixed style and only asserts the apply
 * direction, which is why the revert direction went unnoticed.
 */
import { describe, it, expect, vi } from 'vitest';
import type { StyleSpecification } from 'maplibre-gl';
import { applyBasemapConfigToMap } from '@/components/builder/map-sync';
import { DEFAULT_BASEMAP_CONFIG } from '@/lib/basemap-utils';
import type { MapBasemapConfig } from '@/types/api';

/** A map mock whose setPaintProperty MUTATES the style it hands back, which is
 *  what the real MapLibre map does and what the bug depended on.
 *
 *  `loadStyle` replaces the whole style on the SAME map object and fires any
 *  registered `style.load` listeners, which is what `setStyle` does on a
 *  basemap swap. `setPaintProperty(key, undefined)` deletes the key, matching
 *  maplibre's serializer, which omits a paint property whose value is
 *  undefined. */
function createLiveStyleMap(initialLayers: StyleSpecification['layers']) {
  let style = {} as StyleSpecification;
  let byId = new Map<string, { id: string; paint?: Record<string, unknown> }>();
  const styleLoadListeners: (() => void)[] = [];

  function install(layers: StyleSpecification['layers']) {
    style = {
      version: 8 as const,
      sources: {},
      layers: layers.map((layer) => ({ ...layer, paint: { ...('paint' in layer ? layer.paint : {}) } })),
    } as unknown as StyleSpecification;
    byId = new Map(
      style.layers.map((layer) => [layer.id, layer as { id: string; paint?: Record<string, unknown> }]),
    );
  }
  install(initialLayers);

  return {
    getStyle: vi.fn(() => style),
    getLayer: vi.fn((id: string) => byId.get(id)),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn((id: string, key: string, value: unknown) => {
      const layer = byId.get(id);
      if (!layer) return;
      layer.paint = { ...(layer.paint ?? {}) };
      if (value === undefined) delete layer.paint[key];
      else layer.paint[key] = value;
    }),
    on: vi.fn((event: string, cb: () => void) => {
      if (event === 'style.load') styleLoadListeners.push(cb);
    }),
    /** Simulate setStyle: a brand new style on the same map, then style.load. */
    loadStyle(layers: StyleSpecification['layers']) {
      install(layers);
      for (const cb of [...styleLoadListeners]) cb();
    },
    paintOf: (id: string) => (byId.get(id)?.paint ?? {}),
  };
}

const waterLayer = (color: string) => ([
  { id: 'water', type: 'fill', source: 'openmaptiles', paint: { 'fill-color': color } },
] as unknown as StyleSpecification['layers']);

const POSITRON_WATER = '#a0c8f0';
const DARK_WATER = '#1b2733';
const MONOCHROME_WATER = '#d9dde0';

describe('applyBasemapConfigToMap revert passes', () => {
  it('restores the original water fill when land_water_tone returns to default', () => {
    const map = createLiveStyleMap([
      { id: 'water', type: 'fill', source: 'openmaptiles', paint: { 'fill-color': '#a0c8f0' } },
    ] as unknown as StyleSpecification['layers']);

    applyBasemapConfigToMap(map as never, { ...DEFAULT_BASEMAP_CONFIG, land_water_tone: 'monochrome' });
    expect(map.paintOf('water')['fill-color']).toBe('#d9dde0');

    applyBasemapConfigToMap(map as never, { ...DEFAULT_BASEMAP_CONFIG });
    expect(map.paintOf('water')['fill-color']).toBe('#a0c8f0');
  });

  it('restores the original background colour when the override is cleared', () => {
    const map = createLiveStyleMap([
      { id: 'background', type: 'background', paint: { 'background-color': '#fafaf8' } },
    ] as unknown as StyleSpecification['layers']);

    applyBasemapConfigToMap(map as never, { ...DEFAULT_BASEMAP_CONFIG, background_color: '#101820' });
    expect(map.paintOf('background')['background-color']).toBe('#101820');

    applyBasemapConfigToMap(map as never, null);
    expect(map.paintOf('background')['background-color']).toBe('#fafaf8');
  });

  it('restores hillshade paint when relief_contrast is cleared', () => {
    const map = createLiveStyleMap([
      { id: 'hillshade', type: 'hillshade', source: 'terrain', paint: { 'hillshade-exaggeration': 0.2 } },
    ] as unknown as StyleSpecification['layers']);

    applyBasemapConfigToMap(map as never, { ...DEFAULT_BASEMAP_CONFIG, relief_contrast: 'strong' });
    expect(map.paintOf('hillshade')['hillshade-exaggeration']).toBe(0.85);
    expect(map.paintOf('hillshade')['hillshade-shadow-color']).toBe('#47545c');

    applyBasemapConfigToMap(map as never, { ...DEFAULT_BASEMAP_CONFIG });
    expect(map.paintOf('hillshade')['hillshade-exaggeration']).toBe(0.2);
    // A key the pristine style never carried is unset, not left stranded.
    expect(map.paintOf('hillshade')).not.toHaveProperty('hillshade-shadow-color');
  });

  it('clears the label halo width stamped by label_mode subtle', () => {
    const map = createLiveStyleMap([
      { id: 'place-label', type: 'symbol', source: 'openmaptiles', paint: { 'text-color': '#333' } },
    ] as unknown as StyleSpecification['layers']);

    applyBasemapConfigToMap(map as never, { ...DEFAULT_BASEMAP_CONFIG, label_mode: 'subtle' });
    expect(map.paintOf('place-label')['text-halo-width']).toBe(0.8);

    applyBasemapConfigToMap(map as never, { ...DEFAULT_BASEMAP_CONFIG, label_mode: 'full' });
    expect(map.paintOf('place-label')).not.toHaveProperty('text-halo-width');
  });

  it('leaves paint keys this helper never wrote alone', () => {
    const map = createLiveStyleMap([
      { id: 'water', type: 'fill', source: 'openmaptiles', paint: { 'fill-color': '#a0c8f0' } },
    ] as unknown as StyleSpecification['layers']);

    applyBasemapConfigToMap(map as never, { ...DEFAULT_BASEMAP_CONFIG, land_water_tone: 'muted' });
    // Stand in for applySublayerOverrides, which runs right after this helper.
    map.setPaintProperty('water', 'fill-outline-color', '#123456');

    applyBasemapConfigToMap(map as never, { ...DEFAULT_BASEMAP_CONFIG });
    expect(map.paintOf('water')['fill-outline-color']).toBe('#123456');
    // And the foreign write must not have disturbed this layer's own revert.
    expect(map.paintOf('water')['fill-color']).toBe('#a0c8f0');
  });

  // fix(#1778 codex round 2 P1): the pristine snapshot used to be dropped by a
  // `style.load` listener this module attached lazily, which meant it was always
  // registered AFTER BuilderMap's persistent handler and therefore ran after the
  // appearance pass that handler triggers. Detection is now synchronous and
  // per key, so listener order cannot matter. Both tests below would fail with
  // the listener-based invalidation: the first because the appearance listener
  // is registered first, the second because no listener exists at all.
  it('re-snapshots pristine across two style swaps that share a layer id', () => {
    const map = createLiveStyleMap(waterLayer(POSITRON_WATER));
    const config: { current: MapBasemapConfig } = {
      current: { ...DEFAULT_BASEMAP_CONFIG, land_water_tone: 'monochrome' },
    };
    // Stand-in for BuilderMap's persistent style.load handler, registered
    // BEFORE any appearance call, exactly as the real one is.
    map.on('style.load', () => applyBasemapConfigToMap(map as never, config.current));

    // Cycle 1: positron.
    map.loadStyle(waterLayer(POSITRON_WATER));
    expect(map.paintOf('water')['fill-color']).toBe(MONOCHROME_WATER);

    // Cycle 2: dark. Same layer id, different pristine colour.
    map.loadStyle(waterLayer(DARK_WATER));
    expect(map.paintOf('water')['fill-color']).toBe(MONOCHROME_WATER);

    // The second style's pristine must be the second style's own paint.
    config.current = { ...DEFAULT_BASEMAP_CONFIG };
    applyBasemapConfigToMap(map as never, config.current);
    expect(map.paintOf('water')['fill-color']).toBe(DARK_WATER);

    // Back to positron, and its own pristine must come back too.
    config.current = { ...DEFAULT_BASEMAP_CONFIG, land_water_tone: 'monochrome' };
    map.loadStyle(waterLayer(POSITRON_WATER));
    expect(map.paintOf('water')['fill-color']).toBe(MONOCHROME_WATER);
    config.current = { ...DEFAULT_BASEMAP_CONFIG };
    applyBasemapConfigToMap(map as never, config.current);
    expect(map.paintOf('water')['fill-color']).toBe(POSITRON_WATER);
  });

  it('never writes the previous basemap colour onto a style that just loaded', () => {
    const map = createLiveStyleMap(waterLayer(POSITRON_WATER));
    applyBasemapConfigToMap(map as never, { ...DEFAULT_BASEMAP_CONFIG, land_water_tone: 'muted' });
    expect(map.paintOf('water')['fill-color']).toBe('#d8e5e8');

    // No style.load listener is registered anywhere in this test, so nothing
    // can clear a cache before the appearance pass below runs.
    map.loadStyle(waterLayer(DARK_WATER));
    map.setPaintProperty.mockClear();
    applyBasemapConfigToMap(map as never, { ...DEFAULT_BASEMAP_CONFIG });

    expect(map.paintOf('water')['fill-color']).toBe(DARK_WATER);
    // Nothing at all was written for this key: dark's own paint already IS the
    // target. The old code wrote positron's pristine over it.
    const fillColorWrites = map.setPaintProperty.mock.calls.filter(
      (c) => c[0] === 'water' && c[1] === 'fill-color',
    );
    expect(fillColorWrites).toEqual([]);
  });
});
