# GeoLens Admin Guide

Operations guide for managing users, datasets, search, exports, and system health.

All API examples use the frontend URL (`http://localhost:8080`), which proxies `/api/*` requests to the backend in development. In production, point at whatever URL your reverse proxy or load balancer terminates on. Obtain a JWT token first:

```bash
TOKEN=$(curl -s -X POST http://localhost:8080/api/auth/login \
  -d "username=admin&password=admin" | jq -r '.access_token')
```

---

## 1. User Management

GeoLens uses role-based access control with three roles:

| Role | Permissions |
|---|---|
| **admin** | Full access: manage users, all datasets, system settings, audit logs |
| **editor** | Create and edit datasets, upload files, export data |
| **viewer** | Read-only access to datasets they are permitted to see |

### Create a user

```bash
curl -X POST http://localhost:8080/api/admin/users \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "analyst1",
    "password": "secure-password",
    "role": "editor"
  }'
```

### List all users

```bash
curl http://localhost:8080/api/admin/users \
  -H "Authorization: Bearer $TOKEN"
```

Supports pagination: `?skip=0&limit=50`

### Get a specific user

```bash
curl http://localhost:8080/api/admin/users/{user_id} \
  -H "Authorization: Bearer $TOKEN"
```

### Update a user

```bash
curl -X PATCH http://localhost:8080/api/admin/users/{user_id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role": "admin"}'
```

### Deactivate a user

Deactivating a user prevents them from logging in without deleting their data:

```bash
curl -X POST http://localhost:8080/api/admin/users/{user_id}/deactivate \
  -H "Authorization: Bearer $TOKEN"
```

---

## 2. Dataset Ingestion

GeoLens supports two ingestion methods: file upload and PostGIS table registration.

### Supported file formats

| Format | Extension | Notes |
|---|---|---|
| Shapefile | `.zip` | Zipped archive containing .shp, .dbf, .shx, .prj |
| GeoPackage | `.gpkg` | Recommended for complex datasets |
| GeoJSON | `.geojson`, `.json` | UTF-8 encoded |
| CSV | `.csv` | Must have lat/lon columns or WKT geometry; defaults to EPSG:4326 |
| GeoTIFF / COG | `.tif`, `.tiff` | Cloud-Optimized GeoTIFF recommended for raster datasets |
| Excel | `.xlsx`, `.xls` | Must have lat/lon columns or WKT geometry |

### Upload a file

```bash
curl -X POST http://localhost:8080/api/ingest/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/data.gpkg"
```

Response:

```json
{
  "job_id": "abc-123",
  "status": "pending",
  "message": "File queued for ingestion"
}
```

The file is processed asynchronously by the Procrastinate job queue. During ingestion:

1. The file is saved to the staging directory
2. GDAL/OGR loads the data into a PostGIS table in the `data` schema
3. A 4326 reprojected geometry column (`geom_4326`) is added with a spatial index
4. Metadata is extracted: SRID, geometry type, feature count, extent, column info
5. Sample values are extracted (up to 10 distinct values per column from first 1000 rows)
6. A quality score is computed
7. The `catalog.datasets` record is updated with all metadata

Maximum upload size: 500 MB (configurable via `UPLOAD_MAX_SIZE_MB`).

### Register an existing PostGIS table

If data is already loaded into the `data` schema:

```bash
curl -X POST http://localhost:8080/api/ingest/register \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "table_name": "my_existing_table",
    "name": "My Dataset",
    "description": "An existing table registered as a dataset"
  }'
```

The table must exist in the `data` schema and have a `geom` geometry column.

---

## 3. Dataset Management

### List all datasets

```bash
curl http://localhost:8080/api/datasets/ \
  -H "Authorization: Bearer $TOKEN"
```

Supports pagination: `?skip=0&limit=50`

### Get a single dataset

```bash
curl http://localhost:8080/api/datasets/{dataset_id} \
  -H "Authorization: Bearer $TOKEN"
```

The response includes all metadata: name, description, tags, SRID, geometry type, feature count, extent bounding box, column info, quality score, visibility, and timestamps.

### Update dataset metadata

Admins and editors can update user-editable metadata fields:

```bash
curl -X PATCH http://localhost:8080/api/datasets/{dataset_id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Updated Name",
    "description": "Better description for discoverability",
    "tags": ["hydrology", "water", "nyc"],
    "contact": {"name": "Jane Doe", "email": "jane@org.com"},
    "license": "CC-BY-4.0",
    "source_organization": "Department of Environmental Protection",
    "data_vintage_start": "2023-01-01",
    "data_vintage_end": "2023-12-31"
  }'
```

### Dataset visibility

Datasets have three visibility levels:

| Visibility | Who can see it |
|---|---|
| `public` | All authenticated users |
| `private` | Only the owner and admins |
| `restricted` | Users with explicit role-based grants |

Visibility is set during ingestion or via metadata update.

### View dataset rows

```bash
curl "http://localhost:8080/api/datasets/{dataset_id}/rows?limit=10&offset=0" \
  -H "Authorization: Bearer $TOKEN"
```

Returns paginated attribute data from the underlying PostGIS table.

---

## 4. Search Configuration

GeoLens provides full-text search, spatial search, and faceted filtering.

### How search works

The search system uses PostgreSQL full-text search with a weighted `tsvector` generated column:

| Weight | Field | Priority |
|---|---|---|
| A (highest) | Dataset name | Primary match |
| B | Description | Secondary match |
| C | Tags | Tertiary match |
| D (lowest) | Column names, sample values | Attribute-level match |

The `websearch_to_tsquery` function supports natural language queries: `"water AND infrastructure"`, `"NOT deprecated"`, `"rivers OR streams"`.

### Search examples

```bash
# Full-text search
curl "http://localhost:8080/api/search/datasets?q=water+infrastructure" \
  -H "Authorization: Bearer $TOKEN"

# Spatial search (bounding box: minx,miny,maxx,maxy)
curl "http://localhost:8080/api/search/datasets?bbox=-74.1,40.6,-73.8,40.9" \
  -H "Authorization: Bearer $TOKEN"

# Faceted filters
curl "http://localhost:8080/api/search/datasets?geometry_type=Point&srid=4326&tags=emergency" \
  -H "Authorization: Bearer $TOKEN"

# Combined search with sorting and pagination
curl "http://localhost:8080/api/search/datasets?q=roads&sort_by=name&limit=20&offset=0" \
  -H "Authorization: Bearer $TOKEN"
```

### Available filters

| Parameter | Type | Description |
|---|---|---|
| `q` | string | Full-text search query |
| `bbox` | string | Bounding box: `minx,miny,maxx,maxy` (WGS84) |
| `tags` | string[] | Filter by tags |
| `geometry_type` | string | Filter by geometry type (Point, MultiPolygon, etc.) |
| `srid` | integer | Filter by coordinate reference system |
| `source_organization` | string | Filter by source organization |
| `date_from` / `date_to` | date | Filter by creation date |
| `vintage_start` / `vintage_end` | date | Filter by data vintage range |
| `sort_by` | string | Sort: `relevance`, `date_added`, `name`, `last_updated` |
| `offset` / `limit` | integer | Pagination |

### OGC API Records

The search is also available via the OGC API Records standard:

```bash
# List collections
curl http://localhost:8080/api/collections \
  -H "Authorization: Bearer $TOKEN"

# Search items
curl "http://localhost:8080/api/collections/datasets/items?q=water" \
  -H "Authorization: Bearer $TOKEN"

# Get single record
curl http://localhost:8080/api/collections/datasets/items/{dataset_id} \
  -H "Authorization: Bearer $TOKEN"
```

### Saved searches

Users can save search queries for reuse:

```bash
# Save a search
curl -X POST http://localhost:8080/api/search/saved \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "NYC Water Data",
    "params": {"q": "water", "bbox": "-74.3,40.4,-73.7,40.95"}
  }'

# List saved searches
curl http://localhost:8080/api/search/saved \
  -H "Authorization: Bearer $TOKEN"

# Load a saved search
curl http://localhost:8080/api/search/saved/{search_id} \
  -H "Authorization: Bearer $TOKEN"

# Delete a saved search
curl -X DELETE http://localhost:8080/api/search/saved/{search_id} \
  -H "Authorization: Bearer $TOKEN"
```

Saved searches are private to each user (ownership-enforced).

---

## 5. Data Quality

Each dataset receives a quality score computed during ingestion.

### Score dimensions

| Dimension | Weight | Description |
|---|---|---|
| Metadata completeness | 30% | Percentage of optional metadata fields filled (description, tags, contact, license, source organization, data vintage) |
| Geometry validity | 30% | Percentage of geometries passing `ST_IsValid` (sampled from first 10,000 features) |
| Attribute completeness | 25% | Average non-null percentage across all non-geometry columns |
| CRS defined | 15% | 100 if SRID is set, 0 otherwise |

### Improving quality scores

To improve a dataset's quality score:

1. **Add metadata**: Fill in description, tags, contact, license, source organization, and data vintage via the PATCH endpoint
2. **Fix geometries**: Use `ST_MakeValid` in PostGIS to repair invalid geometries
3. **Fill null attributes**: Reduce null values in data columns
4. **Set CRS**: Ensure the data has a defined coordinate reference system

The quality score is visible in:
- Search results (`properties.quality_score`)
- Dataset detail responses (`quality_score`)
- The web UI quality badge

---

## 6. Export

### Export a dataset

```bash
# GeoPackage (default)
curl -o output.gpkg \
  "http://localhost:8080/api/datasets/{dataset_id}/export" \
  -H "Authorization: Bearer $TOKEN"

# GeoJSON
curl -o output.geojson \
  "http://localhost:8080/api/datasets/{dataset_id}/export?format=geojson" \
  -H "Authorization: Bearer $TOKEN"

# Shapefile (returns zip)
curl -o output.zip \
  "http://localhost:8080/api/datasets/{dataset_id}/export?format=shp" \
  -H "Authorization: Bearer $TOKEN"

# CSV
curl -o output.csv \
  "http://localhost:8080/api/datasets/{dataset_id}/export?format=csv" \
  -H "Authorization: Bearer $TOKEN"
```

### Export options

| Parameter | Description | Example |
|---|---|---|
| `format` | Output format: `gpkg`, `geojson`, `shp`, `csv` | `format=geojson` |
| `target_crs` | Reproject to a different CRS | `target_crs=EPSG:3857` |
| `bbox` | Spatial filter (WGS84) | `bbox=-74.1,40.6,-73.8,40.9` |
| `where` | Attribute filter expression | `where=pop > 1000` |

### CRS reprojection

```bash
# Export in Web Mercator
curl -o output_3857.gpkg \
  "http://localhost:8080/api/datasets/{dataset_id}/export?target_crs=EPSG:3857" \
  -H "Authorization: Bearer $TOKEN"
```

### Filtered export

```bash
# Export only features within a bounding box where population > 10000
curl -o filtered.geojson \
  "http://localhost:8080/api/datasets/{dataset_id}/export?format=geojson&bbox=-74.1,40.6,-73.8,40.9&where=population > 10000" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 7. OGC API Access (QGIS, ArcGIS)

GeoLens serves vector tiles via a FastAPI tile gateway (ST_AsMVT) with signed URL token authentication, and OGC features via the FastAPI backend.

### Vector Tiles

Access vector tiles at:

```
http://localhost:8080/api/tiles/{dataset_id}/{z}/{x}/{y}.pbf?token=<signed-token>
```

Tile tokens are obtained via the `/api/tiles/token` endpoint.

### OGC Features (FastAPI)

Access OGC features at:

```
http://localhost:8080/api/datasets/{dataset_id}/features/
```

### Connecting QGIS

1. Open QGIS and go to Layer > Add Layer > Add Vector Tile Layer
2. Create a new connection:
   - **URL**: `http://localhost:8080/api/tiles/{dataset_id}/{z}/{x}/{y}.pbf?token=<signed-token>`
3. Click Connect and add the layer

For OGC Features (GeoJSON):
1. Layer > Add Layer > Add Vector Layer
2. Use the GeoJSON URL: `http://localhost:8080/api/datasets/{dataset_id}/features/`
3. Add a custom HTTP header: `Authorization: Bearer <your-token>`

### Connecting ArcGIS Pro

1. Insert > Connections > New Vector Tile Service
2. URL: `http://localhost:8080/api/tiles/{dataset_id}/{z}/{x}/{y}.pbf?token=<signed-token>`
3. Obtain a signed tile token from the `/api/tiles/token` endpoint

---

## 8. Monitoring

### Health endpoints

```bash
# Application health (via frontend proxy)
curl http://localhost:8080/health

# Direct API health
curl http://localhost:8001/health
```

### Docker service health

```bash
# View all service statuses
docker compose ps

# Check specific service
docker compose ps db
docker compose ps api
```

### Logs

```bash
# Follow all logs
docker compose logs -f

# Follow specific service logs
docker compose logs -f api
docker compose logs -f db

# Last 100 lines
docker compose logs --tail=100 api
```

### Audit logs

Admin users can query the audit log for dataset access and modification history:

```bash
# All audit logs
curl "http://localhost:8080/api/admin/audit-logs" \
  -H "Authorization: Bearer $TOKEN"

# Filter by action
curl "http://localhost:8080/api/admin/audit-logs?action=dataset.export" \
  -H "Authorization: Bearer $TOKEN"

# Filter by user and date range
curl "http://localhost:8080/api/admin/audit-logs?user_id={user_id}&date_from=2024-01-01" \
  -H "Authorization: Bearer $TOKEN"
```

Available audit actions: `dataset.view`, `dataset.export`, `dataset.download_cog`, `metadata.edit`, `collection.create`, `collection.update`, `collection.delete`, `collection.add_datasets`, `collection.remove_dataset`, `map.create`, `map.update`, `map.delete`, `map.duplicate`, `map.share`, `map.update_share_token`, `map.revoke_share`, `map.add_layer`, `map.remove_layer`, `feature.insert`, `feature.replace`, `feature.update`, `feature.delete`, `embed_token.create`, `embed_token.update`, `embed_token.revoke`, `embed_token.bulk_revoke`, `oauth_provider.create`, `oauth_provider.update`, `oauth_provider.delete`, `config_import`, `update`, `reset`, `probe_service`, `preview_service_layer`

### Catalog statistics

```bash
curl http://localhost:8080/api/admin/stats \
  -H "Authorization: Bearer $TOKEN"
```

Returns: total datasets, recent additions (30 days), total storage bytes, datasets by geometry type, datasets by visibility.

### Database size

```bash
docker compose exec db psql -U geolens -d geolens -c "
  SELECT pg_size_pretty(pg_database_size('geolens')) AS db_size;
"
```

Per-table sizes:

```bash
docker compose exec db psql -U geolens -d geolens -c "
  SELECT table_name,
         pg_size_pretty(pg_total_relation_size('data.' || table_name)) AS size
  FROM catalog.datasets
  ORDER BY pg_total_relation_size('data.' || table_name) DESC;
"
```

---

### 8.1 Admin UI Pages

The admin web UI (`/admin`) is the day-to-day operator interface. The most useful pages besides Users and Settings are:

#### Audit Log (`/admin/audit`)

Browse and filter the full audit log with action, user, resource, and date filters. Supports CSV and JSON export of the current filter view via the toolbar download button. Use this page to investigate "who changed what" without writing API queries.

#### Jobs (`/admin/jobs`)

Lists all ingestion jobs across all users with status, source filename, and timing. Failed jobs link to the error message and the user who started them. Useful for triaging stuck or repeatedly failing imports.

#### Shared Maps (`/admin/shared-maps`)

System-wide view of every share token and embed token created on the instance. Shows map title, owner, expiry, allowed origins, and view count. Tokens can be revoked from this page without finding the parent map first. Use this to audit external sharing, especially before public events or when rotating leaked tokens.

#### Config Ops (`/admin/config-ops`)

Export the entire instance configuration (settings + OAuth providers, secrets redacted) as a JSON file, or import a previously exported configuration in either `merge` or `overwrite` mode. The dry-run button shows exactly what would change before applying anything. Use this to copy configuration between dev/staging/prod instances or to back up settings before major upgrades.

The companion **Validate Connectivity** button probes storage, cache, and every enabled OIDC provider and reports per-provider latency and error details — useful for diagnosing post-deployment issues without SSH access.

---

## 9. Backup and Restore

### Database backup

Create a full database dump:

```bash
docker compose exec db pg_dump -U geolens -d geolens -Fc -f /tmp/geolens_backup.dump
docker compose cp db:/tmp/geolens_backup.dump ./geolens_backup.dump
```

For a plain SQL backup:

```bash
docker compose exec db pg_dump -U geolens -d geolens > geolens_backup.sql
```

### Scheduled backups

Add a cron job on the host:

```bash
# Daily backup at 2 AM
0 2 * * * cd /path/to/geolens && docker compose exec -T db pg_dump -U geolens -d geolens -Fc > /backups/geolens_$(date +\%Y\%m\%d).dump
```

### Restore from backup

```bash
# Stop the API to prevent writes
docker compose stop api

# Restore
docker compose cp ./geolens_backup.dump db:/tmp/geolens_backup.dump
docker compose exec db pg_restore -U geolens -d geolens --clean /tmp/geolens_backup.dump

# Restart
docker compose start api
```

### Volume backup

For a full volume-level backup:

```bash
# Stop services
docker compose down

# Backup the pgdata volume
docker run --rm -v geolens_pgdata:/data -v $(pwd):/backup alpine tar czf /backup/pgdata_backup.tar.gz -C /data .

# Restart
docker compose up -d
```

### Restore volume

```bash
docker compose down
docker run --rm -v geolens_pgdata:/data -v $(pwd):/backup alpine sh -c "rm -rf /data/* && tar xzf /backup/pgdata_backup.tar.gz -C /data"
docker compose up -d
```

---

## 10. OAuth / OIDC Single Sign-On

GeoLens supports external identity providers via OAuth 2.0 / OpenID Connect. Supported provider types are **Google**, **Microsoft (Entra ID)**, and **generic OIDC**.

All OAuth flows use **PKCE** (Proof Key for Code Exchange, S256) automatically. Client secrets are encrypted at rest using Fernet encryption derived from the application's `JWT_SECRET_KEY`.

### How it works

1. A user clicks an OAuth provider button on the login page
2. GeoLens redirects to the IdP authorization endpoint with PKCE parameters
3. The IdP authenticates the user and redirects back to `/api/auth/oauth/{slug}/callback`
4. GeoLens exchanges the authorization code for tokens, fetches user info, and either links to an existing account (by email match) or creates a new local user
5. A GeoLens JWT is issued and the user is redirected to the frontend

### Configuring providers via the Admin UI

The simplest way to configure OAuth is through the admin settings panel:

1. Navigate to **Admin > Settings > Authentication**
2. Scroll to the **OAuth Providers** section
3. Click **Add Provider**
4. Select the provider type, fill in the required fields, and click **Create**

Providers can be enabled, disabled, edited, or deleted from the same panel.

### Configuring providers via the API

Providers can also be managed programmatically. All endpoints require the `manage_settings` permission (admin role).

#### Create a provider

```bash
curl -X POST http://localhost:8080/api/settings/oauth-providers/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "google",
    "display_name": "Google",
    "provider_type": "google",
    "client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com",
    "client_secret": "YOUR_CLIENT_SECRET",
    "discovery_url": "https://accounts.google.com/.well-known/openid-configuration",
    "scopes": "openid profile email",
    "default_role": "viewer",
    "enabled": true
  }'
```

#### List providers

```bash
curl http://localhost:8080/api/settings/oauth-providers/ \
  -H "Authorization: Bearer $TOKEN"
```

The response never includes the `client_secret`. Secrets are write-only.

#### Update a provider

```bash
curl -X PATCH http://localhost:8080/api/settings/oauth-providers/{provider_id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

Only include `client_secret` in the update payload if you need to rotate it. Omitting it preserves the existing secret.

#### Delete a provider

```bash
curl -X DELETE http://localhost:8080/api/settings/oauth-providers/{provider_id} \
  -H "Authorization: Bearer $TOKEN"
```

Deleting a provider also removes all linked OAuth accounts for that provider.

### Provider configuration reference

| Field | Required | Description |
|---|---|---|
| `slug` | Yes | URL-safe identifier used in callback URLs (e.g. `google`, `azure-ad`) |
| `display_name` | Yes | Label shown on the login page button |
| `provider_type` | Yes | One of: `google`, `microsoft`, `oidc` |
| `client_id` | Yes | OAuth client ID from the IdP |
| `client_secret` | Yes | OAuth client secret |
| `discovery_url` | No | OIDC discovery URL (`.well-known/openid-configuration`). Auto-populates for Google and Microsoft |
| `authorize_url` | No | Authorization endpoint (only needed if `discovery_url` is not set) |
| `token_url` | No | Token endpoint (only needed if `discovery_url` is not set) |
| `userinfo_url` | No | Userinfo endpoint (only needed if `discovery_url` is not set) |
| `scopes` | No | Space-separated scopes. Default: `openid profile email` |
| `default_role` | No | Role assigned to new users: `viewer`, `editor`, or `admin`. Default: `viewer` |
| `group_claim` | No | JWT claim containing group memberships (e.g. `groups`) |
| `group_role_mapping` | No | JSON object mapping IdP group names to GeoLens roles |
| `enabled` | No | Whether the provider appears on the login page. Default: `true` |

### Step-by-step: Google OAuth

1. Go to the [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create a new **OAuth 2.0 Client ID** (application type: Web application)
3. Add the authorized redirect URI:
   ```
   https://your-geolens-host/api/auth/oauth/google/callback
   ```
4. Copy the **Client ID** and **Client Secret**
5. In GeoLens, create the provider (UI or API):

```bash
curl -X POST http://localhost:8080/api/settings/oauth-providers/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "google",
    "display_name": "Google",
    "provider_type": "google",
    "client_id": "123456789.apps.googleusercontent.com",
    "client_secret": "GOCSPX-xxxxxxxxxxxx",
    "discovery_url": "https://accounts.google.com/.well-known/openid-configuration",
    "scopes": "openid profile email",
    "default_role": "viewer",
    "enabled": true
  }'
```

6. The "Sign in with Google" button will appear on the login page immediately

### Step-by-step: Microsoft Entra ID

1. In the [Azure Portal](https://portal.azure.com), go to **Microsoft Entra ID > App registrations > New registration**
2. Set the redirect URI to:
   ```
   https://your-geolens-host/api/auth/oauth/microsoft/callback
   ```
3. Under **Certificates & secrets**, create a new client secret
4. Note your **Application (client) ID**, **Directory (tenant) ID**, and the secret value
5. Create the provider in GeoLens:

```bash
curl -X POST http://localhost:8080/api/settings/oauth-providers/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "microsoft",
    "display_name": "Microsoft",
    "provider_type": "microsoft",
    "client_id": "YOUR_APPLICATION_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET_VALUE",
    "discovery_url": "https://login.microsoftonline.com/YOUR_TENANT_ID/v2.0/.well-known/openid-configuration",
    "scopes": "openid profile email",
    "default_role": "viewer",
    "enabled": true
  }'
```

### Step-by-step: Generic OIDC

For any OIDC-compliant provider (Keycloak, Okta, Auth0, etc.):

1. Register a new application in your IdP
2. Set the redirect URI to:
   ```
   https://your-geolens-host/api/auth/oauth/{slug}/callback
   ```
   Replace `{slug}` with whatever slug you plan to use (e.g. `keycloak`, `okta`)
3. If the IdP publishes a discovery document, use `discovery_url`. Otherwise, provide `authorize_url`, `token_url`, and `userinfo_url` explicitly:

```bash
curl -X POST http://localhost:8080/api/settings/oauth-providers/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "keycloak",
    "display_name": "Keycloak",
    "provider_type": "oidc",
    "client_id": "geolens",
    "client_secret": "your-keycloak-secret",
    "discovery_url": "https://keycloak.example.com/realms/main/.well-known/openid-configuration",
    "scopes": "openid profile email",
    "default_role": "editor",
    "enabled": true
  }'
```

### Group-to-role mapping

If your IdP includes group memberships in the ID token or userinfo response, you can map those groups to GeoLens roles automatically.

1. Set `group_claim` to the name of the claim containing group names (commonly `groups`)
2. Set `group_role_mapping` to a JSON object mapping group names to roles:

```json
{
  "GeoLens-Admins": "admin",
  "GeoLens-Editors": "editor",
  "GeoLens-Viewers": "viewer"
}
```

The first matching group wins. If no groups match, the `default_role` is used.

Example with the API:

```bash
curl -X PATCH http://localhost:8080/api/settings/oauth-providers/{provider_id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "group_claim": "groups",
    "group_role_mapping": {
      "GIS-Admins": "admin",
      "GIS-Staff": "editor"
    }
  }'
```

### User account linking

When a user signs in via OAuth:

- If they have previously signed in with the same provider and subject ID, they are logged in to the existing account
- If no prior OAuth link exists but a local user has the same email address (case-insensitive), the OAuth identity is linked to that existing user
- Otherwise, a new user account is created with a username derived from the email prefix or display name

This means existing local users can start using OAuth without losing their data -- as long as the email addresses match.
