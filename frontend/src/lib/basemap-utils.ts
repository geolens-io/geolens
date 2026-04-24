import type { StyleSpecification } from 'maplibre-gl';
import type { BasemapEntry } from '@/api/settings';
import positronThumb from '@/assets/basemaps/positron.png';
import darkThumb from '@/assets/basemaps/dark.png';
import osmThumb from '@/assets/basemaps/osm.png';
import brightThumb from '@/assets/basemaps/bright.png';

export const LIGHT_PRESET_ID = 'openfreemap-positron';
export const DARK_PRESET_ID = 'openfreemap-dark';
export const BLANK_BASEMAP_ID = 'blank';

const BLANK_THUMBNAIL = `data:image/svg+xml,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160">' +
  '<rect fill="#f3f4f6" width="160" height="160" rx="8" stroke="#d1d5db" stroke-width="2" stroke-dasharray="8 4"/>' +
  '<line x1="30" y1="30" x2="130" y2="130" stroke="#9ca3af" stroke-width="3" stroke-linecap="round"/>' +
  '<text x="80" y="148" text-anchor="middle" font-size="12" fill="#9ca3af" font-family="system-ui,sans-serif">None</text>' +
  '</svg>'
)}`;

const BUILTIN_THUMBNAILS: Record<string, string> = {
  'blank': BLANK_THUMBNAIL,
  'openfreemap-positron': positronThumb,
  'openfreemap-dark': darkThumb,
  'openstreetmap': osmThumb,
  'osm-standard': osmThumb,
  'openfreemap-bright': brightThumb,
};

const FALLBACK_THUMBNAIL = `data:image/svg+xml,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160">' +
  '<rect fill="#e5e7eb" width="160" height="160" rx="8"/>' +
  '<circle cx="80" cy="72" r="36" fill="none" stroke="#9ca3af" stroke-width="2"/>' +
  '<ellipse cx="80" cy="72" rx="16" ry="36" fill="none" stroke="#9ca3af" stroke-width="1.5"/>' +
  '<line x1="44" y1="72" x2="116" y2="72" stroke="#9ca3af" stroke-width="1.5"/>' +
  '<line x1="80" y1="36" x2="80" y2="108" stroke="#9ca3af" stroke-width="1.5"/>' +
  '<text x="80" y="136" text-anchor="middle" font-size="12" fill="#9ca3af" font-family="system-ui,sans-serif">Map</text>' +
  '</svg>'
)}`;

/** Get the thumbnail URL for a basemap, with a fallback globe icon for custom basemaps */
export function basemapThumbnail(id: string): string {
  return BUILTIN_THUMBNAILS[id] ?? FALLBACK_THUMBNAIL;
}

const LEGACY_KEY_MAP: Record<string, string> = {
  positron: 'openfreemap-positron',
  'dark-matter': 'openfreemap-dark',
  voyager: 'openfreemap-positron',
  'carto-positron': 'openfreemap-positron',
  'carto-dark-matter': 'openfreemap-dark',
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
  if (url === BLANK_BASEMAP_ID) {
    return {
      version: 8 as const,
      sources: {},
      layers: [
        {
          id: 'background',
          type: 'background' as const,
          paint: { 'background-color': 'rgba(0,0,0,0)' },
        },
      ],
      glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
    };
  }
  const urlPath = url.split('?')[0];
  if (urlPath.endsWith('.json') || url.includes('/styles/')) {
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
