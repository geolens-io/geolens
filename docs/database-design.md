# GeoLens Database Design

**Document Purpose**: Third-party audit reference for the GeoLens PostgreSQL database.
**Generated**: 2026-02-16
**Database**: PostgreSQL 17.5 with PostGIS 3.5.2

---

## 1. Overview

GeoLens uses a single PostgreSQL database (`geolens`) with schema-based separation between application metadata and user-uploaded geospatial data. Schema migrations are managed by Alembic (current revision: `e7f1g5b89c01`).

### Schemas

| Schema | Purpose |
|--------|---------|
| `catalog` | Application tables — users, datasets, collections, audit logs, jobs |
| `data` | User-uploaded geospatial tables (one table per dataset, auto-named `ds_<hash>`) |
| `public` | PostGIS system tables (`spatial_ref_sys`) |
| `tiger`, `tiger_data`, `topology` | PostGIS extension schemas (bundled with `postgis_tiger_geocoder`, `postgis_topology`) — not used by the application |
| `ogr_system_tables` | GDAL/OGR internal metadata |

### Extensions

| Extension | Version | Purpose |
|-----------|---------|---------|
| `postgis` | 3.5.2 | Geometry types, spatial functions, coordinate transforms |
| `postgis_tiger_geocoder` | 3.5.2 | Bundled with PostGIS image (not actively used) |
| `postgis_topology` | 3.5.2 | Bundled with PostGIS image (not actively used) |
| `pg_trgm` | 1.6 | Trigram similarity for fuzzy text search |
| `fuzzystrmatch` | 1.2 | Phonetic matching (dependency of tiger geocoder) |

---

## 2. Database Roles & Access Control

### Roles

| Role | Login? | Superuser? | Purpose |
|------|--------|------------|---------|
| `geolens` | Yes | Yes | Application owner — full DDL/DML access |
| `geolens_reader` | No | No | Abstract role granting SELECT on individual data tables (used by tile queries) |

### Schema Privileges

| Role | `catalog` | `data` | `public` |
|------|-----------|--------|----------|
| `geolens_reader` | No access | USAGE (read) | USAGE |

Per-table SELECT grants on `data.ds_*` are issued during ingestion via the `geolens_reader` role.

---

## 3. Catalog Schema — Entity-Relationship Diagram

```
┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│    users     │       │    roles     │       │  collections │
│──────────────│       │──────────────│       │──────────────│
│ id (PK)      │──┐    │ id (PK)      │──┐    │ id (PK)      │
│ username (UQ)│  │    │ name (UQ)    │  │    │ name (UQ)    │
│ email (UQ)   │  │    │ description  │  │    │ description  │
│ password_hash│  │    └──────────────┘  │    │ created_by   │──→ users.id
│ oidc_subject │  │         │            │    │ created_at   │
│ oidc_issuer  │  │    ┌────┴────┐       │    └──────┬───────┘
│ is_active    │  │    │user_roles│       │           │
│ status       │  │    │─────────│       │    ┌──────┴────────────┐
│ created_at   │  ├───→│user_id  │       │    │collection_datasets│
│ updated_at   │  │    │role_id  │←──────┘    │───────────────────│
└──────┬───────┘  │    └─────────┘            │ collection_id (PK)│──→ collections.id
       │          │                           │ dataset_id (PK)   │──→ datasets.id
       │          │    ┌──────────────────┐   │ added_by          │──→ users.id
       │          │    │ dataset_grants   │   │ sort_order        │
       │          │    │─────────────────-│   └───────────────────┘
       │          │    │ dataset_id (PK)  │──→ datasets.id
       │          │    │ role_id (PK)     │──→ roles.id
       │          │    └─────────────────-┘
       │          │
       │          │    ┌──────────────────────┐
       │          ├───→│ datasets             │
       │          │    │──────────────────────│
       │          │    │ id (PK)              │
       │          │    │ table_name (UQ)      │──→ data.ds_<hash> (logical)
       │          │    │ name                 │
       │          │    │ description          │
       │          │    │ tags[]               │
       │          │    │ srid                 │
       │          │    │ geometry_type         │
       │          │    │ feature_count        │
       │          │    │ extent (geometry)    │
       │          │    │ column_info (jsonb)  │
       │          │    │ source_format        │
       │          │    │ source_filename      │
       │          │    │ original_srid        │
       │          │    │ visibility           │
       │          │    │ created_by           │──→ users.id
       │          │    │ contact (jsonb)      │
       │          │    │ license              │
       │          │    │ source_organization  │
       │          │    │ data_vintage_start   │
       │          │    │ data_vintage_end     │
       │          │    │ sample_values (jsonb)│
       │          │    │ search_vector (tsv)  │
       │          │    │ quality_score (jsonb)│
       │          │    │ current_version      │
       │          │    └──────────┬───────────┘
       │          │               │
       │          │    ┌──────────┴───────────┐
       │          ├───→│ dataset_versions     │
       │          │    │─────────────────────-│
       │          │    │ id (PK)              │
       │          │    │ dataset_id           │──→ datasets.id
       │          │    │ version_number       │
       │          │    │ source_filename      │
       │          │    │ source_format        │
       │          │    │ feature_count        │
       │          │    │ srid                 │
       │          │    │ geometry_type         │
       │          │    │ file_hash            │
       │          │    │ uploaded_by          │──→ users.id
       │          │    │ uploaded_at          │
       │          │    └──────────────────────┘
       │          │    (UQ: dataset_id + version_number)
       │          │
       │          │    ┌──────────────────────┐
       │          ├───→│ ingest_jobs          │
       │          │    │──────────────────────│
       │          │    │ id (PK)              │
       │          │    │ dataset_id           │──→ datasets.id (nullable)
       │          │    │ status               │
       │          │    │ source_filename      │
       │          │    │ file_path            │
       │          │    │ error_message        │
       │          │    │ user_metadata (jsonb)│
       │          │    │ created_by           │──→ users.id
       │          │    │ started_at           │
       │          │    │ completed_at         │
       │          │    │ created_at           │
       │          │    └──────────────────────┘
       │          │
       │          │    ┌──────────────────────┐
       │          ├───→│ audit_logs           │
       │          │    │──────────────────────│
       │          │    │ id (PK)              │
       │          │    │ user_id              │──→ users.id (nullable)
       │          │    │ action               │
       │          │    │ resource_type        │
       │          │    │ resource_id          │
       │          │    │ details (jsonb)      │
       │          │    │ ip_address           │
       │          │    │ created_at           │
       │          │    └──────────────────────┘
       │          │
       │          │    ┌──────────────────────┐
       │          ├───→│ saved_searches       │
       │          │    │──────────────────────│
       │          │    │ id (PK)              │
       │          │    │ user_id              │──→ users.id
       │          │    │ name                 │
       │          │    │ params (jsonb)       │
       │          │    │ created_at           │
       │          │    │ updated_at           │
       │          │    └──────────────────────┘
       │          │    (UQ: user_id + name)
       │          │
       │          │    ┌──────────────────────┐
       │          └───→│ api_keys             │
       │               │──────────────────────│
       │               │ id (PK)              │
       │               │ user_id              │──→ users.id
       │               │ key_hash (UQ)        │
       │               │ name                 │
       │               │ is_active            │
       │               │ created_at           │
       │               │ last_used_at         │
       │               └──────────────────────┘
       │
       │          ┌──────────────────────────────┐
       │          │ procrastinate_jobs            │
       │          │ procrastinate_events          │
       │          │ procrastinate_workers         │
       │          │ procrastinate_periodic_defers │
       │          │──────────────────────────────│
       │          │ (Managed by Procrastinate     │
       │          │  job queue library)           │
       └─────────└──────────────────────────────-┘
```

---

## 4. Table Definitions

### 4.1 `catalog.users`

Stores local and OIDC-authenticated user accounts.

| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| `id` | uuid | NO | `gen_random_uuid()` | PRIMARY KEY |
| `username` | varchar(150) | NO | | UNIQUE |
| `email` | varchar(255) | YES | | UNIQUE |
| `password_hash` | text | YES | | |
| `oidc_subject` | varchar(255) | YES | | UNIQUE |
| `oidc_issuer` | varchar(512) | YES | | |
| `is_active` | boolean | NO | `true` | |
| `status` | varchar(20) | NO | `'active'` | |
| `created_at` | timestamptz | NO | `now()` | |
| `updated_at` | timestamptz | NO | `now()` | |

**Notes**:
- `password_hash` is NULL for OIDC-only users; `oidc_subject`/`oidc_issuer` are NULL for local users.
- `status` supports `'active'` and `'pending'` (for admin-approval workflows). A partial index `idx_users_status_pending` covers pending users.
- Passwords are hashed with bcrypt via `passlib`.

### 4.2 `catalog.roles`

Predefined application roles.

| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| `id` | uuid | NO | `gen_random_uuid()` | PRIMARY KEY |
| `name` | varchar(50) | NO | | UNIQUE |
| `description` | text | YES | | |

**Seed data**: `admin` (full access), `editor` (create/manage datasets), `viewer` (read-only).

### 4.3 `catalog.user_roles`

Many-to-many join between users and roles.

| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| `user_id` | uuid | NO | | PK (composite), FK → users.id ON DELETE CASCADE |
| `role_id` | uuid | NO | | PK (composite), FK → roles.id ON DELETE CASCADE |

### 4.4 `catalog.datasets`

Central metadata registry for every imported geospatial dataset.

| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| `id` | uuid | NO | `gen_random_uuid()` | PRIMARY KEY |
| `table_name` | varchar(255) | NO | | UNIQUE |
| `name` | text | NO | | |
| `description` | text | YES | | |
| `tags` | text[] | YES | | |
| `srid` | integer | YES | | |
| `geometry_type` | varchar(50) | YES | | |
| `feature_count` | integer | YES | | |
| `extent` | geometry | YES | | GiST indexed |
| `column_info` | jsonb | YES | | |
| `source_format` | varchar(50) | YES | | |
| `source_filename` | varchar(500) | YES | | |
| `original_srid` | integer | YES | | |
| `visibility` | varchar(20) | NO | | |
| `created_by` | uuid | YES | | FK → users.id ON DELETE SET NULL |
| `created_at` | timestamptz | NO | `now()` | |
| `updated_at` | timestamptz | NO | `now()` | |
| `contact` | jsonb | YES | | |
| `license` | text | YES | | |
| `source_organization` | text | YES | | |
| `data_vintage_start` | date | YES | | |
| `data_vintage_end` | date | YES | | |
| `sample_values` | jsonb | YES | | |
| `search_vector` | tsvector | YES | | GIN indexed |
| `quality_score` | jsonb | YES | | |
| `current_version` | integer | NO | `1` | |

**Key fields**:
- `table_name` maps to the physical table in the `data` schema (e.g., `ds_6070caf18a99`).
- `extent` stores the dataset's bounding polygon in EPSG:4326 for spatial search.
- `search_vector` is a pre-computed tsvector for full-text search across name, description, tags, and column names.
- `sample_values` stores representative attribute values per column for faceted attribute search.
- `quality_score` is a computed metadata completeness assessment.
- `visibility` controls access: `public`, `restricted`, or `private`.

**Indexes**: PK, `table_name` (unique), `created_at`, `updated_at`, `geometry_type`, `srid`, `source_organization`, `extent` (GiST), `search_vector` (GIN).

### 4.5 `catalog.dataset_versions`

Version history for re-uploaded datasets.

| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| `id` | uuid | NO | `gen_random_uuid()` | PRIMARY KEY |
| `dataset_id` | uuid | NO | | FK → datasets.id ON DELETE CASCADE |
| `version_number` | integer | NO | | |
| `source_filename` | text | YES | | |
| `source_format` | text | YES | | |
| `feature_count` | integer | YES | | |
| `srid` | integer | YES | | |
| `geometry_type` | text | YES | | |
| `file_hash` | text | YES | | |
| `uploaded_by` | uuid | YES | | FK → users.id ON DELETE SET NULL |
| `uploaded_at` | timestamptz | NO | `now()` | |

**Unique constraint**: `(dataset_id, version_number)`.

### 4.6 `catalog.collections`

Logical groupings of datasets.

| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| `id` | uuid | NO | `gen_random_uuid()` | PRIMARY KEY |
| `name` | text | NO | | UNIQUE |
| `description` | text | YES | | |
| `created_by` | uuid | YES | | FK → users.id ON DELETE SET NULL |
| `created_at` | timestamptz | NO | `now()` | |
| `updated_at` | timestamptz | NO | `now()` | |

### 4.7 `catalog.collection_datasets`

Many-to-many join between collections and datasets.

| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| `collection_id` | uuid | NO | | PK (composite), FK → collections.id ON DELETE CASCADE |
| `dataset_id` | uuid | NO | | PK (composite), FK → datasets.id ON DELETE CASCADE |
| `added_at` | timestamptz | NO | `now()` | |
| `added_by` | uuid | YES | | FK → users.id ON DELETE SET NULL |
| `sort_order` | integer | YES | `0` | |

### 4.8 `catalog.dataset_grants`

Per-dataset role-based access grants (for `restricted` visibility datasets).

| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| `dataset_id` | uuid | NO | | PK (composite), FK → datasets.id ON DELETE CASCADE |
| `role_id` | uuid | NO | | PK (composite), FK → roles.id ON DELETE CASCADE |

### 4.9 `catalog.api_keys`

API key authentication for programmatic access.

| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| `id` | uuid | NO | `gen_random_uuid()` | PRIMARY KEY |
| `user_id` | uuid | NO | | FK → users.id ON DELETE CASCADE |
| `key_hash` | varchar(128) | NO | | UNIQUE |
| `name` | varchar(255) | NO | | |
| `is_active` | boolean | NO | `true` | |
| `created_at` | timestamptz | NO | `now()` | |
| `last_used_at` | timestamptz | YES | | |

**Notes**: Only the SHA-256 hash of the API key is stored. The plaintext key is returned once at creation and cannot be retrieved.

### 4.10 `catalog.audit_logs`

Immutable audit trail for security-relevant actions.

| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| `id` | uuid | NO | `gen_random_uuid()` | PRIMARY KEY |
| `user_id` | uuid | YES | | FK → users.id ON DELETE SET NULL |
| `action` | varchar(50) | NO | | |
| `resource_type` | varchar(50) | NO | | |
| `resource_id` | uuid | YES | | |
| `details` | jsonb | YES | | |
| `ip_address` | varchar(45) | YES | | |
| `created_at` | timestamptz | NO | `now()` | |

**Indexes**: `user_id`, `action`, `resource_id`, `created_at`.

**Tracked actions include**: `login`, `create_dataset`, `update_dataset`, `delete_dataset`, `create_collection`, `create_api_key`, `user_create`, `role_assign`, `role_remove`, and others.

### 4.11 `catalog.saved_searches`

User-saved search queries.

| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| `id` | uuid | NO | `gen_random_uuid()` | PRIMARY KEY |
| `user_id` | uuid | NO | | FK → users.id ON DELETE CASCADE |
| `name` | varchar(255) | NO | | |
| `params` | jsonb | NO | | |
| `created_at` | timestamptz | NO | `now()` | |
| `updated_at` | timestamptz | NO | `now()` | |

**Unique constraint**: `(user_id, name)`.

### 4.12 `catalog.ingest_jobs`

Tracks file upload and ingestion job lifecycle.

| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| `id` | uuid | NO | `gen_random_uuid()` | PRIMARY KEY |
| `dataset_id` | uuid | YES | | FK → datasets.id ON DELETE SET NULL |
| `status` | varchar(20) | NO | | |
| `source_filename` | varchar(500) | YES | | |
| `file_path` | varchar(1000) | YES | | |
| `error_message` | text | YES | | |
| `user_metadata` | jsonb | YES | | |
| `created_by` | uuid | YES | | FK → users.id ON DELETE SET NULL |
| `started_at` | timestamptz | YES | | |
| `completed_at` | timestamptz | YES | | |
| `created_at` | timestamptz | NO | `now()` | |

**Status values**: `pending`, `running`, `complete`, `failed`.

### 4.13 Procrastinate Tables

The `procrastinate_jobs`, `procrastinate_events`, `procrastinate_workers`, and `procrastinate_periodic_defers` tables are managed by the [Procrastinate](https://procrastinate.readthedocs.io/) async job queue library. They handle background task scheduling, execution tracking, and worker registration. Eight triggers on `procrastinate_jobs` manage event propagation and cleanup.

---

## 5. Data Schema — Geospatial Tables

Each imported dataset creates a table in the `data` schema named `ds_<12-char-hex-hash>`. The structure varies by source file but always includes:

| Column | Type | Description |
|--------|------|-------------|
| `gid` | integer | Auto-generated primary key (from ogr2ogr) |
| `geom` | geometry | Native geometry in EPSG:4326 (clipped to ±85.06° lat for Mercator compatibility) |
| `geom_4326` | geometry(Geometry, 4326) | Copy/transform of `geom` in WGS84 (for spatial queries) |
| *(varies)* | *(varies)* | All source attributes preserved as-is from the original file |

**Indexes on each data table**:
- Primary key on `gid`
- GiST spatial index on `geom` (created by ogr2ogr)
- GiST spatial index on `geom_4326` (created during post-processing)

**Access**: `SELECT` granted to `geolens_reader` role.

**Post-import processing**:
1. Geometries clipped to Web Mercator safe bounds (`ST_Intersection` with ±85.06° lat envelope) — prevents `ST_Transform` failures in tile generation
2. `geom_4326` column added and populated
3. `SELECT` granted to `geolens_reader`

---

## 6. Foreign Key Cascade Rules

| Parent Table | Child Table | On Delete | Rationale |
|-------------|-------------|-----------|-----------|
| `users` | `user_roles` | CASCADE | Removing a user removes their role assignments |
| `users` | `api_keys` | CASCADE | Removing a user revokes their API keys |
| `users` | `saved_searches` | CASCADE | Removing a user removes their saved searches |
| `users` | `datasets.created_by` | SET NULL | Preserve dataset if creator is removed |
| `users` | `collections.created_by` | SET NULL | Preserve collection if creator is removed |
| `users` | `audit_logs.user_id` | SET NULL | Preserve audit trail if user is removed |
| `users` | `dataset_versions.uploaded_by` | SET NULL | Preserve version history |
| `users` | `ingest_jobs.created_by` | SET NULL | Preserve job history |
| `users` | `collection_datasets.added_by` | SET NULL | Preserve membership info |
| `datasets` | `collection_datasets` | CASCADE | Removing a dataset removes it from collections |
| `datasets` | `dataset_versions` | CASCADE | Removing a dataset removes its version history |
| `datasets` | `dataset_grants` | CASCADE | Removing a dataset removes its access grants |
| `datasets` | `ingest_jobs.dataset_id` | SET NULL | Preserve job history if dataset is removed |
| `collections` | `collection_datasets` | CASCADE | Removing a collection removes memberships |
| `roles` | `user_roles` | CASCADE | Removing a role removes user assignments |
| `roles` | `dataset_grants` | CASCADE | Removing a role removes dataset grants |

---

## 7. Security Considerations

### Authentication
- Local passwords stored as bcrypt hashes (`passlib`). Plaintext never stored.
- OIDC federated login supported via `oidc_subject` / `oidc_issuer` columns.
- API keys stored as SHA-256 hashes only. Plaintext returned once at creation.
- JWT tokens used for session authentication (not stored in database).

### Authorization
- Three-tier role model: `admin` > `editor` > `viewer`.
- Dataset visibility (`public` / `restricted` / `private`) controls who can access data.
- `dataset_grants` provides per-dataset role-based access for `restricted` datasets.
- The `geolens_reader` role has no access to `catalog` schema, limiting tile query exposure.

### Audit Trail
- `audit_logs` table records all security-relevant actions with user, action, resource, IP, and timestamp.
- Audit records use `SET NULL` on user deletion to preserve the trail.
- `details` JSONB column captures action-specific context (e.g., changed fields, previous values).

### SQL Injection Prevention
- All dynamically-constructed table names validated against `^[a-z0-9_]+$` regex before use in SQL.
- Application uses SQLAlchemy ORM with parameterized queries for catalog operations.
- Data table names are auto-generated hex hashes, never user-supplied.

### Network Isolation
- Tile and feature HTTP endpoints served by FastAPI with built-in RBAC enforcement.
- Tile access controlled via signed URL tokens (HMAC).

---

## 8. Migration History

| Revision | Date | Description |
|----------|------|-------------|
| `cfdc1f5bd7e2` | 2026-02-12 | Initial empty migration |
| `ab41ae86a62f` | 2026-02-13 | Create auth tables (users, roles, user_roles) |
| `3d5778831721` | 2026-02-13 | Create dataset and ingest job tables |
| `b5b423cf12d4` | 2026-02-13 | Add search vector, audit logs, visibility |
| `a1c3e7f29d04` | 2026-02-13 | Add saved searches |
| `bb15dd0e5c55` | 2026-02-13 | Add attribute search (sample_values column) |
| `c7d3a8e01f42` | 2026-02-13 | Add quality score |
| *(10-series)* | 2026-02-14 | Add API keys table |
| *(14-series)* | 2026-02-14 | Deduplicate saved searches, normalize geometry types |
| *(17-series)* | 2026-02-14 | Add user status field, fix FK cascade rules to SET NULL |
| *(18-series)* | 2026-02-14 | Change ingest_jobs.dataset_id FK to SET NULL |
| *(19-series)* | 2026-02-14 | Add user_metadata JSONB to ingest_jobs |
| *(28-series)* | 2026-02-15 | Add collections and dataset versions |

---

## 9. Data Flow

```
File Upload
    │
    ▼
ingest_jobs (status: pending → running)
    │
    ├── ogr2ogr → data.ds_<hash> (geom column, source attributes)
    ├── clip_to_mercator_bounds() → clips geom to ±85.06° lat
    ├── add_4326_column() → geom_4326 with spatial index
    ├── grant_reader_access() → SELECT to geolens_reader
    ├── extract_metadata() → populates datasets row
    └── compute_quality_score() → quality_score JSONB
    │
    ▼
ingest_jobs (status: complete), datasets row created
    │
    ▼
Tile gateway serves data.ds_<hash> via ST_AsMVT
```

---

## 10. Current Data Inventory

| Table | Rows | Total Size |
|-------|------|------------|
| `data.ds_305e27fcf7a2` | 49,183 | 213 MB |
| `data.ds_4e845e8b3cf2` | 25,413 | 84 MB |
| `data.ds_cb82dccfe308` | 56,600 | 71 MB |
| `data.ds_910b711e93d2` | 4,596 | 61 MB |
| `data.ds_6070caf18a99` | 258 | 14 MB |
| `data.ds_29476a5ddae7` | 177 | 1.2 MB |
| `data.ds_8753049304ca` | 243 | 264 KB |
| `data.ds_c4bb4eac829f` | 243 | 264 KB |
| `data.ds_ed0ac0b39d11` | 13 | 160 KB |
| **Catalog tables** | | ~1.8 MB total |
| catalog.audit_logs | 170 | 160 KB |
| catalog.datasets | 9 | 928 KB |
| catalog.ingest_jobs | 30 | 32 KB |
| catalog.api_keys | 28 | 40 KB |
