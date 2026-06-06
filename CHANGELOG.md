# Changelog

All notable public changes to GeoLens are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and releases use semantic versioning.

## [Unreleased]

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
