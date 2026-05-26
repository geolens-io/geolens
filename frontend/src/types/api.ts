import type { Geometry } from 'geojson';
import type { FilterSpecification, HeatmapLayerSpecification, CircleLayerSpecification } from 'maplibre-gl';

/** OGC/PostGIS geometry type values returned by the API. */
export type GeometryTypeName = string;

/** Layer type discriminator for map layers. */
export type MapLayerType = 'vector_geolens' | 'raster_geolens' | 'geojson';

export interface MapTerrainConfig {
  enabled: boolean;
  source_dataset_id: string | null;
  exaggeration: number;
}

export type MapBasemapVisibilityMode = 'full' | 'subtle' | 'hidden';
export type MapBasemapLandWaterTone = 'default' | 'muted' | 'contrast' | 'monochrome';
export type MapBasemapReliefContrast = 'soft' | 'standard' | 'strong';
/** Phase 1051 UX-03: position of the basemap row in the unified stack.
 *  - 'bottom' (default, legacy) — basemap renders BELOW data layers.
 *  - 'top' — basemap renders ABOVE data layers; useful for 3D maps showing
 *    elevation through a translucent basemap.
 *  Stored on the `MapBasemapConfig` jsonb so no backend schema migration is
 *  required — legacy maps load with `undefined` and default to 'bottom'. */
export type MapBasemapPosition = 'top' | 'bottom';

/** Phase 1059 BSE-01: per-sublayer style override stored in MapBasemapConfig.sublayer_overrides.
 *  All fields nullable — null means "use basemap default". Mirrors backend SublayerOverride
 *  Pydantic model at backend/app/modules/catalog/maps/schemas.py.
 *  Color fields MUST be #RRGGBB hex when non-null (validated server-side via regex). */
export interface MapSublayerOverride {
  stroke_color?: string | null;
  stroke_width?: number | null;
  casing_color?: string | null;
  casing_width?: number | null;
  min_zoom?: number | null;
  max_zoom?: number | null;
  opacity?: number | null;
}

/** Known sublayer IDs the editor exposes. Key set is OPEN (D-01 forward-compat) —
 *  consumers should not exhaustively switch on this union; new IDs may appear from
 *  future basemap providers. */
export type KnownSublayerId = 'road' | 'boundary' | 'building' | 'label';

export interface MapBasemapConfig {
  label_mode: MapBasemapVisibilityMode;
  road_visibility: MapBasemapVisibilityMode;
  boundary_visibility: MapBasemapVisibilityMode;
  building_visibility: boolean;
  land_water_tone: MapBasemapLandWaterTone;
  relief_contrast?: MapBasemapReliefContrast | null;
  opacity?: number;
  /** Map canvas background color in #RRGGBB hex format. null/undefined uses the basemap default. */
  background_color?: string | null;
  /** Phase 1051 UX-03: 'top' renders basemap above data; 'bottom' (default)
   *  renders below. See `MapBasemapPosition` above. */
  basemap_position?: MapBasemapPosition;
  /** Phase 1059 BSE-01: per-sublayer overrides keyed by semantic sublayer ID.
   *  Opaque key set — see KnownSublayerId for documented IDs. Backed by
   *  MapBasemapConfig.sublayer_overrides jsonb (zero-migration backward compat). */
  sublayer_overrides?: Record<string, MapSublayerOverride> | null;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface UserResponse {
  id: string;
  username: string;
  email: string | null;
  is_active: boolean;
  status: string;
  last_login_at: string | null;
  created_at: string;
  roles: string[];
}

export interface RasterBandInfo {
  index: number;
  dtype: string;
  nodata: string | null;
  color_interp: string | null;
}

export interface RasterConnect {
  download_url: string | null;
  tile_url: string;
  s3_uri: string | null;
}

export interface StacAsset {
  href: string;
  type?: string;
  title?: string;
  description?: string;
  roles?: string[];
  size_bytes?: number;
}

export interface RasterMetadata {
  epsg: number | null;
  res_x: number | null;
  res_y: number | null;
  band_count: number | null;
  nodata: string | null;
  compression: string | null;
  width: number | null;
  height: number | null;
  size_bytes: number | null;
  tile_url: string | null;
  bands: RasterBandInfo[];
  connect: RasterConnect | null;
  // VRT fields
  status: string | null;
  vrt_type: string | null;
  source_count: number | null;
  resolution_strategy: string | null;
}

export interface RasterPreviewResponse {
  job_id: string;
  source_filename: string | null;
  crs_epsg: number | null;
  crs_wkt: string | null;
  band_count: number;
  width: number;
  height: number;
  dtype: string;
  nodata: number | string | null;
  res_x: number;
  res_y: number;
  compression: string | null;
  file_size_bytes: number | null;
  is_cog_compliant: boolean;
  compliance_reason: string;
  temporal_start: string | null;
}

// Mirrors backend chk_records_record_type CHECK constraint
// (catalog/datasets/domain/models.py:52). Keep in sync if values change.
export type RecordType =
  | 'vector_dataset'
  | 'raster_dataset'
  | 'vrt_dataset'
  | 'map'
  | 'service'
  | 'collection'
  | 'table';
export type DatasetVisibility = 'public' | 'restricted' | 'private';
export type RecordStatus = 'draft' | 'published';
export type DistributionType = 'download' | 'ogc_features' | 'vector_tiles';

export interface DatasetResponse {
  id: string;
  record_id: string;
  table_name: string;
  title: string;
  summary: string | null;
  srid: number | null;
  geometry_type: GeometryTypeName | null;
  feature_count: number | null;
  extent_bbox: number[] | null;
  column_info: { name: string; type: string; semantic_role?: string | null; domain_type?: string | null }[] | null;
  license: string | null;
  source_organization: string | null;
  data_vintage_start: string | null;
  data_vintage_end: string | null;
  source_format: string | null;
  source_filename: string | null;
  tile_columns: string[] | null;
  original_srid: number | null;
  visibility: DatasetVisibility;
  created_by: string | null;
  created_by_display: string;
  created_at: string;
  updated_at: string;
  last_edited_by_display: string | null;
  last_edited_at: string | null;
  record_status: RecordStatus;
  lineage_summary: string | null;
  update_frequency: string | null;
  usage_constraints: string | null;
  access_constraints: string | null;
  sensitivity_classification: string | null;
  theme_category: string[] | null;
  owner_org: string | null;
  published_at: string | null;
  updated_by: string | null;
  current_version: number;
  source_url: string | null;
  quality_statement: string | null;
  collections: Array<{ id: string; name: string }> | null;
  quality_detail?: {
    overall: number;
    metadata_completeness: number;
    geometry_validity: number | null;
    attribute_completeness: number;
    crs_defined: number | null;
    computed_at: string | null;
  } | null;
  record_type: RecordType;
  raster: RasterMetadata | null;
  stac_assets?: Record<string, StacAsset> | null;
  stac_extensions?: string[];
  language?: string;
  is_3d?: boolean | null;
  n_dims?: number | null;
  z_min?: number | null;
  z_max?: number | null;
}

export interface DatasetListResponse {
  datasets: DatasetResponse[];
  total: number;
}

export interface CreateDatasetRequest {
  title: string;
  columns: Array<{ name: string; type: 'text' | 'integer' | 'float' | 'date' | 'boolean' }>;
}

export interface DatasetUpdateRequest {
  title?: string;
  summary?: string;
  visibility?: DatasetVisibility;
  license?: string;
  source_organization?: string;
  data_vintage_start?: string;
  data_vintage_end?: string;
  lineage_summary?: string;
  update_frequency?: string;
  usage_constraints?: string;
  access_constraints?: string;
  sensitivity_classification?: string;
  theme_category?: string[];
  record_status?: RecordStatus;
  owner_org?: string;
  quality_statement?: string;
  source_url?: string;
  is_dem?: boolean | null;
  tile_columns?: string[] | null;
}

// Record sub-resource types
export interface ContactCreate {
  role: string;
  name?: string | null;
  email?: string | null;
  organization?: string | null;
  phone?: string | null;
  extra_json?: Record<string, unknown> | null;
  sort_order?: number;
}

export interface ContactResponse {
  id: string;
  record_id: string;
  role: string;
  name: string | null;
  email: string | null;
  organization: string | null;
  phone: string | null;
  sort_order: number;
  extra_json?: Record<string, unknown> | null;
}

export interface ContactListResponse {
  contacts: ContactResponse[];
  total: number;
}

export interface KeywordCreate {
  keyword: string;
  vocabulary_uri?: string | null;
  keyword_type?: string;
}

export interface KeywordResponse {
  id: string;
  record_id: string;
  keyword: string;
  vocabulary_uri: string | null;
  keyword_type: string;
}

export interface KeywordListResponse {
  keywords: KeywordResponse[];
  total: number;
}

export interface DistributionResponse {
  id: string;
  record_id: string;
  distribution_type: DistributionType;
  format: string | null;
  url: string;
  title: string | null;
  description: string | null;
  protocol: string | null;
  media_type: string | null;
  is_primary: boolean;
  auto_generated: boolean;
}

export interface DistributionListResponse {
  distributions: DistributionResponse[];
  total: number;
}

export interface AttributeMetadataResponse {
  id: string;
  dataset_id: string;
  field_name: string;
  title: string | null;
  description: string | null;
  data_type: string | null;
  units: string | null;
  domain_type: string | null;
  semantic_role: string | null;
  example_values: unknown[] | null;
  ordinal_position: number | null;
  is_nullable: boolean | null;
  is_current: boolean;
  user_modified_fields: string[];
}

export interface AttributeMetadataUpdate {
  title?: string | null;
  description?: string | null;
  units?: string | null;
  semantic_role?: string | null;
  domain_type?: string | null;
}

export interface AttributeMetadataListResponse {
  attributes: AttributeMetadataResponse[];
  total: number;
}

export interface ValidationIssue {
  field: string;
  message: string;
  severity: 'error' | 'warning';
}

export interface ValidationResultResponse {
  is_valid: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  quality_score: Record<string, unknown> | null;
}

/**
 * Structured warnings attached to IngestJob.user_metadata.warnings[] by
 * the backend during ingest. Emitted when the pipeline silently rewrites
 * or drops something so the UI can surface it without surprising users.
 *
 * Source: backend/app/ingest/tasks.py `_append_job_warning`
 */
export interface IngestReservedRenameWarning {
  kind: 'reserved_rename';
  details: Array<{ original: string; renamed: string }>;
}

export interface IngestDbfTruncationWarning {
  kind: 'dbf_truncation_collision';
  details: Array<{ truncated: string; originals: string[] }>;
}

export type IngestJobWarning =
  | IngestReservedRenameWarning
  | IngestDbfTruncationWarning;

export interface OGCRecordProperties {
  type: string;
  title: string;
  description: string | null;
  keywords: string[] | null;
  created: string | null;
  updated: string | null;
  updated_by_display: string | null;
  never_edited: boolean;
  crs: string | null;
  geometry_type: GeometryTypeName | null;
  feature_count: number | null;
  row_count?: number | null;
  column_count?: number | null;
  contacts?: Array<{ name?: string; organization?: string; roles?: string[]; email?: string; phone?: string }> | null;
  license: string | null;
  source_organization: string | null;
  quality_detail?: {
    overall: number;
    metadata_completeness: number;
    geometry_validity: number | null;
    attribute_completeness: number;
    crs_defined: number | null;
    computed_at: string | null;
  } | null;
  record_status?: string | null;
  record_type?: RecordType;
  has_quicklook?: boolean;
  band_count?: number | null;
  epsg?: number | null;
  res_x?: number | null;
  res_y?: number | null;
  width?: number | null;
  height?: number | null;
  dtype?: string | null;
  nodata?: string | null;
  dataset_count?: number;
  vrt_type?: string | null;
  source_count?: number | null;
  gsd?: number | null;
}

export interface OGCRecordLink {
  rel: string;
  href: string;
  type: string;
}

export interface OGCRecordResponse {
  type: "Feature";
  id: string;
  geometry: Geometry | null;
  properties: OGCRecordProperties;
  links: OGCRecordLink[];
  conformsTo?: string[] | null;
  time?: Record<string, unknown> | null;
  assets?: Record<string, { href: string; type?: string; title?: string; roles?: string[] }> | null;
  bbox?: number[] | null;
}

export interface SearchResponse {
  type: "FeatureCollection";
  numberMatched: number;
  numberReturned: number;
  features: OGCRecordResponse[];
  links?: OGCRecordLink[] | null;
}

export interface CatalogSummary {
  geometry_type?: GeometryTypeName[];
  srid?: number[];
  keywords?: string[];
  source_organization?: string[];
}

export interface CatalogCollectionResponse {
  id: string;
  title: string;
  summaries?: CatalogSummary;
  [key: string]: unknown;
}

export interface FacetItem {
  value: string;
  count: number;
}

export interface FacetResponse {
  record_type: Record<string, number>;
  keywords: FacetItem[];
  source_organization: FacetItem[];
  srid: FacetItem[];
  collections?: Array<{ id: string; name: string; dataset_count: number }>;
}

export interface DatasetRowsResponse {
  rows: Record<string, unknown>[];
  approximate_total: number;
  next_cursor: number | null;
  columns: { name: string; type: string }[];
}

export interface CatalogStatsResponse {
  total_datasets: number;
  recent_additions: number;
  total_storage_bytes: number | null;
  datasets_by_geometry_type: Record<string, number>;
  datasets_by_visibility: Record<string, number>;
  users_by_status: Record<string, number>;
  total_users: number;
}

export interface UserListResponse {
  users: UserResponse[];
  total: number;
}

export interface AuditLogResponse {
  id: string;
  user_id: string;
  username: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  details: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
}

export interface AuditLogListResponse {
  logs: AuditLogResponse[];
  total: number;
}

export interface AdminJobResponse {
  id: string;
  status: string;
  source_filename: string | null;
  dataset_id: string | null;
  error_message: string | null;
  user_metadata: Record<string, unknown> | null;
  created_by: string | null;
  username: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface AdminJobListResponse {
  jobs: AdminJobResponse[];
  total: number;
}

export interface UploadResponse {
  job_id: string;
  status: string;
  message: string;
}

export interface RegisterRequest {
  table_name: string;
  title: string;
  summary?: string | null;
  visibility?: string;
}

export interface RegisterResponse {
  dataset_id: string;
  title: string;
  table_name: string;
}

export interface JobStatusResponse {
  id: string;
  status: string;
  dataset_id: string | null;
  source_filename: string | null;
  error_message: string | null;
  warning_message: string | null;
  /**
   * S3: structured warnings surfaced from IngestJob.user_metadata so the
   * frontend can render a banner on the upload success screen / dataset
   * detail page. Empty array when the ingest had no warnings.
   */
  warnings: IngestJobWarning[];
  archive_failed: boolean;
  temporal_parse_errors: Partial<
    Record<'temporal_start' | 'temporal_end', string>
  >;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface ApiKeyResponse {
  id: string;
  user_id: string;
  name: string;
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
}

export interface ApiKeyCreateResponse {
  id: string;
  key: string;
  name: string;
  created_at: string;
}

export interface MyApiKeyResponse {
  id: string;
  name: string;
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
}

export interface OAuthProviderPublic {
  slug: string;
  display_name: string;
  provider_type: string;
}

export interface AuthConfigResponse {
  registration_enabled: boolean;
}

export interface MessageResponse {
  message: string;
}

export interface FilePreviewResponse {
  job_id: string;
  source_filename: string | null;
  columns: { name: string; type: string }[];
  crs: number | null;
  geometry_type: GeometryTypeName | null;
  feature_count: number | null;
  sample_rows: Record<string, unknown>[];
  layer_name: string;
  layers?: { name: string; feature_count: number; field_count: number }[] | null;
  detected_geometry_columns?: {
    x_column: string | null;
    y_column: string | null;
    wkt_column: string | null;
  } | null;
}

export interface CommitImportRequest {
  title: string;
  summary?: string | null;
  visibility?: string;
  srid_override?: number | null;
  token?: string;
  temporal_start?: string | null;
  temporal_end?: string | null;
  compression?: string | null;
  resampling?: string | null;
  nodata_override?: number | string | null;
  layer_name?: string;
  x_column?: string | null;
  y_column?: string | null;
  geom_column?: string | null;
}

export interface CommitImportResponse {
  job_id: string;
  status: string;
  message: string;
}

export interface CollectionResponse {
  id: string;
  name: string;
  description: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  dataset_count: number;
  extent_bbox: number[] | null;
  temporal_start: string | null;
  temporal_end: string | null;
}

export interface CollectionListResponse {
  collections: CollectionResponse[];
  total: number;
}

export interface CollectionCreateRequest {
  name: string;
  description?: string | null;
}

export interface CollectionUpdateRequest {
  name?: string | null;
  description?: string | null;
}

export interface CollectionAddDatasetsRequest {
  dataset_ids: string[];
}

export interface SchemaDiff {
  columns_added: Array<{ name: string; type: string }>;
  columns_removed: Array<{ name: string; type: string }>;
  type_changes: Array<{ name: string; old_type: string; new_type: string }>;
  row_count_old: number | null;
  row_count_new: number | null;
  row_count_delta: number;
}

export interface ReuploadResponse {
  job_id: string;
  status: string;
  message: string;
}

export type ReuploadSourceType = 'file' | 'service_url';

export type ReuploadServicePreviewRequest = ServicePreviewRequest;

export interface ReuploadPreviewResponse {
  job_id: string;
  source_filename: string | null;
  columns: Array<{ name: string; type: string }>;
  crs: number | null;
  geometry_type: GeometryTypeName | null;
  feature_count: number | null;
  sample_rows: Record<string, unknown>[];
  layer_name: string;
  schema_diff: SchemaDiff;
  // GPKG-01 Phase 1058: multi-layer support fields
  all_layers?: Array<{ name: string; feature_count: number; field_count: number }> | null;
  previous_source_layer?: string | null;
}

export interface ReuploadCommitResponse {
  job_id: string;
  status: string;
  message: string;
}

export interface ReuploadCommitRequest {
  srid_override?: number | null;
  token?: string;
  // GPKG-01 Phase 1058: user-chosen layer for multi-layer GPKG files
  layer_name?: string;
}

export interface DatasetVersionResponse {
  id: string;
  dataset_id: string;
  version_number: number;
  source_filename: string | null;
  source_format: string | null;
  feature_count: number | null;
  srid: number | null;
  geometry_type: GeometryTypeName | null;
  file_hash: string | null;
  uploaded_by: string | null;
  uploaded_at: string;
}

export interface DatasetVersionListResponse {
  versions: DatasetVersionResponse[];
  total: number;
}

// Labels
export type ZoomExpressionKind = 'step' | 'interpolate';

export type ZoomStepExpression = ['step', ['zoom'], number, ...number[]];

export type ZoomInterpolateExpression = ['interpolate', ['linear'], ['zoom'], ...number[]];

export type ZoomExpression = ZoomStepExpression | ZoomInterpolateExpression;

export interface LabelConfig {
  column: string;
  fontSize?: number | ZoomExpression;
  textColor?: string;
  haloColor?: string;
  haloWidth?: number;
  minZoom?: number;
  maxZoom?: number;
  placement?: 'point' | 'line' | 'line-center';
  textAnchor?: 'center' | 'top' | 'bottom' | 'left' | 'right' | 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right';
  textOpacity?: number | ZoomExpression;
  textOffset?: [number, number];
  allowOverlap?: boolean;
}

// Popups
export interface PopupConfig {
  enabled: boolean;
  expression: string | null;
  visible_fields: string[] | null;
}

// Data-driven styling
export interface BuilderStyleConfig {
  fillDisabled?: boolean;
  strokeDisabled?: boolean;
  fillOpacitySaved?: number;
  outlineWidthSaved?: number;
  outlineColor?: string;
  outlineWidth?: number;
  heatmapRamp?: string;
  heatmapWeightColumn?: string;
  heightColumn?: string;
  /** Multiplier applied to numeric heightColumn values for fill extrusions. */
  heightScale?: number;
  /** Minimum zoom at which the companion fill-extrusion layer is shown. */
  extrusionMinZoom?: number;
  /** Opacity for the companion fill-extrusion layer. Defaults to the layer opacity cap. */
  extrusionOpacity?: number;
  /** Arrow glyph color for line arrow render mode. */
  arrowColor?: string;
  /** Arrow glyph size for line arrow render mode. */
  arrowSize?: number;
  /** Distance between repeated arrow glyphs for line arrow render mode. */
  arrowSpacing?: number;
  /** Point cluster radius in screen pixels for cluster render mode. */
  clusterRadius?: number;
  /** Max zoom at which points are clustered for cluster render mode. */
  clusterMaxZoom?: number;
  /** Cluster circle color for point cluster render mode. */
  clusterColor?: string;
  /** Cluster count label color for point cluster render mode. */
  clusterTextColor?: string;
  /** Cluster count label text size for point cluster render mode. */
  clusterTextSize?: number;
  symbol?: SymbolStyleConfig;
  /** Phase 256 — line-gradient builder intent. Stops authored in the UI; serialized
   *  to a canonical interpolate-linear-line-progress expression for paint['line-gradient'].
   *  Phase 255 engine consumes a non-empty plain object via lineGradientNeededFor() to
   *  emit lineMetrics: true on the backing vector source. */
  lineGradient?: {
    /** Phase 258 POLISH-06: optional per-stop UUID for stable React keys.
     *  Persisted in the JSONB builder shape only; NEVER emitted to the canonical
     *  interpolate-linear-line-progress paint expression (v13.9 GRAD-05/06 byte
     *  identity contract). Legacy stops without `id` are auto-assigned at hydration
     *  inside LineGradientControls. */
    stops: Array<{ position: number; color: string; id?: string }>;
  };
  /** Virtual builder folder-group membership. Stored on real layers; folder rows are reconstructed client-side. */
  folderGroupId?: string;
  folderGroupName?: string;
  folderGroupExpanded?: boolean;
}

export interface SymbolStyleConfig {
  iconImage?: string;
  iconSize?: number;
  iconRotation?: number;
  iconAnchor?: 'center' | 'left' | 'right' | 'top' | 'bottom' | 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right';
  iconOffset?: [number, number];
  categoryColumn?: string;
  categories?: { value: string | number | null; icon: string }[];
}

export interface StyleConfig {
  [key: string]: unknown;
  mode: 'categorical' | 'graduated';
  column: string;
  ramp: string;
  classCount?: number;
  method?: 'equal_interval' | 'quantile';
  categories?: { value: string | number | null; label?: string; color: string }[];
  breaks?: number[];
  colors?: string[];
  /** Styling target — defaults to 'color' when absent for backward compatibility */
  target?: 'color' | 'radius' | 'width';
  /** Per-class size values for graduated size mode (parallel to colors) */
  sizes?: number[];
  /** Optional viewer-facing label for size-driven legends. */
  sizeLabel?: string;
  /** Optional viewer-facing label for color-driven legends. */
  colorLabel?: string;
  /** [min, max] size range selected by the user (for UI state restoration) */
  sizeRange?: [number, number];
  /** Render mode override for specialized adapters. */
  render_mode?: 'heatmap' | 'hillshade' | 'symbol' | 'arrow' | 'cluster';
  /** Symbol/icon layer config for point datasets. */
  symbol?: SymbolStyleConfig;
  /** Heatmap paint config */
  heatmapPaint?: HeatmapLayerSpecification['paint'];
  /** Saved circle paint config from before switching to heatmap mode */
  savedCirclePaint?: CircleLayerSpecification['paint'];
  /** Builder-only UI state that must not be persisted in MapLibre paint. */
  builder?: BuilderStyleConfig;
}

export interface ColumnValuesResponse {
  values: Array<string | number | null>;
  count: number;
}

export interface ColumnStatsResponse {
  min: number | null;
  max: number | null;
  count: number;
  mean: number | null;
  quantiles: number[];
}

// Maps
export type MapVisibility = 'private' | 'internal' | 'public';

export interface MapLayerResponse {
  id: string;
  dataset_id: string;
  dataset_name: string;
  dataset_geometry_type: GeometryTypeName | null;
  dataset_table_name: string;
  dataset_extent_bbox: number[] | null;
  dataset_column_info: { name: string; type: string }[] | null;
  dataset_feature_count: number | null;
  dataset_sample_values: Record<string, unknown[]> | null;
  display_name: string | null;
  sort_order: number;
  visible: boolean;
  opacity: number;
  paint: Record<string, unknown>;
  layout: Record<string, unknown>;
  filter: FilterSpecification | null;
  label_config?: LabelConfig | null;
  popup_config?: PopupConfig | null;
  style_config?: StyleConfig | null;
  layer_type?: MapLayerType | null;
  dataset_record_type?: RecordType | null;
  show_in_legend?: boolean;
  is_3d?: boolean | null;
  is_dem?: boolean | null;
  dem_vertical_units?: string | null;
}

export interface MapResponse {
  id: string;
  name: string;
  description: string | null;
  notes: string | null;
  center_lng: number | null;
  center_lat: number | null;
  zoom: number | null;
  bearing: number;
  pitch: number;
  basemap_style: string;
  show_basemap_labels: boolean;
  basemap_config: MapBasemapConfig | null;
  terrain_config: MapTerrainConfig | null;
  visibility: MapVisibility;
  thumbnail_url: string | null;
  created_by: string | null;
  created_by_username: string | null;
  created_at: string;
  updated_at: string;
  layers: MapLayerResponse[];
  layer_count: number;
  widgets?: string[] | null;
  forked_from_id: string | null;
  forked_from_name: string | null;
}

export interface DuplicateMapResponse extends MapResponse {
  excluded_layer_count: number;
}

export interface MapSummaryResponse {
  id: string;
  name: string;
  description: string | null;
  visibility: MapVisibility;
  thumbnail_url: string | null;
  layer_count: number;
  created_by_username: string | null;
  created_at: string;
  updated_at: string;
}

export interface MapListResponse {
  maps: MapSummaryResponse[];
  total: number;
}

export interface MapHistoryEntryResponse {
  id: string;
  map_id: string;
  actor_id: string | null;
  actor_username: string | null;
  target_type: string;
  target_id: string | null;
  target_name: string | null;
  action: string;
  summary: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface MapHistoryListResponse {
  events: MapHistoryEntryResponse[];
  total: number;
  skip: number;
  limit: number;
}

export interface MapBrowseParams {
  skip?: number;
  limit?: number;
  search?: string;
  sort_by?: string;
  sort_dir?: string;
  visibility?: string;
}

export interface MapCreateRequest {
  name: string;
  description?: string | null;
  basemap_config?: MapBasemapConfig | null;
  terrain_config?: MapTerrainConfig | null;
}

export interface MapUpdateRequest {
  name?: string | null;
  description?: string | null;
  notes?: string | null;
  center_lng?: number | null;
  center_lat?: number | null;
  zoom?: number | null;
  bearing?: number | null;
  pitch?: number | null;
  basemap_style?: string | null;
  show_basemap_labels?: boolean | null;
  basemap_config?: MapBasemapConfig | null;
  terrain_config?: MapTerrainConfig | null;
  visibility?: MapVisibility | null;
  layers?: MapLayerInput[];
  widgets?: string[] | null;
}

export interface MapLayerInput {
  dataset_id: string;
  sort_order?: number;
  visible?: boolean;
  opacity?: number;
  paint?: Record<string, unknown> | null;
  layout?: Record<string, unknown> | null;
  display_name?: string | null;
  filter?: FilterSpecification | null;
  label_config?: LabelConfig | null;
  popup_config?: PopupConfig | null;
  style_config?: StyleConfig | null;
  layer_type?: MapLayerType | null;
  show_in_legend?: boolean;
}

export interface MapLayerPatch {
  id: string;
  sort_order?: number;
  visible?: boolean;
  opacity?: number;
  paint?: Record<string, unknown> | null;
  layout?: Record<string, unknown> | null;
  display_name?: string | null;
  filter?: FilterSpecification | null;
  label_config?: LabelConfig | null;
  popup_config?: PopupConfig | null;
  style_config?: StyleConfig | null;
  layer_type?: MapLayerType | null;
  show_in_legend?: boolean;
}

export interface MapLayerDiffRequest {
  added?: MapLayerInput[];
  updated?: MapLayerPatch[];
  removed?: string[];
  order?: string[] | null;
}

export interface MapStyleImportWarning {
  code: string;
  message: string;
  source_id?: string | null;
  layer_id?: string | null;
}

export interface MapStyleImportSummary {
  sources_matched: number;
  sources_unsupported: number;
  layers_imported: number;
  layers_skipped: number;
  warnings: MapStyleImportWarning[];
}

export interface MapStyleImportResponse {
  map: MapResponse;
  summary: MapStyleImportSummary;
}

export interface MapIconResponse {
  id: string;
  name: string;
  slug: string;
  media_type: string;
  url: string;
  sprite_id: string;
  size_bytes?: number | null;
  builtin: boolean;
}

export interface MapIconListResponse {
  icons: MapIconResponse[];
}

export interface VisibilityCheckResponse {
  non_public_datasets: string[];
  has_non_public: boolean;
}

// Shared / Public Maps
export interface SharedLayerResponse {
  id?: string;
  dataset_id: string;
  dataset_name: string;
  display_name: string | null;
  table_name: string;
  geometry_type: GeometryTypeName | null;
  column_info: { name: string; type: string; semantic_role?: string | null; domain_type?: string | null }[] | null;
  sort_order: number;
  visible: boolean;
  opacity: number;
  paint: Record<string, unknown>;
  layout: Record<string, unknown>;
  filter: FilterSpecification | null;
  label_config: LabelConfig | null;
  popup_config: PopupConfig | null;
  style_config: StyleConfig | null;
  show_in_legend?: boolean;
  layer_type?: MapLayerType;
  dataset_record_type?: RecordType;
  is_dem?: boolean;
  dem_vertical_units?: string | null;
  is_3d?: boolean | null;
  tile_url: string;
  feature_count?: number | null;
}

export interface SharedMapResponse {
  name: string;
  description: string | null;
  center_lng: number;
  center_lat: number;
  zoom: number;
  bearing: number;
  pitch: number;
  basemap_style: string;
  show_basemap_labels?: boolean;
  basemap_config?: MapBasemapConfig | null;
  terrain_config?: MapTerrainConfig | null;
  has_non_public_layers: boolean;
  layers: SharedLayerResponse[];
}

export interface ShareTokenResponse {
  token: string;
  share_url: string | null;
  expires_at: string | null;
  is_active: boolean;
}

// AI Status
export interface AIStatusResponse {
  provider: string | null;
  model: string | null;
  enabled: boolean;
  configured: boolean;
  semantic_search_enabled: boolean;
  has_embeddings: boolean;
}

export interface EmbeddingStatsResponse {
  total_records: number;
  embedded_records: number;
  missing_records: number;
  coverage_percent: number;
}

export interface BackfillResponse {
  processed: number;
  created: number;
  skipped: number;
  errors: number;
}

// AI Map Generation
export interface MapGenerateRequest {
  prompt: string;
  language?: string;
}

export interface MapGenerateResponse {
  map_id: string;
  map_name: string;
  explanation: string;
  datasets_used: string[];
}

// AI Chat (natural language map editing)
export interface ChatMapLayer {
  id: string;
  name: string;
  dataset_id: string;
  dataset_table_name: string;
  geometry_type: GeometryTypeName | null;
  column_info: { name: string; type: string; semantic_role?: string | null; domain_type?: string | null }[] | null;
  visible: boolean;
  filter: FilterSpecification | null;
  label_config: LabelConfig | null;
  popup_config?: PopupConfig | null;
  style_config: StyleConfig | null;
  paint: Record<string, unknown> | null;
  layer_type?: MapLayerType | null;
  dataset_title?: string | null;
  feature_count?: number | null;
  sample_values?: Record<string, unknown[]> | null;
}

export interface ChatHistoryMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatRequest {
  message: string;
  map_id: string;
  layers: ChatMapLayer[];
  language?: string;
  history?: ChatHistoryMessage[];
}

export interface ChatAction {
  type: 'set_filter' | 'set_style' | 'set_data_driven_style' | 'set_label' | 'toggle_visibility' | 'add_layer' | 'remove_layer' | 'show_query_result' | 'set_opacity';
  layer_id?: string;
  expression?: FilterSpecification | null;
  paint?: Record<string, unknown>;
  clear_paint?: string[];
  replace_paint?: boolean;
  style_config?: StyleConfig;
  label_config?: LabelConfig;
  dataset_id?: string;
  visible?: boolean;
  opacity?: number;
  geojson?: GeoJSON.FeatureCollection;
  bbox?: [number, number, number, number];
}

export interface ChatResponse {
  explanation: string;
  actions: ChatAction[];
}

// Service URL import types
export interface LayerInfo {
  name: string;
  title: string | null;
  geometry_type: GeometryTypeName | null;
  feature_count: number | null;
  layer_type: string;
  layer_id: number | string | null;
  object_id_field: string | null;
  /**
   * Backend-classified layer kind. Phase 1057 CLASS-07 D-09 / D-10.
   * Backend (schemas.py LayerInfo) always emits this field with default 'vector'.
   * Classification rule: 'raster' if adapter=STAC, geometry_type contains 'raster',
   * or collection has coverage_format/bands/image/* mediaType. Everything else
   * (including geometry_type=null after D-05 ogrinfo drop) → 'vector'.
   * Consume this field directly instead of re-deriving from geometry_type string.
   */
  kind: 'vector' | 'raster';
}

export interface ProbeResponse {
  service_type: string;
  url: string;
  layers: LayerInfo[];
  selected_layer_id: number | string | null;
}

export interface ServicePreviewRequest {
  url: string;
  service_type: string;
  layer_name: string;
  layer_title: string | null;
  layer_id: number | string | null;
  token?: string;
  object_id_field?: string | null;
}

export interface ServicePreviewResponse {
  job_id: string;
  source_filename: string | null;
  columns: { name: string; type: string }[];
  crs: number | null;
  geometry_type: GeometryTypeName | null;
  feature_count: number | null;
  sample_rows: Record<string, unknown>[];
  layer_name: string;
}

// Bulk upload types
export type FileEntryStatus =
  | 'uploading'
  | 'upload-failed'
  | 'previewing'
  | 'preview'
  | 'committing'
  | 'commit-failed'
  | 'tracking'
  | 'complete'
  | 'failed';

export type BatchPhase = 'idle' | 'uploading' | 'reviewing' | 'tracking';

export interface FileEntry {
  id: string;
  file: File | null;
  fileName: string;
  status: FileEntryStatus;
  jobId: string | null;
  previewData: FilePreviewResponse | RasterPreviewResponse | null;
  error: string | null;
  submittedTitle?: string | null;
  submittedVisibility?: string | null;
  submittedKind?: DataKind | null;
}

/** Canonical data-kind union used by TypeTag, StatusPill, and import utilities */
export type DataKind = 'vector' | 'raster' | 'table' | 'vrt';

// Table discovery types
export interface DiscoveredTable {
  table_name: string;
  geometry_type: GeometryTypeName | null;
  srid: number | null;
  estimated_rows: number | null;
}

export interface DiscoverResponse {
  tables: DiscoveredTable[];
}

export interface BulkRegisterItem {
  table_name: string;
  title: string;
  summary?: string | null;
  visibility?: string;
}

export interface BulkRegisterRequest {
  tables: BulkRegisterItem[];
}

export interface BulkRegisterResult {
  table_name: string;
  status: 'success' | 'error';
  dataset_id?: string | null;
  title?: string | null;
  error?: string | null;
}

export interface BulkRegisterResponse {
  results: BulkRegisterResult[];
}

// Admin share tokens
export interface AdminShareTokenResponse {
  id: string;
  map_id: string;
  map_name: string;
  token: string;
  is_active: boolean;
  expires_at: string | null;
  created_at: string;
  created_by: string | null;
  embed_token_count: number;
}

export interface AdminShareTokenListResponse {
  tokens: AdminShareTokenResponse[];
  total: number;
}

// Embed tokens
export interface EmbedTokenResponse {
  id: string;
  map_id: string;
  name?: string | null;
  scoped_dataset_ids?: string[];
  token_hint: string;
  allowed_origins: string[] | null;
  expires_at: string;
  is_active: boolean;
  use_count: number;
  last_used_at: string | null;
  created_at: string;
}

export interface EmbedTokenCreatedResponse extends EmbedTokenResponse {
  raw_token: string;
}

// Admin embed tokens
export interface AdminEmbedTokenResponse extends EmbedTokenResponse {
  map_name: string | null;
  creator_username: string | null;
}

export interface AdminEmbedTokenListResponse {
  tokens: AdminEmbedTokenResponse[];
  total: number;
}

export interface BulkRevokeResponse {
  revoked_count: number;
}

// Infrastructure
export interface ProviderHealth {
  status: 'ok' | 'error';
  latency_ms: number;
  error?: string;
}

export interface InfrastructureConfig {
  storage_provider: string;
  cache_provider: string;
  database_type: string;
  database_pooler: string;
  tile_cache: string;
  tile_cache_ttl: number;
  cdn_configured: boolean;
}

export interface InfrastructureResponse {
  config: InfrastructureConfig;
  health: Record<string, ProviderHealth>;
  oidc_providers: Record<string, ProviderHealth>;
}

// --- Presigned upload types ---

export interface UploadConfig {
  presigned_uploads: boolean;
  presigned_threshold_bytes: number;
  max_file_size_bytes: number;
  allowed_extensions: string;
}

export interface PresignedUploadRequest {
  filename: string;
  file_size: number;
  content_type?: string;
}

export interface PresignedUploadResponse {
  job_id: string;
  urls: string[];
  s3_key: string;
  upload_id?: string | null;
  part_size?: number | null;
}

export interface PresignedPartInfo {
  etag: string;
  part_number: number;
}

export interface PresignedCompleteRequest {
  parts?: PresignedPartInfo[];
}

export interface VrtCreateRequest {
  source_dataset_ids: string[];
  vrt_type: 'mosaic' | 'band_stack';
  resolution_strategy: 'finest' | 'coarsest' | 'average';
  title: string;
  summary?: string | null;
  visibility?: string;
}

export interface VrtCreateResponse {
  job_id: string;
  status: string;
  message: string;
}

export interface VrtSourceItem {
  dataset_id: string;
  title: string;
  position: number;
  band_count: number | null;
  resolution_x: number | null;
  resolution_y: number | null;
  crs_epsg: number | null;
  extent_bbox: number[] | null;
}

export interface VrtSourceListResponse {
  sources: VrtSourceItem[];
}

export interface VrtMutationResponse {
  job_id: string;
  status: string;
  message: string;
}

export interface VrtSourceHealth {
  dataset_id: string;
  title: string;
  status: 'healthy' | 'missing' | 'inaccessible';
}

export interface VrtActiveGeneration {
  generation_id: string;
  started_at: string;
  elapsed_seconds: number;
}

export interface VrtStatusResponse {
  status: 'ready' | 'regenerating' | 'failed';
  last_generation_at: string | null;
  source_count: number;
  active_generation: VrtActiveGeneration | null;
  source_health: VrtSourceHealth[];
}

export interface VrtGenerationItem {
  id: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  error_message: string | null;
  source_count: number | null;
  triggered_by: string | null;
}

export interface VrtGenerationListResponse {
  generations: VrtGenerationItem[];
  total: number;
}

// STAC import types
export interface StacConnectResponse {
  url: string;
  catalog_id: string;
  title: string;
  description: string;
  stac_version: string;
}

export interface StacCollectionSummary {
  id: string;
  title: string;
  description: string;
  license: string | null;
  keywords: string[];
  bbox: number[] | null;
  temporal_start: string | null;
  temporal_end: string | null;
  item_count: number | null;
}

export interface StacCollectionsResponse {
  url: string;
  collections: StacCollectionSummary[];
}

export interface StacSearchRequest {
  url: string;
  collections?: string[];
  bbox?: number[];
  datetime_range?: string;
  limit?: number;
}

export interface StacItemSummary {
  id: string;
  collection: string | null;
  title: string;
  bbox: number[] | null;
  datetime: string | null;
  datetime_start: string | null;
  datetime_end: string | null;
  epsg: number | null;
  gsd: number | null;
  cloud_cover: number | null;
  data_asset_href: string | null;
  data_asset_type: string | null;
  data_asset_size_bytes: number | null; // EW-05: STAC file:size extension
  thumbnail_href: string | null;
  asset_count: number;
}

export interface StacSearchResponse {
  items: StacItemSummary[];
  matched: number | null;
  returned: number;
}

export interface StacImportItem {
  id: string;
  collection: string | null;
  title: string;
  data_asset_href: string;
  bbox: number[] | null;
  epsg: number | null;
  datetime_start: string | null;
  datetime_end: string | null;
  keywords: string[];
}

export interface StacImportResult {
  item_id: string;
  dataset_id: string | null;
  status: 'created' | 'skipped' | 'error';
  error: string | null;
}

export interface StacImportResponse {
  results: StacImportResult[];
  created: number;
  skipped: number;
  errors: number;
}

export interface DatasetRelationship {
  id: string;
  source_dataset_id: string;
  target_dataset_id: string;
  source_column: string;
  target_column: string;
  relationship_type: string;
  label: string | null;
  target_dataset_title: string | null;
}

/** Response shape for POST /maps/{id}/layers/bulk-delete (Phase 1047-04 PERF-03). */
export interface MapLayerBulkDeleteFailure {
  id: string;
  reason: string;
}

export interface MapLayerBulkDeleteResponse {
  deleted: string[];
  failed: MapLayerBulkDeleteFailure[];
}
