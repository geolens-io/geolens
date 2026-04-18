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
} as const;

const RECORD_STATUS_KEYS = {
  draft: 'common:enums.recordStatus.draft',
  published: 'common:enums.recordStatus.published',
  archived: 'common:enums.recordStatus.archived',
  deprecated: 'common:enums.recordStatus.deprecated',
} as const;

const SOURCE_FORMAT_KEYS = {
  geojson: 'common:enums.sourceFormat.geojson',
  shp: 'common:enums.sourceFormat.shp',
  shapefile: 'common:enums.sourceFormat.shapefile',
  gpkg: 'common:enums.sourceFormat.gpkg',
  csv: 'common:enums.sourceFormat.csv',
  wfs: 'common:enums.sourceFormat.wfs',
  arcgis_featureserver: 'common:enums.sourceFormat.arcgisFeatureServer',
  ogcapi_features: 'common:enums.sourceFormat.ogcapiFeatures',
  created: 'common:enums.sourceFormat.created',
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
  wfs: 'WFS',
  arcgis_featureserver: 'ArcGIS FeatureServer',
  ogcapi_features: 'OGC API Features',
  created: 'Created in GeoLens',
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

  const key = GEOMETRY_TYPE_KEYS[normalized as keyof typeof GEOMETRY_TYPE_KEYS];
  const defaultValue = defaultGeometryTypeLabel(normalized);

  return key ? resolveLabel(t, key, defaultValue) : defaultValue;
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
