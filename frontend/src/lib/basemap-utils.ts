import type { StyleSpecification } from 'maplibre-gl';
import type { BasemapEntry } from '@/api/settings';

export const LIGHT_PRESET_ID = 'carto-positron';
export const DARK_PRESET_ID = 'carto-dark-matter';

const LEGACY_KEY_MAP: Record<string, string> = {
  positron: 'carto-positron',
  'dark-matter': 'carto-dark-matter',
  voyager: 'carto-positron',
};

/**
 * Convert a basemap URL to a MapLibre style.
 * - If the URL ends with `.json`, it's already a GL style JSON URL -- return as-is.
 *   (GL style JSON basemaps carry their own attribution in the style spec.)
 * - Otherwise (XYZ raster tile URL), wrap it in an inline StyleSpecification.
 *   If attribution is provided, it is set on the raster source so that
 *   MapLibre's AttributionControl displays it.
 */
export function toMaplibreStyle(url: string, attribution?: string): string | StyleSpecification {
  if (url.endsWith('.json')) {
    return url;
  }
  return {
    version: 8 as const,
    sources: {
      basemap: {
        type: 'raster' as const,
        tiles: [url],
        tileSize: 256,
        ...(attribution ? { attribution } : {}),
      },
    },
    layers: [{ id: 'basemap-tiles', type: 'raster' as const, source: 'basemap' }],
    glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
  };
}

/**
 * Map old saved basemap keys (positron, dark-matter, voyager) to new preset IDs.
 * Returns the key as-is if it's not a legacy key.
 */
export function resolveBasemapId(key: string): string {
  return LEGACY_KEY_MAP[key] ?? key;
}

/**
 * Find the appropriate basemap for the current theme.
 * Prefers DARK_PRESET_ID for dark theme and LIGHT_PRESET_ID for light theme.
 * Falls back to the first enabled basemap.
 */
export function getThemeBasemap(
  basemaps: BasemapEntry[],
  resolvedTheme: 'dark' | 'light',
): BasemapEntry | undefined {
  const enabled = basemaps.filter((b) => b.enabled);
  const targetId = resolvedTheme === 'dark' ? DARK_PRESET_ID : LIGHT_PRESET_ID;
  return enabled.find((b) => b.id === targetId) ?? enabled[0];
}

/**
 * Find a basemap by ID, also checking the legacy key mapping.
 */
export function findBasemapById(
  basemaps: BasemapEntry[],
  id: string,
): BasemapEntry | undefined {
  return basemaps.find((b) => b.id === id) ?? basemaps.find((b) => b.id === resolveBasemapId(id));
}
