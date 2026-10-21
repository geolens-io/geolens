import type { components } from '@/types/api.generated';

type TilesetMetadata = components['schemas']['TilesetMetadata'];
type PointCloudMetadata = components['schemas']['PointCloudMetadata'];

export type Viewer3DSource =
  | { kind: 'tileset'; url: string }
  | { kind: 'pointcloud'; url: string; sizeBytes: number | null };

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

/** The COPC file the in-page viewer can read; formats 6 to 8 are the only ones the catalog accepts. */
export function viewablePointCloud(
  pointcloud: PointCloudMetadata | null | undefined,
): Extract<Viewer3DSource, { kind: 'pointcloud' }> | null {
  if (!pointcloud?.url) return null;
  return { kind: 'pointcloud', url: pointcloud.url, sizeBytes: pointcloud.size_bytes ?? null };
}
