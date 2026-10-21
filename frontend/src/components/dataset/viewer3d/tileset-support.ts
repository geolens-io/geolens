import type { TilesetMetadata } from '@/types/api';

// Vector, geometry and voxel tiles, and KTX2 textures, need renderers or a
// transcoder the viewer does not bundle.
const UNSUPPORTED_CONTENT_TYPES = new Set(['vctr', 'geom', 'voxl']);
const UNSUPPORTED_EXTENSIONS = new Set(['KHR_texture_basisu', '3DTILES_content_voxels']);

/**
 * The URL of a tileset the in-page 3D viewer can draw, or null when it cannot.
 * Unrecorded facts (older publishes) try the viewer.
 */
export function viewableTilesetUrl(tileset: TilesetMetadata | null | undefined): string | null {
  if (!tileset?.url) return null;
  if (tileset.content_types?.some((type) => UNSUPPORTED_CONTENT_TYPES.has(type))) return null;
  if (tileset.extensions_required?.some((name) => UNSUPPORTED_EXTENSIONS.has(name))) return null;
  return tileset.url;
}
