const EXT_MIME_MAP: Record<string, string> = {
  '.zip': 'application/zip',
  '.gpkg': 'application/geopackage+sqlite3',
  '.geojson': 'application/geo+json',
  '.json': 'application/geo+json',
  '.csv': 'text/csv',
  '.tif': 'image/tiff',
  '.tiff': 'image/tiff',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  '.xls': 'application/vnd.ms-excel',
};

/** Convert extension list to react-dropzone accept map. Unknown extensions use application/octet-stream. */
export function buildAcceptMap(extensions: string[]): Record<string, string[]> {
  const accept: Record<string, string[]> = {};
  for (const ext of extensions) {
    const mime = EXT_MIME_MAP[ext] ?? 'application/octet-stream';
    if (!accept[mime]) accept[mime] = [];
    if (!accept[mime].includes(ext)) accept[mime].push(ext);
  }
  return accept;
}

/** Derive display badges from extensions -- deduplicate aliases (.tif/.tiff -> .tif, .json -> skip if .geojson present). */
export function deriveFormatBadges(extensions: string[]): string[] {
  const set = new Set(extensions);
  const skip = new Set<string>();
  if (set.has('.tif') && set.has('.tiff')) skip.add('.tiff');
  if (set.has('.geojson') && set.has('.json')) skip.add('.json');
  const badges: string[] = [];
  for (const ext of extensions) {
    if (!skip.has(ext)) badges.push(ext);
  }
  return badges;
}
