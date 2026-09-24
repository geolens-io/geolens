/** A tileset preview is told apart from raster and vector previews and imports as tiles3d. */
import { inferImportedKind, isFilePreview, isRasterPreview, isTilesetPreview, kindFromEntry } from '../utils';
import type { TilesetPreviewResponse } from '@/types/api';

const TILESET_PREVIEW: TilesetPreviewResponse = {
  job_id: 'job-1',
  source_filename: 'campus.zip',
  version: '1.1',
  geometric_error: 16,
  bounding_volume: 'region',
  extent_bbox: [-1, -1, 1, 1],
  unpacked_bytes: 2048,
  entry_count: 3,
};

describe('tileset previews', () => {
  it('is a tileset preview and neither a raster nor a file preview', () => {
    expect(isTilesetPreview(TILESET_PREVIEW)).toBe(true);
    expect(isRasterPreview(TILESET_PREVIEW)).toBe(false);
    expect(isFilePreview(TILESET_PREVIEW)).toBe(false);
  });

  it('imports and displays as the tiles3d kind', () => {
    expect(inferImportedKind({ previewData: TILESET_PREVIEW })).toBe('tiles3d');
    expect(kindFromEntry({ previewData: TILESET_PREVIEW, fileName: 'campus.zip' })).toBe('tiles3d');
  });

  it('displays an entry uploaded as a tileset as tiles3d before it has a preview', () => {
    expect(kindFromEntry({ previewData: null, fileName: 'campus.zip', uploadKind: 'tiles3d' })).toBe('tiles3d');
    expect(kindFromEntry({ previewData: null, fileName: 'campus.zip', uploadKind: null })).toBe('vector');
  });
});
