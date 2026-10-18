const EXPORT_FORMATS = [
  { value: 'gpkg', labelKey: 'export.gpkg', ext: 'gpkg' },
  { value: 'geojson', labelKey: 'export.geojson', ext: 'geojson' },
  { value: 'shp', labelKey: 'export.shp', ext: 'zip' },
  { value: 'csv', labelKey: 'export.csv', ext: 'csv' },
  { value: 'parquet', labelKey: 'export.parquet', ext: 'parquet' },
  { value: 'fgb', labelKey: 'export.fgb', ext: 'fgb' },
  { value: 'pmtiles', labelKey: 'export.pmtiles', ext: 'pmtiles' },
] as const;

export type ExportFormat = (typeof EXPORT_FORMATS)[number]['value'];

const CSV_ONLY = EXPORT_FORMATS.filter((f) => f.value === 'csv');

export function isExportFormat(format: string | null | undefined): format is ExportFormat {
  return EXPORT_FORMATS.some((f) => f.value === format);
}

/** Without a geometry column the server only exports CSV. */
export function exportFormatsFor(geometryType: string | null | undefined) {
  return geometryType == null ? CSV_ONLY : EXPORT_FORMATS;
}

/** Saved name for an export. Path separators become underscores, as browsers do for `download`. */
export function exportFilename(title: string, format: ExportFormat): string {
  const ext = EXPORT_FORMATS.find((f) => f.value === format)!.ext;
  return `${title.replace(/[/\\]/g, '_')}.${ext}`;
}
