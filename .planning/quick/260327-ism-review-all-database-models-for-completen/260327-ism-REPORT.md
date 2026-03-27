# GeoLens Database Model Review

**Date:** 2026-03-27
**Scope:** 32 models across 11 modules (initial research counted 31; DatasetAsset confirmed as an additional model)
**Sources reviewed:**
- All model files: `backend/app/*/models.py` and `backend/app/search/saved.py`
- All Alembic migrations: `backend/alembic/versions/0001–0010` and `initial_schema.sql`
- Primary service and router files for query pattern verification

**Methodology:** Direct source reading of every model file, cross-reference against migration-generated schema constraints and indexes, query pattern analysis across service/router files. Each research finding verified against current source; additional pass performed to surface issues not in the original research.

---

## Executive Summary

The GeoLens schema is fundamentally sound. UUID primary keys, timezone-aware timestamps, proper cascade/set-null semantics, and a well-structured RBAC model are all in place and consistent. Recent migrations (0004, 0005) added important performance indexes and schema corrections.

The primary areas for improvement are:

1. **Missing FK indexes on high-traffic columns** — `api_keys.user_id`, `ingest_jobs.created_by`, `maps.created_by`, `records.created_at` (sort), and `records.source_organization` (facet filter) have no btree indexes. These are hit on every authenticated request or catalog search.

2. **Model/migration drift (accumulating)** — Seven constraints exist in the database (from `initial_schema.sql`) but are absent from the SQLAlchemy model definitions. Alembic autogenerate will attempt to drop them on the next `--autogenerate` run. Two unique constraints in models reference constraint names that do not appear in `__table_args__`. Two model check constraints have value sets that diverge from the schema.

3. **Missing check constraints in models** — Several status/type columns that are constrained at the DB level are not reflected in model `__table_args__`, meaning the Python layer offers no documentation or autogenerate-safe representation of the constraint.

### Summary Statistics

| Severity | Count |
|----------|-------|
| Critical | 0     |
| High     | 9     |
| Medium   | 15    |
| Low      | 7     |
| **Total**| **31**|

---

## Model Inventory

| #  | Module          | Model               | Table                    | PK        | Key Relationships                                    |
|----|-----------------|---------------------|--------------------------|-----------|------------------------------------------------------|
| 1  | datasets        | Record              | records                  | UUID      | -> User (created_by, updated_by)                     |
| 2  | datasets        | Dataset             | datasets                 | UUID      | -> Record (1:1 via record_id)                        |
| 3  | datasets        | RecordContact       | record_contacts          | UUID      | -> Record                                            |
| 4  | datasets        | RecordKeyword       | record_keywords          | UUID      | -> Record                                            |
| 5  | datasets        | RecordDistribution  | record_distributions     | UUID      | -> Record                                            |
| 6  | datasets        | AttributeMetadata   | attribute_metadata       | UUID      | -> Dataset                                           |
| 7  | datasets        | DatasetGrant        | dataset_grants           | composite | -> Dataset + Role                                    |
| 8  | datasets        | DatasetRelationship | dataset_relationships    | UUID      | -> Record (source + target)                          |
| 9  | auth            | User                | users                    | UUID      | <-> Role (M2M via user_roles)                        |
| 10 | auth            | Role                | roles                    | UUID      | <-> User (M2M)                                       |
| 11 | auth            | UserRole            | user_roles               | composite | -> User + Role                                       |
| 12 | auth            | ApiKey              | api_keys                 | UUID      | -> User                                              |
| 13 | auth            | RefreshToken        | refresh_tokens           | UUID      | -> User                                              |
| 14 | auth/oauth      | OAuthProvider       | oauth_providers          | UUID      | standalone (SAML columns added in migration 0010)    |
| 15 | auth/oauth      | OAuthAccount        | oauth_accounts           | UUID      | -> OAuthProvider + User                              |
| 16 | collections     | Collection          | collections              | UUID      | -> User (created_by)                                 |
| 17 | collections     | CollectionDataset   | collection_datasets      | composite | -> Collection + Dataset                              |
| 18 | collections     | DatasetVersion      | dataset_versions         | UUID      | -> Dataset + User                                    |
| 19 | maps            | Map                 | maps                     | UUID      | -> User (created_by), self-ref (forked_from)         |
| 20 | maps            | MapLayer            | map_layers               | UUID      | -> Map + Dataset                                     |
| 21 | maps            | MapShareToken       | map_share_tokens         | UUID      | -> Map + User                                        |
| 22 | raster          | RasterAsset         | raster_assets            | UUID      | -> Dataset (1:1); VRT tracking fields added          |
| 23 | raster          | VrtGeneration       | vrt_generations          | UUID      | -> Dataset                                           |
| 24 | raster          | VrtSourceLink       | vrt_source_links         | UUID      | -> Dataset (vrt + source), both FK cols indexed      |
| 25 | raster          | DatasetAsset        | dataset_assets           | UUID      | -> Dataset; STAC asset key/href table                |
| 26 | jobs            | IngestJob           | ingest_jobs              | UUID      | -> Dataset + User                                    |
| 27 | audit           | AuditLog            | audit_logs               | UUID      | -> User                                              |
| 28 | embed_tokens    | EmbedToken          | embed_tokens             | UUID      | -> Map + User                                        |
| 29 | embeddings      | RecordEmbedding     | record_embeddings        | UUID      | -> Record                                            |
| 30 | settings        | AppSetting          | app_settings             | Text key  | standalone KV                                        |
| 31 | search          | SavedSearch         | saved_searches           | UUID      | -> User                                              |
| 32 | raster          | DatasetAsset        | dataset_assets           | UUID      | -> Dataset; added after initial research (32nd model)|

---

## Findings by Severity

### HIGH — Missing Indexes on Frequently Queried FK Columns

#### H1 — `api_keys.user_id` has no index

**Affected:** `ApiKey` — `backend/app/auth/models.py:71`
**Table:** `catalog.api_keys`

The `user_id` FK column is used in auth resolution on every API-key-authenticated request (`ApiKey.user_id == current_user.id`), in admin listing, and in bulk deletion (`delete(ApiKey).where(ApiKey.user_id == user_id)`). No btree index exists in any migration. The `ix_refresh_tokens_user_id` index exists for RefreshToken but no equivalent exists for ApiKey.

**Impact:** Every API key resolution performs a sequential scan on `api_keys` filtered by `user_id`. Tables stay small in practice but the scan cost adds up on services with high API key usage volume.

**Recommendation:**

```sql
CREATE INDEX idx_api_keys_user_id ON catalog.api_keys (user_id);
```

Or in Alembic:
```python
op.create_index("idx_api_keys_user_id", "api_keys", ["user_id"], schema="catalog")
```

**Effort:** Trivial

---

#### H2 — `ingest_jobs.created_by` has no index

**Affected:** `IngestJob` — `backend/app/jobs/models.py:11`
**Table:** `catalog.ingest_jobs`

Filtered in admin job listing (`IngestJob.created_by == user_id`) at `backend/app/admin/router.py:316` and joined to users at line 330. No index exists despite `idx_ingest_jobs_status` being present (added in migration 0004).

**Impact:** Admin job list queries that filter by user require a full table scan. Low impact now but grows linearly with job volume.

**Recommendation:**

```sql
CREATE INDEX idx_ingest_jobs_created_by ON catalog.ingest_jobs (created_by);
```

**Effort:** Trivial

---

#### H3 — `maps.created_by` has no index

**Affected:** `Map` — `backend/app/maps/models.py:47`
**Table:** `catalog.maps`

The primary access pattern for maps is ownership-based: `Map.created_by == user_id` appears at `backend/app/maps/service.py:174, 414, 989` (at minimum). No btree index on `created_by` exists despite `idx_maps_visibility` and `idx_maps_created_at_desc` both being present (migration 0004). Map listing and visibility checks both filter on this column.

**Impact:** Every map listing query requires a heap scan on `maps` filtered by `created_by`. As user map counts grow, this becomes the dominant cost in the maps service.

**Recommendation:**

```sql
CREATE INDEX idx_maps_created_by ON catalog.maps (created_by);
```

**Effort:** Trivial

---

#### H4 — `records.created_at` has no descending index

**Affected:** `Record` — `backend/app/datasets/models.py:120`
**Table:** `catalog.records`

The primary sort column for record listing and search results is `Record.created_at.desc()`, used at `backend/app/datasets/service.py:273` and `backend/app/search/service.py:858, 876`. The composite index `idx_records_visibility_status_creator` helps with WHERE clauses but does not cover the ORDER BY on `created_at`. Every catalog browse that pages results hits this sort path.

**Impact:** Sort on unindexed `created_at DESC` requires a filesort after the WHERE filter. At scale this adds significant query time for paginated catalog browsing.

**Recommendation:**

```sql
CREATE INDEX idx_records_created_at_desc ON catalog.records (created_at DESC);
```

**Effort:** Trivial

---

#### H5 — `records.source_organization` has no index

**Affected:** `Record` — `backend/app/datasets/models.py:72`
**Table:** `catalog.records`

Used as a facet filter (`Record.source_organization == source_organization`) and in DISTINCT aggregation for facet counts. Referenced at `backend/app/search/service.py:285, 448, 726` and in the OGC facets endpoint at `backend/app/search/router.py:705–709`. This is a high-selectivity equality filter.

**Impact:** Every search with an org filter performs a heap scan. Facet count aggregations are particularly costly without an index on this column.

**Recommendation:**

```sql
CREATE INDEX idx_records_source_organization
    ON catalog.records (source_organization)
    WHERE source_organization IS NOT NULL;
```

**Effort:** Trivial

---

### HIGH — Model/Migration Drift (Unique Constraints Missing from Models)

#### H6 — `SavedSearch` model missing `UniqueConstraint` for `(user_id, name)`

**Affected:** `SavedSearch` — `backend/app/search/saved.py:15–32`
**Table:** `catalog.saved_searches`

The migration creates `uq_saved_searches_user_name UNIQUE (user_id, name)` (initial_schema.sql:1724). The upsert in `create_saved_search()` at line 50 explicitly names this constraint: `on_conflict_do_update(constraint="uq_saved_searches_user_name", ...)`. The model's `__table_args__` contains only `{"schema": "catalog"}` — no `UniqueConstraint` declaration.

**Impact:**
- Alembic autogenerate will generate a migration to drop `uq_saved_searches_user_name`, which would break the upsert operation.
- The business rule (one saved search per user per name) is not documented in the model.

**Recommendation:**

```python
__table_args__ = (
    UniqueConstraint("user_id", "name", name="uq_saved_searches_user_name"),
    {"schema": "catalog"},
)
```

**Effort:** Trivial

---

#### H7 — `DatasetVersion` model missing `UniqueConstraint` for `(dataset_id, version_number)`

**Affected:** `DatasetVersion` — `backend/app/collections/models.py:49–71`
**Table:** `catalog.dataset_versions`

The migration creates `uq_dataset_version UNIQUE (dataset_id, version_number)` (initial_schema.sql:1684). The model's `__table_args__` is only `{"schema": "catalog"}`.

**Impact:** Same autogenerate risk as H6. Without the `UniqueConstraint` in the model, Alembic may generate a DROP CONSTRAINT migration on next autogenerate run.

**Recommendation:**

```python
__table_args__ = (
    UniqueConstraint("dataset_id", "version_number", name="uq_dataset_version"),
    {"schema": "catalog"},
)
```

**Effort:** Trivial

---

#### H8 — `RasterAsset` model missing `chk_raster_assets_status` and `chk_raster_assets_vrt_type`

**Affected:** `RasterAsset` — `backend/app/raster/models.py:11`
**Table:** `catalog.raster_assets`

The initial_schema.sql defines two check constraints on `raster_assets`:
- `chk_raster_assets_status`: enforces `status IN ('ready', 'regenerating', 'failed')`
- `chk_raster_assets_vrt_type`: enforces `vrt_type IS NULL OR vrt_type IN ('mosaic', 'band_stack')`

Neither appears in the `RasterAsset` model's `__table_args__`. The current `__table_args__` only declares `UniqueConstraint("dataset_id", ...)`.

**Impact:** Same autogenerate risk pattern as H6/H7. Alembic will attempt to drop both constraints on the next `--autogenerate` run. Additionally, the application has no Python-level documentation of the valid status values (important given the VRT rebuild workflow has at least three states).

**Recommendation:**

```python
__table_args__ = (
    UniqueConstraint("dataset_id", name="uq_raster_assets_dataset"),
    CheckConstraint(
        "status IN ('ready', 'regenerating', 'failed')",
        name="chk_raster_assets_status",
    ),
    CheckConstraint(
        "vrt_type IS NULL OR vrt_type IN ('mosaic', 'band_stack')",
        name="chk_raster_assets_vrt_type",
    ),
    {"schema": "catalog"},
)
```

**Effort:** Small

---

#### H9 — `chk_records_record_type` value set diverges between model and schema

**Affected:** `Record` — `backend/app/datasets/models.py:28`
**Table:** `catalog.records`

The model's `chk_records_record_type` check constraint includes `'table'` as a valid value:
```
record_type IN ('vector_dataset', 'raster_dataset', 'vrt_dataset', 'map', 'service', 'collection', 'table')
```

The initial_schema.sql check constraint does NOT include `'table'`:
```
record_type IN ('vector_dataset', 'raster_dataset', 'vrt_dataset', 'map', 'service', 'collection')
```

There is no migration in 0001–0010 that alters this constraint. This means either: (a) `'table'` was added to the model but a migration was never written to update the DB constraint, or (b) the initial_schema.sql is outdated and `'table'` records can be inserted but will fail the DB check constraint in a freshly initialized schema.

**Impact:** If `'table'` is a live record type in production, any attempt to insert a `record_type='table'` row in a freshly initialized environment will raise a `CheckViolationError`. If the constraint was updated in the DB directly (outside of migration), autogenerate will detect the drift and generate a conflicting migration.

**Recommendation:** Write a migration to alter the check constraint to include `'table'`:

```python
op.execute("""
    ALTER TABLE catalog.records DROP CONSTRAINT chk_records_record_type;
    ALTER TABLE catalog.records ADD CONSTRAINT chk_records_record_type
        CHECK (record_type IN (
            'vector_dataset', 'raster_dataset', 'vrt_dataset',
            'map', 'service', 'collection', 'table'
        ));
""")
```

**Effort:** Small

---

### MEDIUM — Missing Check Constraints in Models

#### M1 — `Map.visibility` has no CHECK constraint

**Affected:** `Map` — `backend/app/maps/models.py:34`
**Table:** `catalog.maps`

`Map.visibility` is `Text` with a Python default of `"private"` but no `CheckConstraint` in `__table_args__` and no constraint in the migration. The `MapVisibility` enum in schemas.py defines `private`, `public`, `unlisted` but nothing enforces this at the DB level.

**Recommendation:**

```python
CheckConstraint(
    "visibility IN ('private', 'public', 'unlisted')",
    name="chk_maps_visibility",
)
```

**Effort:** Small

---

#### M2 — `IngestJob.status` has no CHECK constraint

**Affected:** `IngestJob` — `backend/app/jobs/models.py:21`
**Table:** `catalog.ingest_jobs`

`status` is `String(20)` with a server_default of `"pending"` but no `CheckConstraint`. Known values from code: `pending`, `running`, `completed`, `failed`, `cancelled`.

**Recommendation:**

```python
CheckConstraint(
    "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
    name="chk_ingest_jobs_status",
)
```

**Effort:** Small

---

#### M3 — `User.status` has no CHECK constraint

**Affected:** `User` — `backend/app/auth/models.py:20`
**Table:** `catalog.users`

`status` is `String(20)` with `server_default="active"`. The partial index `idx_users_status_pending` implies at least `active` and `pending` as known values. No CHECK constraint in model or migration.

**Recommendation:**

```python
CheckConstraint(
    "status IN ('active', 'pending', 'suspended', 'deactivated')",
    name="chk_users_status",
)
```

**Effort:** Small

---

#### M4 — `User.auth_provider` has no CHECK constraint

**Affected:** `User` — `backend/app/auth/models.py:26`
**Table:** `catalog.users`

`auth_provider` is `String(20)` with `server_default="local"`. Known values: `local`, `oidc`, `saml`. No CHECK in model or migration.

**Recommendation:**

```python
CheckConstraint(
    "auth_provider IN ('local', 'oidc', 'saml')",
    name="chk_users_auth_provider",
)
```

**Effort:** Small

---

#### M5 — `RasterAsset.cog_status` has no CHECK constraint

**Affected:** `RasterAsset` — `backend/app/raster/models.py:50`
**Table:** `catalog.raster_assets`

`cog_status` is `String(20), nullable=True`. Known values from the COG compliance code: `compliant`, `non_compliant`, `unknown`. No CHECK constraint in model or schema (unlike `status` which has `chk_raster_assets_status` in the DB).

**Recommendation:**

```python
CheckConstraint(
    "cog_status IS NULL OR cog_status IN ('compliant', 'non_compliant', 'unknown')",
    name="chk_raster_assets_cog_status",
)
```

Add this constraint to both the model `__table_args__` and a new migration.

**Effort:** Small

---

#### M6 — `VrtGeneration.status` has no CHECK constraint

**Affected:** `VrtGeneration` — `backend/app/raster/models.py:95`
**Table:** `catalog.vrt_generations`

`status` is `String(20)` with `server_default="pending"`. Known values: `pending`, `running`, `completed`, `failed`. Index `ix_vrt_generations_status` exists in migration but no CHECK.

**Recommendation:**

```python
CheckConstraint(
    "status IN ('pending', 'running', 'completed', 'failed')",
    name="chk_vrt_generations_status",
)
```

**Effort:** Small

---

#### M7 — `OAuthProvider.provider_type` has no CHECK constraint

**Affected:** `OAuthProvider` — `backend/app/auth/oauth/models.py:32`
**Table:** `catalog.oauth_providers`

`provider_type` is `String(20)` with no CHECK. Known values from code: `oidc`, `google`, `microsoft`, `saml`. No CHECK in model or migration.

**Recommendation:**

```python
CheckConstraint(
    "provider_type IN ('oidc', 'google', 'microsoft', 'saml')",
    name="chk_oauth_providers_type",
)
```

**Effort:** Small

---

#### M8 — `RecordContact` model missing `chk_contact_role` that exists in DB

**Affected:** `RecordContact` — `backend/app/datasets/models.py:244`
**Table:** `catalog.record_contacts`

The initial_schema.sql defines `chk_contact_role` enforcing ISO 19115 role values: `resourceProvider`, `custodian`, `owner`, `user`, `distributor`, `originator`, `pointOfContact`, `principalInvestigator`, `processor`, `publisher`, `author`, `sponsor`, `coAuthor`, `collaborator`, `editor`, `mediator`, `rightsHolder`, `contributor`, `funder`, `stakeholder`.

The `RecordContact` model's `__table_args__` is only `{"schema": "catalog"}` — no `CheckConstraint` is declared.

**Impact:** Same autogenerate risk as H6/H7/H8. Alembic will try to drop the constraint. Inserting contacts with non-standard ISO roles would silently pass at the application layer but fail at the DB layer, producing confusing `CheckViolationError`s.

**Recommendation:**

```python
__table_args__ = (
    CheckConstraint(
        "role IN ('resourceProvider', 'custodian', 'owner', 'user', 'distributor', "
        "'originator', 'pointOfContact', 'principalInvestigator', 'processor', "
        "'publisher', 'author', 'sponsor', 'coAuthor', 'collaborator', 'editor', "
        "'mediator', 'rightsHolder', 'contributor', 'funder', 'stakeholder')",
        name="chk_contact_role",
    ),
    {"schema": "catalog"},
)
```

**Effort:** Small

---

#### M9 — `RecordKeyword` model missing `chk_keyword_type` that exists in DB

**Affected:** `RecordKeyword` — `backend/app/datasets/models.py:267`
**Table:** `catalog.record_keywords`

The initial_schema.sql defines `chk_keyword_type` enforcing ISO 19115 keyword type values: `discipline`, `place`, `stratum`, `temporal`, `theme`, `dataCentre`, `featureType`, `instrument`, `platform`, `process`, `product`, `project`, `service`, `subTopicCategory`, `taxon`.

The `RecordKeyword` model's `__table_args__` only contains the schema comment about the functional unique index — no `CheckConstraint`.

**Impact:** Same autogenerate-drop risk. The model's `keyword_type` has a `server_default="theme"` with no validation of which other values are acceptable.

**Recommendation:**

```python
__table_args__ = (
    CheckConstraint(
        "keyword_type IN ('discipline', 'place', 'stratum', 'temporal', 'theme', "
        "'dataCentre', 'featureType', 'instrument', 'platform', 'process', "
        "'product', 'project', 'service', 'subTopicCategory', 'taxon')",
        name="chk_keyword_type",
    ),
    # NOTE: uniqueness enforced by functional unique index in migration
    {"schema": "catalog"},
)
```

**Effort:** Small

---

#### M10 — `Map.basemap_style` and `Map.visibility` use `Text` instead of bounded `String(N)`

**Affected:** `Map` — `backend/app/maps/models.py:29–36`
**Table:** `catalog.maps`

Both columns use `Text` (unbounded) despite having a small known value set. `Record.visibility` uses `String(20)` for comparison. Using `Text` for these columns doesn't document the expected length and creates slightly wider rows.

**Recommendation:** Change to `String(30)` for `basemap_style` (basemap IDs like `openfreemap-positron` are under 30 chars) and `String(20)` for `visibility`. This is a forward-only schema change with no data risk.

**Effort:** Small

---

#### M11 — `Record.owner_org` has unclear semantic distinction from `source_organization`

**Affected:** `Record` — `backend/app/datasets/models.py:73`
**Table:** `catalog.records`

`owner_org` is `Text, nullable=True`. The column IS actively used — it is set in `datasets/service.py:457-458`, serialized in `datasets/schemas.py:130,173`, and read in `datasets/router.py:326,1115` and `collections/router.py:105`. However, it has no filtering or search use (unlike `source_organization`, which drives facet filtering and display). The semantic distinction between `owner_org` (the organization that owns the data) and `source_organization` (the organization that published/provided the data) is not documented anywhere in the codebase.

**Recommendation:** Add a docstring or inline comment to `Record` clarifying the semantic distinction between `owner_org` and `source_organization`. If the distinction is not meaningful for this project, consolidate into a single column and migrate existing data. If kept, consider adding `owner_org` to search facets if ownership filtering is valuable.

**Effort:** Small (clarification required first)

---

#### M12 — `Map.thumbnail` stored as base64 data URI in `Text` column

**Affected:** `Map` — `backend/app/maps/models.py:39`
**Table:** `catalog.maps`

Base64-encoded thumbnails stored inline can grow to 40–80 KB per row for complex maps. Map list queries that select the full row scan through this data even when thumbnails are not needed. Raster quicklooks use an external URI pattern (`quicklook_256_uri`) which avoids this bloat.

**Recommendation:** Add a `thumbnail_uri Text` column following the raster quicklook pattern and migrate existing thumbnails to storage. Mark the `thumbnail` column as deprecated. This is a larger effort but eliminates a known performance cliff at scale.

**Effort:** Medium

---

#### M13 — `MapLayer.layer_type` has no CHECK constraint

**Affected:** `MapLayer` — `backend/app/maps/models.py:76`
**Table:** `catalog.map_layers`

`layer_type` is `String(50)` with `server_default="vector_geolens"`. Known values from service code: `vector_geolens`, `raster_geolens`, `geojson`. No CHECK in model or migration.

**Recommendation:**

```python
CheckConstraint(
    "layer_type IN ('vector_geolens', 'raster_geolens', 'geojson')",
    name="chk_map_layers_layer_type",
)
```

**Effort:** Small

---

#### M14 — `RasterAsset.storage_backend` has no CHECK constraint

**Affected:** `RasterAsset` — `backend/app/raster/models.py:28`
**Table:** `catalog.raster_assets`

`storage_backend` is `String(20)` with `server_default="local"`. Known values: `local`, `s3`. No CHECK in model or schema.

**Recommendation:**

```python
CheckConstraint(
    "storage_backend IN ('local', 's3')",
    name="chk_raster_assets_storage_backend",
)
```

**Effort:** Trivial

---

#### M15 — `DatasetAsset.key` has no CHECK constraint

**Affected:** `DatasetAsset` — `backend/app/raster/models.py` (DatasetAsset class)
**Table:** `catalog.dataset_assets`

`key` is `String(50)` with a documented set of valid values: `data`, `vrt`, `thumbnail`, `overview`, `metadata`. The model docstring lists these keys but no `CheckConstraint` enforces them.

**Recommendation:**

```python
CheckConstraint(
    "key IN ('data', 'vrt', 'thumbnail', 'overview', 'metadata')",
    name="chk_dataset_assets_key",
)
```

**Effort:** Trivial

---

### LOW — Minor Improvements

#### L1 — `record_embeddings.record_id` has no standalone index

**Affected:** `RecordEmbedding` — `backend/app/embeddings/models.py:21`
**Table:** `catalog.record_embeddings`

The `UniqueConstraint("record_id", "model_name", ...)` implicitly provides a left-prefix index on `record_id`. The cosine similarity query in helpers.py filters on `record_id != ...`, which benefits from this composite index. No additional action needed, but this should be noted as covered.

**Status:** Low concern — existing composite unique index covers the left-prefix lookup.

---

#### L2 — `OAuthAccount.user_id` has no explicit index

**Affected:** `OAuthAccount` — `backend/app/auth/oauth/models.py:71`
**Table:** `catalog.oauth_accounts`

FK to `catalog.users` but no explicit index. OAuth account lookups by user are infrequent (login flow only) so the impact is low. However, an index would improve consistency with the rest of the FK pattern.

**Recommendation:**

```sql
CREATE INDEX idx_oauth_accounts_user_id ON catalog.oauth_accounts (user_id);
```

**Effort:** Trivial

---

#### L3 — Inconsistent `lazy` loading strategies across relationships

**Affected:** Multiple models
**Finding:** Three distinct lazy loading strategies are used with no apparent convention:
- `lazy="selectin"`: `User.roles`, `Role.users`, `ApiKey.user`, `RefreshToken.user`, `OAuthAccount.user`, `OAuthAccount.provider`
- `lazy="joined"`: `Dataset.record`, `AuditLog.user`
- `lazy="select"` (default): all others

`selectin` loads eagerly on every query regardless of whether the relationship is used. For high-traffic paths like `ApiKey.user` (every API-key request), this adds a second query per request. For `User.roles` it is intentional (needed for RBAC on every auth check).

**Recommendation:** Document the loading strategy choices. Consider whether `lazy="selectin"` on `OAuthAccount.provider` is always needed or if it should match `lazy="select"` since the provider object is rarely needed after the login flow.

**Effort:** Small

---

#### L4 — `Collection.name` has unique index in migration but no `unique=True` in model

**Affected:** `Collection` — `backend/app/collections/models.py:17`
**Table:** `catalog.collections`

The migration creates `uq_collections_name UNIQUE (name)` (initial_schema.sql:2095) as a unique index. The model declares `name: Mapped[str] = mapped_column(Text, nullable=False)` without `unique=True`. Same drift pattern as H6/H7 but lower severity since autogenerate handles unique indexes and unique constraints slightly differently.

**Recommendation:**

```python
name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
```

Or add a `UniqueConstraint` in `__table_args__` to be explicit about the constraint name `uq_collections_name`.

**Effort:** Trivial

---

#### L5 — `DatasetRelationship` FK columns reference `records.id` despite being named `*_dataset_id`

**Affected:** `DatasetRelationship` — `backend/app/datasets/models.py:394`
**Table:** `catalog.dataset_relationships`

`source_dataset_id` and `target_dataset_id` both declare `ForeignKey("catalog.records.id", ...)`. The column names suggest they are dataset IDs, but they reference the records table. Since datasets and records are 1:1 this works, but it creates confusion for anyone reading the model without context.

**Recommendation:** Add a comment explaining the relationship:
```python
# NOTE: These columns store record IDs (not dataset IDs) because the relationship
# is defined at the record level (records are the discoverable catalog entry).
# Dataset and record share a 1:1 FK, so record.id == dataset.record_id.
source_dataset_id: Mapped[uuid.UUID] = mapped_column(
    ForeignKey("catalog.records.id", ondelete="CASCADE"), nullable=False
)
```

**Effort:** Trivial

---

#### L6 — `RasterAsset.current_generation_id` has no FK constraint

**Affected:** `RasterAsset` — `backend/app/raster/models.py:11`
**Table:** `catalog.raster_assets`

`current_generation_id` stores a `VrtGeneration.id` value but declares no `ForeignKey`. If a `VrtGeneration` row is deleted, this becomes a dangling reference with no DB-enforced cleanup.

**Recommendation:**

```python
current_generation_id: Mapped[uuid.UUID | None] = mapped_column(
    ForeignKey("catalog.vrt_generations.id", ondelete="SET NULL"), nullable=True
)
```

**Effort:** Small (requires migration for the FK constraint)

---

#### L7 — `VrtSourceLink` model missing `UniqueConstraint` for `(vrt_dataset_id, source_dataset_id)`

**Affected:** `VrtSourceLink` — `backend/app/raster/models.py:123`
**Table:** `catalog.vrt_source_links`

The initial_schema.sql creates `uq_vsl_vrt_source UNIQUE (vrt_dataset_id, source_dataset_id)`. The `VrtSourceLink` model's `__table_args__` is only `{"schema": "catalog"}`. Both FK columns have explicit `index=True` (so the autogenerate index drift issue does not apply), but the unique constraint itself is not reflected in the model. Same drift pattern as H6/H7 but lower severity because the unique constraint does not appear to be referenced by name in application code.

**Recommendation:**

```python
__table_args__ = (
    UniqueConstraint(
        "vrt_dataset_id", "source_dataset_id", name="uq_vsl_vrt_source"
    ),
    {"schema": "catalog"},
)
```

**Effort:** Trivial

---

## Positive Observations

The schema demonstrates strong patterns that should be preserved:

1. **Consistent UUID primary keys** with `server_default=func.gen_random_uuid()` across all 32 tables — no application-level UUID generation required.

2. **Timezone-aware timestamps everywhere** — all `DateTime` columns use `timezone=True` including the `record_embeddings` fix in migration 0005.

3. **Correct CASCADE/SET NULL semantics** — user-owned data uses `SET NULL` (audit trail preserved when user is deleted); child records use `CASCADE` (orphan prevention). No FK uses `RESTRICT` inappropriately.

4. **`passive_deletes=True` on parent relationships** — lets PostgreSQL handle cascade deletes efficiently without loading children into the session.

5. **Computed persisted `search_vector`** — the `TSVECTOR` column with weighted field contributions uses a DB-level `Computed` column with `persisted=True`, ensuring FTS index is always current without application triggers.

6. **Partial indexes where appropriate** — `uq_embed_tokens_one_active_per_map` (one active token per map), `idx_users_status_pending` (only index pending users), and `procrastinate` queue indexes all use WHERE clauses to minimize index size.

7. **GIST index on `spatial_extent`** — spatial queries use the correct PostGIS index type, properly declared in `__table_args__` using `postgresql_using="gist"`.

8. **GIN indexes on TSVECTOR and JSONB columns** — `idx_records_search_vector` and the FTS indexes on `record_contacts` and `record_keywords` use the correct index type for text search.

9. **Check constraints on critical `Record` columns** — `visibility`, `record_status`, `record_type`, `update_frequency`, `sensitivity_classification`, and `temporal_ordering` are all constrained at the DB level.

10. **Well-structured RBAC composite indexes** — `idx_records_visibility_status_creator` and `idx_dataset_grants_role_dataset` (both from migration 0005) cover the primary access patterns efficiently.

---

## Prioritized Action Plan

### Tier 1 — Do First (Index additions, zero risk, immediate performance benefit)

These are additive-only changes with no risk of data loss or constraint violations.

| ID | Change | Table | Effort |
|----|--------|-------|--------|
| H1 | Add index on `api_keys.user_id` | api_keys | Trivial |
| H2 | Add index on `ingest_jobs.created_by` | ingest_jobs | Trivial |
| H3 | Add index on `maps.created_by` | maps | Trivial |
| H4 | Add index on `records.created_at DESC` | records | Trivial |
| H5 | Add partial index on `records.source_organization WHERE NOT NULL` | records | Trivial |
| L2 | Add index on `oauth_accounts.user_id` | oauth_accounts | Trivial |

All six can be delivered in a single migration:

```python
def upgrade() -> None:
    op.create_index("idx_api_keys_user_id", "api_keys", ["user_id"], schema="catalog")
    op.create_index("idx_ingest_jobs_created_by", "ingest_jobs", ["created_by"], schema="catalog")
    op.create_index("idx_maps_created_by", "maps", ["created_by"], schema="catalog")
    op.create_index(
        "idx_records_created_at_desc", "records", ["created_at"],
        schema="catalog", postgresql_using="btree"
    )
    op.create_index(
        "idx_records_source_organization", "records", ["source_organization"],
        schema="catalog",
        postgresql_where=sa.text("source_organization IS NOT NULL")
    )
    op.create_index("idx_oauth_accounts_user_id", "oauth_accounts", ["user_id"], schema="catalog")
```

---

### Tier 2 — Do Soon (Model/migration drift, prevents autogenerate surprises)

Safe to batch into one migration but each model file also needs updating:

| ID | Change | File | Effort |
|----|--------|------|--------|
| H6 | Add `UniqueConstraint` to `SavedSearch` | search/saved.py | Trivial |
| H7 | Add `UniqueConstraint` to `DatasetVersion` | collections/models.py | Trivial |
| H8 | Add `chk_raster_assets_status` and `chk_raster_assets_vrt_type` to `RasterAsset` | raster/models.py | Small |
| H9 | Write migration to add `'table'` to `chk_records_record_type` in DB | datasets/models.py + new migration | Small |
| L4 | Add `unique=True` to `Collection.name` | collections/models.py | Trivial |
| L7 | Add `UniqueConstraint` to `VrtSourceLink` | raster/models.py | Trivial |
| M8 | Add `chk_contact_role` to `RecordContact` | datasets/models.py | Small |
| M9 | Add `chk_keyword_type` to `RecordKeyword` | datasets/models.py | Small |

Note: H8, M8, and M9 involve reflecting existing DB constraints into models (no DB changes needed for the constraints themselves).

---

### Tier 3 — Do When Touching the Area (CHECK constraints, data integrity hardening)

These add new constraints to the DB and require migrations. Zero risk if value sets are correct.

| ID | Change | Table |
|----|--------|-------|
| M1 | `chk_maps_visibility` | maps |
| M2 | `chk_ingest_jobs_status` | ingest_jobs |
| M3 | `chk_users_status` | users |
| M4 | `chk_users_auth_provider` | users |
| M5 | `chk_raster_assets_cog_status` | raster_assets |
| M6 | `chk_vrt_generations_status` | vrt_generations |
| M7 | `chk_oauth_providers_type` | oauth_providers |
| M13 | `chk_map_layers_layer_type` | map_layers |
| M14 | `chk_raster_assets_storage_backend` | raster_assets |
| M15 | `chk_dataset_assets_key` | dataset_assets |

Verify that all existing rows satisfy the proposed CHECK values before deploying. A pre-flight query (e.g., `SELECT DISTINCT status FROM catalog.ingest_jobs`) is recommended for each.

---

### Tier 4 — Consider (Longer-term schema improvements)

| ID | Change | Notes |
|----|--------|-------|
| L6 | Add FK from `RasterAsset.current_generation_id` to `vrt_generations.id` | Prevents dangling references; requires migration |
| M10 | Clarify `Record.owner_org` vs `source_organization` distinction | Document or consolidate |
| M11 | Migrate `Map.thumbnail` to external storage URI | Eliminates per-row bloat; medium effort |
| M12 | Change `Map.basemap_style` and `Map.visibility` from `Text` to `String(N)` | Minor benefit; document-only change is acceptable |
| L3 | Audit and standardize lazy loading strategies | Review `selectin` relationships for necessity |
| L5 | Add clarifying comments to `DatasetRelationship` FK columns | Code clarity only |

---

## Appendix: Relationship Loading Strategy Audit

| Model | Relationship | Strategy | Notes |
|-------|-------------|----------|-------|
| User | roles | `selectin` | Intentional: RBAC requires roles on every auth check |
| Role | users | `selectin` | Reverse side; rarely traversed in practice |
| ApiKey | user | `selectin` | Loaded on every API key auth — review if full User object is always needed |
| RefreshToken | user | `selectin` | Same pattern |
| OAuthAccount | user | `selectin` | Only on OAuth login flow; could be `select` |
| OAuthAccount | provider | `selectin` | Only on OAuth login flow; could be `select` |
| Dataset | record | `joined` | Intentional: dataset queries always need record metadata |
| AuditLog | user | `joined` | Intentional: admin log views always show username |
| Record | dataset | `select` (default) | Lazy — loaded only when explicitly accessed |
| Record | contacts | `select` (default) | Lazy — loaded only when explicitly accessed |
| Record | keywords | `select` (default) | Lazy — loaded only when explicitly accessed |
| Record | distributions | `select` (default) | Lazy — loaded only when explicitly accessed |
| AttributeMetadata | dataset | `select` (default) | Lazy |
| RecordEmbedding | record | `select` (default) | Lazy |

**Inconsistency:** `ApiKey.user` uses `selectin` meaning the full `User` object is loaded from a second query on every API key resolution. If only `user.id`, `user.status`, or `user.roles` are needed downstream, a more targeted query could reduce the per-request load. The `selectin` is defensible for now but should be reviewed when optimizing the auth hot path.
