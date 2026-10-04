import type {
  CommitImportRequest,
  FileEntry,
  FilePreviewResponse,
  RasterPreviewResponse,
  TilesetPreviewResponse,
  PointCloudPreviewResponse,
} from '@/types/api';

type AnyPreview = FilePreviewResponse | RasterPreviewResponse | TilesetPreviewResponse | PointCloudPreviewResponse;

export function isRasterPreview(data: AnyPreview): data is RasterPreviewResponse {
  return 'band_count' in data;
}

export function isFilePreview(data: AnyPreview): data is FilePreviewResponse {
  return 'layers' in data || 'layer_name' in data;
}

export function isTilesetPreview(data: AnyPreview): data is TilesetPreviewResponse {
  return 'bounding_volume' in data;
}

export function isPointCloudPreview(data: AnyPreview): data is PointCloudPreviewResponse {
  return 'point_count' in data && 'point_format' in data;
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
  if (isTilesetPreview(entry.previewData)) return 'tiles3d';
  if (isPointCloudPreview(entry.previewData)) return 'pointcloud';
  if (isRasterPreview(entry.previewData)) return 'raster';

  if (request?.x_column || request?.y_column || request?.geom_column) {
    return 'vector';
  }

  if (entry.previewData.geometry_type || entry.previewData.detected_geometry_columns) {
    return 'vector';
  }

  return 'table';
}

/** Geometry columns the single-file form submits unchanged: its auto mode. */
export function detectedGeometryRequest(
  preview: FilePreviewResponse,
): Pick<CommitImportRequest, 'x_column' | 'y_column' | 'geom_column'> {
  const detected = preview.detected_geometry_columns;
  if (preview.geometry_type || !detected) return {};
  if (detected.x_column && detected.y_column) {
    return { x_column: detected.x_column, y_column: detected.y_column };
  }
  if (detected.wkt_column) return { geom_column: detected.wkt_column };
  return {};
}
