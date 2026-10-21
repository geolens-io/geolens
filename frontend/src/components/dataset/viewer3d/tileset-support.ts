import type { TilesetMetadata } from '@/types/api';

// Vector, geometry and voxel tiles, and KTX2 textures, need renderers or a
// transcoder the viewer does not bundle.
const UNSUPPORTED_CONTENT_TYPES = new Set(['vctr', 'geom', 'voxl']);
const UNSUPPORTED_EXTENSIONS = new Set(['KHR_texture_basisu', '3DTILES_content_voxels']);

/** Whether the in-page 3D viewer can draw this tileset. Unrecorded facts (older publishes) try the viewer. */
export function canViewTileset(tileset: TilesetMetadata | null | undefined): boolean {
  if (!tileset?.url) return false;
  if (tileset.content_types?.some((type) => UNSUPPORTED_CONTENT_TYPES.has(type))) return false;
  return !tileset.extensions_required?.some((name) => UNSUPPORTED_EXTENSIONS.has(name));
}
