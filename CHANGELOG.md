# Changelog

All notable public changes to GeoLens are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and releases use semantic versioning.

## [Unreleased]

## [1.2.4] - 2026-06-11

### Security

- Record contact, keyword, and distribution sub-resources now re-authorize the
  backing dataset, so a private record's contact details and related metadata
  are no longer disclosed to authenticated users who cannot access that record.
- Private raster and vector tiles are no longer served with shared-cache
  headers. Tiles for non-public datasets are marked private so a shared cache
  (a CDN or the bundled reverse proxy) cannot retain and replay them to later
  unauthenticated requests, including unpublished public-dataset previews.
- The map visibility-check endpoint now authorizes read access to the map
  before reporting its non-public dataset names, so the titles of private
  datasets can no longer be enumerated through maps the caller cannot read.
- Outbound fetches of user-supplied URLs (service probes, STAC and OGC API
  sources, manifest downloads) now pin the validated IP address at connection
  time, closing a DNS-rebinding window where a hostname could resolve to a
  public address during validation and a private address at fetch time.
- The remote-service preview path now passes authorization tokens to GDAL
  through a private (0600) header file and rejects tokens containing control
  characters, preventing token disclosure through the process environment and
  HTTP header injection.
- The deployment's production security posture — API documentation exposure and
  the Secure flag on the OAuth session cookie — is now controlled by an explicit
  `ENVIRONMENT` setting instead of the `LOG_JSON` logging flag. Deployments that
  have not set `ENVIRONMENT` retain their previous behavior.
- The bundled reverse proxy now redacts the `api_key` query parameter from its
  access logs, so API keys passed in the query string are no longer written to
  logs in cleartext.
- The web application now ships a Content-Security-Policy restricting script
  sources, a defense-in-depth backstop against token exfiltration should a
  cross-site scripting issue ever be introduced.
- The STAC `POST /search` endpoint now caps the size of GeoJSON `intersects`
  geometries, matching the existing `GET` limit, to prevent an unauthenticated
  geometry-based denial of service.
- A fresh install now generates strong, unique database and admin passwords
  instead of keeping the published defaults, and no longer silently retains a
  default admin password on a headless (`curl | sh`) install.

### Fixed

- Database migrations upgrade cleanly on enterprise deployments of the core
  package; a migration-graph fork that caused `alembic upgrade head` to fail has
  been resolved.
- The background job queue now works on managed/external PostgreSQL configured
  via `DATABASE_URL_OVERRIDE`; the connection's schema search path was dropped,
  which broke job processing and data ingestion on those deployments.
- Admin-configured rate limits (login, global, semantic search, and basemap
  proxy) now take effect when changed, instead of being ignored until the
  service restarted.
- Automated off-site backups to S3-compatible storage now upload successfully;
  the request signature was computed incorrectly and every upload was rejected.

## [1.2.3] - 2026-06-10

### Security

- Map read endpoints, including anonymous and shared-map views, now re-authorize
  each layer's dataset. Layers backed by datasets the caller cannot access are
  omitted, and their signed vector-tile URLs no longer expose private tile data.
- OGC API – Records item lookup by `externalId` now enforces dataset visibility,
  so private catalog records are no longer disclosed to unauthenticated requests.
- Virtual raster (VRT) creation and source addition now authorize each source
  dataset against the caller, preventing one user from compositing another user's
  private raster into a VRT they own and reading its pixels back. VRT
  source-listing and status responses now omit members the caller cannot access.
- AI metadata-assist endpoints now authorize the requested dataset, preventing a
  user from generating drafts against another user's private dataset, which
  previously exposed that dataset's metadata, source, schema, and sample values.

## [1.2.0] - 2026-06-02

### Added

- Map plugins are the supported extension point for map-builder behavior.
- Share links support optional expiration timestamps and non-expiring links.
- Single-band raster styling now includes percentile and standard-deviation
  stretch controls.
- Layer labels expose clearer saved-state indicators in the map builder.

### Changed

- Renamed the legacy map-widget vocabulary to map plugins across API schemas,
  database columns, frontend labels, and generated SDK surfaces.
- Updated public package metadata to version `1.2.0` across the backend,
  frontend, CLI, and SDK packages.
- Simplified public documentation around installation, support routing, and
  release notes.

### Fixed

- Preserved map render-mode settings across save and reload.
- Improved share-link settings rendering for allowed origins, expiration
  presets, embeds, and exports.
- Tightened public docs examples so first-run API requests include an
  executable JWT minting flow.

### Removed

- Removed the dormant DEM contour-line control from the map builder.
- Removed public runbook stubs for deferred product surfaces.

## [1.1.0] - 2026-05-20

### Added — Map Builder API surface

- `GET /maps/` lists maps visible to the current user.
- `POST /maps/` creates a saved map.
- `GET /maps/{map_id}` returns a saved map and its metadata.
- `PUT /maps/{map_id}` updates map metadata and core view settings.
- `DELETE /maps/{map_id}` removes a saved map.
- `POST /maps/{map_id}/duplicate/` duplicates a saved map.
- `PATCH /maps/{map_id}/layers` reorders or updates map layers.
- `POST /maps/{map_id}/layers` adds a dataset layer to a map.
- `POST /maps/{map_id}/layers/bulk-delete` deletes multiple layers.
- `DELETE /maps/{map_id}/layers/{layer_id}` removes a single layer.
- `GET /maps/{map_id}/history` lists map revision history.
- `GET /maps/{map_id}/style.json` returns a MapLibre style document.
- `GET /maps/{map_id}/share/` returns the active share token hint.
- `POST /maps/{map_id}/share/` creates a share token.
- `PATCH /maps/{map_id}/share/` updates share-token expiration.
- `DELETE /maps/{map_id}/share/` revokes a share token.
- `GET /maps/{map_id}/thumbnail/` returns the saved thumbnail.
- `PUT /maps/{map_id}/thumbnail/` stores a map thumbnail.
- `POST /maps/import` imports a saved map payload.

### Changed

- `PUT /maps/{id}/thumbnail/` request body changed from `text/plain` to a
  structured payload so clients can validate thumbnail metadata consistently.

## [1.0.2] - 2026-05-05

### Fixed

- Hardened quickstart configuration examples and local development setup.
- Published packaging fixes for the install script, containers, CLI, and SDKs.
- Moved detailed product documentation to docs.getgeolens.com while keeping the
  repository README focused on orientation and local development.

## [1.0.1] - 2026-05-04

### Fixed

- Corrected release packaging metadata and generated SDK artifacts.
- Improved smoke-test coverage for the demo stack and CLI install path.

## [1.0.0] - 2026-05-03

### Added

- Initial public release of the GeoLens catalog, API, map builder, CLI, SDKs,
  Docker development stack, and public documentation entrypoints.
