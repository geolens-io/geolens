import type { Geometry } from 'geojson';
import type { FilterSpecification } from 'maplibre-gl';

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
  quicklook_url: string | null;
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

export interface DatasetResponse {
  id: string;
  record_id: string;
  table_name: string;
  title: string;
  summary: string | null;
  srid: number | null;
  geometry_type: string | null;
  feature_count: number | null;
  extent_bbox: number[] | null;
  column_info: { name: string; type: string }[] | null;
  license: string | null;
  source_organization: string | null;
  data_vintage_start: string | null;
  data_vintage_end: string | null;
  source_format: string | null;
  source_filename: string | null;
  original_srid: number | null;
  visibility: string;
  created_by: string | null;
  created_by_display: string;
  created_at: string;
  updated_at: string;
  last_edited_by_display: string | null;
  last_edited_at: string | null;
  record_status: string | null;
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
    geometry_validity: number;
    attribute_completeness: number;
    crs_defined: number;
    computed_at: string;
  } | null;
  record_type: string;
  raster: RasterMetadata | null;
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
  visibility?: string;
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
  record_status?: string;
  owner_org?: string;
  quality_statement?: string;
  source_url?: string;
}

// Record sub-resource types
export interface ContactCreate {
  role: string;
  name?: string | null;
  email?: string | null;
  organization?: string | null;
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
  distribution_type: string;
  format: string;
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
  geometry_type: string | null;
  feature_count: number | null;
  contact: Record<string, unknown> | null;
  license: string | null;
  source_organization: string | null;
  quality_detail?: {
    overall: number;
    metadata_completeness: number;
    geometry_validity: number;
    attribute_completeness: number;
    crs_defined: number;
    computed_at: string;
  } | null;
  record_status?: string | null;
  record_type?: string;
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
}

export interface SearchResponse {
  type: "FeatureCollection";
  numberMatched: number;
  numberReturned: number;
  features: OGCRecordResponse[];
}

export interface CatalogSummary {
  geometry_type?: string[];
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
  geometry_type: string | null;
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
  geometry_type: string | null;
  feature_count: number | null;
  sample_rows: Record<string, unknown>[];
  layer_name: string;
  schema_diff: SchemaDiff;
}

export interface ReuploadCommitResponse {
  job_id: string;
  status: string;
  message: string;
}

export interface ReuploadCommitRequest {
  srid_override?: number | null;
  token?: string;
}

export interface DatasetVersionResponse {
  id: string;
  dataset_id: string;
  version_number: number;
  source_filename: string | null;
  source_format: string | null;
  feature_count: number | null;
  srid: number | null;
  geometry_type: string | null;
  file_hash: string | null;
  uploaded_by: string | null;
  uploaded_at: string;
}

export interface DatasetVersionListResponse {
  versions: DatasetVersionResponse[];
  total: number;
}

// Labels
export interface LabelConfig {
  column: string;
  fontSize?: number;
  textColor?: string;
  haloColor?: string;
  haloWidth?: number;
  minZoom?: number;
  maxZoom?: number;
}

// Data-driven styling
export interface StyleConfig {
  mode: 'categorical' | 'graduated';
  column: string;
  ramp: string;
  classCount?: number;
  method?: 'equal_interval' | 'quantile';
  categories?: { value: string; color: string }[];
  breaks?: number[];
  colors?: string[];
}

export interface ColumnValuesResponse {
  values: string[];
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
  dataset_geometry_type: string | null;
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
  style_config?: StyleConfig | null;
  layer_type?: string | null;
  dataset_record_type?: string | null;
  show_in_legend?: boolean;
}

export interface MapResponse {
  id: string;
  name: string;
  description: string | null;
  center_lng: number | null;
  center_lat: number | null;
  zoom: number | null;
  bearing: number;
  pitch: number;
  basemap_style: string;
  visibility: string;
  thumbnail: string | null;
  created_by: string | null;
  created_by_username: string | null;
  created_at: string;
  updated_at: string;
  layers: MapLayerResponse[];
  layer_count: number;
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
  visibility: string;
  thumbnail: string | null;
  layer_count: number;
  created_by_username: string | null;
  created_at: string;
  updated_at: string;
}

export interface MapListResponse {
  maps: MapSummaryResponse[];
  total: number;
}

export interface MapCreateRequest {
  name: string;
  description?: string | null;
}

export interface MapUpdateRequest {
  name?: string | null;
  description?: string | null;
  center_lng?: number | null;
  center_lat?: number | null;
  zoom?: number | null;
  bearing?: number | null;
  pitch?: number | null;
  basemap_style?: string | null;
  visibility?: string | null;
  layers?: MapLayerInput[];
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
  style_config?: StyleConfig | null;
  layer_type?: string | null;
}

// Shared / Public Maps
export interface SharedLayerResponse {
  dataset_id: string;
  dataset_name: string;
  display_name: string | null;
  table_name: string;
  geometry_type: string | null;
  column_info: { name: string; type: string }[] | null;
  sort_order: number;
  visible: boolean;
  opacity: number;
  paint: Record<string, unknown>;
  layout: Record<string, unknown>;
  filter: FilterSpecification | null;
  label_config?: LabelConfig | null;
  style_config?: StyleConfig | null;
  show_in_legend?: boolean;
  tile_url: string;
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
  has_non_public_layers: boolean;
  layers: SharedLayerResponse[];
}

export interface ShareTokenResponse {
  token: string;
  share_url: string;
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
  geometry_type: string | null;
  column_info: { name: string; type: string }[] | null;
  visible: boolean;
  filter: FilterSpecification | null;
  label_config: LabelConfig | null;
  style_config: StyleConfig | null;
  paint: Record<string, unknown> | null;
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
  style_config?: StyleConfig;
  label_config?: LabelConfig;
  dataset_id?: string;
  visible?: boolean;
  opacity?: number;
  geojson?: Record<string, unknown>;
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
  geometry_type: string | null;
  feature_count: number | null;
  layer_type: string;
  layer_id: number | string | null;
  object_id_field: string | null;
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
  geometry_type: string | null;
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
}

// Table discovery types
export interface DiscoveredTable {
  table_name: string;
  geometry_type: string | null;
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
