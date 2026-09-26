type Translate = (key: string, options?: Record<string, unknown>) => unknown;

const GEOMETRY_TYPE_KEYS = {
  POINT: 'common:enums.geometryType.point',
  LINESTRING: 'common:enums.geometryType.lineString',
  POLYGON: 'common:enums.geometryType.polygon',
  MULTIPOINT: 'common:enums.geometryType.multiPoint',
  MULTILINESTRING: 'common:enums.geometryType.multiLineString',
  MULTIPOLYGON: 'common:enums.geometryType.multiPolygon',
} as const;

const VISIBILITY_KEYS = {
  public: 'common:enums.visibility.public',
  internal: 'common:enums.visibility.internal',
  private: 'common:enums.visibility.private',
  restricted: 'common:enums.visibility.restricted',
} as const;

const RECORD_STATUS_KEYS = {
  draft: 'common:enums.recordStatus.draft',
  ready: 'common:enums.recordStatus.ready',
  internal: 'common:enums.recordStatus.internal',
  published: 'common:enums.recordStatus.published',
} as const;

const SOURCE_FORMAT_KEYS = {
  geojson: 'common:enums.sourceFormat.geojson',
  shp: 'common:enums.sourceFormat.shp',
  shapefile: 'common:enums.sourceFormat.shapefile',
  gpkg: 'common:enums.sourceFormat.gpkg',
  csv: 'common:enums.sourceFormat.csv',
  fgb: 'common:enums.sourceFormat.fgb',
  kml: 'common:enums.sourceFormat.kml',
  fgdb: 'common:enums.sourceFormat.fgdb',
  wfs: 'common:enums.sourceFormat.wfs',
  arcgis_featureserver: 'common:enums.sourceFormat.arcgisFeatureServer',
  ogcapi_features: 'common:enums.sourceFormat.ogcapiFeatures',
  created: 'common:enums.sourceFormat.created',
  '3dtiles': 'common:enums.sourceFormat.tiles3d',
  copc: 'common:enums.sourceFormat.copc',
} as const;

const BOUNDING_VOLUME_KEYS = {
  region: 'common:enums.boundingVolume.region',
  box: 'common:enums.boundingVolume.box',
  sphere: 'common:enums.boundingVolume.sphere',
} as const;

const SEARCH_SORT_KEYS = {
  relevance: 'search:filters.relevance',
  date_added: 'search:filters.dateAdded',
  name: 'search:filters.name',
  last_updated: 'search:filters.lastUpdated',
} as const;

const SEARCH_SORT_DEFAULTS = {
  relevance: 'Relevance',
  date_added: 'Date Added',
  name: 'Name',
  last_updated: 'Last Updated',
} as const;

const SOURCE_FORMAT_DEFAULTS = {
  geojson: 'GeoJSON',
  shp: 'SHP',
  shapefile: 'Shapefile',
  gpkg: 'GeoPackage',
  csv: 'CSV',
  fgb: 'FlatGeobuf',
  kml: 'KML',
  fgdb: 'File Geodatabase',
  wfs: 'WFS',
  arcgis_featureserver: 'ArcGIS FeatureServer',
  ogcapi_features: 'OGC API Features',
  created: 'Created in GeoLens',
  '3dtiles': '3D Tiles',
  copc: 'COPC',
} as const;

function resolveLabel(t: Translate, key: string, defaultValue: string): string {
  const value = t(key, { defaultValue });
  return typeof value === 'string' ? value : defaultValue;
}

function humanizeToken(value: string): string {
  return value
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(' ');
}

function normalizeGeometryType(value: string | null | undefined): string {
  return value?.trim().toUpperCase() ?? '';
}

// No base OGC type name ends in Z or M, so stripping the longest match first
// (ZM before Z or M alone) never misreads part of the base name as a suffix.
const COORD_SUFFIXES = ['ZM', 'Z', 'M'] as const;

function splitCoordSuffix(value: string): { base: string; suffix: string } {
  for (const suffix of COORD_SUFFIXES) {
    if (value.length > suffix.length && value.endsWith(suffix)) {
      return { base: value.slice(0, -suffix.length), suffix };
    }
  }
  return { base: value, suffix: '' };
}

function normalizeEnumValue(value: string | null | undefined): string {
  return value?.trim().toLowerCase() ?? '';
}

function defaultGeometryTypeLabel(value: string): string {
  switch (value) {
    case 'POINT':
      return 'Point';
    case 'LINESTRING':
      return 'LineString';
    case 'POLYGON':
      return 'Polygon';
    case 'MULTIPOINT':
      return 'MultiPoint';
    case 'MULTILINESTRING':
      return 'MultiLineString';
    case 'MULTIPOLYGON':
      return 'MultiPolygon';
    default:
      return humanizeToken(value);
  }
}

export function getGeometryTypeLabel(
  t: Translate,
  geometryType: string | null | undefined,
): string {
  const normalized = normalizeGeometryType(geometryType);

  if (!normalized) {
    return '';
  }

  // A measured/3D type (e.g. MULTIPOINTM) carries its Z/M/ZM suffix past the
  // base-type lookup below; translate the base and reattach the suffix as-is
  // rather than losing it to (or mangling it through) the fallback humanizer.
  const { base, suffix } = splitCoordSuffix(normalized);
  const key = GEOMETRY_TYPE_KEYS[base as keyof typeof GEOMETRY_TYPE_KEYS];

  if (!key) {
    return defaultGeometryTypeLabel(normalized);
  }

  return resolveLabel(t, key, defaultGeometryTypeLabel(base)) + suffix;
}

/**
 * Reattaches the Z/M/ZM coordinate suffix a catalog-normalized geometry_type
 * never carries — `chk_datasets_geometry_type` only allows the plain OGC
 * name, so a dataset's measured/3D-ness has to come from is_3d + n_dims
 * (backend `metadata_extent.py`) instead of the type string itself.
 */
export function withCoordSuffix(
  geometryType: string | null | undefined,
  is3d: boolean | null | undefined,
  nDims: number | null | undefined,
): string | null | undefined {
  if (!geometryType) return geometryType;
  if (is3d) return `${geometryType}${nDims === 4 ? 'ZM' : 'Z'}`;
  if (nDims === 3) return `${geometryType}M`;
  return geometryType;
}

export function getVisibilityLabel(
  t: Translate,
  visibility: string | null | undefined,
): string {
  const normalized = normalizeEnumValue(visibility);

  if (!normalized) {
    return '';
  }

  const key = VISIBILITY_KEYS[normalized as keyof typeof VISIBILITY_KEYS];
  const defaultValue = humanizeToken(normalized);

  return key ? resolveLabel(t, key, defaultValue) : defaultValue;
}

export function getRecordStatusLabel(
  t: Translate,
  recordStatus: string | null | undefined,
): string {
  const normalized = normalizeEnumValue(recordStatus);

  if (!normalized) {
    return '';
  }

  const key = RECORD_STATUS_KEYS[normalized as keyof typeof RECORD_STATUS_KEYS];
  const defaultValue = humanizeToken(normalized);

  return key ? resolveLabel(t, key, defaultValue) : defaultValue;
}

export function getSourceFormatLabel(
  t: Translate,
  sourceFormat: string | null | undefined,
): string {
  const normalized = normalizeEnumValue(sourceFormat);

  if (!normalized) {
    return '';
  }

  const key = SOURCE_FORMAT_KEYS[normalized as keyof typeof SOURCE_FORMAT_KEYS];
  const defaultValue =
    SOURCE_FORMAT_DEFAULTS[normalized as keyof typeof SOURCE_FORMAT_DEFAULTS] ??
    humanizeToken(normalized);

  return key ? resolveLabel(t, key, defaultValue) : defaultValue;
}

export function getSearchSortLabel(
  t: Translate,
  sortBy: string | null | undefined,
): string {
  const normalized = normalizeEnumValue(sortBy);

  if (!normalized) {
    return '';
  }

  const key = SEARCH_SORT_KEYS[normalized as keyof typeof SEARCH_SORT_KEYS];
  const defaultValue =
    SEARCH_SORT_DEFAULTS[normalized as keyof typeof SEARCH_SORT_DEFAULTS] ??
    humanizeToken(normalized);

  return key ? resolveLabel(t, key, defaultValue) : defaultValue;
}

/** The label of a 3D Tiles root bounding volume kind: region, box or sphere. */
export function getBoundingVolumeLabel(
  t: Translate,
  volume: string | null | undefined,
): string {
  const normalized = normalizeEnumValue(volume);

  if (!normalized) {
    return '';
  }

  const key = BOUNDING_VOLUME_KEYS[normalized as keyof typeof BOUNDING_VOLUME_KEYS];
  const defaultValue = humanizeToken(normalized);

  return key ? resolveLabel(t, key, defaultValue) : defaultValue;
}
