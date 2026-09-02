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

/** A map mock whose setPaintProperty MUTATES the style it hands back, which is
 *  what the real MapLibre map does and what the bug depended on. */
function createLiveStyleMap(layers: StyleSpecification['layers']) {
  const style = {
    version: 8 as const,
    sources: {},
    layers: layers.map((layer) => ({ ...layer, paint: { ...('paint' in layer ? layer.paint : {}) } })),
  } as unknown as StyleSpecification;
  const byId = new Map(style.layers.map((layer) => [layer.id, layer]));
  return {
    getStyle: vi.fn(() => style),
    getLayer: vi.fn((id: string) => byId.get(id)),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn((id: string, key: string, value: unknown) => {
      const layer = byId.get(id) as { paint?: Record<string, unknown> } | undefined;
      if (!layer) return;
      layer.paint = { ...(layer.paint ?? {}) };
      if (value === undefined) delete layer.paint[key];
      else layer.paint[key] = value;
    }),
    on: vi.fn(),
    paintOf: (id: string) => ((byId.get(id) as { paint?: Record<string, unknown> })?.paint ?? {}),
  };
}

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
  });

  it('drops the pristine snapshot when a new style loads', () => {
    const map = createLiveStyleMap([
      { id: 'water', type: 'fill', source: 'openmaptiles', paint: { 'fill-color': '#a0c8f0' } },
    ] as unknown as StyleSpecification['layers']);

    applyBasemapConfigToMap(map as never, { ...DEFAULT_BASEMAP_CONFIG, land_water_tone: 'muted' });
    expect(map.paintOf('water')['fill-color']).toBe('#d8e5e8');

    // A basemap swap replaces the style; positron and dark share layer ids, so
    // a cache that survived it would restore the previous basemap's colours.
    const styleLoad = map.on.mock.calls.find((c) => c[0] === 'style.load')?.[1] as () => void;
    expect(styleLoad).toBeTypeOf('function');
    map.setPaintProperty('water', 'fill-color', '#1b2733');
    styleLoad();

    applyBasemapConfigToMap(map as never, { ...DEFAULT_BASEMAP_CONFIG, land_water_tone: 'muted' });
    applyBasemapConfigToMap(map as never, { ...DEFAULT_BASEMAP_CONFIG });
    expect(map.paintOf('water')['fill-color']).toBe('#1b2733');
  });
});
