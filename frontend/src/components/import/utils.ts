import type { CommitImportRequest, FileEntry, FilePreviewResponse, RasterPreviewResponse } from '@/types/api';
import type { DataKind } from './TypeTag';
import { kindFromExtension } from './TypeTag';

export function isRasterPreview(
  data: FilePreviewResponse | RasterPreviewResponse,
): data is RasterPreviewResponse {
  return 'band_count' in data;
}

export function isFilePreview(
  data: FilePreviewResponse | RasterPreviewResponse,
): data is FilePreviewResponse {
  return 'layers' in data || 'layer_name' in data;
}

export function stripExtension(filename: string): string {
  const dot = filename.lastIndexOf('.');
  return dot > 0 ? filename.slice(0, dot) : filename;
}

export function inferImportedKind(
  entry: Pick<FileEntry, 'previewData'>,
  request?: Pick<CommitImportRequest, 'x_column' | 'y_column' | 'geom_column'>,
): NonNullable<FileEntry['submittedKind']> {
  if (!entry.previewData) return 'table';
  if (isRasterPreview(entry.previewData)) return 'raster';

  if (request?.x_column || request?.y_column || request?.geom_column) {
    return 'vector';
  }

  if (entry.previewData.geometry_type || entry.previewData.detected_geometry_columns) {
    return 'vector';
  }

  return 'table';
}

/** Extract file extension (e.g. ".gpkg") or empty string if none */
export function fileExt(fileName: string): string {
  const dotIdx = fileName.lastIndexOf('.');
  return dotIdx >= 0 ? fileName.slice(dotIdx).toLowerCase() : '';
}

/** Derive display kind from a FileEntry (preview-aware, falls back to extension) */
export function kindFromEntry(entry: Pick<FileEntry, 'previewData' | 'fileName'>): DataKind {
  if (entry.previewData) {
    if (isRasterPreview(entry.previewData)) return 'raster';
    if ((entry.previewData as FilePreviewResponse).geometry_type) return 'vector';
    return 'table';
  }
  return kindFromExtension(fileExt(entry.fileName));
}
