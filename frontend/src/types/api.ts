import type { Geometry } from 'geojson';
import type { FilterSpecification, HeatmapLayerSpecification, CircleLayerSpecification } from 'maplibre-gl';
import type { components } from './api.generated';

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

/** Map projection. 'mercator' (default) or experimental 'globe'. */
export type MapProjection = 'mercator' | 'globe';

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
  /** Map projection: 'mercator' (default) or experimental 'globe'.
   *  undefined/null loads as 'mercator'. Persisted jsonb-additive on basemap_config. */
  projection?: MapProjection;
  /** Phase 1059 BSE-01: per-sublayer overrides keyed by semantic sublayer ID.
   *  Opaque key set — see KnownSublayerId for documented IDs. Backed by
   *  MapBasemapConfig.sublayer_overrides jsonb (zero-migration backward compat). */
  sublayer_overrides?: Record<string, MapSublayerOverride> | null;
}

export type TokenResponse = components['schemas']['TokenResponse'];

export type UserQuotaUsage = components['schemas']['UserQuotaUsage'];

export type UserResponse = components['schemas']['UserResponse'];

export type RasterBandInfo = components['schemas']['RasterBandInfo'];

export type RasterConnect = components['schemas']['RasterConnect'];

export type StacAsset = components['schemas']['StacAsset'];

export type PointCloudMetadata = components['schemas']['PointCloudMetadata'];

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
// (catalog/datasets/domain/models.py). Keep in sync if values change.
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
// (catalog/datasets/domain/models.py:35). Keep in sync if values change.
export type DatasetVisibility = 'public' | 'internal' | 'restricted' | 'private';
/** fix(#1183): deliberately NOT a union. Unlike `visibility`, `record_status`
 *  has no CHECK constraint backing it — the values come from the workflow
 *  extension's `status_order()`, so an overlay may define its own. This was
 *  typed `'draft' | 'published'`, which made the two community statuses it
 *  omitted (`ready`, `internal`) a compile error to handle. Community default
 *  order: draft, ready, internal, published. */
export type RecordStatus = string;
export type DistributionType = 'download' | 'ogc_features' | 'vector_tiles';

/** feat(#1218): how the data entered the catalog. Distinct from `record_type`
 *  (what the data is): a vector dataset can be an uploaded file, a registered
 *  PostGIS table, or a copy pulled from a remote service. The backend computes
 *  this from source_format + record_type and serves it as `origin`; OriginBadge
 *  re-exports the type so the rule has one name across the app. */
export type DatasetOrigin = 'upload' | 'postgis' | 'service' | 'stac' | 'created';
/** Reuses the VRT member-probe vocabulary so one legend covers both. NULL in the
 *  database is projected to 'unknown' on the wire — the column stores no such
 *  literal, so there is exactly one way to spell "never determined". */
export type SourceHealth = 'healthy' | 'missing' | 'inaccessible' | 'unknown';
export type SchemaDriftStatus = 'none' | 'drifted' | 'unknown';
/** feat(#1224): how a dataset's last refresh of its SOURCE compares to the
 *  cadence it declares in `update_frequency` — due past one declared period,
 *  overdue past two. Computed server-side on every read, never stored, so there
 *  is no client-side copy of the rule to drift. 'unknown' when the origin
 *  cannot be refreshed at all (`created`), when no cadence is declared
 *  (asNeeded, irregular, notPlanned, unknown), or when nothing has been
 *  refreshed yet. Advisory: it never gates an action.
 *
 *  NOT the same thing as `QualityFreshnessState` in lib/quality-freshness.ts,
 *  which measures the quality score's `computed_at` against the same
 *  `update_frequency` with its own thresholds and its own states
 *  ('fresh' | 'stale' | 'missing'). Both words say freshness; only one is about
 *  the source. Keep the `source` qualifier on every name and label. */
export type SourceFreshness = 'fresh' | 'due' | 'overdue' | 'unknown';

/** Response returned by dataset publication-status mutation endpoints. */
export type StatusUpdateResponse = components['schemas']['StatusUpdateResponse'];

// feat(#1746 B4): structured credential for a protected service, mirroring
// backend `ServiceAuthRequest` (app/platform/service_auth.py). Mutually
// exclusive with the deprecated `token` field on every request that carries
// both — see `reject_service_auth_conflict`. Aliased from the generated
// schema rather than hand-mirrored, since this one is already in the OpenAPI
// snapshot (unlike ArcgisSigninRequest below, which predates its regen).
export type ServiceAuthRequest = components['schemas']['ServiceAuthRequest'];

/** Mirrors backend `DerivedFromResponse` (datasets/domain/schemas.py).
 *
 * fix(#765 review): a named type here too, matching the backend model the
 * SDKs now generate from. `params` stays open because it is the operation's
 * own parameter dict AND is redacted per requester — `visible_derived_from`
 * drops any dataset id the caller cannot see. */
export interface DerivedFrom {
  dataset_id: string;
  /** CQL2-JSON filter that selected the source features; absent when the
   * whole source dataset was used. */
  source_filter?: Record<string, unknown> | null;
  operation: string;
  params: Record<string, unknown>;
  created_at: string;
}

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

export type PreviousVersion = components['schemas']['PreviousVersionResponse'];
export type RestorePreviousVersionResponse =
  components['schemas']['RestorePreviousVersionResponse'];

export type DatasetListResponse = components['schemas']['DatasetListResponse'];

export interface CreateDatasetRequest {
  title: string;
  columns: Array<{ name: string; type: 'text' | 'integer' | 'float' | 'date' | 'boolean' }>;
}

export interface DatasetUpdateRequest {
  title?: string;
  summary?: string;
  visibility?: DatasetVisibility;
  license?: string;
  attribution?: string | null;
  source_organization?: string;
  data_vintage_start?: string | null;
  data_vintage_end?: string | null;
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
// Request body: the generated type marks defaulted fields (`sort_order`) required, but the API accepts omitting them.
export interface ContactCreate {
  role: string;
  name?: string | null;
  email?: string | null;
  organization?: string | null;
  phone?: string | null;
  extra_json?: Record<string, unknown> | null;
  sort_order?: number;
}

export type ContactResponse = components['schemas']['ContactResponse'];

export type ContactListResponse = components['schemas']['ContactListResponse'];

// Request body: the generated type marks defaulted fields (`keyword_type`) required, but the API accepts omitting them.
export interface KeywordCreate {
  keyword: string;
  vocabulary_uri?: string | null;
  keyword_type?: string;
}

export type KeywordResponse = components['schemas']['KeywordResponse'];

export type KeywordListResponse = components['schemas']['KeywordListResponse'];

export type DistributionResponse = components['schemas']['DistributionResponse'];

export type DistributionListResponse = components['schemas']['DistributionListResponse'];

/** feat(#1395): the only field the set-primary control writes. The backend
 * `DistributionUpdate` schema accepts the full row (title/url/etc.), but this
 * UI never edits those — a distribution editor is a separate feature. */
export interface DistributionUpdate {
  is_primary?: boolean;
}

export type AttributeMetadataResponse = components['schemas']['AttributeMetadataResponse'];

export type AttributeMetadataUpdate = components['schemas']['AttributeMetadataUpdate'];

export type AttributeMetadataListResponse = components['schemas']['AttributeMetadataListResponse'];

export type ValidationIssue = components['schemas']['ValidationIssue'];

export type ValidationResultResponse = components['schemas']['ValidationResultResponse'];

export type IngestReservedRenameWarning = components['schemas']['ReservedRenameWarning'];

export type IngestDbfTruncationWarning = components['schemas']['DbfTruncationCollisionWarning'];

export type IngestMercatorClipWarning = components['schemas']['MercatorClipWarning'];

export type IngestJobWarning =
  | IngestReservedRenameWarning
  | IngestDbfTruncationWarning
  | IngestMercatorClipWarning;

// The API declares these as plain strings or open dicts; the frontend narrows them to the shapes it reads.
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

export type OGCRecordLink = components['schemas']['OGCRecordLink'];

// GeoJSON Feature narrowing: the API declares `type` as a string and `geometry` as an open dict.
export type OGCRecordResponse = Omit<
  components['schemas']['OGCRecordResponse'],
  'type' | 'geometry' | 'properties'
> & {
  type: 'Feature';
  geometry: Geometry | null;
  properties: OGCRecordProperties;
};

export interface SearchResponse {
  type: "FeatureCollection";
  numberMatched: number;
  numberMatchedAllTypes?: number | null;
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

export type DatasetRowsResponse = components['schemas']['DatasetRowsResponse'];

export type CatalogStatsResponse = components['schemas']['CatalogStatsResponse'];

export type UserListResponse = components['schemas']['UserListResponse'];

export type AuditLogResponse = components['schemas']['AuditLogResponse'];

export type AuditLogListResponse = components['schemas']['AuditLogListResponse'];

export type AdminJobResponse = components['schemas']['AdminJobResponse'];

export type AdminJobListResponse = components['schemas']['AdminJobListResponse'];

export type UploadResponse = components['schemas']['UploadResponse'];

export type TableRegisterResponse = components['schemas']['TableRegisterResponse'];

export type JobStatusResponse = components['schemas']['JobStatusResponse'];

// feat(#1677): POST /jobs/{id}/cancel. `run_id` is the refresh run the
// cancel finalized when the job had one bound (refreshes/reuploads do;
// plain imports don't); `already` marks the idempotent repeat.
export type JobCancelResponse = components['schemas']['JobCancelResponse'];

/** fix(#875): 'read_only' keys authenticate GET/HEAD/OPTIONS only. */
export type ApiKeyScope = 'full' | 'read_only';

export interface ApiKeyResponse {
  id: string;
  user_id: string;
  name: string;
  fingerprint: string | null;
  is_active: boolean;
  expires_at: string | null;
  scope: ApiKeyScope;
  created_at: string;
  last_used_at: string | null;
}

export type ApiKeyCreateResponse = components['schemas']['ApiKeyCreateResponse'];

export interface MyApiKeyResponse {
  id: string;
  name: string;
  fingerprint: string | null;
  is_active: boolean;
  expires_at: string | null;
  scope: ApiKeyScope;
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
  /** FRONT-01 (Phase 1223): when true the root guard redirects anonymous
   *  visitors from "/" to "/login".  Default false on the server; the
   *  field may be absent on older server versions (treat as false). */
  landing_first?: boolean;
  /** Admin-configured site-wide announcement banner; shown only when
   *  enabled AND text is non-empty (both default off/empty). Color is a
   *  theme token: warning | info | success | destructive (unknown values
   *  fall back to warning). */
  banner_enabled?: boolean;
  banner_text?: string;
  banner_color?: string;
  auth_methods?: string[];
  /** SIGNUP-01 (Phase 1231): when true the login page shows the signup
   *  affordance.  Default false — field may be absent on older server
   *  versions (treat as false). */
  allow_signup?: boolean;
  /** SIGNUP-03/04 (Phase 1231): when true the register flow issues a
   *  verification email and requires email confirmation before login.
   *  Field may be absent on older server versions (treat as false). */
  email_verification_required?: boolean;
  /** SSO-03 (Phase 1236 Plan 02): when false, password login is disabled for
   *  non-admin users and the login page should hide the username/password form.
   *  Absent on older server versions — treat as true (password login available). */
  password_login_enabled?: boolean;
}

export interface MessageResponse {
  message: string;
}

/** Auth register endpoint response (`RegisterResponse` in the OpenAPI schema). */
export interface SignupResponse {
  message: string;
  /** M1 follow-up (Phase 1234): authoritative post-registration step —
   *  'verify_email' when a verification email was sent, else 'await_approval'.
   *  Identical for a new signup and a swallowed collision (enumeration-safety).
   *  Absent on older servers → treat as 'await_approval'. */
  next_step?: 'verify_email' | 'await_approval';
}

// The API declares detected geometry columns as an open dict; the import form reads these three.
export type FilePreviewResponse = Omit<components['schemas']['PreviewResponse'], 'detected_geometry_columns'> & {
  detected_geometry_columns?: {
    x_column: string | null;
    y_column: string | null;
    wkt_column: string | null;
  } | null;
};

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
  strict_cog?: boolean;
  layer_name?: string;
  x_column?: string | null;
  y_column?: string | null;
  geom_column?: string | null;
  // feat(#1746 B4): structured credential, mutually exclusive with `token`
  // above — see `ServiceAuthRequest`.
  auth?: ServiceAuthRequest | null;
}

export interface CommitImportResponse {
  job_id: string;
  status: string;
  message: string;
}

export type CollectionResponse = components['schemas']['CollectionResponse'];

export type CollectionListResponse = components['schemas']['CollectionListResponse'];

export interface CollectionCreateRequest {
  name: string;
  description?: string | null;
}

export interface CollectionUpdateRequest {
  name?: string | null;
  description?: string | null;
}

export type SchemaDiff = components['schemas']['SchemaDiff'];

export type ReuploadResponse = components['schemas']['ReuploadResponse'];

export type ReuploadSourceType = 'file' | 'service_url';

export type ReuploadServicePreviewRequest = components['schemas']['ReuploadServicePreviewRequest'];

export type ReviewReason =
  | 'source_count_unavailable'
  | 'empty_result'
  | 'destructive_schema_change'
  | 'geometry_type_changed'
  | 'srid_changed'
  | 'coordinate_dimension_reduced'
  | 'arcgis_id_coverage_unavailable'
  | 'arcgis_source_membership_changed'
  | 'live_data_changed';

// The API declares `all_layers` entries as open dicts; GeoPackage previews list these fields.
export type ReuploadPreviewResponse = Omit<components['schemas']['ReuploadPreviewResponse'], 'all_layers'> & {
  all_layers?: Array<{ name: string; feature_count: number; field_count: number }> | null;
};

export type ReuploadCommitResponse = components['schemas']['ReuploadCommitResponse'];

export type ReuploadCommitRequest = components['schemas']['ReuploadCommitRequest'];

export type DatasetVersionResponse = components['schemas']['DatasetVersionResponse'];

export type DatasetVersionListResponse = components['schemas']['DatasetVersionListResponse'];

// feat(#1285): the refresh door (#1277/#1313) and its run history
// (GET /datasets/{id}/refresh-runs). Hand-mirrored like the version types
// above rather than aliased from api.generated's `components`, matching this
// file's existing convention for the datasets domain.
// Request body: the generated type marks `verification_policy`, which has a server default, required.
export type DatasetRefreshRequest = Omit<components['schemas']['DatasetRefreshRequest'], 'verification_policy'> & {
  verification_policy?: components['schemas']['DatasetRefreshRequest']['verification_policy'];
};

export type DatasetRefreshResponse = components['schemas']['DatasetRefreshResponse'];

export type DatasetRefreshRunResponse = components['schemas']['DatasetRefreshRunResponse'];

export type DatasetRefreshRunListResponse = components['schemas']['DatasetRefreshRunListResponse'];

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
export type PopupConfig = components['schemas']['PopupConfig'];

// Data-driven styling
export interface BuilderStyleConfig {
  fillDisabled?: boolean;
  strokeDisabled?: boolean;
  fillOpacitySaved?: number;
  /** Solid fill-color stashed while a fill-pattern owns the fill (#910). */
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
  /** ux(#839): show the cluster count label. Absent = true (counts on). */
  clusterShowCounts?: boolean;
  /**
   * Optional cluster color ramp keyed on point_count (cluster render mode).
   * With 2+ stops the cluster circle is colored by a MapLibre `step` expression
   * on point_count (parity with the MapLibre "create and style clusters"
   * example); an empty/absent ramp falls back to the flat clusterColor. Stops
   * are sorted ascending by count — the lowest is the base color, subsequent
   * counts are the step thresholds.
   */
  clusterColorRamp?: Array<{ count: number; color: string }>;
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
  // fix(HT-19): optional — a valid DEM config carries only render_mode (plus
  // builder metadata); requiring the data-driven trio forced `as unknown as`
  // casts that hid the DEM state model from the type checker.
  mode?: 'categorical' | 'graduated';
  column?: string;
  ramp?: string;
  classCount?: number;
  method?: 'equal_interval' | 'quantile' | 'jenks' | 'std_dev' | 'manual';
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
  /**
   * Optional per-entry legend label override (ENH-06). When set, the legend
   * renders this string instead of the layer's display/dataset name. Rides
   * the free-form style_config dict — no backend schema change required.
   */
  legendLabel?: string;
  /** [min, max] size range selected by the user (for UI state restoration) */
  sizeRange?: [number, number];
  /** Whether the color ramp is applied in reverse order (ENH-05). Persisted so legend/map reflect the flip. */
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
  plugins?: string[] | null;
  /** Custom map-level legend title (ENH-06). Null/empty clears it. */
  legend_title?: string | null;
}

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

export type MapStyleImportWarning = components['schemas']['MapStyleImportWarning'];

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
    | { name: string; type: string; title?: string; semantic_role?: string | null; domain_type?: string | null }[]
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
export interface AIProbeCheck {
  configured: boolean;
  ok: boolean | null;
  status?: number | null;
  error?: string | null;
}

export interface AIProbeReport {
  chat: AIProbeCheck;
  embeddings: AIProbeCheck;
}

export interface AIStatusResponse {
  provider: string | null;
  model: string | null;
  enabled: boolean;
  configured: boolean;
  semantic_search_enabled: boolean;
  has_embeddings: boolean;
  // Present only when the request opted in via ?probe=true (#635).
  probe?: AIProbeReport;
}

// fix(#2025): the backfill run in flight, as the admin panel's progress bar
// reads it. records_total is null until the run has selected its records.
export interface BackfillRunProgress {
  job_id: string;
  status: string;
  records_processed: number;
  records_total: number | null;
  started_at: string | null;
  heartbeat_at: string | null;
}

export interface BackfillRunSummary {
  job_id: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  records_processed: number;
  // A finished run with a non-zero figure here left coverage gaps, so the
  // history must not render it as a clean success.
  records_failed: number | null;
  error_code: string | null;
}

// Seconds each action should take at the last completed run's measured rate.
export interface BackfillEstimate {
  missing_seconds: number;
  all_seconds: number;
}

export interface EmbeddingStatsResponse {
  total_records: number;
  // fix(#1503): scoped to the ACTIVE embedding model — the only vectors
  // semantic search can use.
  embedded_records: number;
  missing_records: number;
  // Subset of missing_records holding vectors from superseded models.
  // Cleared by Regenerate All, not by Generate Missing.
  stale_records: number;
  coverage_percent: number;
  current_run: BackfillRunProgress | null;
  recent_runs: BackfillRunSummary[];
  estimate: BackfillEstimate | null;
}

// fix(#1542): the backfill runs on the job queue, so this is an
// acknowledgement, not a result. A full regenerate takes minutes and used to
// hold the request open past the 600s edge timeout. Poll /jobs/{job_id} for
// the run's outcome.
export interface BackfillTenantRun {
  tenant_id: string;
  job_id: string | null;
  status: 'pending' | 'already_running' | 'not_queued';
}

export interface BackfillResponse {
  job_id: string | null;
  status: string;
  other_tenants?: BackfillTenantRun[];
}

// AI Map Generation
export type MapGenerateRequest = components['schemas']['MapGenerateRequest'];

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

/** Dataset-scoped chat: the server resolves all dataset context from the DB. */
export interface DatasetChatRequest {
  message: string;
  dataset_id: string;
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
  /** Optional dataset display name carried on add_layer actions by the backend. */
  dataset_name?: string;
  visible?: boolean;
  opacity?: number;
  geojson?: GeoJSON.FeatureCollection;
  bbox?: [number, number, number, number];
  /**
   * Tabular query result rows from show_query_result actions. Phase 1135 AI-08.
   * Present only when the AI returned structured row data (not a spatial-only result).
   * When present, the inline data-analysis card is rendered inside the assistant bubble.
   * When absent, only the existing geojson+bbox flyover path executes.
   * Rows are arrays of cell values, positionally paired with `columns`.
   */
  rows?: unknown[][];
  /** Column names for the show_query_result inline data table. */
  columns?: string[];
  /** Total matched row count (rows may be truncated for payload size). */
  row_count?: number;
  /** True when `rows` was capped below the full `row_count`. */
  truncated?: boolean;
  /** feat(#675): analysis operation behind a run_analysis preview, carried so
   *  the builder can prefill the Analysis panel ("Save as dataset"). */
  operation?: string;
  /** feat(#675): sanitized buffer distance for the Analysis-panel handoff. */
  distance_meters?: number;
}

export interface ChatResponse {
  explanation: string;
  actions: ChatAction[];
}

// Service URL import types
export type LayerInfo = components['schemas']['LayerInfo'];

export type ProbeResponse = components['schemas']['ProbeResponse'];

export type ServicePreviewRequest = components['schemas']['ServicePreviewRequest'];

// The API declares preview columns as open dicts; they carry a name and a type.
export type ServicePreviewResponse = Omit<components['schemas']['ServicePreviewResponse'], 'columns'> & {
  columns: Array<{ name: string; type: string }>;
};

// fix(service-auth wave, lane A2): hand-typed ahead of the SDK regen. The
// ArcGIS sign-in endpoint (lane A1, POST /services/arcgis/signin/) isn't in
// the OpenAPI snapshot yet; this mirror should be replaced by the generated
// shape in api.generated.ts once that lane merges and `make sdks` runs.
export interface ArcgisSigninRequest {
  portal_url: string;
  username: string;
  password: string;
}

export interface ArcgisSigninResponse {
  token: string;
  expires_at: string;
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

export type BulkRegisterItem = components['schemas']['BulkRegisterItem'];

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
  /** Datasets the user may still create before the count cap; null = unlimited. */
  remaining_dataset_quota: number | null;
}

export type PresignedUploadRequest = components['schemas']['PresignedUploadRequest'];

export type PresignedUploadResponse = components['schemas']['PresignedUploadResponse'];

// Request body: the generated type marks `visibility`, which has a server default, required.
export type VrtCreateRequest = Omit<components['schemas']['VrtCreateRequest'], 'visibility'> & {
  visibility?: components['schemas']['VrtCreateRequest']['visibility'];
};

export type VrtCreateResponse = components['schemas']['VrtCreateResponse'];

export type VrtSourceItem = components['schemas']['VrtSourceItem'];

export type VrtSourceListResponse = components['schemas']['VrtSourceListResponse'];

export type VrtSourceHealth = components['schemas']['VrtSourceHealth'];

export type VrtActiveGeneration = components['schemas']['VrtActiveGeneration'];

export type VrtStatusResponse = components['schemas']['VrtStatusResponse'];

export type VrtGenerationItem = components['schemas']['VrtGenerationItem'];

export type VrtGenerationListResponse = components['schemas']['VrtGenerationListResponse'];

// STAC import types
export interface StacConnectResponse {
  url: string;
  catalog_id: string;
  title: string;
  description: string;
  stac_version: string;
  /** Landing page conformance classes; absent from servers that predate the field. */
  conforms_to?: string[];
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

export interface StacNextPage {
  /** Opaque, server-issued; echo it back unchanged. */
  cursor?: string | null;
}

export interface StacSearchRequest {
  url: string;
  collections?: string[];
  bbox?: number[];
  datetime_range?: string;
  limit?: number;
  /** The previous response's `next_page`, sent with the same filters. */
  next_page?: StacNextPage;
  /** Percent; sent together with `cloud_cover_mode`. */
  max_cloud_cover?: number;
  cloud_cover_mode?: 'query' | 'filter';
  // feat(#1764): a credential for a protected catalog, applied to this call.
  auth?: ServiceAuthRequest;
}

export interface StacItemSummary {
  id: string;
  collection: string | null;
  item_href: string | null;
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
  data_asset_key: string | null;
  data_asset_size_bytes: number | null; // EW-05: STAC file:size extension
  // Why /import would refuse this item's asset by its URL alone, or null if
  // the href passes import's format, length and credential checks (also
  // null when there's no asset at all — check data_asset_href for that).
  // Import separately checks each asset's host and can still refuse a null
  // item there, per item, without failing the rest of the batch. Optional
  // rather than always-present so an older server that predates this field
  // still parses: this app always matches its own API, but the field
  // itself is a newer contract than some servers a client could still hit.
  data_asset_import_refusal?: 'not_http' | 'credentials' | 'too_long' | null;
  thumbnail_href: string | null;
  asset_count: number;
}

export interface StacSearchResponse {
  items: StacItemSummary[];
  matched: number | null;
  returned: number;
  next_page?: StacNextPage | null;
}

export interface StacAssetSizesResponse {
  sizes: { id: string; size_bytes: number | null }[];
}

export interface StacImportItem {
  id: string;
  collection: string | null;
  title: string;
  data_asset_href: string;
  data_asset_key: string | null;
  data_asset_type: string | null;
  item_href: string | null;
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
  broken?: boolean;
}

/** GAP-033: list envelope for GET /datasets/{id}/relationships/. */
export interface DatasetRelationshipListResponse {
  relationships: DatasetRelationship[];
  total: number;
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

/** M4 analysis tools: parameterized PostGIS operations. */
export type AnalysisOperation =
  | 'buffer'
  | 'centroid'
  | 'clip'
  | 'dissolve'
  | 'spatial_join'
  | 'measure'
  | 'select_by_location'
  | 'intersect';

export interface AnalysisPreviewRequest {
  operation: Exclude<AnalysisOperation, 'dissolve'>;
  /** Buffer distance in meters (buffer only). */
  distance_meters?: number;
  /** GeoJSON Polygon/MultiPolygon mask in EPSG:4326 (clip and select_by_location).
   * NOT accepted for intersect, which takes a layer only. */
  mask?: GeoJSON.Polygon | GeoJSON.MultiPolygon;
  /** Polygon dataset supplying the second layer: the area clipped to, selected
   * against, or overlaid with (clip, select_by_location, intersect; the
   * alternative to mask for the first two, and required for intersect). */
  mask_dataset_id?: string;
  /** Layer to join against; each source feature gains a join_count (spatial_join only). */
  join_dataset_id?: string;
  /** Columns copied from the intersecting join feature, prefixed 'join_' (spatial_join only). */
  join_fields?: string[];
  /**
   * [minx, miny, maxx, maxy] in EPSG:4326, typically the map's current
   * viewport. When present, only source features intersecting the envelope
   * are considered before the preview's row cap applies, so a capped result
   * reflects what is on screen rather than an arbitrary sample in ingest
   * order (fix(#727)). Applies to every operation; omit it to preview the
   * whole dataset, unchanged from before this field existed.
   */
  bbox?: number[];
  /** CQL2-JSON filters on the source, mask and join layers. */
  filter?: Record<string, unknown>;
  mask_filter?: Record<string, unknown>;
  join_filter?: Record<string, unknown>;
}

export interface AnalysisPreviewResponse {
  geojson: GeoJSON.FeatureCollection;
  feature_count: number;
  truncated: boolean;
  bbox: number[] | null;
  /**
   * Source dataset total (1:1 ops only; null when the op filters rows, e.g.
   * clip). When the request carried a bbox this is a live count of rows
   * intersecting it rather than the dataset's cached whole-table total
   * (fix(#727)) — also null when that live count could not be computed
   * within the query budget, same as match_count.
   */
  source_feature_count?: number | null;
  /**
   * Exact total across the WHOLE source, not just the previewed features.
   * Null for operations that report no such total, and when the count could
   * not be computed within the query budget.
   *
   * What it counts is per-operation, so read it against the operation you
   * sent rather than treating it as one number:
   * - select_by_location: selected source features. IS the output total.
   * - intersect: output pieces. IS the output total.
   * - spatial_join: intersecting source/join PAIRS. NOT the output total —
   *   the join keeps every source row, so one source row matching four join
   *   rows contributes 4 here and 1 to the result. Use source_feature_count
   *   for that operation's total.
   *
   * "WHOLE source" means the request's bbox when one was sent, same sense
   * source_feature_count uses. intersect and spatial_join both scope this
   * total to a bbox on the request (fix(#727)); select_by_location's count
   * is a separate uncapped query the bbox never reaches, so it stays
   * unscoped even though its preview rows are viewport-limited too.
   */
  match_count?: number | null;
}

export interface AnalysisMaterializeRequest {
  operation: AnalysisOperation;
  title: string;
  distance_meters?: number;
  /** GeoJSON Polygon/MultiPolygon mask in EPSG:4326 (clip and select_by_location).
   * NOT accepted for intersect, which takes a layer only. */
  mask?: GeoJSON.Polygon | GeoJSON.MultiPolygon;
  /** Polygon dataset supplying the second layer: the area clipped to, selected
   * against, or overlaid with (clip, select_by_location, intersect; the
   * alternative to mask for the first two, and required for intersect). */
  mask_dataset_id?: string;
  by_field?: string;
  /** Layer to join against; each source feature gains a join_count (spatial_join only). */
  join_dataset_id?: string;
  /** Columns copied from the intersecting join feature, prefixed 'join_' (spatial_join only). */
  join_fields?: string[];
  /** CQL2-JSON filters on the source, mask and join layers. */
  filter?: Record<string, unknown>;
  mask_filter?: Record<string, unknown>;
  join_filter?: Record<string, unknown>;
}

export interface AnalysisMaterializeResponse {
  job_id: string;
  status: string;
}
