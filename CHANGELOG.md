# Changelog

All notable public changes to GeoLens are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and releases use semantic versioning.

## [Unreleased]

## [1.4.2] - 2026-07-01

### Changed

- **Public API reference no longer lists edition, SAML, or audit-log-export
  operations.** The SAML-to-local conversion and audit-log export endpoints are
  excluded from the published OpenAPI schema and the generated docs API
  reference, alongside the edition and enterprise-tabs endpoints that were
  already hidden. The endpoints still work at runtime for administrators; only
  their listing in the public schema is removed. The Python and TypeScript SDKs
  are regenerated to match.

## [1.4.1] - 2026-06-28

### Changed

- **Automated database backups now run by default.** The `backup` service
  (scheduled `pg_dump` + object-storage archive, with daily/weekly retention)
  previously required opting in via `--profile backup`; it now runs on every
  `docker compose up`. Configure schedule and retention with the `BACKUP_*`
  environment variables. Off-site S3 upload remains gated on
  `BACKUP_S3_ENABLED=true` and signs with AWS Signature V4 (Cloudflare R2,
  modern AWS S3, and MinIO compatible).
- **The map builder's AI assistant is available to anyone who can view a map.**
  Viewers — not just the map's owner — can now ask the assistant questions about
  a map's data (counts, statistics, spatial analysis). Using the AI to *edit* a
  map remains limited to the owner, and AI-suggested changes still only persist
  when the owner saves the map.
- **Custom share-link expiration is an advanced sharing control.**
  The backend now enforces the same edition gate the UI already applied; basic
  Community share/revoke is unchanged.
- **Vector tiles send an ETag.** Re-uploaded datasets now refresh in the map
  without waiting for the cache TTL to expire.
- **Editors with AI-chat permission can use builder chat.** Non-admin users
  granted `use_ai_chat` can now open the Map Builder AI assistant when AI is
  configured.

### Added

- **Color map clusters by size.** Clustered point layers in the Map Builder can
  now be colored by cluster size (point count) via a configurable step ramp —
  toggle "Color by cluster size" in the cluster style controls and tune the
  per-tier breakpoints. Default breakpoints are tuned to be visible on typical
  datasets.
- **Standalone `geolens-backup` image.** A multi-arch (amd64 + arm64)
  `geolens-backup` image is now published to GHCR alongside the api, worker, and
  frontend images, so prebuilt installs run backups without a local build.

### Security

- **Embed tokens are now revoked when sharing is withdrawn.** Revoking a share,
  switching a map from public to private, or removing the dataset an embed was
  scoped to now immediately invalidates the corresponding embed tokens (and
  their cached access), so copied iframe/tile URLs can no longer outlive the
  map's sharing state.
- **Per-token iframe domain enforcement on the embed shell.** Restricted embeds
  now serve a token-specific `Content-Security-Policy: frame-ancestors` so the
  embedded document itself is protected by the configured domain allowlist, not
  only the underlying data/tile calls. Unrestricted (Community) embeds remain
  openly frameable; normal app routes keep `SAMEORIGIN`.

### Fixed

- **AI assistant no longer fails with a generic error on maps you don't own.**
  Asking the builder's AI about a map you can view but not edit previously
  surfaced "Something went wrong. Please try again." with a retry that never
  worked; it now answers read-only questions, and genuine permission errors
  show a clear, non-retryable message instead of a blind retry.
- **Map Builder correctness fixes.** Bulk visibility/opacity on a multi-layer
  selection now matches single-layer behavior (companion outlines, labels,
  hypsometric relief, and clusters included); numeric-column filters now show a
  removable chip; per-sublayer basemap opacity now composes with the master
  opacity slider instead of overriding it; switching a line to data-driven color
  clears stale gradient state; adding a dataset while you have unsaved edits now
  appears immediately; a folder group's visibility toggle now hides/shows every
  child layer; and drag-to-add from the catalog handle works reliably on touch.
- **Exported MapLibre styles render correctly.** Style export now emits the
  matching vector `source-layer`, the `cols=` columns needed for low-zoom
  data-driven/label/filter styling, a valid `raster-dem` terrain source, and the
  DEM color-relief layer — so a downloaded style loads with features, labels,
  terrain, and hypsometric tint intact.
- **AI chat undo no longer reverts an unrelated edit.** Clicking Undo on a chat
  query answer can no longer roll back an earlier style change from a previous
  turn.
- **Map builder, admin console, and search polish.** The builder's layer editor
  panel no longer scrolls the whole page; the admin "Published Maps" page now
  lists published maps (it previously always read as empty) and the admin sidebar
  shows live counts; per-user storage usage is reported honestly against the
  configured quota; deactivating a user now surfaces the specific server message;
  the catalog search box reads "Search the catalog"; and the light/dark theme
  toggle now lives only in the top-bar menu.

## [1.4.0] - 2026-06-20

This release adds the demo front door, outbound notifications, and
email-verified signup.

### Added

- **Login-as-landing / demo front door.** The root URL can now serve the login
  page directly as the landing experience, making it easier to present a
  self-hosted instance as a gated demo without a separate marketing layer.
  Controlled by a per-deployment setting; existing installs retain the default
  catalog home.
- **Google Sign-in (Google OAuth provider).** Operators can now enable Google as
  a social sign-in provider through the admin OAuth-providers configuration.
  Configuring the provider ID + client credentials is all that is required; users
  then sign in via the standard OAuth flow.
- **Per-user storage and upload quotas.** Administrators can cap per-user file
  storage and upload usage via admin settings. Quotas are enforced at upload
  time (HTTP 413/422 when exceeded) and are DB-configurable without a restart.
  Quotas are an operator guardrail enforced at upload submission, not an atomic
  billing/security boundary (concurrent uploads may marginally overshoot the
  dataset-count cap; tracked as #302).
- **Outbound notification channels (SMTP email + webhook).** A new notification
  port lets operators configure one or more outbound sinks — SMTP email or an
  HTTPS webhook — for server-side events. Connection parameters (host, port,
  TLS, credentials, webhook URL + secret) are managed in admin Network settings,
  with a test-send button to confirm delivery before relying on them.
- **Event-driven notifications.** Operators can subscribe individual events —
  new-user signup, ingest complete, ingest failure, health alert — to the
  configured notification channels via per-event toggles in admin settings.
  Each event type can be enabled or disabled independently.
- **Email-verified self-serve registration (optional, default OFF).** A new
  `EMAIL_VERIFICATION_REQUIRED` setting (default disabled) enables operator-gated
  self-serve signup with an email-verification step. When enabled, new
  registrations receive a verification email; accounts are activated only after
  the link is clicked. Requires outbound SMTP to be configured. The setting is
  default-disabled and has no effect on installs that do not set it. Known
  limitation: when this mode is enabled with SMTP, self-serve signup is not
  username-enumeration-safe — the HTTP response is uniform but a verification
  email is delivered only for a new (available) username, so a registrant can
  infer username existence out-of-band (tracked as #267). It is rate-limited and
  disabled by default.

### Fixed

- OSS OAuth provider creation no longer fails with a 500 when SAML columns are
  absent from the baseline schema. Migration `0008` adds the necessary columns
  conditionally, resolving the error for fresh installs and existing deployments
  that lack those optional SAML columns.

### Upgrade notes

- **No breaking changes for self-hosted operators.** Pull the new images and run
  the standard upgrade. Schema changes since 1.3.0 are additive migrations
  (`0008`–`0009`). All new features that require configuration (Google sign-in,
  outbound notifications, email-verified signup) are default-disabled; no action
  is needed to preserve existing behavior.

## [1.3.0] - 2026-06-18

This release includes hardening work, map-builder authoring improvements, and
self-hosted release/upgrade updates.

### Added

- **Data-driven classification in the map builder.** Numeric layers can now be
  styled with Jenks natural-breaks, standard-deviation, and manual class
  breaks in addition to the existing equal-interval/quantile schemes, making it
  easier to produce defensible choropleths from your own attribute data.
- **Color-ramp controls for accessible cartography.** Ramps can be reversed in
  place, and the picker now includes color-vision-deficiency-safe (CVD-safe)
  palettes so maps remain legible for color-blind viewers.
- **Per-layer legend customization.** Each layer's legend title and entry
  labels can be overridden independently of the layer name, so published
  legends can use human-readable wording without renaming the underlying
  layer. (Additive migration `0004_add_maps_legend_title`.)
- **Layer search in the builder stack.** Large maps gain a search box to filter
  the layer list by name, plus zoom-to-layer and copy/paste-style and
  bulk-style actions to speed up authoring multi-layer maps.
- **Raster/DEM authoring fidelity.** Adding raster layers now surfaces real
  band labels and band-count metadata, and hillshade/DEM styling reflects the
  actual source instead of placeholder defaults.
- **GeoDCAT-AP discovery profile.** A new GeoDCAT-AP (EU/INSPIRE geospatial
  profile of DCAT-AP) serialization is available alongside DCAT-3 and DCAT-US,
  with catalog, per-dataset, and validation endpoints — broadening
  interoperability with European government data portals.
- **Conformant-by-filtering DCAT feeds + DCAT-3 validation.** The DCAT-3,
  DCAT-US, and GeoDCAT-AP catalog feeds now emit only records that pass that
  profile's validator, so the feeds stay conformant without forcing metadata at
  publish time; incomplete records are skipped rather than emitted
  non-conformant. A DCAT-3 validation endpoint joins the existing DCAT-US one,
  and `REQUIRE_METADATA_FOR_PUBLISH` remains the optional stricter publish gate
  for deployments that prefer enforcement.
- **Terrain guard rails for small-extent DEMs.** 3D terrain now masks
  raster-DEM nodata in the elevation encoding (no more boundary spikes from a
  `-9999` fill) and warns when the active DEM covers only a small slice of the
  viewport, with docs recommending draping a high-res DEM over a coarse global
  DEM for small areas.

### Fixed

- Removed redundant "create" buttons on the empty Collections and Maps pages —
  the empty state now shows a single primary call-to-action instead of three.
- DCAT-US `rights`/usage-constraints now serialize as a list per the schema
  (previously a bare string), so records carrying usage constraints validate
  and appear in the conformant feed.
- Map-builder rendering and persistence correctness fixes: layer style updates
  no longer clobber sibling fields on multi-field restores, disabled strokes no
  longer resurrect on a visibility toggle, empty-array filters no longer break
  rendering, and solid↔pattern fill transitions clean up stale paint keys.
- Numerous backend correctness and robustness fixes across config/settings
  handling, ingest and raster lifecycle, API error shapes, and the CLI/SDK
  round-trip, each landing with a regression test. Performance fixes to several
  hot paths (tile and query routes, AI token budgeting) reduce latency and
  resource use under load.
- Frontend cache, auth, and internationalization fixes: stale cache and auth
  state are cleared more reliably, and locale key-existence/parity is enforced
  so translated strings cannot silently fall back to keys.
- **Raster/COG ingestion restored.** A regression made every raster, COG, and
  VRT-mosaic ingest fail (the STAC `dataset_assets` write resolved its ORM via
  the wrong internal port), so newly uploaded rasters never completed. Fixed,
  with a regression test; the STAC `dataset_assets` table is now populated as
  intended.
- **Public/shared map viewer renders data on first load.** Maps opened via a
  shared link or direct URL — especially 3D-terrain maps — could appear with
  only the basemap (and terrain mesh) because the data layers raced the map's
  style load and were never added. The viewer now retries the layer sync once
  the style settles, so the hillshade relief and all data layers render on a
  cold page load just as they do in the builder.

### Security

This release continues the hardening work from the 1.2.x security advisories
(`GHSA-p23g-mvhj-jh3j` and `GHSA-p77j-g7h5-r2vw`) with additional
regression-covered fixes:

- **Cross-resource re-authorization.** Endpoints that return sub-resources or
  follow references now re-authorize the backing dataset/map rather than
  trusting the URL-level resource, closing several paths where a caller could
  read data from a resource they were not entitled to.
- **Tile and asset privacy and caching.** Private raster and vector tiles and
  derived assets are no longer served with shared-cache headers, so a CDN or
  bundled reverse proxy cannot retain and replay them to later unauthenticated
  requests.
- **Input hardening.** Tightened validation and bounds across request inputs,
  outbound-URL handling, and the AI subsystem to reduce the attack surface for
  malformed or hostile inputs.

### Changed

- **Default-preserving migrations.** Added reversible migrations `0005`–`0007`
  and supporting runtime paths. Self-hosted installs keep the same default
  behavior, require no new configuration, and serve datasets, tiles, and maps
  the same way as before.

### Upgrade notes

- **No breaking changes for self-hosted operators.** The standard prebuilt
  upgrade applies — pull the new images and run the usual upgrade path (see
  [UPGRADING.md](./UPGRADING.md)). All schema changes since 1.2.4 are additive,
  reversible migrations (`0004`–`0007`); no configuration is removed or made
  mandatory. The deployment groundwork is dormant in the default configuration,
  so no action is required to adopt it.

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

- Database migrations upgrade cleanly on deployments of the core package; a
  migration-graph fork that caused `alembic upgrade head` to fail has been
  resolved.
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
