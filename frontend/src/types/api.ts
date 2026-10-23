import type { Geometry } from 'geojson';
import type { FilterSpecification, HeatmapLayerSpecification, CircleLayerSpecification } from 'maplibre-gl';
import type { components } from './api.generated';

/** OGC/PostGIS geometry type values returned by the API. */
export type GeometryTypeName = string;

/** Layer type discriminator for map layers. */
export type MapLayerType = 'vector_geolens' | 'raster_geolens' | 'geojson';

export type MapTerrainConfig = components['schemas']['TerrainConfig'];

export type MapBasemapVisibilityMode = components['schemas']['BasemapSublayerVisibility'];
export type MapBasemapLandWaterTone = components['schemas']['BasemapLandWaterTone'];
export type MapBasemapReliefContrast = components['schemas']['BasemapReliefContrast'];
/** Position of the basemap row in the unified stack.
 *  - 'bottom' (default) — basemap renders below data layers.
 *  - 'top' — basemap renders above data layers; useful for 3D maps showing
 *    elevation through a translucent basemap.
 *  Maps saved without a value load as 'bottom'. */
export type MapBasemapPosition = components['schemas']['BasemapPosition'];

/** Map projection. 'mercator' (default) or experimental 'globe'. */
export type MapProjection = components['schemas']['BasemapProjection'];

/** Per-sublayer style override stored in MapBasemapConfig.sublayer_overrides.
 *  All fields nullable — null means "use basemap default". Color fields must be
 *  #RRGGBB hex when non-null (validated server-side). */
export type MapSublayerOverride = components['schemas']['SublayerOverride'];

// `opacity` has a server default, so a config saved before it existed omits it.
export type MapBasemapConfig = Omit<components['schemas']['BasemapConfig'], 'opacity'> & { opacity?: number };

export type TokenResponse = components['schemas']['TokenResponse'];

export type UserQuotaUsage = components['schemas']['UserQuotaUsage'];

export type UserResponse = components['schemas']['UserResponse'];

export type GroupResponse = components['schemas']['GroupResponse'];
export type GroupListResponse = components['schemas']['GroupListResponse'];
export type GroupRef = components['schemas']['GroupRef'];
export type GroupRefListResponse = components['schemas']['GroupRefListResponse'];
export type DatasetGroupsResponse = components['schemas']['DatasetGroupsResponse'];
export type GroupMemberListResponse = components['schemas']['GroupMemberListResponse'];

/** @public Mirrored by the backend drift checker (backend/scripts/check_fe_type_drift.py). */
export type RasterBandInfo = components['schemas']['RasterBandInfo'];

export type TilesetMetadata = components['schemas']['TilesetMetadata'];

export type RasterMetadata = components['schemas']['RasterMetadata'];

/** What a staged 3D Tiles tileset archive holds, read without unpacking it. */
export type TilesetPreviewResponse = components['schemas']['TilesetPreviewResponse'];
export type PointCloudPreviewResponse = components['schemas']['PointCloudPreviewResponse'];

/** Upload kinds for 3D Tiles archives and COPC point clouds. */
export type UploadKind = NonNullable<components['schemas']['PresignedUploadRequest']['kind']>;
export type UrlUploadKind = NonNullable<components['schemas']['UrlUploadRequest']['kind']>;

export type RasterPreviewResponse = components['schemas']['RasterPreviewResponse'];

// Mirrors backend chk_records_record_type CHECK constraint
// (catalog/datasets/domain/models.py).
export type RecordType =
  | 'vector_dataset'
  | 'raster_dataset'
  | 'vrt_dataset'
  | 'map'
  | 'service'
  | 'collection'
  | 'table'
  | 'tiles3d_dataset'
  | 'pointcloud_dataset';
// Mirrors backend chk_records_visibility CHECK constraint
// (catalog/datasets/domain/models.py).
export type DatasetVisibility = components['schemas']['CommitRequest']['visibility'];
/** How the data entered the catalog. Distinct from `record_type`
 *  (what the data is): a vector dataset can be an uploaded file, a registered
 *  PostGIS table, or a copy pulled from a remote service. The backend computes
 *  this from source_format + record_type and serves it as `origin`; OriginBadge
 *  re-exports the type so the rule has one name across the app. */
export type DatasetOrigin = NonNullable<components['schemas']['ReuploadCommitRequest']['expected_origin_kind']>;
/** Reuses the VRT member-probe vocabulary so one legend covers both. NULL in the
 *  database is projected to 'unknown' on the wire — the column stores no such
 *  literal, so there is exactly one way to spell "never determined". */
export type SourceHealth = 'healthy' | 'missing' | 'inaccessible' | 'unknown';
export type SchemaDriftStatus = 'none' | 'drifted' | 'unknown';
/** How a dataset's last refresh of its SOURCE compares to the cadence it
 *  declares in `update_frequency`: due past one declared period, overdue past
 *  two. Computed server-side on every read. 'unknown' when the origin cannot be
 *  refreshed (`created`), no cadence is declared, or nothing has been refreshed
 *  yet. Advisory: it never gates an action.
 *
 *  Not `QualityFreshnessState` in lib/quality-freshness.ts, which measures the
 *  quality score's `computed_at`. Keep the `source` qualifier on every name. */
export type SourceFreshness = 'fresh' | 'due' | 'overdue' | 'unknown';

/** Response returned by dataset publication-status mutation endpoints. */
export type StatusUpdateResponse = components['schemas']['StatusUpdateResponse'];

// Structured credential for a protected service, mirroring
// backend `ServiceAuthRequest` (app/platform/service_auth.py). Mutually
// exclusive with the deprecated `token` field on every request that carries
// both — see `reject_service_auth_conflict`.
export type ServiceAuthRequest = components['schemas']['ServiceAuthRequest'];

// The API declares these as plain strings; the frontend narrows them to the vocabularies it switches on.
export type DatasetResponse = Omit<
  components['schemas']['DatasetResponse'],
  'visibility' | 'record_type' | 'origin' | 'source_health' | 'schema_drift_status' | 'source_freshness'
> & {
  visibility: DatasetVisibility;
  record_type: RecordType;
  origin?: DatasetOrigin | null;
  source_health: SourceHealth;
  schema_drift_status: SchemaDriftStatus;
  source_freshness: SourceFreshness;
};

export type RestorePreviousVersionResponse =
  components['schemas']['RestorePreviousVersionResponse'];

export type DatasetRetention = components['schemas']['DatasetRetention'];

export type DatasetRetentionResponse = components['schemas']['DatasetRetentionResponse'];

export type DatasetListResponse = components['schemas']['DatasetListResponse'];

export type CreateDatasetRequest = components['schemas']['CreateEmptyDatasetRequest'];

export type DatasetUpdateRequest = components['schemas']['DatasetMeta'];

// Record sub-resource types
// Request body: the generated type marks defaulted fields (`sort_order`) required, but the API accepts omitting them.
export type ContactCreate = Omit<components['schemas']['ContactCreate'], 'sort_order'> & { sort_order?: number };

export type ContactResponse = components['schemas']['ContactResponse'];

export type ContactListResponse = components['schemas']['ContactListResponse'];

// Request body: the generated type marks defaulted fields (`keyword_type`) required, but the API accepts omitting them.
export type KeywordCreate = Omit<components['schemas']['KeywordCreate'], 'keyword_type'> & { keyword_type?: string };

export type KeywordResponse = components['schemas']['KeywordResponse'];

export type KeywordListResponse = components['schemas']['KeywordListResponse'];

export type DistributionResponse = components['schemas']['DistributionResponse'];

export type DistributionListResponse = components['schemas']['DistributionListResponse'];

export type DistributionUpdate = components['schemas']['DistributionUpdate'];

export type AttributeMetadataResponse = components['schemas']['AttributeMetadataResponse'];

export type AttributeMetadataUpdate = components['schemas']['AttributeMetadataUpdate'];

export type AttributeMetadataListResponse = components['schemas']['AttributeMetadataListResponse'];

export type ValidationIssue = components['schemas']['ValidationIssue'];

export type ValidationResultResponse = components['schemas']['ValidationResultResponse'];

type IngestReservedRenameWarning = components['schemas']['ReservedRenameWarning'];

type IngestDbfTruncationWarning = components['schemas']['DbfTruncationCollisionWarning'];

type IngestMercatorClipWarning = components['schemas']['MercatorClipWarning'];

export type IngestJobWarning =
  | IngestReservedRenameWarning
  | IngestDbfTruncationWarning
  | IngestMercatorClipWarning;

// The API declares these as plain strings or open dicts; the frontend narrows them to the shapes it reads.
/** @public Mirrored by the backend drift checker (backend/scripts/check_fe_type_drift.py). */
export type OGCRecordProperties = Omit<
  components['schemas']['OGCRecordProperties'],
  'record_type' | 'source_freshness' | 'source_health' | 'quality_detail' | 'contacts'
> & {
  record_type: RecordType;
  source_freshness: SourceFreshness;
  source_health: SourceHealth;
  quality_detail?: {
    overall: number;
    metadata_completeness: number;
    geometry_validity: number | null;
    attribute_completeness: number | null;
    crs_defined: number | null;
    computed_at: string | null;
  } | null;
  contacts: Array<{ name?: string; organization?: string; roles?: string[]; email?: string; phone?: string }>;
};

// GeoJSON Feature narrowing: the API declares `type` as a string and `geometry` as an open dict.
export type OGCRecordResponse = Omit<
  components['schemas']['OGCRecordResponse'],
  'type' | 'geometry' | 'properties'
> & {
  type: 'Feature';
  geometry: Geometry | null;
  properties: OGCRecordProperties;
};

// GeoJSON FeatureCollection narrowing: the API declares `type` as a string, and the features carry the narrowed record shape.
export type SearchResponse = Omit<components['schemas']['OGCFeatureCollectionResponse'], 'type' | 'features'> & {
  type: 'FeatureCollection';
  features: OGCRecordResponse[];
};

interface CatalogSummary {
  geometry_type?: GeometryTypeName[];
  srid?: number[];
  keywords?: string[];
  source_organization?: string[];
}

// The API declares `summaries` as an open dict; the filter panels read these facets from it.
export type CatalogCollectionResponse = Omit<components['schemas']['OGCCollectionMetadataResponse'], 'summaries'> & {
  summaries?: CatalogSummary | null;
};

export type FacetItem = components['schemas']['FacetValueCount'];

export type FacetResponse = components['schemas']['FacetCountResponse'];

export type DatasetRowsResponse = components['schemas']['DatasetRowsResponse'];

export type CatalogStatsResponse = components['schemas']['CatalogStatsResponse'];

export type UserListResponse = components['schemas']['UserListResponse'];

export type AuditLogResponse = components['schemas']['AuditLogResponse'];

export type AuditLogListResponse = components['schemas']['AuditLogListResponse'];

export type AdminJobResponse = components['schemas']['AdminJobResponse'];

export type AdminJobListResponse = components['schemas']['AdminJobListResponse'];

export type UploadResponse = components['schemas']['UploadResponse'];

export type JobStatusResponse = components['schemas']['JobStatusResponse'];

// POST /jobs/{id}/cancel. `run_id` is the refresh run the
// cancel finalized when the job had one bound (refreshes/reuploads do;
// plain imports don't); `already` marks the idempotent repeat.
export type JobCancelResponse = components['schemas']['JobCancelResponse'];

/**
 * 'read_only' keys authenticate GET/HEAD/OPTIONS only; 'publish' keys also
 * upload and write metadata and maps, but never delete or write features.
 */
export type ApiKeyScope = components['schemas']['ApiKeyCreateRequest']['scope'];

export type ApiKeyResponse = components['schemas']['AdminApiKeyListItem'];

export type ApiKeyCreateResponse = components['schemas']['ApiKeyCreateResponse'];

export type MyApiKeyResponse = components['schemas']['ApiKeyListItem'];

export type DatasetApiKeyResponse = components['schemas']['DatasetApiKeyListItem'];

export type DatasetApiKeyCreateRequest = components['schemas']['DatasetApiKeyCreateRequest'];

export type OAuthProviderPublic = components['schemas']['OAuthProviderPublic'];

// Older servers omit the fields below; the login and register flows default them.
export type AuthConfigResponse = Omit<
  components['schemas']['ConfigResponse'],
  | 'landing_first'
  | 'banner_enabled'
  | 'banner_text'
  | 'banner_color'
  | 'allow_signup'
  | 'email_verification_required'
  | 'password_login_enabled'
> & {
  landing_first?: boolean;
  banner_enabled?: boolean;
  banner_text?: string;
  banner_color?: string;
  allow_signup?: boolean;
  email_verification_required?: boolean;
  password_login_enabled?: boolean;
};

export type MessageResponse = components['schemas']['RegisterResponse'];

export type SignupResponse = components['schemas']['RegisterResponse'];

// The API declares detected geometry columns as an open dict; the import form reads these three.
export type FilePreviewResponse = Omit<components['schemas']['PreviewResponse'], 'detected_geometry_columns'> & {
  detected_geometry_columns?: {
    x_column: string | null;
    y_column: string | null;
    wkt_column: string | null;
  } | null;
};

// Request body: the generated type marks defaulted fields required, and the form keeps `visibility` as a free string.
export type CommitImportRequest = Omit<components['schemas']['CommitRequest'], 'visibility' | 'strict_cog'> & {
  visibility?: string;
  strict_cog?: boolean;
};

export type CommitImportResponse = components['schemas']['CommitResponse'];

export type CollectionResponse = components['schemas']['CollectionResponse'];

export type CollectionListResponse = components['schemas']['CollectionListResponse'];

export type CollectionCreateRequest = components['schemas']['CollectionCreate'];

export type CollectionUpdateRequest = components['schemas']['CollectionUpdate'];

export type SchemaDiff = components['schemas']['SchemaDiff'];

export type ReuploadResponse = components['schemas']['ReuploadResponse'];

export type ReuploadSourceType = 'file' | 'service_url';

export type ReuploadServicePreviewRequest = components['schemas']['ReuploadServicePreviewRequest'];

// The API declares `all_layers` entries as open dicts; GeoPackage previews list these fields.
export type ReuploadPreviewResponse = Omit<components['schemas']['ReuploadPreviewResponse'], 'all_layers'> & {
  all_layers?: Array<{ name: string; feature_count: number; field_count: number }> | null;
};

export type ReuploadCommitResponse = components['schemas']['ReuploadCommitResponse'];

export type ReuploadCommitRequest = components['schemas']['ReuploadCommitRequest'];

export type DatasetVersionResponse = components['schemas']['DatasetVersionResponse'];

export type DatasetVersionListResponse = components['schemas']['DatasetVersionListResponse'];

// Refresh requests and run history (GET /datasets/{id}/refresh-runs).
// Request body: the generated type marks `verification_policy`, which has a server default, required.
export type DatasetRefreshRequest = Omit<components['schemas']['DatasetRefreshRequest'], 'verification_policy'> & {
  verification_policy?: components['schemas']['DatasetRefreshRequest']['verification_policy'];
};

export type DatasetRefreshResponse = components['schemas']['DatasetRefreshResponse'];

export type DatasetRefreshRunResponse = components['schemas']['DatasetRefreshRunResponse'];

export type DatasetRefreshRunListResponse = components['schemas']['DatasetRefreshRunListResponse'];

// Labels
export type ZoomExpressionKind = 'step' | 'interpolate';

type ZoomStepExpression = ['step', ['zoom'], number, ...number[]];

type ZoomInterpolateExpression = ['interpolate', ['linear'], ['zoom'], ...number[]];

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
export type PopupConfig = components['schemas']['PopupConfig'];

// Data-driven styling
export interface BuilderStyleConfig {
  fillDisabled?: boolean;
  strokeDisabled?: boolean;
  fillOpacitySaved?: number;
  /** Solid fill-color stashed while a fill-pattern owns the fill. */
  fillColorSaved?: string;
  outlineWidthSaved?: number;
  outlineColor?: string;
  outlineWidth?: number;
  heatmapRamp?: string;
  /** Heatmap color-ramp direction. Builder-private; true renders the ramp reversed. */
  heatmapReversed?: boolean;
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
  /** Show the cluster count label. Absent = true. */
  clusterShowCounts?: boolean;
  /**
   * Optional cluster color ramp keyed on point_count (cluster render mode).
   * With 2+ stops the cluster circle is colored by a MapLibre `step` expression
   * on point_count; an empty/absent ramp falls back to the flat clusterColor.
   * Stops are sorted ascending by count — the lowest is the base color,
   * subsequent counts are the step thresholds.
   */
  clusterColorRamp?: Array<{ count: number; color: string }>;
  symbol?: SymbolStyleConfig;
  /** Line-gradient builder intent. Stops authored in the UI are serialized to a
   *  canonical interpolate-linear-line-progress expression for paint['line-gradient'].
   *  A non-empty plain object makes lineGradientNeededFor() enable lineMetrics on
   *  the backing vector source. */
  lineGradient?: {
    /** Optional per-stop UUID for stable React keys. Persisted in the JSONB
     *  builder shape only; never emitted to the paint expression. Stops without
     *  `id` are assigned one at hydration. */
    stops: Array<{ position: number; color: string; id?: string }>;
  };
  /** Raster colormap name (single-band). Builder-private; mutates the tile URL via buildColormapTileUrl. */
  colormap?: string;
  /** Raster stretch mode: minmax | percentile | stddev. Builder-private. */
  stretch?: string;
  /** Configurable percentile-low bound for stretch=percentile. */
  pmin?: number;
  /** Configurable percentile-high bound for stretch=percentile. */
  pmax?: number;
  /** Configurable sigma multiplier for stretch=stddev. */
  sigma?: number;
  /** DEM hypsometric (color-relief) tint enabled. Builder-private; read back into paint['_hypso-enabled'] on load. */
  hypso_enabled?: boolean;
  /** DEM hypsometric color-ramp name. Builder-private; read back into paint['_hypso-ramp'] on load. */
  hypso_ramp?: string;
  /** DEM hypsometric ramp direction. Builder-private; read back into paint['_hypso-reversed'] on load. */
  hypso_reversed?: boolean;
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
  // Optional: a valid DEM config carries only render_mode (plus builder metadata).
  mode?: 'categorical' | 'graduated';
  column?: string;
  ramp?: string;
  classCount?: number;
  method?: 'equal_interval' | 'quantile' | 'jenks' | 'std_dev' | 'manual';
  categories?: { value: string | number | null; label?: string; color: string }[];
  breaks?: number[];
  colors?: string[];
  /** Colour of features whose classified value is null (graduated colour mode). */
  nullColor?: string;
  /** Styling target — defaults to 'color' when absent for backward compatibility */
  target?: 'color' | 'radius' | 'width';
  /** Per-class size values for graduated size mode (parallel to colors) */
  sizes?: number[];
  /** Optional viewer-facing label for size-driven legends. */
  sizeLabel?: string;
  /** Optional viewer-facing label for color-driven legends. */
  colorLabel?: string;
  /**
   * Optional per-entry legend label override. When set, the legend renders
   * this string instead of the layer's display/dataset name.
   */
  legendLabel?: string;
  /** [min, max] size range selected by the user (for UI state restoration) */
  sizeRange?: [number, number];
  /** Whether the color ramp is applied in reverse order. Persisted so legend/map reflect the flip. */
  reversed?: boolean;
  /** Render mode override for specialized adapters. */
  render_mode?: 'heatmap' | 'hillshade' | 'symbol' | 'arrow' | 'cluster' | 'terrain' | 'image';
  /** Symbol/icon layer config for point datasets. */
  symbol?: SymbolStyleConfig;
  /** Heatmap paint config */
  heatmapPaint?: HeatmapLayerSpecification['paint'];
  /** Saved circle paint config from before switching to heatmap mode */
  savedCirclePaint?: CircleLayerSpecification['paint'];
  /** Builder-only UI state that must not be persisted in MapLibre paint. */
  builder?: BuilderStyleConfig;
}

export type ColumnValuesResponse = components['schemas']['ColumnValuesResponse'];

export type ColumnStatsResponse = components['schemas']['ColumnStatsResponse'];

// Maps
export type MapVisibility = components['schemas']['MapVisibility'];

// The API declares these as open dicts or strings; the frontend narrows them to the shapes it reads.
export type MapLayerResponse = Omit<
  components['schemas']['MapLayerResponse'],
  | 'dataset_column_info'
  | 'dataset_sample_values'
  | 'filter'
  | 'label_config'
  | 'style_config'
  | 'layer_type'
  | 'dataset_record_type'
> & {
  dataset_column_info?: { name: string; type: string }[] | null;
  dataset_sample_values?: Record<string, unknown[]> | null;
  filter?: FilterSpecification | null;
  label_config?: LabelConfig | null;
  style_config?: StyleConfig | null;
  // Layers the builder synthesizes carry no layer type.
  layer_type?: MapLayerType | null;
  dataset_record_type?: RecordType | null;
};

// The basemap and terrain configs and the layers carry the frontend's narrowed shapes.
export type MapResponse = Omit<components['schemas']['MapResponse'], 'basemap_config' | 'terrain_config' | 'layers'> & {
  basemap_config?: MapBasemapConfig | null;
  terrain_config?: MapTerrainConfig | null;
  layers: MapLayerResponse[];
};

export type DuplicateMapResponse = Omit<
  components['schemas']['DuplicateMapResponse'],
  'basemap_config' | 'terrain_config' | 'layers'
> & {
  basemap_config?: MapBasemapConfig | null;
  terrain_config?: MapTerrainConfig | null;
  layers: MapLayerResponse[];
};

export type MapSummaryResponse = components['schemas']['MapSummaryResponse'];

export type MapListResponse = components['schemas']['MapListResponse'];

export type MapHistoryEntryResponse = components['schemas']['MapHistoryEventResponse'];

export type MapHistoryListResponse = components['schemas']['MapHistoryListResponse'];

export interface MapBrowseParams {
  skip?: number;
  limit?: number;
  search?: string;
  sort_by?: string;
  sort_dir?: string;
  visibility?: string;
  owned_only?: boolean;
}

export type MapCreateRequest = Omit<components['schemas']['MapCreate'], 'basemap_config'> & {
  basemap_config?: MapBasemapConfig | null;
};

export type MapUpdateRequest = Omit<components['schemas']['MapUpdate'], 'basemap_config' | 'layers'> & {
  basemap_config?: MapBasemapConfig | null;
  layers?: MapLayerInput[] | null;
};

// Request body: the generated type marks defaulted fields required, but the API accepts omitting them.
export type MapLayerInput = Omit<
  components['schemas']['MapLayerInput'],
  'sort_order' | 'visible' | 'opacity' | 'show_in_legend' | 'filter' | 'label_config' | 'style_config' | 'layer_type'
> & {
  sort_order?: number;
  visible?: boolean;
  opacity?: number;
  show_in_legend?: boolean;
  filter?: FilterSpecification | null;
  label_config?: LabelConfig | null;
  style_config?: StyleConfig | null;
  layer_type?: MapLayerType | null;
};

export type MapLayerPatch = Omit<
  components['schemas']['MapLayerPatch'],
  'filter' | 'label_config' | 'style_config' | 'layer_type'
> & {
  filter?: FilterSpecification | null;
  label_config?: LabelConfig | null;
  style_config?: StyleConfig | null;
  layer_type?: MapLayerType | null;
};

// Request body: `fallback_full_replace` has a server default, so it may be omitted.
export type MapLayerDiffRequest = Omit<
  components['schemas']['MapLayerDiffRequest'],
  'added' | 'updated' | 'fallback_full_replace'
> & {
  added?: MapLayerInput[];
  updated?: MapLayerPatch[];
  fallback_full_replace?: boolean;
};

export type MapStyleImportSummary = components['schemas']['MapStyleImportSummary'];

export type MapStyleImportResponse = Omit<components['schemas']['MapStyleImportResponse'], 'map'> & { map: MapResponse };

export type MapIconResponse = components['schemas']['MapIconResponse'];

export type MapIconListResponse = components['schemas']['MapIconListResponse'];

export type VisibilityCheckResponse = components['schemas']['VisibilityCheckResponse'];

// Shared / Public Maps
export type SharedLayerResponse = Omit<
  components['schemas']['SharedLayerResponse'],
  'column_info' | 'filter' | 'label_config' | 'style_config' | 'layer_type' | 'dataset_record_type'
> & {
  column_info?:
    | {
        name: string;
        type: string;
        title?: string;
        value_labels?: Record<string, string>;
        semantic_role?: string | null;
        domain_type?: string | null;
      }[]
    | null;
  filter?: FilterSpecification | null;
  label_config?: LabelConfig | null;
  style_config?: StyleConfig | null;
  // The public viewer adapts MapLayerResponse layers, which may lack a layer type.
  layer_type?: MapLayerType;
  dataset_record_type?: RecordType | null;
};

// Payloads from older servers omit `show_basemap_labels`; normalizeSavedMap defaults it.
export type SharedMapResponse = Omit<
  components['schemas']['SharedMapResponse'],
  'show_basemap_labels' | 'basemap_config' | 'terrain_config' | 'layers'
> & {
  show_basemap_labels?: boolean;
  basemap_config?: MapBasemapConfig | null;
  terrain_config?: MapTerrainConfig | null;
  layers: SharedLayerResponse[];
};

export type ShareTokenResponse = components['schemas']['ShareTokenResponse'];

export type MapAccessResponse = components['schemas']['MapAccessResponse'];

// AI Status
export type AIProbeCheck = components['schemas']['AIProbeCheck'];

export type AIProbeReport = components['schemas']['AIProbeReport'];

export type AIStatusResponse = components['schemas']['AIStatusResponse'];

export type EmbeddingStatsResponse = components['schemas']['EmbeddingStatsResponse'];

export type BackfillResponse = components['schemas']['BackfillResponse'];

// AI Map Generation
export type MapGenerateRequest = components['schemas']['MapGenerateRequest'];

// AI Chat (natural language map editing)
// The API declares layer config, filters and column info as open dicts; the frontend keeps the shapes it builds.
export type ChatMapLayer = Omit<
  components['schemas']['ChatMapLayer'],
  'column_info' | 'sample_values' | 'filter' | 'label_config' | 'style_config'
> & {
  column_info?: { name: string; type: string; semantic_role?: string | null; domain_type?: string | null }[] | null;
  sample_values?: Record<string, unknown[]> | null;
  filter?: FilterSpecification | null;
  label_config?: LabelConfig | null;
  style_config?: StyleConfig | null;
};

export type ChatHistoryMessage = components['schemas']['ChatHistoryMessage'];

export type ChatRequest = Omit<components['schemas']['ChatRequest'], 'layers'> & { layers: ChatMapLayer[] };

export type DatasetChatRequest = components['schemas']['DatasetChatRequest'];

// The API declares these as open dicts and lists; the frontend keeps the typed shapes it applies.
export type ChatAction = Omit<
  components['schemas']['ChatAction'],
  'expression' | 'style_config' | 'label_config' | 'geojson' | 'bbox'
> & {
  expression?: FilterSpecification | null;
  style_config?: StyleConfig | null;
  label_config?: LabelConfig | null;
  geojson?: GeoJSON.FeatureCollection | null;
  bbox?: [number, number, number, number] | null;
};

export type ChatResponse = Omit<components['schemas']['ChatResponse'], 'actions'> & { actions: ChatAction[] };

// Service URL import types
export type LayerInfo = components['schemas']['LayerInfo'];

export type ProbeResponse = components['schemas']['ProbeResponse'];

export type ServicePreviewRequest = components['schemas']['ServicePreviewRequest'];

// The API declares preview columns as open dicts; they carry a name and a type.
export type ServicePreviewResponse = Omit<components['schemas']['ServicePreviewResponse'], 'columns'> & {
  columns: Array<{ name: string; type: string }>;
};

export type ArcgisSigninRequest = components['schemas']['ArcGISSignInRequest'];

export type ArcgisSigninResponse = components['schemas']['ArcGISSignInResponse'];

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
  previewData: FilePreviewResponse | RasterPreviewResponse | TilesetPreviewResponse | PointCloudPreviewResponse | null;
  uploadKind?: UploadKind | null;
  error: string | null;
  /** Byte-transfer progress (0–1) during the `uploading` phase; null when unknown/done. */
  progress?: number | null;
  submittedTitle?: string | null;
  submittedVisibility?: string | null;
  submittedKind?: DataKind | null;
  /** The latest commit's request, so a refused commit's review keeps the user's edits. */
  commitRequest?: CommitImportRequest | null;
}

/** Canonical data-kind union used by TypeTag, StatusPill, and import utilities */
export type DataKind = 'vector' | 'raster' | 'table' | 'vrt' | 'tiles3d' | 'pointcloud';

// Table discovery types
export type DiscoveredTable = components['schemas']['DiscoveredTable'];

export type DiscoverResponse = components['schemas']['DiscoverResponse'];

export type BulkRegisterRequest = components['schemas']['BulkRegisterRequest'];

export type BulkRegisterResult = components['schemas']['BulkRegisterResult'];

export type BulkRegisterResponse = components['schemas']['BulkRegisterResponse'];

// Admin share tokens
export type AdminShareTokenResponse = components['schemas']['AdminShareTokenResponse'];

export type AdminShareTokenListResponse = components['schemas']['AdminShareTokenListResponse'];

// Embed tokens
export type EmbedTokenResponse = components['schemas']['EmbedTokenResponse'];

export type EmbedTokenCreatedResponse = components['schemas']['EmbedTokenCreatedResponse'];

// Admin embed tokens
export type AdminEmbedTokenResponse = components['schemas']['AdminEmbedTokenResponse'];

export type AdminEmbedTokenListResponse = components['schemas']['AdminEmbedTokenListResponse'];

export type BulkRevokeResponse = components['schemas']['BulkRevokeResponse'];

// Infrastructure
export type ProviderHealth = components['schemas']['ProviderHealth'];

export type InfrastructureResponse = components['schemas']['InfrastructureResponse'];

// --- Presigned upload types ---

export type UploadConfig = components['schemas']['UploadConfigResponse'];

export type PresignedUploadResponse = components['schemas']['PresignedUploadResponse'];

// Request body: the generated type marks `visibility`, which has a server default, required.
export type VrtCreateRequest = Omit<components['schemas']['VrtCreateRequest'], 'visibility'> & {
  visibility?: components['schemas']['VrtCreateRequest']['visibility'];
};

export type VrtCreateResponse = components['schemas']['VrtCreateResponse'];

export type VrtSourceListResponse = components['schemas']['VrtSourceListResponse'];

export type VrtSourceHealth = components['schemas']['VrtSourceHealth'];

export type VrtStatusResponse = components['schemas']['VrtStatusResponse'];

export type VrtGenerationListResponse = components['schemas']['VrtGenerationListResponse'];

// STAC import types
export type StacConnectResponse = components['schemas']['StacConnectResponse'];

export type StacCollectionSummary = components['schemas']['StacCollectionSummary'];

export type StacCollectionsResponse = components['schemas']['StacCollectionsResponse'];

export type StacNextPage = components['schemas']['StacNextPage'];

// Request body: `limit` has a server default, so it may be omitted.
export type StacSearchRequest = Omit<components['schemas']['StacSearchRequest'], 'limit'> & { limit?: number };

export type StacItemSummary = components['schemas']['StacItemSummary'];

export type StacSearchResponse = components['schemas']['StacSearchResponse'];

export type StacAssetSizesResponse = components['schemas']['StacAssetSizesResponse'];

export type StacImportItem = components['schemas']['StacImportItem'];

export type StacImportResult = components['schemas']['StacImportResult'];

export type StacImportResponse = components['schemas']['StacImportResponse'];

export type DatasetRelationship = components['schemas']['DatasetRelationshipResponse'];

export type DatasetRelationshipListResponse = components['schemas']['DatasetRelationshipListResponse'];

export type MapLayerBulkDeleteResponse = components['schemas']['BulkDeleteLayersResponse'];

/** M4 analysis tools: parameterized PostGIS operations. */
export type AnalysisOperation = components['schemas']['AnalysisMaterializeRequest']['operation'];

// The API declares the mask as an open dict; it is a GeoJSON polygon.
export type AnalysisPreviewRequest = Omit<components['schemas']['AnalysisPreviewRequest'], 'mask'> & {
  mask?: GeoJSON.Polygon | GeoJSON.MultiPolygon | null;
};

// The API declares the preview as an open dict; it is a GeoJSON feature collection.
export type AnalysisPreviewResponse = Omit<components['schemas']['AnalysisPreviewResponse'], 'geojson'> & {
  geojson: GeoJSON.FeatureCollection;
};

// The API declares the mask as an open dict; it is a GeoJSON polygon.
export type AnalysisMaterializeRequest = Omit<components['schemas']['AnalysisMaterializeRequest'], 'mask'> & {
  mask?: GeoJSON.Polygon | GeoJSON.MultiPolygon | null;
};

export type AnalysisMaterializeResponse = components['schemas']['AnalysisMaterializeResponse'];
