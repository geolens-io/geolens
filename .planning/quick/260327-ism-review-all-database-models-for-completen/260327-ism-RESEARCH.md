# Database Model Review - Research

**Researched:** 2026-03-27
**Domain:** SQLAlchemy models, PostGIS, Alembic migrations
**Confidence:** HIGH

## Summary

Comprehensive review of all 31 SQLAlchemy models across 11 modules in the GeoLens catalog schema. The schema is well-structured with consistent patterns (UUID PKs, timezone-aware timestamps, server defaults, cascade deletes). The primary areas for improvement are: missing indexes on frequently-filtered FK columns, a few model/migration drift issues, missing check constraints on enum-like string columns, and one unique constraint that exists only in the migration but not in the model definition.

**Primary recommendation:** Add missing FK indexes and align model definitions with migration-level constraints.

## User Constraints (from CONTEXT.md)

### Implementation Decisions
- Output format: Structured markdown report with severity ratings
- Optimization focus: All dimensions (query performance, indexes, normalization, data integrity, storage)
- Action on findings: Document only -- no code or migration changes

### Claude's Discretion
- Severity classification scheme (critical/high/medium/low)
- Ordering of findings within report

## Model Inventory

| # | Module | Model | Table | PK | Key Relationships |
|---|--------|-------|-------|----|--------------------|
| 1 | datasets | Record | records | UUID | -> User (created_by, updated_by) |
| 2 | datasets | Dataset | datasets | UUID | -> Record (1:1 via record_id) |
| 3 | datasets | RecordContact | record_contacts | UUID | -> Record |
| 4 | datasets | RecordKeyword | record_keywords | UUID | -> Record |
| 5 | datasets | RecordDistribution | record_distributions | UUID | -> Record |
| 6 | datasets | AttributeMetadata | attribute_metadata | UUID | -> Dataset |
| 7 | datasets | DatasetGrant | dataset_grants | composite | -> Dataset + Role |
| 8 | datasets | DatasetRelationship | dataset_relationships | UUID | -> Record (source + target) |
| 9 | auth | User | users | UUID | <-> Role (M2M via user_roles) |
| 10 | auth | Role | roles | UUID | <-> User (M2M) |
| 11 | auth | UserRole | user_roles | composite | -> User + Role |
| 12 | auth | ApiKey | api_keys | UUID | -> User |
| 13 | auth | RefreshToken | refresh_tokens | UUID | -> User |
| 14 | auth/oauth | OAuthProvider | oauth_providers | UUID | standalone |
| 15 | auth/oauth | OAuthAccount | oauth_accounts | UUID | -> OAuthProvider + User |
| 16 | collections | Collection | collections | UUID | -> User (created_by) |
| 17 | collections | CollectionDataset | collection_datasets | composite | -> Collection + Dataset |
| 18 | collections | DatasetVersion | dataset_versions | UUID | -> Dataset + User |
| 19 | maps | Map | maps | UUID | -> User (created_by), self-ref (forked_from) |
| 20 | maps | MapLayer | map_layers | UUID | -> Map + Dataset |
| 21 | maps | MapShareToken | map_share_tokens | UUID | -> Map + User |
| 22 | raster | RasterAsset | raster_assets | UUID | -> Dataset (1:1) |
| 23 | raster | VrtGeneration | vrt_generations | UUID | -> Dataset |
| 24 | raster | VrtSourceLink | vrt_source_links | UUID | -> Dataset (vrt + source) |
| 25 | raster | DatasetAsset | dataset_assets | UUID | -> Dataset |
| 26 | jobs | IngestJob | ingest_jobs | UUID | -> Dataset + User |
| 27 | audit | AuditLog | audit_logs | UUID | -> User |
| 28 | embed_tokens | EmbedToken | embed_tokens | UUID | -> Map + User |
| 29 | embeddings | RecordEmbedding | record_embeddings | UUID | -> Record |
| 30 | settings | AppSetting | app_settings | Text key | standalone KV |
| 31 | search | SavedSearch | saved_searches | UUID | -> User |

## Findings

### CRITICAL

None identified. The schema is fundamentally sound.

### HIGH - Missing Indexes on Frequently Queried FK Columns

**H1: `api_keys.user_id` has no index**

The `ApiKey.user_id` FK column is filtered in auth resolution (`ApiKey.user_id == current_user.id`), admin listing, and bulk deletion (`delete(ApiKey).where(ApiKey.user_id == user_id)`). No btree index exists. While the table is small today, API key lookup occurs on every authenticated API-key request.

- Files: `backend/app/auth/models.py:79`, `backend/app/auth/router.py:231`
- Fix: `CREATE INDEX idx_api_keys_user_id ON catalog.api_keys (user_id);`

**H2: `ingest_jobs.created_by` has no index**

Filtered in admin job listing (`IngestJob.created_by == user_id`) and joined to users. No index exists.

- Files: `backend/app/jobs/models.py:37`, `backend/app/admin/router.py:316`
- Fix: `CREATE INDEX idx_ingest_jobs_created_by ON catalog.ingest_jobs (created_by);`

**H3: `maps.created_by` has no index**

Heavily filtered in map listing/ownership queries (`Map.created_by == user_id`) with 5 call sites in `maps/service.py`. No index exists despite the visibility + ownership being the primary access pattern for maps.

- Files: `backend/app/maps/models.py:47`, `backend/app/maps/service.py:174,414,989`
- Fix: `CREATE INDEX idx_maps_created_by ON catalog.maps (created_by);`

**H4: `records.created_at` has no descending index**

The primary sort column for record listing and search results (`Record.created_at.desc()`) has no index. The composite `idx_records_visibility_status_creator` helps with WHERE but does not cover ORDER BY. Every catalog browse hits this sort path.

- Files: `backend/app/datasets/service.py:273`, `backend/app/search/service.py:858,876`
- Fix: `CREATE INDEX idx_records_created_at_desc ON catalog.records (created_at DESC);`

**H5: `records.source_organization` has no index**

Used as a facet filter (`Record.source_organization == source_organization`) and in DISTINCT aggregation for facet counts. Queried on every search with an org filter.

- Files: `backend/app/search/service.py:285,448,726`, `backend/app/search/router.py:705-709`
- Fix: `CREATE INDEX idx_records_source_organization ON catalog.records (source_organization) WHERE source_organization IS NOT NULL;`

### HIGH - Model/Migration Drift

**H6: `SavedSearch` model missing `UniqueConstraint` for `(user_id, name)`**

The migration (`initial_schema.sql:1725`) creates `uq_saved_searches_user_name UNIQUE (user_id, name)` and the upsert code references it by name (`constraint="uq_saved_searches_user_name"`). However, the model class has no `UniqueConstraint` in `__table_args__` -- it only declares `{"schema": "catalog"}`. This means:
- Autogenerate will try to drop the constraint
- The model does not document the business rule

File: `backend/app/search/saved.py:15-32`

**H7: `DatasetVersion` model missing `UniqueConstraint` for `(dataset_id, version_number)`**

The migration creates `uq_dataset_version UNIQUE (dataset_id, version_number)` but the model has no `UniqueConstraint` in `__table_args__`.

File: `backend/app/collections/models.py:49-72`

### MEDIUM - Missing Check Constraints

**M1: `Map.visibility` has no CHECK constraint**

`Map.visibility` is `Text` (not even `String(N)`) with a Python default of `"private"` but no database-level CHECK. The `MapVisibility` enum in schemas.py lists `private`, `public`, `unlisted` but nothing enforces this at the DB level. Compare with `Record.visibility` which has `chk_records_visibility`.

File: `backend/app/maps/models.py:34-36`

**M2: `IngestJob.status` has no CHECK constraint**

`IngestJob.status` is `String(20)` with index but no CHECK. Possible values scattered through code: `pending`, `running`, `completed`, `failed`, `cancelled`. Compare with `Record.record_status` which has a CHECK.

File: `backend/app/jobs/models.py:22-23`

**M3: `User.status` has no CHECK constraint**

`User.status` is `String(20)` with server_default `"active"`. The partial index `idx_users_status_pending` implies known values (at least `active`, `pending`), but no CHECK constraint exists to enforce valid values.

File: `backend/app/auth/models.py:20-22`

**M4: `User.auth_provider` has no CHECK constraint**

`User.auth_provider` is `String(20)` with no CHECK. Known values: `local`, `oidc`, `saml`.

File: `backend/app/auth/models.py:26-28`

**M5: `RasterAsset.status` and `RasterAsset.cog_status` have no CHECK constraints**

Both are `String(20)` with known value sets but no database enforcement.

File: `backend/app/raster/models.py:40,61`

**M6: `VrtGeneration.status` has no CHECK constraint**

`String(20)` with server_default `"pending"` but no CHECK. Has an index (`ix_vrt_generations_status`).

File: `backend/app/raster/models.py:105-106`

### MEDIUM - Data Integrity

**M7: `VrtSourceLink` missing unique constraint on `(vrt_dataset_id, source_dataset_id)`**

Nothing prevents the same source COG from being linked to a VRT dataset twice. The application may enforce this in code, but a unique constraint would provide a stronger guarantee. Position ordering alone is insufficient since two links with different positions but the same source would be semantically invalid.

File: `backend/app/raster/models.py:123-143`

**M8: `OAuthProvider.provider_type` has no CHECK constraint**

Known values: `oidc`, `google`, `microsoft`, `saml`. No database enforcement.

File: `backend/app/auth/oauth/models.py:32`

**M9: `RecordDistribution.distribution_type` CHECK is present but `RecordContact.role` has none**

`RecordContact.role` is `String(30)` with no CHECK. Typical values: `pointOfContact`, `custodian`, `author`, etc. (ISO 19115 roles). The sibling `RecordDistribution` properly constrains its `distribution_type`.

File: `backend/app/datasets/models.py:254`

### MEDIUM - Schema Design

**M10: `Record.owner_org` column appears unused**

`Record.owner_org` is defined as `Text, nullable=True` but no query in the codebase references it. `Record.source_organization` serves the organizational filtering role. This is either dead schema or a planned-but-unimplemented feature.

File: `backend/app/datasets/models.py:73`

**M11: `Map.thumbnail` stored as `Text` (base64 data URI)**

Base64-encoded thumbnails stored inline in the row can grow large (tens of KB) and bloat table scans. For maps with many layers or high-res thumbnails, this slows down list queries that `SELECT *` the maps table. Consider moving to external storage (like raster quicklooks already do) or a separate table.

File: `backend/app/maps/models.py:39`

**M12: `Map.basemap_style` and `Map.visibility` use `Text` instead of bounded `String(N)`**

These columns have a small known value set but use unbounded `Text`. While functionally equivalent in PostgreSQL, `String(N)` documents the expected length and provides an implicit validation layer. Compare with how `Record.visibility` uses `String(20)`.

File: `backend/app/maps/models.py:29-36`

### LOW - Minor Improvements

**L1: `record_embeddings.record_id` has no standalone index**

The unique constraint on `(record_id, model_name)` implicitly indexes lookups by `record_id` (left prefix), so this is partially covered. However, the cosine similarity query in `helpers.py:50` filters on `record_id !=` which benefits from the composite index. Low severity because the table is typically small.

File: `backend/app/embeddings/models.py:22`

**L2: `OAuthAccount.user_id` has no index**

FK to `catalog.users` but no explicit index. Queries by user_id would require a seq scan. Low severity because OAuth account lookups are infrequent.

File: `backend/app/auth/oauth/models.py:78`

**L3: Inconsistent `lazy` strategies across relationships**

Some relationships use `lazy="selectin"` (User.roles, ApiKey.user, RefreshToken.user, OAuthAccount.user), others use `lazy="joined"` (Dataset.record, AuditLog.user), and most use `lazy="select"` (default). While not necessarily wrong, the inconsistency suggests ad-hoc tuning rather than a deliberate strategy. Review whether `selectin` relationships are always needed (they load eagerly on every query).

**L4: `Collection.name` has unique index in migration but no `unique=True` in model**

The migration creates `uq_collections_name UNIQUE (name)` but the model declares `name: Mapped[str] = mapped_column(Text, nullable=False)` without `unique=True`. Same drift pattern as H6/H7.

File: `backend/app/collections/models.py:17`

**L5: `DatasetRelationship` FKs point to `records.id` not `datasets.id`**

`source_dataset_id` and `target_dataset_id` both reference `catalog.records.id` via FK, but the column names say "dataset". This works because records and datasets are 1:1, but the naming is misleading -- these are record IDs, not dataset IDs.

File: `backend/app/datasets/models.py:409-413`

**L6: `RasterAsset.current_generation_id` has no FK constraint**

This column stores a `VrtGeneration.id` value but declares no `ForeignKey`. If a VrtGeneration row is deleted, this becomes a dangling reference. The application must handle staleness manually.

File: `backend/app/raster/models.py:62`

## Summary Statistics

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High | 7 |
| Medium | 12 |
| Low | 6 |

## Positive Observations

The schema demonstrates several strong patterns worth preserving:

1. **Consistent UUID primary keys** with `server_default=func.gen_random_uuid()` across all tables
2. **Timezone-aware timestamps** everywhere (fixed for record_embeddings in migration 0005)
3. **Proper CASCADE/SET NULL** on all foreign keys matching the business semantics
4. **`passive_deletes=True`** on parent relationships, letting PostgreSQL handle cascades efficiently
5. **Good use of computed columns** -- `search_vector` as a persisted TSVECTOR with proper weighting
6. **Partial indexes** where appropriate (embed_tokens active-per-map, users pending status)
7. **GIST index on spatial_extent** for spatial queries
8. **GIN indexes on TSVECTOR** columns for full-text search
9. **Check constraints** on critical enum columns (Record visibility, status, type, etc.)
10. **Composite indexes** added in migration 0005 for the primary RBAC access path

## Sources

### Primary (HIGH confidence)
- Direct reading of all 11 model files in `backend/app/*/models.py`
- Full index listing from `backend/alembic/versions/initial_schema.sql`
- Migrations 0001-0010 in `backend/alembic/versions/`
- Query pattern analysis across service and router files
