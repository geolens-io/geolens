// GAP-023: ~30 API response types in `src/api/*.ts` are hand-typed mirrors of
// backend Pydantic models with NO codegen and NO compile-time guard. When the
// backend schema changes a field name or its required/optional-ness, the mirror
// silently desyncs — the documented "silent-422 / undefined-field" class.
//
// This is the lightest guard that actually catches that drift: for each cited
// mirror we declare its field shape (required vs optional keys, transcribed from
// the TS interface) and assert it against the corresponding OpenAPI schema in
// the committed `backend/openapi.json` snapshot. A backend rename/add/remove, or
// a required↔optional flip, fails this test until the mirror is updated.
//
// Refresh order when this fails legitimately (a real backend change): regenerate
// the snapshot (`make openapi`), then update the matching descriptor + the
// hand-typed interface in `src/api/*.ts` together.
//
// The committed OpenAPI snapshot is imported as JSON (Vite resolves the path) —
// no node:fs / @types/node dependency in tsconfig.app.json, matching the project
// convention for tests that read repo files.
import openApiDoc from '../../../../backend/openapi.json';

interface MirrorShape {
  /** OpenAPI components.schemas key this mirror tracks. */
  schema: string;
  /** Source mirror (for failure messages). */
  source: string;
  /** Keys the TS interface declares as required (no `?`). */
  required: string[];
  /** Keys the TS interface declares as optional (`?`). */
  optional: string[];
  /**
   * Documented, intentional deviations from the OpenAPI schema. Each entry is a
   * field name that may exist on the mirror but NOT the schema (or vice-versa)
   * for a known reason — recorded here so genuine drift still fails.
   */
  allowExtraOnMirror?: string[];
}

// Field shapes transcribed from the hand-typed mirrors. Keep in sync with the
// interfaces in src/api/*.ts (the whole point is that this must be updated
// deliberately alongside any mirror change).
const MIRRORS: MirrorShape[] = [
  {
    schema: 'MapDefaultsResponse',
    source: 'settings.ts MapDefaults',
    required: ['center_lat', 'center_lng', 'zoom'],
    optional: [],
  },
  {
    schema: 'TileConfigResponse',
    source: 'settings.ts TileConfig',
    required: ['cdn_base_url', 'public_app_url', 'public_api_url', 'public_base_url', 'mvt_source_layer_prefix'],
    optional: [],
  },
  {
    schema: 'SettingItem',
    source: 'settings.ts SettingItem',
    required: ['key', 'value', 'source', 'label'],
    optional: [],
  },
  {
    schema: 'ConfigModeResponse',
    source: 'settings.ts ConfigModeResponse',
    required: ['env_only'],
    optional: [],
  },
  {
    schema: 'FeatureFlagsResponse',
    source: 'settings.ts FeatureFlags',
    required: ['enable_dataset_editing', 'require_metadata_for_publish'],
    optional: [],
  },
  {
    schema: 'ApiKeyStatusResponse',
    source: 'settings.ts ApiKeyStatusResponse',
    required: ['anthropic_configured', 'openai_configured'],
    optional: [],
  },
  {
    schema: 'BasemapPublicResponse',
    source: 'settings.ts BasemapEntry',
    required: ['id', 'label', 'url', 'enabled', 'is_preset'],
    optional: ['attribution'],
    // GAP-023 documented deviation: the mirror keeps an optional `api_key` for
    // the admin shape, but GET /settings/basemaps/ returns BasemapPublicResponse
    // which intentionally EXCLUDES api_key. Allowed extra on the mirror only.
    allowExtraOnMirror: ['api_key'],
  },
  {
    schema: 'VectorTileToken',
    source: 'tiles.ts VectorTileToken',
    required: ['kind', 'sig', 'exp', 'scope', 'expires_in'],
    optional: [],
  },
  {
    schema: 'RasterTileToken',
    source: 'tiles.ts RasterTileToken',
    required: ['kind', 'tile_url', 'bounds', 'minzoom', 'maxzoom', 'tile_size', 'format'],
    optional: [],
  },
  {
    schema: 'RelatedDatasetItem',
    source: 'datasets.ts RelatedDatasetItem',
    // geometry_type/record_type/feature_count/band_count are `T | null` (present
    // but nullable) in TS — required keys, not optional.
    required: ['id', 'name', 'geometry_type', 'similarity', 'record_type', 'feature_count', 'band_count'],
    optional: [],
  },
];

interface OpenApiSchema {
  properties?: Record<string, unknown>;
  required?: string[];
}

function loadSchemas(): Record<string, OpenApiSchema> {
  const doc = openApiDoc as unknown as {
    components?: { schemas?: Record<string, OpenApiSchema> };
  };
  return doc.components?.schemas ?? {};
}

describe('GAP-023: hand-typed API mirrors stay in sync with the OpenAPI snapshot', () => {
  const schemas = loadSchemas();

  it('loaded the OpenAPI snapshot', () => {
    expect(Object.keys(schemas).length).toBeGreaterThan(0);
  });

  it.each(MIRRORS)('$source matches $schema', (mirror) => {
    const schema = schemas[mirror.schema];
    expect(schema, `OpenAPI schema "${mirror.schema}" missing — regenerate the snapshot`).toBeDefined();

    const schemaProps = new Set(Object.keys(schema.properties ?? {}));
    const schemaRequired = new Set(schema.required ?? []);
    const allowExtra = new Set(mirror.allowExtraOnMirror ?? []);

    const mirrorKeys = new Set([...mirror.required, ...mirror.optional]);

    // 1) No field on the schema is missing from the mirror (drift: backend added
    //    a field the frontend doesn't read).
    const missingFromMirror = [...schemaProps].filter((k) => !mirrorKeys.has(k));
    expect(
      missingFromMirror,
      `${mirror.source} is missing fields present on ${mirror.schema}`,
    ).toEqual([]);

    // 2) No field on the mirror is absent from the schema (drift: backend
    //    removed/renamed a field) — except documented intentional extras.
    const extraOnMirror = [...mirrorKeys].filter((k) => !schemaProps.has(k) && !allowExtra.has(k));
    expect(
      extraOnMirror,
      `${mirror.source} declares fields absent from ${mirror.schema}`,
    ).toEqual([]);

    // 3) Catch the DANGEROUS optionality direction only: a field the schema
    //    guarantees (required) but the mirror declares optional (`?`). That is
    //    the silent-undefined seed — the frontend treats an always-present field
    //    as possibly-missing. (The reverse — required in TS, "optional" in the
    //    schema — is just the Pydantic nullable-with-default case: the field is
    //    always present in the response but nullable, which TS models as
    //    `field: T | null` (a required key). That is not drift, so it's not
    //    asserted here.)
    for (const key of mirror.optional) {
      if (allowExtra.has(key) || !schemaProps.has(key)) continue;
      expect(
        schemaRequired.has(key),
        `${mirror.source}.${key} is optional but ${mirror.schema}.${key} is required by the backend`,
      ).toBe(false);
    }
  });
});
