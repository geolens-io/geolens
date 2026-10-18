import type { RecordType } from '@/types/api';

export const EXPORT_FORMATS = [
  { value: 'gpkg', labelKey: 'export.gpkg', ext: 'gpkg' },
  { value: 'geojson', labelKey: 'export.geojson', ext: 'geojson' },
  { value: 'shp', labelKey: 'export.shp', ext: 'zip' },
  { value: 'csv', labelKey: 'export.csv', ext: 'csv' },
  { value: 'parquet', labelKey: 'export.parquet', ext: 'parquet' },
  { value: 'fgb', labelKey: 'export.fgb', ext: 'fgb' },
  { value: 'pmtiles', labelKey: 'export.pmtiles', ext: 'pmtiles' },
] as const;

const CSV_ONLY = EXPORT_FORMATS.filter((f) => f.value === 'csv');

export function exportFormatsFor(recordType?: RecordType) {
  return recordType === 'table' ? CSV_ONLY : EXPORT_FORMATS;
}

/** Saved name for an export, or null when `format` is not an export format. Path separators become underscores, as browsers do for `download`. */
export function exportFilename(title: string, format: string): string | null {
  const match = EXPORT_FORMATS.find((f) => f.value === format);
  if (!match) return null;
  return `${title.replace(/[/\\]/g, '_')}.${match.ext}`;
}
