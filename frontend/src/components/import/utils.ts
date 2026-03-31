import type { FilePreviewResponse, RasterPreviewResponse } from '@/types/api';

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
