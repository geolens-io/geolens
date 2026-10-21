import type { TilesetMetadata } from '@/types/api';

// Vector, geometry, voxel, composite and JSON glTF tiles, KTX2 textures, and
// the legacy multiple-contents and implicit-tiling spellings need renderers,
// a transcoder or loader paths the viewer does not have.
const UNSUPPORTED_CONTENT_TYPES = new Set(['vctr', 'geom', 'voxl', 'cmpt', 'gltf']);
const UNSUPPORTED_EXTENSIONS = new Set([
  'KHR_texture_basisu',
  '3DTILES_content_voxels',
  '3DTILES_multiple_contents',
  '3DTILES_implicit_tiling',
]);

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
