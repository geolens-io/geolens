# Changelog

All notable public changes to GeoLens are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and releases use semantic versioning.

## [Unreleased]

### Fixed

- Tenant-ownership adoption no longer fails when a role that is a member of a gateway is dropped
  while the run is validating the cluster; the vanished member is skipped instead. (#1913)
- `make dev` preflight now judges a `.env` line whose key is empty or holds a tab the way docker
  compose loads it: a value compose cannot resolve is refused before the build instead of at
  compose load, and a multiline value under such a key no longer fails the check. (#1909)
- A raster replace or a dataset reupload that waited behind a feature edit, column change or
  tile-columns edit wrote back the tile cache version it had read before waiting, so the edit
  committed during the wait was served under a stale tile URL. Both worker swaps now roll the
  version atomically once they hold the catalog row, as the request side has since #1910. (#1911)
- A reupload could fail with a catalog-lock conflict instead of waiting when another operation
  briefly held the dataset's catalog row. The lock budget the table swap sets for its own DDL no
  longer carries over to the wait that follows it. (#1917)
- The import-commit and re-upload-commit doors accepted a service token containing control
  characters or whitespace when the job was an ArcGIS one, or one whose service type was not
  recorded. Both now answer 422 before anything is reserved or staged. WFS and OGC API Features
  commits already refused such a token at the door and are unchanged. (#1755)

## [1.18.1] - 2026-09-05

Security release. Upgrade is a plain image pull; there are no migrations.

### Security

- Uploaded files and archive members that GDAL would treat as instructions rather than data
  (driver documents, and SQLite or GeoPackage schemas declaring virtual tables that reference
  external files) could make the ingest preview and import read local files on the worker or
  contact remote hosts, returning the contents to the uploader. Every local-upload GDAL subprocess
  now runs under an input-driver allowlist derived from the declared upload format, a shared
  safe-env helper that skips pointer-following and network drivers, and a content check that
  identifies archive members by their bytes; the structural test requires all three. Reported by
  the 2026-09-04 security audit. (#1846, GHSA-hrf5-v3cq-frx5)
- The job context Procrastinate attaches to worker log records carried service-import credentials
  in cleartext on installs without a credential store, because the log redactor only scrubbed the
  message string. Structured extras are now deep-redacted, every wire shape of a registered
  credential is scrubbed, and `credential_ref` joins the denylist. (#1844)
- The deprecated `?api_key=` query-string lane authorized every method; it now authenticates
  read-only requests only, as its documentation always said. Header keys are unchanged. (#1845)
- A CQL2 filter with a large IN list made the OGC Features items endpoint rename query binds in
  quadratic time on the event loop, so a handful of anonymous requests could stall the API. The
  rename is a single pass, the compiled bind count is capped, and the filtered items route carries
  its own 10 requests per second per IP limit. (#1845)
- `GET /jobs/by-dataset/{id}` and the VRT generations listing returned another user's job fields
  (error text, who triggered it, warnings) to any signed-in reader of a published dataset; both now
  apply the same provenance gate as the refresh-run history, and a structural test requires a
  disclosure predicate on every route whose response carries those fields. (#1860)
- Minting an embed token snapshotted a map's datasets without a visibility check, so an owner who
  had lost access to a dataset could still mint a long-lived capability for it. The mint now
  applies the same filter as map updates and refuses with 403, matching the map routes. (#1860)
- The OAuth sign-in exchanged tokens and fetched user info through a plain HTTP client rather than
  the redirect-revalidating one, and never validated the endpoints a provider's discovery document
  named. Every OAuth request now goes through the SSRF-safe transport with redirects off, the four
  discovered endpoints are validated before use, and a malformed discovered endpoint is refused
  with the same 503 as a private one instead of a 500. (#1861)
- Service probes reported a blocked redirect as an invalid credential and could echo the
  redirect's hostname, and the ArcGIS preview reported it as an ogrinfo failure; both now answer
  the fixed refusal with one audit row. Three JSON readers lacked the depth guard, so a nested body
  could turn a probe, a source-health check, or a sign-in into a 500. Table discovery listed
  attempt-scoped staging tables as registrable. (#1858)

### Fixed

- Corrupt, encrypted, or unsupported-compression archive members are refused with the same coded
  422 as other unsafe uploads instead of failing the job with an unhandled error. (#1846)
- Deeply nested CQL2 filters return a coded 400 instead of a 500. (#1845)
- A failed token refresh reported success and retried with the dead token, and a refresh that
  failed while another tab had already rotated the token logged the tab out; the AI chat transcript
  in the browser survived logout in the same tab; unsaved dataset metadata drafts, including text
  still open in an editor, followed navigation and could be saved onto the next dataset. (#1862)
- Login page keeps its branding and the site footer at every width and no longer flashes the
  community badge before the edition setting has loaded; the import dropzone headline no longer doubles its
  verb and the success count is pluralised; a map created from a dataset opens on that dataset,
  including when the map loads after the layer; Downloads offers an authenticated download per
  export format; qualitative colour palettes assign distinct colours per category. (#1863)

### Upgrade notes

- OAuth providers configured with explicit endpoint URLs and reachable only through an
  `HTTPS_PROXY` lose that egress: the token exchange and user-info requests now use the same
  connection-pinning transport as discovery, which cannot honour an environment proxy. Discovery-
  configured providers were already in this position. (#1861)
- The embed-token mint refuses a dataset the minter cannot see with 403 instead of 400. (#1860)

- Deployments whose custom clients sent an API key in the query string for mutating requests must
  move the key to the `X-Api-Key` header.
- `.xlsx` and `.kmz` uploads now meet the archive safety checks at preview time rather than only at
  commit; the checks are the same.

## [1.18.0] - 2026-09-04

### Added

- **WFS and OGC API Features service imports now accept a username and
  password, or an API key in a custom header, instead of only a bearer
  token.** The import wizard's Service tab and the dataset refresh dialog both
  offer a method select: none, bearer token, username and password, or a named
  header. The credential is not stored with the dataset: it is validated,
  carried to the worker for that one job, and a refresh still asks for it
  again rather than remembering it. Job arguments carrying it are purged by
  the existing cleanup sweep once the job reaches a terminal state, the same
  way a bearer token's arguments already were. On the backend, the same four
  entry points that already handled a bearer token (probe, preview, commit,
  refresh) now compose the credential into the request GDAL and the OGC client
  actually send, and it is redacted from logs the same way a bearer token
  already was. Operators: this release renames the ingest job queue these
  imports run on to `ingest-auth-v2`. If you ever need to roll back to a
  release before this one, follow the queue-draining steps in RUNBOOK.md's
  upgrade-and-rollback section (§10) first, or affected imports are left stuck
  rather than picked up by the older worker (#1770, #1756, #1760, #1834).

- **Sign in to ArcGIS Online or a Portal for ArcGIS deployment directly from
  the import wizard, instead of pasting a token.** For an ArcGIS FeatureServer
  or MapServer URL, the Service tab and the refresh dialog now offer a
  username-and-password sign-in alongside the existing token field. GeoLens
  exchanges the credentials for a short-lived token through the portal's own
  sign-in service; the password is held only for that one request and cleared
  the moment it settles, success or failure. Repeated sign-in attempts against
  one ArcGIS account, or from one GeoLens user, are rate-limited, since an
  unlimited retry here would let one GeoLens user lock a colleague out of
  their own ArcGIS account (#1757, #1758, #1759, #1820).

- **The CLI can replace an uploaded dataset's data directly.** `geolens
  replace <dataset-id> <file>` wraps the same reupload flow the web app's
  Re-upload dialog already uses: it uploads the file, previews the detected
  layer, SRID and feature count, and asks for confirmation before
  committing. `--layer` picks a layer out of a multi-layer file instead of
  silently taking the first one, `--srid` overrides the detected SRID, and
  `--wait` polls the job to a terminal state and exits non-zero on failure.
  It refuses a dataset bound to a service, a STAC item, or a registered
  table, the same way the web dialog does, and points at `geolens refresh`
  instead (#1767).

- **An admin can reset another user's password.** A "Reset password" action
  on the user row opens a one-field dialog. The login page already told a
  locked-out user to contact an administrator, but until now an
  administrator had no way to actually do it. The reset revokes the
  account's existing sessions, refresh tokens, and API keys, the same way a
  self-service password change already does, so a leaked old password stops
  working immediately. The action is also available on an admin's own row,
  since it is the only in-app way back for an admin who is signed in but
  has forgotten their password (#1741, #1772).

- **A manifest source can declare a checksum to force re-import when a file
  changes under a stable URL.** `geolens apply` fingerprints a manifest
  entry from its declared fields, so a source that always points at the
  same URL, an ETL job's `latest.gpkg`, say, classified as up to date
  forever once imported, with no way to force a refresh short of renaming
  the file. A new `checksum` field on the source now feeds into that
  fingerprint, so bumping it reclassifies the entry for re-import. The
  field is declared, not verified: GeoLens does not fetch the source to
  check the declared digest against the file's actual bytes (#1773).

### Changed

- **The refresh dialog's token hint no longer promises a credential is
  "never stored."** A crashed worker can leave a failed job's arguments
  briefly readable before the cleanup sweep runs, so the copy now says the
  credential is used for this refresh only and is not stored with the
  dataset (#1759).

- **The reported match count on a large feature or record listing can now be
  an estimate, not an exact count.** Native feature listing and OGC Features
  `numberMatched` count exactly up to 20,000 matching rows; past that, the
  response reports the database planner's row estimate instead of paying for
  an exact count on every page. A response carrying an estimate sets a new
  `X-GeoLens-Number-Matched: estimated` header, so a client that needs to know
  can check for it. This is not an OpenAPI or SDK change (`numberMatched`
  keeps its existing place in both response schemas), but it is a contract
  change API consumers should know about: pagination follows the rows GeoLens
  actually fetched, not the reported count, so a `next` link is still reliable
  even when the total beside it is approximate (#1799).

- **`GET /search/datasets/` now declares a raster dataset's projection, grid,
  band, and nodata metadata on its response schema.** `proj:code`,
  `proj:shape`, `raster:bands`, `res_x`, and `res_y` were already computed and
  written onto the response, but were absent from the declared response model,
  so FastAPI silently stripped them before a client ever saw them; every
  compatibility check the map builder's VRT creator ran against those fields,
  CRS, grid alignment, band count, dtype, and nodata, was dead code against
  the real endpoint. The fields are now declared and regenerated
  `backend/openapi.json`, both SDKs, and the frontend's generated API types
  (#1805).

- **Three more error responses are now declared in the OpenAPI contract, both
  SDKs, and the frontend's generated API types.** All three were already
  raised at runtime, only undocumented: 409 on `POST /admin/api-keys/` for a
  pending, suspended, or deactivated target user, and 412 on both `GET
  /datasets/{dataset_id}/export` and `GET /datasets/{dataset_id}/download/cog`
  for a failed conditional-request precondition. No behavior changed; a
  generated client can now see these outcomes in its own types (#1783).

- **A new `DB_STATEMENT_TIMEOUT_SECONDS` setting bounds how long a single
  database statement can run inside an API request, default 300 seconds, 0
  disables it.** Nothing bounded statement execution before this; only
  checkout from the connection pool was bounded, not the query itself. It
  applies to every API transaction (the worker keeps running unbounded, since
  it legitimately runs a single statement for minutes while indexing or
  reprojecting a freshly ingested table). Operators: a query that previously
  ran to completion no matter how long it took now fails after five minutes by
  default; raise or disable the setting if a workload genuinely needs longer
  (#1804).

- **A new `/health/live` endpoint answers the process's own liveness, separate
  from `/health`,** which still checks the database, object store, and cache
  and answers unhealthy if any of them is down. The shipped api container
  healthcheck and the compose healthcheck now target `/health/live`. Operators
  with their own orchestrator and a liveness probe pointed at `/health` should
  move it to `/health/live`: a database, MinIO, or Valkey outage should not
  restart-loop an otherwise healthy api pod, which is what pointing liveness
  at a dependency-readiness endpoint causes. Readiness checks should stay on
  `/health` (#1804).

### Removed

- **Two undocumented search compatibility forms are gone.** `?cql2_filter_lang=...`
  (an alternate spelling of the published `filter-lang` parameter) and a JSON
  `keywords` request body on `GET /search/datasets/` were kept working after
  #1666 corrected the published OpenAPI contract, so a client generated from
  the older contract would not silently break. Both were accepted but never
  published, and the deprecation window has passed since #1666 shipped in
  1.16.0. A client generated from a pre-1.16.0 contract must regenerate
  against the current one. (#1671)

### Fixed

- **Switching import tabs no longer strands an in-progress upload, STAC
  import, or service import.** None of the Upload, STAC, or Service tabs
  kept their work alive across a tab switch: unmounting the form left the
  server's job running with nothing in the UI able to reconnect to it. All
  three now adopt an in-flight or already-finished attempt on remount
  instead of starting a duplicate. The same lane also closed a related race
  on the Upload tab, where a file dropped while a background query was
  still loading could be silently discarded by a fast tab switch (#1763,
  #1834).

- **Refreshing a dataset that needs a credential now fails immediately with
  a clear reason, instead of accepting the request and failing later in the
  background.** A dataset imported with a service token carried no record
  on its own row that it needed one, so a credential-less refresh was
  accepted and then failed inside the worker with copy meant for the
  original import, not a refresh. The refusal now happens at the door
  (#1754).

- **Import job status reliability fixes.** A failed status check on the job
  progress view shown during an active import previously left it spinning
  forever instead of showing an error; it now shows the failure with a way to
  start over or retry. That view can also cancel the job directly now:
  cancellation was previously reachable only from the admin job list and a
  dataset's refresh history, not from the view a user is actually watching
  while the import runs. Cancelling a re-upload while its file is still
  downloading to staging is now honored immediately instead of being silently
  discarded: a lock held for the whole download made every cancel attempt
  during that window fail and roll back the cancellation already recorded, so
  the job ran on for minutes after the user asked it to stop. Client timeouts
  are also raised to match what the server can actually take: a dataset
  re-upload's request used to time out client-side at 30 seconds well before a
  large, up to 500 MB, transfer could finish, and a file or service-import
  preview could similarly be aborted while its 60- to 300-second backend
  operation was still running; both now use a timeout matched to the
  server-side budget. A multipart upload's individual part upload had no stall
  detection at all, so a part stuck on a half-open connection could hang
  forever; it now aborts once progress stalls, rather than waiting on a flat
  deadline that a slow-but-active transfer could miss. An upload abandoned at
  the preview step, the owner simply walks away, is now recorded as cancelled
  instead of failed, so it stops appearing in the admin failed-jobs list for
  work that was never actually attempted. `geolens publish --wait` now exits
  non-zero and reports the real outcome for a failed, cancelled, or timed-out
  job, instead of printing "Published:" regardless (#1774, #1777, #1800,
  #1803).

- **Dataset and OGC API correctness fixes.** The table browser and the OGC
  Features and native feature-list endpoints raised a 500 or 503 for a
  dataset whose column happened to share a name with a SQL keyword (`desc`,
  `order`, `user`, and similar, common in ogr2ogr output from DBF fields),
  and the same endpoints raised a 503 for any property filter on a
  non-text column. Both now work correctly. STAC and OGC `/collections`
  paginated listings had no defined row order beyond the page's own
  contents, so a harvesting client following `rel=next` links could see a
  row twice or miss one; results are now consistently ordered. An OGC
  Records `datetime=` filter also matched every record with no temporal
  extent regardless of the date queried; it now only matches when the
  record's own timestamp does (#1793, #1799).

- **A raster dataset's published STAC metadata now matches the STAC Raster
  Extension's own shape.** A locally ingested raster serialized its band
  nodata value as a numeric string instead of a number, and a remotely
  described Cloud-Optimized GeoTIFF could publish an empty `raster:bands` band
  object instead of omitting one GeoLens has no data for; both violate the
  extension's schema and could break a strict STAC consumer such as pystac or
  rio-stac reading the item (#1803).

- **Editing a feature with an unclosed polygon ring no longer poisons every
  later bounding-box read of the dataset.** The write path validated
  geometry with a library that silently repairs an unclosed ring, then
  stored the caller's original, unrepaired GeoJSON. Every later request
  whose bounding box touched that feature raised an unhandled server error,
  reaching anonymous viewers of public datasets too. Feature writes now
  store the repaired geometry (#1780).

- **Map builder save conflicts are handled correctly instead of silently
  overwriting another editor's changes.** A save that failed because
  someone else had changed the map's layers in the meantime was misread as
  an unsupported request and escalated to a full overwrite of the server's
  layer set, undoing the other editor's work. A stale save now refetches
  the map and retries with the reconciled layer list instead (#1794).

- **Three more map builder rendering bugs are fixed.** Deleting one of two
  layers that share a deduplicated data source left the deleted layer's map
  graphics behind: no stack row, no legend entry, unclickable, and still baked
  into any capture taken afterward. A layer styled with per-category icons
  rendered every feature with the fallback icon below zoom 10, snapping to the
  correct icon only once zoom 10 was reached. And a layout or visibility edit
  made during a basemap swap could be dropped entirely, or replayed out of
  order once the swap settled, so a toggle made and then reverted during the
  swap could still land on the map showing the wrong state (#1794).

- **Two line-drawing and editing bugs are fixed.** A line layer's gradient
  could be edited into a non-ascending stop order, which maplibre-gl rejects
  outright and drops the whole gradient expression rather than the one bad
  stop; stop positions are now kept strictly ascending as they are edited. And
  the undo history kept while drawing or editing a feature grew without any
  limit, so a long drag or a long editing session held an ever-growing stack
  of snapshots in memory; it is now capped (#1795).

- **Admin settings fixes.** The Appearance tab's "Show Powered by GeoLens"
  toggle sent the wrong settings key and always failed with a 400. Two
  metadata option lists, update frequency and sensitivity, offered values the
  database rejects outright, so picking one lost an entire batch of staged
  metadata edits to an unhandled server error with no indication which field
  caused it; both lists now only offer values the database accepts. Saving
  only the login page's privacy-policy link, with no other branding change
  alongside it, silently saved nothing while still reporting success, because
  the save helper only ever forwarded one of the two branding fields it
  declared (#1769, #1776, #1790).

- **Accessibility fixes across the admin console and map builder.** The
  destructive button and badge styles failed WCAG contrast in dark mode.
  Several controls, including role selects, basemap toggles, and filter
  inputs, had no accessible name for a screen reader. The admin API key
  list silently hid any key past the first 50 and could reorder between
  refreshes (#1782, #1805).

- **Drawing and search state no longer leak between users signing in and
  out in the same browser tab.** A logout followed by a login with no page
  reload could leave the previous user's in-progress edit target, selected
  feature, or typed search carried into the next signed-in session (#1761).

- **Raster tile and export reliability fixes.** A vector tile query with no
  defined row order beyond its feature cap could return a different result on
  every rebuild, so different app servers could serve inconsistent tiles for
  the same request; tile queries are now consistently ordered. The dataset
  export endpoint no longer holds a pooled database connection open for the
  full duration of the conversion, which could otherwise starve other requests
  during a large or slow export. Every export format, GeoParquet included, is
  now bounded to the same deadline as the edge proxy's read timeout, instead
  of a synchronous export running for up to an hour behind a ten-minute proxy
  window. The raster tile proxy had the same connection-pool problem on a
  smaller scale: it held its database connection open across up to three
  30-second attempts against Titiler, so an anonymous caller varying the tile
  cache-busting parameter could hold a connection for well over a minute and
  starve unrelated requests in the same worker; the connection is now released
  before that upstream call (#1781, #1785, #1791, #1804).

- **Two data-loss bugs in the raster and VRT publish path are fixed.** A lost
  commit acknowledgement or a cancellation during a raster replace or VRT
  publish could leave the terminal cleanup believing the publish had failed,
  so it deleted the storage objects the already-committed dataset row now
  pointed at, leaving the dataset naming bytes that no longer existed with no
  way in the product to restore them. Separately, on a local-storage install,
  a worker-side validation failure (a lowered upload size limit catching a
  file already queued, for example) deleted the user's only copy of the
  uploaded file instead of leaving it in place (#1784).

- **A registered PostGIS table now picks up writes made outside GeoLens
  again.** The render column GeoLens derives for a registered table was only
  ever written once, at registration. A row moved, deleted and reloaded, or
  reloaded wholesale by an owner's own ETL job, went invisible on every map,
  tile, export and query that reads that column, with no error anywhere.
  Refresh now re-derives it, so the fix arrives the next time the dataset is
  refreshed, including after the owner's tool drops and recreates the table
  outright (#1823).

- **Registering a PostGIS table whose geometry column is not named `geom`
  is now refused with a clear reason, instead of silently cataloguing it as
  a non-spatial table.** `ogr2ogr -f PostgreSQL` names its geometry column
  `wkb_geometry` by default, which made the most ordinary way of loading a
  table into the data schema produce a dataset that rendered nothing and
  explained nothing. GeoLens now looks for a geometry column under another
  name and, if it finds one, names it in the refusal and points at the fix
  (#1740).

- **Replacing a dataset's file can no longer silently overwrite a service or
  STAC binding that changed underneath it.** A replacement started against a
  dataset bound to an upload is refused up front if the dataset is bound to
  a remote source instead, but that check only ran once, before the file was
  staged. If the dataset's origin changed in the time it took a person to
  review and confirm the replacement, the commit went through anyway and
  silently rebound the dataset to the uploaded file. The commit now
  re-checks the origin immediately before it takes effect and refuses if it
  no longer matches what the client last saw (#1821).

- **The CLI stops looping between "logged in" and "please log in again"
  when the OS keyring refuses a write.** When a bearer token landed in the
  credentials file because the keyring write failed, a companion refresh
  token could still end up in the keyring, so the next command read half a
  session from each location and never converged. The refresh token now
  follows the bearer token to wherever it actually landed (#1815).

- **A refused service preview returns a clear, coded error instead of a
  generic server failure.** Preview requests that failed for a known reason,
  such as a cross-origin redirect, an SSRF refusal, or a malformed
  credential, could still fall through to a plain 500 if the failure didn't
  match one of the narrower cases already handled. Every documented refusal
  reason now maps to its own 4xx status and message (#1833).

- **Several map-editing bugs from an internal audit are fixed:** a layer
  saved at zero opacity came back fully opaque; `POST /maps/import` had no
  cap on the number of layers it would accept; a filter with no size cap
  could be stored and re-serialized on every read at several megabytes; a
  filter with no depth cap crashed the write with a 500 during validation,
  before it was ever saved; a layer's zoom range and popup configuration
  were both lost on export and re-import; and a deleted map's thumbnail and
  social-preview image were never removed from storage. The map gallery
  listing also no longer scans the entire layer table to compute per-map
  layer counts, which showed up as measurably slower gallery loads on
  catalogs with many maps and layers (#1801).

- **Backup and restore operational fixes.** Offsite S3 backup copies were
  never pruned, so a long-running instance with S3 backups enabled grew that
  bucket without bound; they now follow the same retention as local backups.
  The weekly database dump and the staging archives used during a restore
  are now written atomically (to a temporary name, then renamed on success),
  so a container killed mid-write can no longer leave a truncated file that
  the retention pruner or a later restore mistakes for a good backup
  (#1798).

- **`scripts/restore.sh` no longer restarts the api and worker against a
  database a failed restore left half-populated.** A hard `pg_restore` failure
  or a failed post-restore grant reconciliation left the database
  `--clean`-dropped and only partly repopulated, with no ACLs re-applied, but
  the script's cleanup step restarted the api and worker regardless, and their
  boot-time migration run then applied against that wreckage. The restart now
  runs only once `pg_restore` has succeeded (or exited with the expected
  `--clean --if-exists` warnings) and grant reconciliation has run and been
  verified; a failed restore leaves both services stopped with an explicit
  message instead (#1798).

- **Two more upgrade-safety fixes.** `scripts/upgrade.sh` now rebuilds the
  database image when its Dockerfile is synced from the release, so a release
  that bumps the PostGIS or pgvector base actually takes effect on upgrade
  instead of silently continuing to run the previous image, which could leave
  a migration depending on the newer base failing mid-run with no earlier
  warning. And a failure propagating a commercial extension's migration paths
  at boot now aborts the migration run instead of only logging the error and
  continuing, which previously let `alembic upgrade heads` report success
  while silently applying only the core schema and skipping the extension's
  own migrations (#1798).

- **CLI and TypeScript SDK reliability fixes from an internal audit.** CLI
  requests now time out instead of hanging indefinitely against an
  unresponsive host; `geolens login --api-key` now clears a stale session
  token instead of leaving it to silently outrank the new key; a stored
  refresh token is now used to renew an expired session on `geolens status` as
  well as `whoami`, instead of only the latter. On the TypeScript SDK side,
  `createGeolensClient()` now builds a client scoped to each call instead of
  reconfiguring one shared module-level client, so two concurrent callers, a
  client built per request in a Node server, say, no longer overwrite each
  other's base URL, bearer token, or API key on the object the first caller is
  still holding (#1802).

- **A WFS or OGC API Features header token outside the accepted character set
  is now refused before any credential is spent.** Import commit and reupload
  commit used to accept such a token, stash it as a single-use credential, and
  only have the worker refuse it once the request reached ogr2ogr, burning
  the credential for nothing; service preview used a weaker check and
  accepted a token commit would later reject. All three doors now return the
  same 422 the refresh door already gave, before anything is staged or spent
  (#1752).

- **The ArcGIS import preview now shows the layer's feature count**, the same
  number probe already reported but preview previously left blank.
  Separately, the GDAL bearer-token header file used during import now
  lives on a container-private tmpfs instead of an untracked spot in the
  system temp directory, so it disappears the moment the container
  restarts and is never archived by the job that backs up the staging
  volume. The worker clears any file a crashed run left behind at its own
  next boot; it runs no periodic sweep of its own, and the API's periodic
  sweep looks at its own container's tmpfs, not the worker's, so it cannot
  reach one (#1751).

- **Several small service-import fixes from an internal audit.** The service
  token field in the import wizard, the reupload dialog, and the refresh
  dialog no longer invites a password manager to offer to save it or fill in
  the signed-in admin's own password. An ArcGIS sign-in failure now shows the
  same clear message a WFS auth failure already did, instead of falling back
  to a generic "Access denied." The token help text no longer points at the
  ArcGIS `generateToken` HTML form, which no longer renders; it explains the
  API-key and `client=referer` alternatives instead. And a layer picker no
  longer collapses two same-named layers from one service into a single row
  (#1750).

- **The optional `cloud-dev` profile's Valkey cache now actually starts.** It
  tried to drop from root to its own user with a capability its own
  `cap_drop: [ALL]` had already removed, so it exited immediately on every
  install that enabled the profile, silently leaving `REDIS_URL` unset.
  Valkey now runs as its own user from the start, skipping the privilege drop
  it could never complete (#1747).

- **PostgreSQL's own log directory no longer grows without bound inside the
  data volume.** Log rotation was enabled with no filename pattern, rotation
  age, or truncate-on-rotation setting, so the collector rotated files but
  never reclaimed them. Logs now rotate daily, truncate on rotation, and are
  capped at 7 files regardless of volume; RUNBOOK.md's server-logs section
  describes the new bound (#1783).

- **A failed vector file import, service import, or VRT build now notifies
  the operator the same way a failed raster import or re-upload already
  did**, if `notify_on_ingest_failed` is on. The four ingest tasks had grown
  separate copies of the failure-write logic, and only the raster and
  re-upload copies ever sent the notification (#1784).

- **Two storage and database leaks from a hard worker crash are now cleaned
  up instead of surviving forever.** A raster or VRT ingest that wrote its
  COG, quicklooks, or VRT to object storage and was then killed before its
  terminal commit left those objects unreferenced by any row and unreachable
  by any existing sweep; the job row now records the keys it is about to
  write, and the periodic and startup recovery sweeps reap them once the job
  is confirmed not to have landed. A hard kill after an analysis
  `materialize` commit left the same gap for the output table it had just
  created; both sweeps now drop an output table nothing ever adopted (#1803).

- **Worker process metrics and a completed-job counter that had read zero
  since the initial release are fixed.** The worker never started the RSS
  and connection-pool metric collectors the API process already runs, even
  though it hosts GDAL/ogr2ogr and carries a much larger memory limit.
  Separately, `geolens_jobs_completed_total` was derived from counting rows
  in a status the worker's own retention setting deletes before they can be
  counted, so the metric, the matching RUNBOOK entry, and the "Job
  throughput" Grafana panel never moved. It is now incremented at the job's
  terminal transition instead. A finished queue job that failed, was
  cancelled, or was aborted was also never purged from the job-queue table;
  it now follows the same `INGEST_JOBS_RETENTION_DAYS` window the ingest-jobs
  mirror already uses (#1804).

- **Three admin-configurable settings that had no admin UI control now have
  one.** `semantic_search_rate_limit` and `basemap_proxy_rate_limit` had no
  environment-variable fallback at all, and `email_verification_required`'s
  own docstring claimed the admin UI was the only way to set it; all three
  are now exposed on their respective settings tabs. Separately, the SAML
  provider admin page was gated on a coarser permission check than the API
  behind it enforces, the same drift already corrected for the Settings tabs
  by an earlier fix; it now uses the same mode-aware check (#1805).

- **The map builder's Share panel now explains a refused public toggle.**
  Turning a map public while it still holds non-public dataset layers was
  refused by the API with a 400, but the panel could not parse the response
  and swallowed it, so the toggle appeared to do nothing. The refusal now
  renders as an inline message under the visibility control, names the
  datasets that block it, and is announced to screen readers; the duplicate
  generic error toast no longer also fires for the same failure (#1841).

### Security

- **The ArcGIS token GeoLens sends on its own probe, preview, count, and
  pagination requests now travels as an `X-Esri-Authorization: Bearer`
  header instead of a `?token=` query parameter,** so it no longer appears
  in a request URL or in the HTTP client's own request-log line, which
  redaction runs too late to see. Esri's own header name is used rather than
  the standard `Authorization`, because a portal behind a Web Adaptor with its
  own web-tier authentication (IWA or PKI) consumes the standard header before
  ArcGIS ever sees the request; if a portal still answers such a request with
  an HTTP 401 or 403, GeoLens retries once with the query form on the same
  origin.
  An ArcGIS Server older than 10.5.1, read from the service's own
  `currentVersion`, keeps the query form outright, since it does not read a
  bearer header at all. The GDAL fetch that pulls the feature data itself is
  unchanged and still uses the query form: the worker's header file only
  accepts a base64url-shaped token, which an ArcGIS token is not guaranteed
  to be, and that path was already redacted from job arguments and error
  text. A single function now builds the count-query URL everywhere it is
  needed, rather than three copies each composing it slightly differently.
  Also: an SSRF refusal encountered while probing an ArcGIS service now
  reaches the caller instead of degrading to a generic "unhealthy" answer,
  and the query-form fallback now registers its token with the log scrubber
  the same way the header form already did (#1840).

- **ArcGIS sign-in attempts are now counted before the credential is sent,
  not after.** A sign-in request cancelled mid-flight could previously go
  uncounted against the rate limit even though the password may already
  have reached ArcGIS, understating how many attempts were actually made
  against an account. This release adds migration `0058`, which adds a
  `user_scope` column to the sign-in attempt ledger; it runs automatically
  as part of the normal upgrade (#1820).

- **A service token could remain readable on a failed import or re-upload job
  row until the next cleanup sweep.** A worker that failed a job dispatched
  with a WFS, OGC API Features, or ArcGIS credential left the token in the
  job's stored arguments, since only a successful job's row was deleted. Both
  tasks now strip their own token on any terminal failure, and the periodic
  stale-job sweep strips it from any row a crashed worker left behind (#1753).

- **Two more sensitive query parameters are now redacted from logs and
  stored source URLs.** `authkey` (ArcGIS) and `maxar_api_key` (Maxar) join
  the existing `api_key` and `token` entries, closing a gap where either
  could appear in the clear in a stored service pointer or a composed GDAL
  query string (#1830).

- **`restore.sh`, `check-env.sh`, and `upgrade.sh` no longer read `.env` by
  shell-sourcing it.** Shell-sourcing runs the file as a script, so an
  operator-typed value containing a bare space, a backtick, or a `$(...)`
  sequence, an admin password prompt accepts any of those, ran as a command
  with the operator's own privileges instead of being read as a value. All
  three scripts now read only the keys they need through a dedicated parser.
  RUNBOOK.md's own restore and role-rotation instructions, which told an
  operator to source `.env` directly, are corrected to match (#1798).

- **The embed viewer no longer sends the signed-in user's session token
  with raster tile requests.** A bare embed link, no embed token, opened by
  a signed-in user on the same browser leaked that user's own bearer token
  to raster tile requests, defeating the anonymity an embed view is
  supposed to guarantee. The raw embed token is also now redacted from
  generated diagnostic reports (#1795).

- **A revoked embed token could still be served from cache for a request
  racing the revocation, or during a Redis outage.** A request that read the
  token as still active in the instant before a revocation committed could
  cache it again as valid, and a token cached during a Redis outage could
  survive a revocation issued once Redis recovered. Both are now fail-closed:
  a revocation now wins the race and survives an outage on either side. This
  release adds migration `0057`, which adds the revocation-tracking table
  backing this; it runs automatically as part of the normal upgrade (#1796).

- **A password over 72 bytes could crash the login endpoint, and the same
  input could crash-loop the API container on first boot.** bcrypt hashes
  at most 72 bytes and raises rather than truncating; `/auth/login` and the
  change-password endpoint took an unbounded password straight to the
  hasher, and an operator-generated `GEOLENS_ADMIN_PASSWORD` longer than 72
  bytes made the API container fail to start at all. An over-long password
  is now treated as a non-match rather than a crash, and the same bound is
  checked at boot for the admin password. The CSRF cookie also gained the
  same duplicate-cookie hardening its paired refresh-token cookie already
  had (#1796).

- **CORS could be tricked into trusting a client-controlled Host header.**
  When an incoming request's Origin failed the configured allowlist, both CORS
  resolvers fell back to reading the request's Host header instead of
  refusing, and the proxy forwards Host verbatim, so a request naming an
  arbitrary Host both failed and passed the allowlist check on the same call.
  The fallback no longer runs after an explicit rejection (#1796).

- **Two OAuth and SAML sign-in gaps closed.** Signing in through an OAuth or
  OIDC provider no longer creates an account while self-service registration
  is disabled: JIT provisioning never read the "Registration enabled" switch,
  so an operator who added a provider without also restricting it by email
  domain had, in effect, open signup, and any account at that identity
  provider could sign in and be created as a viewer, who can list and export
  every internal dataset. Existing users are unaffected. Separately, an
  installation using the group-role-mapping extension now re-evaluates an
  OAuth-mapped role on every login instead of binding it once at account
  creation. Before this, the mapping could only add a role, never take one
  away: removing someone from a mapped group at the identity provider now
  revokes the GeoLens role that membership had granted (#1796).

- **Service tokens no longer appear in plaintext in application logs.**
  httpx's own request logging and Procrastinate's worker job logging both
  wrote the composed request URL or job arguments at INFO, including the
  token, past the existing structured-log redaction, which only inspected
  known field keys rather than the rendered message text. Both loggers are
  now scrubbed (#1749).

- **Application error logs no longer leak query values or share-link tokens.**
  Database errors logged the full failing statement together with its bound
  parameters, which the existing log redaction could not see because it only
  inspects known field keys, not rendered text. A 500 or a database outage on
  a shared-map link also logged its share token in the clear, unlike the
  access log line beside it, which has redacted it since #821. Both are now
  redacted (#1804).

- **Vector tiles could return columns outside a dataset's declared column
  allowlist.** The `cols=` request parameter was documented as bounded by the
  dataset's `tile_columns` allowlist, but actually unioned any column past it,
  so a client could read a column the allowlist was meant to keep out of the
  tile. It now only ever narrows the projection the allowlist already permits.
  Operators with a narrow allowlist and a data-driven style keyed on a column
  outside it will need to add that column to the allowlist (#1804).

- **Dataset CSV downloads are hardened against spreadsheet formula
  execution.** An attribute value written by anyone with edit access to a
  public dataset reached an anonymous downloader's CSV file byte for byte;
  opening it in Excel or a similar tool could execute the value if it parsed
  as a formula. A cell that could be read as a formula is now escaped; an
  ordinary negative number is left alone (#1804).

- **Private Cloud-Optimized GeoTIFF downloads no longer stay valid for an hour
  after the token that authorized them expires.** The signed redirect for a
  COG download was valid for a flat hour regardless of the caller's own access
  token, so a private or internal dataset's download URL, once issued, kept
  working long after the short-lived token behind it should have. The signed
  URL's lifetime is now capped to what remains of the caller's own token
  (#1804).

- **The SQL sandbox closes several parsing edge cases that could bypass its
  access checks or leak a query in an error response.** A handful of
  PostgreSQL's built-in functions, `user`, `current_role`, and similar,
  parsed in a shape the access allowlist did not recognize as a function
  call, letting them slip past it. Some malformed SQL raised the wrong
  exception type and reached the client as a raw 500 with the full query
  logged. A query ending in a `--` comment could also be spliced with
  GeoLens's own row-limit wrapper in a way that broke the limit (#1797).

- **AI chat trust-boundary fixes.** The chat surface's `query_data` tool sat
  behind the same permission as the hardened raw-SQL endpoint but skipped its
  capacity limit, self-join cap, and row and column caps; it now shares all of
  them. Dataset content reaching the model, including sample values from
  another user's public dataset, and every tool result handed back to the
  model are now fenced as untrusted data with an explicit instruction that it
  cannot be treated as an instruction, closing a cross-user path into a
  prompt-injection surface (#1797).

- **AI chat quota and error-disclosure fixes.** A chat request that failed,
  timed out, or was cancelled after already spending provider tokens recorded
  no usage against the caller's daily AI token budget, so a caller who could
  reliably force one of those outcomes could exceed it for free; usage is now
  recorded on every exit path. Error responses also no longer leak raw
  exception text, including SQL statements and AI-provider connection details,
  to the browser (#1797).

- **Two raster and VRT worker hardening fixes close resource-exhaustion
  paths.** Generating a quicklook for a malformed or adversarially crafted
  Cloud-Optimized GeoTIFF could read an unbounded array into memory; the read
  is now clamped to a fixed multiple of the target size. A stalled remote
  raster source could hang a worker indefinitely during VRT metadata reads and
  quicklook rendering, a hazard reintroduced after an earlier fix; GDAL
  connect and read timeouts are applied again on those paths (#1803).

- **The admin-configurable global rate limit now actually limits by caller.**
  It was keyed by client IP and URL path rather than IP and endpoint, so a
  caller could multiply their effective budget by varying a path parameter, a
  dataset id or a tile coordinate, that the route table was supposed to fix in
  place, not the limiter (#1785).

- **Two more gaps let an anonymous caller cost more than the deployment's rate
  limits allow.** The `/api/tiles/raster-proxy/` URL answered every request
  with no rate limit at all, bypassing the one nginx enforced on the same
  handler's other URL spelling. And the vector tile `cols=` parameter fed
  unvalidated into the tile cache key, so a wide public table could be cached
  under an unbounded number of keys for the one set of bytes those requests
  actually returned, evicting legitimate tiles from the cache on a Valkey-less
  install (#1785).

## [1.17.0] - 2026-08-30

### Added

- **Cancel a running import or refresh.** Imports and dataset refreshes can now
  be cancelled while they are pending or in flight, from the refresh history on
  a dataset's source panel and from the admin job list. A cancelled run stops
  before anything reaches the live table: the finalize path is fenced on the
  job's attempt, so a worker that finishes after the cancel commits rolls its
  swap back rather than publishing data the user already walked away from.
  Existing data and version history are left untouched, and the cancel lands in
  the audit log. Asking twice is harmless. The job's owner can cancel, so can an
  admin, and so can the dataset's own owner, which means a stuck job can always
  be cleared by someone with a stake in the dataset (#1677, #1709).

- **Import a dataset from a file URL.** A new File URL tab on the import page
  takes an HTTP(S) link to a data file, fetches it server-side, and hands it to
  the same preview and commit pipeline an upload uses, layer picker and raster
  branch included. Plenty of public data is published as a stable link rather
  than a file you keep on disk. The URL goes through the same SSRF checks as
  every other outbound fetch and is re-checked on each redirect hop. The size cap
  is enforced per chunk as the body streams, so an origin that lies about its
  length, or simply never stops sending, cannot get past it. Once staged, the
  file faces the same extension, content-sniff and quota checks as a direct
  upload (#1705, #1708).

### Fixed

- **Published-package verification no longer races the release it verifies.**
  The workflow triggered off the SDK, CLI and MCP publishes, then polled five
  minutes for a GitHub Release and GHCR images that land much later: the release
  waits for the prod compose smoke to boot the published images and run the audit
  suite. On 1.16.0 the automatic attempts gave up more than two minutes before
  the release existed, so every release needed a manual rerun that then passed
  trivially. Each check now runs off the trigger that can actually satisfy it,
  and resolves the exact tag under test instead of falling back to `latest`
  (#1707).

## [1.16.1] - 2026-08-28

### Added

- **Instance setting to restrict public visibility to admins.** A new
  `restrict_public_visibility` setting (default off, General tab): when
  enabled, non-admin users can still create and edit content, but any request
  to mark a dataset, map, or import `public` is refused with a clear 403.
  Enforcement runs server-side through one shared gate at every
  visibility-writing surface — dataset metadata, map save, STAC import,
  ingest commit and fan-out, register, VRT create, and manifest apply — and a
  structural test walks the route table so a new visibility-accepting handler
  cannot ship ungated. The UI hides or disables the Public option for
  non-admins with a note. Existing public content is untouched. Built for
  open-SSO instances such as the public demo, where anonymous-facing search
  facets otherwise accumulate whatever visitors mark public (#1691, #1704).

- **STAC items now advertise their origin assets.** A dataset imported by
  reference from a remote STAC catalog stores the source item's data asset
  (the COG href) and serves it on GeoLens's own STAC items beside the tile
  asset, clearly roled `data` vs `visual`, so generic clients — stac-browser,
  the QGIS STAC plugin, rio-viz — can actually read pixels from items GeoLens
  republishes. A successful refresh repairs existing by-reference datasets
  idempotently, which doubles as the backfill (#1692, #1703).

### Fixed

- **PMTiles basemaps render again.** The shared tile request transform
  absolutified every URL that did not start with `http`, and MapLibre runs
  `transformRequest` before its custom-protocol dispatch, so a `pmtiles://`
  basemap source became `http://<origin>pmtiles://...` and never reached the
  protocol handler — every PMTiles basemap added in 1.16.0 failed to render
  with a "Failed to construct Request" error. Only site-relative paths are
  absolutified now; scheme-carrying and protocol-relative URLs pass through
  untouched (#1696).

- **Browsers can consume public exports cross-origin.** The export and COG
  download routes now answer CORS preflights and carry Access-Control
  headers: anonymous requests get the wildcard treatment with the range and
  conditional request headers allowed and `Content-Range`, `Accept-Ranges`,
  `Content-Length`, `ETag`, and `Content-Disposition` exposed, while origins
  listed in `CORS_ALLOWED_ORIGINS` keep the API middleware's explicit-origin
  credentialed policy untouched — the API stays authoritative and the edge
  only fills the anonymous gap. A browser page on another origin can now
  point the pmtiles protocol or DuckDB-WASM straight at a live export URL
  (#1698, #1701).

- **Exported map images derive attribution from MapLibre's live state.** The
  credit band in saved thumbnails and share images now reads the renderer's
  own used/usedForTerrain flags rather than approximating them from
  visibility and zoom, falling back to the previous model when those
  internals are unreachable. Deduplication and joining now match the
  on-screen control, and embedded object/embed/iframe/video markup in
  attribution HTML gets the same accessible-text treatment as images
  (#1553, #1702).

## [1.16.0] - 2026-08-27

### Added


- **Server-side CQL2 filtering on feature collections.** OGC API Features
  clients can now send `filter=` (with `filter-lang=cql2-text` or
  `cql2-json`) on `/collections/{id}/items` and the server evaluates it in
  SQL, ANDed with `bbox` and the property-filter extension. Until now a
  spec-driven client had to download every feature and filter locally. Each
  collection also gains a `/queryables` endpoint derived from the live
  database schema, published with `additionalProperties: false`, so the
  advertised property set always matches what filter validation accepts.
  The conformance document now declares Part 3 queryables/filter plus CQL2
  advanced comparison and basic spatial functions, which is exactly the set
  QGIS 3.44+ checks before pushing its filter expressions to the server
  instead of filtering client-side; a regression test pins that set so it
  cannot silently regress (#1674, #1680).

- **Four more upload formats: FlatGeobuf, KML, KMZ, and zipped File
  Geodatabase.** The GDAL build in the worker has read these all along — they
  were simply never on the accepted-extensions list, so an upload was refused
  at the door. `.fgb` uploads store `source_format = 'fgb'` (a new value in
  the `chk_datasets_source_format` constraint); `.kmz` is recorded as `kml`,
  one format in two containers; and a `.zip` is now recorded as `fgdb` rather
  than `shapefile` when it carries a `.gdb` directory, which also stops the
  Shapefile DBF field-name-truncation warning from firing on a File
  Geodatabase that has no DBF. Replace-in-place accepts the same four.
  Upload-time content checks came along: FlatGeobuf's 8-byte magic is
  verified directly (puremagic has no signature for it), a KMZ goes through
  the same zip-bomb checks as any other archive, and a `.kml` must at least
  open an XML tag.

- **PMTiles export.** Any vector dataset can be exported as a single
  PMTiles archive of MVT tiles and hosted from a static file server or
  object store, with no tile server involved. The tile pyramid's depth
  adapts to the dataset's extent (a citywide dataset gets street-level
  zoom 14, a global one stops at zoom 8) so archives stay a sensible size.
  The format appears everywhere other exports do: the export menu, DCAT
  distributions, and STAC/OGC assets, with existing datasets backfilled
  (#1686).

- **FlatGeobuf export.** The export menu, DCAT distributions, and STAC/OGC
  assets gain `fgb` alongside GeoPackage, GeoJSON, Shapefile, CSV, and
  GeoParquet, with a backfill for existing spatial datasets. Served as
  `application/vnd.flatgeobuf`, the vendor type the format's maintainers
  proposed (#1681).

- **PMTiles basemaps.** A basemap URL can now be a PMTiles archive, either
  `pmtiles://https://...` or a bare `https://....pmtiles`, such as a
  protomaps world build or a GeoLens PMTiles export. The admin settings
  form probes the archive header before saving and rejects a vector
  archive that has no style to render it with. Together with PMTiles
  export this closes the offline loop: export a dataset, drop the file
  behind any static host, and point a basemap at it, no tile server and
  no API key (#1688).

- **The CLI manifest accepts the new vector formats.** `geolens apply`
  manifests can now declare FlatGeobuf, KML, KMZ, and zipped File
  Geodatabase sources, the same four formats the upload doors accepted in
  this release, so scripted and version-controlled ingest is not weaker
  than the browser path (#1694).

- **A failed upload now leaves a trace, and a way to report it.** UploadForm
  calls the presign, PUT, direct-upload POST, preview/detection, commit, and
  commit-fan-out endpoints directly from a plain try/catch instead of through
  a TanStack mutation, so none of their failures ever reached the shared
  problem-reporter tap in main.tsx: a broken CSV just showed an error with
  nothing recorded anywhere a user could report. Each of those calls now
  reports its own failure into the same buffer (status, error text, and
  filename only, never the file body or a presigned URL's signature),
  including a 2xx response with a malformed JSON body and a preview rejection
  that isn't an `ApiError`, both of which used to fall through the reporting
  entirely. A failed file's row now also carries a "Report this problem"
  action that opens the reporter pre-scoped to Import / Ingestion. Also
  fixed: the error text on the first, or only, staged file in a batch was
  invisible, because its row started expanded by state even though
  upload-failed rows have no expand panel to show.

### Changed

- **Anonymous visitors can report problems too.** The in-app problem reporter
  (error-triggered floating button + wizard) was gated to signed-in users, but
  error capture already runs for everyone and the report itself is a prefilled
  GitHub issue that needs no GeoLens session. On a public instance most
  traffic browses anonymously, so a visitor who hit a broken map had no way to
  say so. The gate is removed; the button still appears only after an error is
  captured.
- **`https://` links in the site banner are clickable.** The admin-configured
  announcement banner rendered its text as plain escaped text, so a URL in it
  could only be retyped. Matched `https://` URLs now render as anchors
  (new tab, `rel="noopener noreferrer"`); everything else stays escaped text,
  so banner content still cannot inject markup.


- **Multi-layer files say what they contain.** A File Geodatabase or
  GeoPackage holds layers, not sheets; the import review now uses the
  right word for each container, shows an "N layers" badge, and "Import
  all" respects the layer selection instead of ignoring it (#1685).

### Security


- **Service tokens are leased, not stored, at every import door.** The
  refresh door has handed ArcGIS service tokens to the worker through a
  one-use Valkey lease since 1.13; the first-import and reupload doors
  still wrote the raw token into durable job-queue arguments, where a
  failed or queued job held it in plaintext until the retention purge,
  while the import UI promised tokens are "never stored". All three doors
  now behave the same way, keyed on what the install has: with a
  credential store configured the token is stashed under a one-use
  reference the worker consumes; if the stash fails the request is
  refused with a 503 rather than silently downgraded; and an install with
  no store configured keeps the previous durable-argument behavior, now
  logged. This also fixes a latent bug where an import with no run rows
  would lose its lease after 900 seconds (#1689).

### Fixed

- **A database hiccup no longer narrows which file types you can upload.**
  Both upload doors tolerate a failed settings lookup by falling back to a
  built-in extension list, and that list was frozen at the formats available
  when it was written. GeoParquet has been missing from it since GeoParquet
  import shipped, so during exactly the transient failure the fallback exists
  to survive, a `.parquet` upload was refused for a reason no operator had
  configured. Both fallbacks now read the configured default. A narrower list
  was never the safer one: the extension check gates nothing by itself, since
  content validation, the size limit, and the storage quota all still run.

- **The API contract now describes what the server actually accepts and
  returns.** Three things in the generated OpenAPI schema described FastAPI's
  defaults where the app overrides them, and anyone generating a client
  inherited all three. Validation failures were declared as
  `HTTPValidationError` on every operation with request validation, while the
  server has always answered `application/problem+json` with a `ProblemDetail`
  whose `detail` is a single string. `keywords` was declared as a JSON request
  body on a GET rather than the query parameter it is. And `filter-lang` was
  published under its internal name `cql2_filter_lang`, so a generated client
  sent a parameter the handler never read and its filter language was silently
  ignored. All three are corrected on `/search/datasets/` and
  `/collections/datasets/items` (#1666).

  SDK users: the generated surface changes shape — `body` becomes `keywords`,
  `cql2_filter_lang` becomes `filter_lang`, and `HTTPValidationError` is gone.
  Regenerating is the fix, and nothing needs it urgently: the server still
  accepts both the old `cql2_filter_lang` spelling and the old JSON-body
  `keywords`, so a client built against the previous contract keeps working
  unchanged. Neither legacy form is published, and both will be removed in a
  future release — a request body on a GET in particular is not reliably
  forwarded by proxies and CDNs.

- **A raster open-failure error no longer echoes the internal staging path.**
  Deferred from #1640, which fixed the vector side: when a corrupt or
  unopenable raster upload reached `rasterio.open`, `IngestJob.error_message`
  carried the raw rasterio message verbatim — e.g. `'<path>' not recognized
  as being in a supported file format.` — leaking the internal
  `/app/staging/<uuid>_...` path instead of the original upload filename.
  Any `RasterioIOError` raised by that open call (unrecognized format,
  corrupt/truncated IFD, missing file, ...) is now replaced with a short
  message built from the upload's original filename instead (e.g. `Could not
  open 'survey.tif' as a raster dataset — the file may be corrupt,
  incomplete, or not a valid GeoTIFF (.tif) file.`); the full rasterio
  message still reaches structured logs at error level, and a failure raised
  by anything other than the open call itself keeps its real message
  unchanged.


- **Refreshing a large ArcGIS layer pages like importing one.** Refresh
  performed a single unpaged fetch and trusted the server's paging
  metadata, exactly what the import path's guarded loop exists to
  distrust (servers that misreport pagination support, sparse object IDs,
  transfer limits). A short result could then swap in cleanly as a
  silently truncated dataset. Refresh now runs the same guarded
  `resultOffset` loop as import, and a connectivity probe failure now
  stamps `last_checked_at` so a failing source is visibly stale rather
  than frozen at its last success (#1678).

- **Exported map styles import back.** `GET /maps/{id}/style.json` emits
  `sprite` in MapLibre's array form, but import only accepted a string,
  so a style document GeoLens itself produced failed re-import with a
  422. Import accepts both forms now, a test pins the full
  export-import round trip, and the export operation's previously empty
  response schema now names the MapLibre Style Specification and the one
  guarantee beyond it (#1679).

- **A broken migration overlay now fails the migration run.** When an
  installed edition overlay's migration provider failed to load,
  `alembic upgrade heads` logged an error, skipped that overlay's entire
  revision chain, and exited 0, so a deployment pipeline gating on the
  exit code reported a partial schema as a successful migration. Both
  failure classes now raise; a Community install without overlays is
  unaffected (#1668).

- **Single-worker installs no longer restart on a request quota.**
  uvicorn's `--limit-max-requests` is a rolling worker recycle only when
  the multiprocess supervisor exists; with `UVICORN_WORKERS=1` (the
  documented small-VM tuning) hitting the limit exited the whole process,
  which surfaced as a clean unexplained container restart and a ~17
  second outage roughly every 13 hours under ordinary monitoring
  traffic. The flag is now applied only when there are at least two
  workers (#1687).

- **Container logs are bounded.** The production compose file pinned no
  log rotation, so a long-lived container's json-file log grew without
  limit. Every service now caps logs at three 50 MB files. Existing
  deployments pick this up on the next `docker compose up -d` after
  pulling the change; a plain restart is not enough (#1690).

- **Anonymous downloads work for public rasters, not just vectors.** A
  public, published vector dataset could be exported anonymously, but the
  COG download for an equally public raster answered 401 unless the
  caller first minted a download token, which broke "open this raster in
  QGIS" for exactly the datasets meant to be showcased. The route's
  access checks were already correct; the dependency above them refused
  anonymous requests before those checks ran. Anonymous requests now
  reach the same public-visibility gate the vector path uses (#1693).

## [1.15.1] - 2026-08-24

### Changed

- **An upload that was never started is now `cancelled`, not `failed`.** Ask
  for a presigned upload URL and walk away, and the job row sat `pending` until
  the stale sweep marked it failed with "pending too long (never queued)" — a
  state that reads, in the admin jobs list and in the failed-jobs count beside
  it, exactly like an ingest that broke. Nothing was ever attempted for those
  rows, so they now settle `cancelled` with "Abandoned: upload was never
  completed", at all three places that can settle them: the background sweep,
  the status poll, and a worker's startup recovery. Only that class moves.
  Every other never-queued job keeps reporting `failed` — including a service
  or URL import whose dispatch never landed, because retry is offered on failed
  jobs and taking that away would cost a recoverable job its recovery. The
  cleanup pass counts cancellations apart from failures, so an operator reading
  a sweep's audit entry sees what it actually did, and the import view stops
  polling a job once it settles cancelled instead of asking for its status
  every two seconds for the life of the tab. No schema change: `cancelled` was
  already a permitted job status (#1556).

### Fixed

- **GeoPackage exports are now byte-deterministic under load.** Two exports
  of unchanged data could still hash differently after `normalize_gpkg_timestamps`
  ran on both, because SQLite's own file-change-counter header fields
  (offsets 24–27 and 92–95) are incremented by transaction *count*, not by
  content, and ogr2ogr's write path can commit a different number of
  transactions between two otherwise-identical builds under CI load. That
  broke the export artifact cache's byte-determinism gate (#1532): a
  contested selection refuses every range request, so it silently disabled
  range-serving for the default export format whenever this fired. GPKG
  normalization now also stamps those two header fields with a value
  derived from the file's own normalized content, after the SQLite
  connection closes: identical exports still land on the identical value,
  but two exports of different data no longer collide on the same one
  (#1633).
- **Low-bit-depth rasters (NBITS < 8) no longer fail COG conversion.**
  LULC and palette rasters commonly pack 1/2/4-bit samples into a rasterio
  `uint8` container, via GDAL's `IMAGE_STRUCTURE` `NBITS` tag, which lives
  at the band level rather than the dataset level. The COG converter picked
  a `PREDICTOR` from the dtype string alone, so it handed `gdal_translate` a
  `PREDICTOR=2` the tool hard-refuses on anything outside 8/16/32/64-bit
  samples, failing the whole conversion step and the ingest job with it.
  This is what broke `Peshawar_City_LULC_2050.tif` on the demo.
  `convert_to_cog` now checks each band's actual bit width before deciding
  whether a predictor creation option is safe to pass.

- **A corrupt vector upload no longer shows a raw GDAL diagnostic dump.**
  When ogr2ogr or ogrinfo couldn't open an uploaded file — a corrupt or
  incomplete GeoPackage, Shapefile, or similar — the stored and displayed
  `IngestJob.error_message` was GDAL's raw stderr verbatim: either a 100+
  line driver enumeration or SQLite's own corrupt-database diagnostics,
  both including the internal staging file path. Both failure shapes are
  now recognized and replaced with a short message built from the original
  upload filename, e.g. "Could not open 'march.gpkg' as a spatial dataset —
  the file may be corrupt, incomplete, or not a valid GeoPackage (.gpkg)
  file."; the full stderr still reaches structured logs at error level, and
  every other ogr2ogr/ogrinfo failure keeps its real message unchanged
  (#1640).

## [1.15.0] - 2026-08-23

### Added

- **The MCP server is published to the official MCP Registry.** Each release
  now registers `geolens-mcp` in the community registry
  (`io.github.geolens-io/geolens`) alongside the PyPI publish, so MCP clients
  that browse the registry can find the GeoLens server without knowing the
  package name (#1623).

### Changed

- **The map engine is now maplibre-gl 6.5.0.** The frontend moved off the
  5.x line, whose last release was 5.24.0, onto v6. The upgrade is
  behaviour-preserving for saved maps: Mercator and terrain rendering are
  pixel-identical to 5.24.0, and globe maps differ only within tile-timing
  variance. Two internal migrations came with it. The tile worker is now
  registered explicitly, since v6 ships it as a separate ESM file instead of
  inlining it, and missing sprite images resolve through
  `setMissingStyleImageResolver` rather than a notify-only event, which
  removes the intermittently absent icon that the old listener could produce.
  A new smoke test asserts that vector tiles are actually requested, a
  property no existing test covered, so a dead tile worker can no longer pass
  the suite (#1624).

- **The layer opacity slider fades polygon and line layers as one surface.**
  A vector layer has two opacity controls: the Style Editor's per-feature
  `fill-opacity`/`line-opacity` and the master slider. The builder multiplied
  them into a single per-feature value, so wherever two features in the same
  layer overlapped the overlap drew darker, and a layer at 50% was never
  uniformly 50%. The master now drives maplibre-gl v6's `fill-layer-opacity`
  and `line-layer-opacity`, which composite the whole layer once after the
  per-feature pass; per-feature opacity is written as stored. Polygon outlines
  take the same route, so shared edges stop double-darkening. Point, cluster,
  heatmap and raster layers have no such property in v6 and keep the previous
  multiply (#1625).

### Fixed

- **Exported style.json honours the layer opacity slider.** The primary fill or
  line layer copied its paint through verbatim and never applied `layer.opacity`,
  while the outline, extrusion and icon companions did — so a layer faded in the
  builder rendered fully opaque in a shared or embedded style. The export now
  folds the master opacity into `fill-opacity`/`line-opacity` (multiplying a
  number, wrapping an expression) instead of emitting the v6 `-layer-opacity`
  keys, which every maplibre-gl before 6 rejects at load. The stored per-feature
  value travels in the layer metadata so importing a GeoLens export gives back
  both tiers unchanged, and a style authored for v6 with `fill-layer-opacity`
  imports onto the layer opacity instead of being dropped (#1626).

- **Object-valued feature properties render as JSON in the map popup.** A
  feature property holding an object or array (a JSON column, a nested
  attribute) rendered as the literal text `[object Object]` when clicked,
  while the accessible data panel already rendered the same value as JSON
  text. Both components now call one shared formatter, so an object or array
  property renders the same way in either place (#1627).

- **Editing an attribute cell no longer loses what you typed.** The dataset
  Data tab rebuilt its column definitions on every render, and because
  TanStack Table renders a column's `cell` function as a React component type,
  that rebuild remounted every cell instead of re-rendering it. An open cell
  editor was reset to the stored value, so a save started from a re-render —
  the map above finishing its load, a background query settling — wrote
  nothing and showed nothing: no update, no rejection message, the editor just
  closed. Column definitions are now stable, so an in-progress edit survives
  unrelated renders, and a value the backend or the type check rejects stays
  in the box to be corrected (#1628).

## [1.14.2] - 2026-08-21

### Added

- **S3 storage works without static keys.** With `STORAGE_PROVIDER=s3`, boot
  validation demanded `S3_ACCESS_KEY_ID`/`S3_SECRET_ACCESS_KEY` even when the
  environment carried ambient AWS credentials, so keyless setups — EKS with
  IRSA or Pod Identity, ECS task roles — could not start at all. The validator
  now accepts an ambient credential source (a web-identity role or a container
  credentials URI) in place of the static pair, while a half-configured pair
  is still rejected. The storage layer and GDAL already resolved the SDK
  default chain; the validator was the only thing in the way (#1616).

### Fixed

- **Vector ingest works against a TLS-verified database.** Under
  `DATABASE_SSL_MODE=verify-full`, the CA certificate reached asyncpg as an
  SSLContext but never reached ogr2ogr, whose libpq connection string carried
  no `sslrootcert` — so every vector ingest failed certificate verification
  while the rest of the app connected fine. The ogr2ogr and Procrastinate
  connection strings now carry the same TLS parameters as the API path, values
  are quoted and escaped per libpq rules, and percent-encoded credentials are
  decoded to match what SQLAlchemy sends (#1617).
- **The operator runbook covers managed-database and object-storage restore on
  Kubernetes.** The backup/restore runbook assumed the Docker Compose stack;
  restoring a chart deployment — RDS point-in-time restore, the Secret
  cutover, GitOps-owned releases, S3 object-version promotion, and the full
  managed-storage prefix layout — is now drilled and documented, including the
  recovery asymmetry table for what a database-only restore does and does not
  bring back (#1618).

### Security

- **CI dependency audit unblocked.** pip 26.1.2 — a transitive dependency of
  the audit tooling, not of GeoLens itself — matched the newly published
  PYSEC-2026-3721 advisory and failed every strict audit run; bumped to
  26.2.1 (#1619).

## [1.14.1] - 2026-08-20

### Added

- **The login privacy-policy link is now a per-instance setting.** Every
  self-hosted login and register page linked to getgeolens.com's privacy
  policy, which describes our data practices rather than the operator's. The
  link now comes from a `privacy_url` setting on the General tab (or the
  `PRIVACY_URL` environment variable) and stays hidden until one is set, so an
  instance never shows another operator's policy to its users by default
  (#1592).

### Fixed

- **Metric-buffer questions in chat stop failing at the sandbox.** Asking for a
  buffer in metres made the assistant reproduce a 3 000-character PostGIS
  expression character for character, and it got that wrong often enough that
  roughly every other such question came back as a refused query rather than an
  answer. The assistant now writes a short call and the server renders the
  expression itself, so the shape can no longer be wrong (#1589).
- **A bare `/api` no longer redirects to `http://<host>:8080/api/`.** The
  shipped nginx answered the slash redirect with an absolute `Location` built
  from the container port and plain http, which behind a TLS edge sent clients
  to an unreachable address. It now emits a relative `Location: /api/` (#1597).
- **Anonymous catalog search answers cross-origin browser requests.** The
  read-only `/search/datasets` and `/search/facets` routes sent no
  `Access-Control-Allow-Origin` to an origin outside the allow-list while the
  OGC Records and STAC routes did, so a static page could query the standards
  surface but not native search. They now get the same credential-free
  wildcard, with a preflight that advertises only the `GET` they answer; the
  authenticated saved-search routes are unchanged. Both CORS policies also
  expose `Retry-After` on a 429 and send `Vary: Origin`, so a cross-origin
  caller can read the retry window and a caching proxy in front of the API
  keys its entries by origin. The shipped nginx ignores that header on its
  raster-tile cache, whose CORS value is a static wildcard for every caller,
  so tiles stay one cache entry per tile instead of one per embedding site
  (#1596, #1602, #1605).
- **A force reseed no longer breaks the demo links the examples gallery
  depends on.** `scripts/seed-showcase.py` now pins the four externally
  linked showcase maps and the meteorites dataset: `--force` repairs the
  Sentinel map in place and keeps every pinned row's UUID and share links,
  `--prune`/`--prune-userdata` hard-keep them, and a new `--force-pinned`
  says exactly what it destroys before an operator uses it (#1607).
- **Default extension ports match their Protocol signatures.** Four default
  port methods and two default AI-provider stream methods had drifted from the
  parameter names their Protocols declare, so a keyword caller or an overlay
  forwarding by name hit a `TypeError` against the default. The signatures are
  now pinned by a structural test (#1590).
- **A falsy non-string sent for `public_app_url` or `public_api_url` is
  rejected instead of clearing the value.** JSON `false`, `0`, `[]` or `{}`
  silently cleared the configured URL; only `null` and an empty string clear it
  now, and anything else is a 422.

## [1.14.0] - 2026-08-18

### Added

- **Rendered map images carry attribution.** Exported PNGs, map thumbnails
  and social preview cards drew no credits at all, not the basemap's and not
  the datasets'. Every rendered image now carries the full credit set,
  wrapping to as many lines as it needs rather than truncating a provider
  name; credits that cannot be turned into text are counted in an explicit
  "+N more" marker rather than dropped, and nothing is ever painted outside
  the frame (#1486, #1541).
- **`HEAD`, byte ranges and conditional requests on the COG download.**
  `HEAD` returned 405, which left GDAL `/vsicurl/` unable to open a dataset
  without fetching it whole. The route now answers `HEAD` from object
  metadata on every backend, serves ranges bound to one representation
  through a strong ETag, honours `If-Match`, `If-None-Match` (including `*`
  on a row with no stored digest) and `If-Range`, and issues one object-store
  read per range instead of one per megabyte (#1528, #1540, #1554, #1574).
- **Dataset exports are served from a cached artifact.** Every request to
  `/datasets/{id}/export`, including every byte-range probe, used to run a
  fresh conversion, so one GDAL open cost roughly ten conversions and could
  splice two different artifacts under one URL while the data changed. The
  artifact is now built once per dataset, format, filter set and data
  version, and every range is a slice of that stored object under a strong
  ETag; a range against a stale artifact, or against a selection where two
  different artifacts are still live, gets a fresh full response, never a
  splice. A bare range that starts at byte 0 is honoured on the very first
  build too, because GDAL's first request is `Range: bytes=0-16383` and it
  gives up on a whole-body 200; that leading slice is refused only while a
  different artifact for the same selection was served within the last two
  freshness windows. `If-Match`, `If-None-Match` and `If-Range` are honoured
  on both the cached and the rebuilt path. Freshness is a fixed 60 s window plus the
  upload time, so a write that misses the cache-version bump costs at most
  that much staleness, never a wrong download; the cache holds at most
  8 GiB and reclaims after four hours. GeoPackage and zipped Shapefile
  exports are byte-deterministic for unchanged data (the per-conversion
  timestamps ogr2ogr stamped are normalized), so unchanged data hashes the
  same twice. The export and COG download routes are excluded from gzip in
  the app and in the bundled nginx, because a compressed 200 and a raw 206
  cannot share one validator (#1532, #1582, #1585).
- **A map thumbnail can be produced without a browser.** `scripts/` gains a
  backfill for maps a browser never opened, which on a seeded instance was
  every private map (#1501).
- **Cookie-mode auth headers are declared in the OpenAPI document.**
  `X-GeoLens-Auth-Mode` and `X-CSRF-Token` are now operation parameters on
  the login, refresh and logout routes rather than prose, so generated
  clients see them (#1498, #1496).

### Changed

- **An API key or token that cannot be resolved now returns 401 on every
  endpoint that reads credentials.** It used to get a 401 from the eight OGC
  and STAC detail routes and be discarded in silence by the other 58
  handlers, which answered 200 with the public subset. That response looks
  exactly like a catalog holding nothing more, so a client whose key expired
  overnight kept working against a quietly smaller view of the data. Which
  answer you got depended on which route you hit, so the behaviour could not
  be documented. Requests that send no credential are unaffected and still
  get the public view.

  Three cases sit outside the rule. `POST /auth/logout` accepts a dead access
  token, so a session whose token has already expired can still be cleared. A
  request that a capability authorized on its own is served and the unrelated
  dead credential is ignored rather than refused, so an embed viewer with a
  stale browser session still renders: a valid `X-Embed-Token`, or a valid
  signed tile template (`sig`, `exp`, `scope`). An invalid or missing one puts
  the request back under the rule. And a shared-map link that is unknown or
  revoked still answers 404 or 410 for every caller, because no credential
  could have made that link work (#1518, #1524, #401).
- **The admin embedding regenerate runs on the job queue.** A full
  regenerate used to run inside the HTTP request and outgrow the 600 s edge
  timeout at roughly 59,000 records, after which the operator saw a 504 while
  the server kept working, and a retry started a second concurrent
  regenerate. The endpoint now returns a job id immediately, the run happens
  on the queue, PostgreSQL enforces one active regenerate at a time, and the
  audit trail records exactly one terminal outcome per run whichever actor
  closes it (#1542, #1550, #1556, #1575).
- **Stored embeddings record the configuration that produced them.** Rows
  used to carry only the model name, so one model behind two endpoints, or
  at two widths, was two vector spaces under one label and semantic search
  could compare across them and return well-formed nonsense. Each stored
  vector now carries a fingerprint of the model, dimensions and endpoint
  that produced it; semantic search, related items, the non-force backfill
  and the admin coverage panel all filter on the live configuration's
  fingerprint, so rows from another configuration are invisible rather than
  wrong. Rows written before this release keep matching on model name alone
  until they are regenerated; upgrading changes nothing an operator sees and
  triggers no re-embed. Search's candidate scan uses pgvector's iterative
  scan so a catalog holding foreign rows cannot starve the live ones. Related
  items compare against the anchor record's own model and fingerprint, so a
  record embedded under an older configuration still finds its neighbours
  among rows of that same configuration, and a record with several stored
  vectors anchors on the one search would use (#1546, #1578, #1580, #1583).

  Overlay authors: `EXTENSION_API_VERSION` is now 9, bumped twice in this
  release. `CatalogPort` gained a required `resolve_embedding_config`,
  `generate_embedding` takes the resolved configuration as a pin,
  `get_record_embedding` returns the row's model and fingerprint alongside the
  vector, `get_embedding_distances` takes that pair as two required keyword-only
  arguments, and `get_nearest_record_ids` takes the caller's already-read
  anchor — the vector and that pair together, in one required `anchor` keyword —
  instead of reading one for itself.
- **A force embedding regenerate no longer deletes before it can finish.**
  It used to commit `DELETE` of every embedding before generating anything,
  so any abort after that point left the catalog with no vectors. Old rows
  are now replaced per batch inside the same transaction that writes the
  new ones, and vectors for records the run could not embed are reclaimed
  once at the end, against a database-clock cutoff taken before the run
  read its records, so a vector the ingest path wrote during the run
  survives it. The run's `created` count is the number of rows written
  (#1549, #1581, #1584).

### Fixed

- **The embed snippet boots and renders a map.** It could not start, and
  retried at roughly 60 requests a second while failing (#1515, #1520).
- **A domain-locked embed token delivers its layers.** Setting
  `allowed_origins` produced a token that returned zero layers and 403 on
  every tile, because the API compared against an origin browsers never send
  from a framed document. The lock is enforced by `frame-ancestors` at the
  document layer, as it always was; the API now accepts the deployment's own
  configured origin. Setting a lock while `PUBLIC_APP_URL` is unset or points
  at loopback is refused up front instead of failing on every later request,
  and every URL handed to someone else is built from the configured public
  origin rather than the admin's current hostname (#1531, #1548).
- **`PUBLIC_APP_URL` is validated the same way on both doors and both
  sides.** The environment path never ran the validator, so a value ending in
  `/api`, an IPv4-mapped IPv6 literal, or a loopback address other than
  `127.0.0.1` could reach the share panel and build links that could not
  open. Both the environment and the admin setting now apply one rule, the
  frontend applies the same rule, and dot segments in the path are resolved
  the way browsers resolve them before the `/api` check (#1555, #1576).
- **A missing raster dataset answers 404 instead of 204.** An absent dataset
  was indistinguishable from an empty tile (#1516, #1523).
- **`HEAD` on the dataset export route no longer returns 405**, which had
  hung GDAL (#1513, #1522).
- **A force embedding backfill can no longer delete vectors it cannot
  regenerate.** The model, its dimensions and its endpoint are resolved once
  and pinned for the run, verified past the settings cache before anything is
  deleted, and re-checked around every provider call so a change landing
  mid-run stops the run rather than writing vectors into a space the live
  search will not match (#1511, #1519, #1525, #1539).
- **A backfill stops when the embedding column moves by any route.** An
  admin width change was already caught through settings; a column altered
  by hand, restored from a dump, or left half-rebuilt now stops the run at
  the first batch and names the width, instead of retrying every record
  against a column that can never accept it. An already-wrong column is
  caught before the first batch is written, and one bad vector still costs
  one record rather than the run (#1533, #1579).
- **Changing the embedding model publishes its dimensions atomically.** A
  reader between the two writes saw a model paired with the previous model's
  width (#1529, #1538).
- **Settings cache keys for one save are evicted together**, closing a window
  where paired values could be read mismatched (#1543, #1547).
- **A failing backfill no longer costs more than a succeeding one.** Every
  failed record rendered a full traceback with the SQL parameters inline,
  which under the development log renderer cost close to a second per
  record; a per-record failure now logs one compact, credential-redacted
  line and the traceback once per exception type per run (#1544, #1577).
- **Browsing the catalog works in storage-denied browser contexts.** An
  unguarded `sessionStorage` read threw and left the landing page's browse
  action dead (#1527, #1535).
- **A rejected audit row can no longer destroy the caller's mutation.** Each
  audit sink runs in its own savepoint, so a row the database rejects rolls
  back alone (#1491, #1497).
- **The builder never persists a blank auto-captured thumbnail.** A capture
  taken before the first frame painted stored a solid fill; the crop is now
  measured before upload and a blank one is skipped (#1502, #1504).
- **Embedding coverage stats and Generate Missing agree with search.** Both
  are scoped to the active model, so a model swap no longer reports full
  coverage from rows search cannot use, and Generate Missing selects the
  records that actually lack a usable vector (#1503, #1505, #1506, #1510).
- **`seed-showcase.py --force` repairs the Matterhorn showcase** instead of
  dying on the manifest re-push (#1508, #1509).
- **The interactive latency alert no longer fires on bulk traffic** (#1517, #1521).
- **Release notes announce when they fall back to the commit log** instead of
  doing it silently (#1530, #1534).
- **Basemap attribution help text no longer calls the field optional** for
  XYZ tile providers that require credit (#1499).

### Internal

- A structural gate now fails the build on any unguarded
  `sessionStorage`/`localStorage` access under `frontend/src` (#1536, #1545).
- Removed a salted-hash seed that made a raster replace test flaky under
  `pytest-xdist` (#1526, #1537).
- An embedding backfill test asserted on the batch the anomalous record
  landed in, which on a shared worker database depends on how many records
  earlier tests left behind; it now asserts on the shape of the retry
  (#1587).
- Playwright refuses to run from a linked worktree without
  `E2E_ALLOW_WORKTREE=1`, because the dev stack always serves the main
  checkout (#1492).
- CI gates the committed README screenshot dimensions (#1500).

## [1.13.1] - 2026-08-14

### Added

- **Dataset attribution is persisted and displayed.** Attribution supplied
  at manifest ingest used to stop in the job metadata; it now lands on the
  record, comes back through the catalog API, and renders in the map's
  attribution control wherever the dataset is drawn (#1477, #1472).
- **Globe projection gets an atmosphere and a space background.** Maps
  saved with the globe projection render MapLibre's sky atmosphere and a
  deep-space backdrop behind the sphere, in both the builder and the
  viewer; mercator maps are unchanged (#1474, #1488).

### Fixed

- **Multi-color line symbology icons render again.** The layer list,
  sidebar, and legends drew a blank icon for every line layer with banded
  or graduated colors, because a zero-height bounding box disables the
  icon's gradient under the SVG default units. The gradient now uses
  user-space coordinates (#1494).
- **A logged exception can no longer pin the API event loop.** Production
  tracebacks are logged plain instead of through the rich renderer, which
  could spend minutes rendering a single traceback while the loop served
  nothing else (#1490).
- **Date fields in a dataset PATCH no longer 500 the request.** Audit
  details are serialized in JSON mode, so date-typed metadata fields
  write cleanly instead of failing the whole mutation (#1489, #1484).
- **Standards endpoints serve HEAD wherever the preflight advertises it.**
  A browser client that preflights a HEAD against a standards path was
  told it is allowed and then got a 405 (#1478, #1470).
- **DCAT feeds publish real raster access surfaces.** COG-backed rasters
  published a bare object-storage key as their distribution URL; raster
  and VRT datasets now list working access URLs (#1475, #1469).
- **Upgrades pull new images before stopping the app, and restore it if
  the upgrade fails.** The outage window no longer includes image
  download time, and a failed upgrade brings the previous release back
  up (#1476, #1467).

## [1.13.0] - 2026-08-13

### Security

- **Browser sessions now authenticate refresh with HttpOnly cookies and CSRF
  protection.** Refresh tokens move out of localStorage into an HttpOnly
  cookie scoped to the auth routes, with double-submit CSRF enforcement on
  the two routes where the cookie authenticates. The cookie flow is an
  explicit opt-in header, so CLI, SDK, and direct API consumers keep the
  byte-identical body-token contract. Logout is now a real server-side
  security event that revokes every refresh token and invalidates
  outstanding access JWTs (#1446, #1302).
- **Revocation gains a time-scoped horizon.** Refresh-token lookups and
  access-JWT validation refuse any credential issued at or before the
  user's last full revocation, an ordering-independent backstop layered on
  the existing `token_version` machinery. Logout, password change, and
  SAML-to-local conversion all stamp it (#1458, #1455).
- **The login/revocation serialization the horizon backstops is pinned by a
  deterministic test.** A login racing a logout either commits first and is
  revoked or completes wholly after it as a clean successor; the test
  forces the interleaving on observed lock state, never timers, so it
  cannot pass vacuously (#1460, #1459).
- **Tile serving refuses cached authorization for datasets that no longer
  exist.** The tile path re-checks dataset liveness before honoring a
  cached authorization decision (#1454, #1451).
- **Ingest can no longer resurrect a deleted dataset's tile cache by name.**
  Freed table names are retired in a persistent tombstone set consulted at
  registration and name generation (#1444, #1443).

### Changed

- **Deleting a registered dataset detaches it instead of dropping the
  table.** The catalog row, grants, tiles, and caches are removed while the
  operator's physical table survives; datasets GeoLens ingested itself are
  still dropped in full. The delete dialog says which will happen (#1453,
  #1452).
- **Tombstones now record what was freed.** Retirements carry the freed
  relation's oid and the prior owner; detaches that leave the table
  standing are recorded in a sibling `detached_relations` table, so future
  ownership-aware re-registration has the identity it needs (#1457, #1456).
- **The extension API version is now 7.** Overlay packages built against
  earlier versions must be rebuilt before deploying this release (#1444).
- **The admin data table is on react-table v9** (#1445, #1407).
- Dependency updates across the backend and frontend (#1447, #1448, #1449,
  #1450).

### Fixed

- **Raster tiles now send CORS headers.** External map clients that fetch
  tiles (MapLibre GL, the ArcGIS Maps SDK for JavaScript, OpenLayers) can
  consume GeoLens raster tiles cross-origin; out-of-extent empty tiles
  carry the same header, and the value is a static wildcard so tile caches
  can never replay a per-origin decision (#1465, #1464).
- **Auto-generated vector-tile distributions no longer claim OGC:WMTS.**
  The XYZ template is labeled `XYZ`, with payload semantics in `format`
  and `media_type`; a migration relabels existing auto-generated rows and
  leaves user-authored distributions untouched (#1466, #1463).

## [1.12.0] - 2026-08-12

### Added

- **Coding agents can now query dataset contents through the MCP server.**
  A hardened read-only SQL endpoint exposes the NL-to-SQL sandbox directly:
  queries run against the caller's RBAC-scoped table allowlist with the
  sandbox's statement validation, row, byte, and timeout caps, and the MCP
  server surfaces it as a `query` tool alongside the existing catalog reads
  (#1406).
- **Chat query results can be saved as datasets from the builder.** The
  result-preview overlay a chat query renders in the map builder now has a
  save path that materializes the preview into a real dataset (#1403).
- **Predicate chat queries offer a layer-filter follow-up.** When a chat
  answer is a predicate over a layer's features, the panel offers applying
  it as that layer's filter instead of leaving the answer stranded in the
  transcript (#1402).
- **Distributions can be reordered around a primary.** The dataset page's
  distributions list gains a set-primary control, and writing a new primary
  demotes the incumbent instead of leaving two rows both claiming it
  (#1399, #1393).
- **Source validation failures read as sentences.** The machine codes the
  source validator emits are mapped to user-facing strings in all four
  locales instead of leaking code identifiers into the UI (#1397).
- **The showcase seed gains a Hurricane Exposure map, and three global
  showcase maps render on the globe.** `seed-showcase.py` adds a seventh
  map joining hurricane tracks against coastal exposure, and the
  world-spanning showcase maps switch from mercator to globe projection
  (#1404).

### Changed

- **A raster CRS override now assigns the CRS instead of reprojecting to
  it.** Supplying an EPSG code at import or replace time relabels the raster
  in place: pixel values, the pixel grid and the corner coordinates all come
  through the conversion untouched, and only the CRS they are read under
  changes. That is what both documented uses of the field want — a file with
  no CRS has nothing to reproject from, and a file whose declared CRS is
  wrong reprojects from a wrong starting point and lands somewhere wrong.
  Two consequences: a dataset ingested with an override now sits where those
  coordinates put it in the CRS you named, and because the conversion no
  longer resamples, the uploaded file is deleted after a successful lossless
  ingest rather than kept as a second permanent copy. Deliberate
  reproject-at-ingest is not offered; rasters are reprojected at serve time
  and at export time (#1291).
- **A refresh run's `origin_kind` is documented as the door it executed
  through, not the dataset's origin.** The API description, both backend
  vocabularies, and the Source panel's run history now state the
  distinction explicitly; a run's kind and its dataset's origin can
  visibly disagree (a STAC-imported raster mid-replacement shows origin
  "stac" next to a run recorded "upload") and equality was never the
  contract (#1422).

### Fixed

- **A VRT's declared composition can no longer disagree with the served
  mosaic.** Adding or removing a VRT source stages the intended member set
  on the generation and applies it to the catalog in the same transaction
  that publishes the regenerated artifact. A worker death between accepting
  the mutation and finishing the build now leaves the catalog exactly as it
  was instead of describing sources the served VRT does not have. A
  mid-flight deletion of a staged source fails the run whole, and rolling
  deployments are fenced: an outdated worker refuses the staged job loudly
  instead of silently dropping the change (#1424).
- **VRT regeneration now invalidates tile caches.** The regeneration swap
  rolls the dataset's tile cache version the way every other refresh door
  already did, so a regeneration that changes the mosaic's shape stops
  serving pre-swap tiles from the URL-keyed and in-process caches until
  TTLs happen to expire (#1425).
- **Raster tile metadata stops going stale across API processes.** The
  per-process raster metadata cache keys on the tile URL's version
  parameter, so a raster replace, VRT regeneration, or source refresh is
  observed by every API worker immediately instead of after a
  sixty-second window. A request naming a future version cannot
  pre-poison the cache for the swap that later arrives (#1421).
- **Dataset pages notice refreshes started elsewhere.** Returning focus to
  an open dataset tab refetches the run history unconditionally, so a
  refresh dispatched by the CLI or another editor is observed and the
  page's caches roll instead of staying stale until remount (#1420).
- **Interrupted presigned uploads no longer strand objects.** Storage
  objects from presigned uploads whose tracking row never completed are
  reconciled against the tracking table and swept (#1401).
- **A reupload that removes geometry retires the synthetic geometry row**
  instead of leaving the dataset claiming a spatial column it no longer
  has (#1389).
- **VRT validation refuses sources whose pixel geometry was never
  measured** instead of composing them into a mosaic with undefined
  resolution (#1388).
- **Tenant-ownership adoption completes on the head schema.** The
  forward-only adoption path used by operators reaches the current schema
  without requiring an intermediate checkout (#1405).

## [1.11.1] - 2026-08-10

### Added

- **Raster replace is now reachable from the reupload dialog.** The
  in-place COG replacement that shipped in 1.11.0 gets its frontend door:
  the reupload dialog offers replace for raster datasets (#1362).
- **Remote rasters now report a measured resolution and rotation flag.**
  STAC-imported and refreshed raster assets read the affine transform from
  Titiler, so `res_x`/`res_y`/`is_rotated` are populated the same way a
  local upload populates them instead of staying blank (#1374, #1384).

### Fixed

- **Raster tiles stop serving stale imagery after a replace.** Tile URLs
  now carry the dataset's content version, so a raster replace, reupload,
  or source refresh rolls the shared nginx tile cache instead of serving
  the old pixels until the cache expired. A mismatched or duplicated
  version parameter is served uncached rather than rejected, so open tabs
  keep rendering (#1372).
- **Rotated rasters report their true pixel size.** Resolution was
  computed from the affine's axis components, understating a 30°-rotated
  raster by 13%; it now uses the pixel vector lengths on both ingest
  paths. Axis-aligned rasters are unaffected; a rotated raster's stored
  resolution corrects on its next ingest or refresh (#1384).
- **STAC `gsd` is published in metres, as the spec defines it.** Exports
  used to emit the raw CRS-unit value (degrees for EPSG:4326, feet for
  state-plane systems). Projected CRSs now convert through PROJ's
  metres-per-unit; geographic CRSs omit the field rather than publish an
  angular value as a length. The OGC Records surface is unchanged (#1384).
- **Reupload keeps geometry and record type honest.** Swapping a
  dataset's file derives the effective geometry and record type through
  a precedence of measured, declared, and stored values, so an empty or
  all-NULL-geometry file no longer reclassifies a still-spatial dataset
  as tabular (#1361, #1373).
- **User-authored distributions no longer hide the built-in export
  rows** on a record's distribution list (#1370).
- **CRS WKT is stored as WKT2:2019 at both raster ingest paths**, with a
  data migration converting existing WKT1 rows (#1376).
- **STAC assets keyed by an empty string are recovered after the item
  moves** instead of being reported unidentified (#1363).
- **ArcGIS imports request every field**, so service imports keep their
  full attribute set (#1368).
- **Vector tile purges after a reupload or PostGIS refresh now take
  effect.** The tile cache was only initialized in the API process, so the
  worker's post-swap purges silently evicted nothing and stale tiles could
  serve until the cache TTL expired; the cache is now initialized in the
  bootstrap both processes share (#1371).
- **Auto-generated distributions reconcile when a dataset's modality
  changes** (#1369).
- **A raster's origin carries its provenance hash from first ingest**
  instead of only gaining one after its first replace (#1360).
- **Single-dataset delete errors are sanitized** before reaching the
  client (#1358).

### Performance

- **Duplicate-source guards use an index** on the origin-reference keys
  they query instead of scanning (#1365).

### Operations

- **Migration 0041 is a data migration**: it rewrites stored WKT1 CRS
  definitions to WKT2:2019 in batches. Deploy logs report
  `converted to WKT2:2019: N row(s)`; the downgrade is a no-op.

## [1.11.0] - 2026-08-10

### Added

- **Datasets can now be refreshed from their source.** A dataset imported
  from a remote origin (an OGC/ArcGIS service, a STAC catalog, or a
  registered PostGIS table) can be re-pulled in place from the Source panel,
  the CLI (`geolens dataset refresh`), or `POST /datasets/{id}/refresh`.
  Refresh runs are durable rows with admission control: one run per dataset
  at a time, every attempt recorded with before/after counts and schema
  drift, and the dataset keeps serving its current data until the new data
  is ready (#1274, #1277, #1313, #1323, #1305).
- **STAC refreshes re-resolve moved items and assets.** A refresh re-reads
  the stored item document, follows the catalog to the asset's current
  location, and falls back to a collection-scoped search when the item URL
  itself is gone. Nothing is adopted unverified: the item must affirm the
  identity the import recorded, and a binding that predates identity
  tracking is refused with advice to re-import rather than guessed at.
  Imports now capture the item pointer, collection, and asset key so
  every future refresh has something to verify against (#1326).
- **Source health and freshness are visible everywhere datasets are.**
  STAC and service origins are probed for availability; dataset pages,
  search summaries, and the MCP server now surface health, freshness
  derived from the declared update frequency, and drift state, and the
  read-only Source panel shows the origin, storage mode, safe source
  pointer, and full refresh history (#1261, #1264, #1271, #1279, #1304,
  #1278, #1280).
- **A raster dataset's COG can be replaced in place** through the reupload
  door, preserving the dataset's identity, maps, and shares while swapping
  the underlying imagery (#1290).
- **Opt-in least-privilege database runtime role.** Setting
  `GEOLENS_RUNTIME_DB_ROLE` makes the API and worker connect under a role
  that owns no DDL, as defense in depth for self-hosted deployments
  (#1287).

### Fixed

- **VRT regeneration is visible and recoverable.** Generation timestamps
  now project into `last_refreshed_at`, and a recovery sweep reconciles
  regenerations whose worker died mid-flight instead of leaving them
  stranded (#1322).
- **STAC refresh refusals now explain themselves in the UI.** The refusal
  wordings introduced by the STAC door were missing from the frontend's
  error map, so a dataset imported before identity tracking showed a
  generic conflict message instead of the re-import instruction (#1333).
- **Duplicate-source detection keys on the canonical origin pair**, so a
  different spelling of the same asset URL can no longer slip past the
  guard or falsely block a distinct source (#1320).
- **Bulk delete no longer returns raw exception text** to the client
  (#1309).
- **Local object-storage listings are contained to their prefix** (#1307).
- **Stroke-only polygon styles render honest swatches** in the legend and
  layer panel instead of filled squares (#1310).
- **Generated SDK constructors keep a stable argument order.** The OpenAPI
  snapshot now serializes schema properties in declaration order, so
  regenerating an SDK cannot silently shift positional constructor
  arguments again (#1263).

### Security

- **Dataset provenance is projected owner-or-admin.** Anonymous and
  non-owner readers of a public dataset see the safe source pointer but
  not the structured origin binding, and refresh-run history hides who
  triggered each run (#1321).
- **Titiler now uses scoped object-store credentials** instead of the
  instance-wide MinIO/S3 identity (#1284).

### Operations

- **Protected service refreshes need a shared credential store.** Passing
  a service token to a refresh requires `REDIS_URL` (Valkey/Redis) so the
  credential can reach the worker without touching disk; deployments that
  only refresh public sources need no change.

## [1.10.0] - 2026-08-07

### Security

- **Password logins and dataset creation now write audit records, and the
  action registry can no longer drift silently from what's actually logged.**
  Failed and successful password-based logins, plus `dataset.create`, were
  gaps in audit coverage; a new registry test walks every `AuditEvent` call
  site (keyword or positional) and fails if it references an action that
  isn't declared (#1230).

### Fixed

- **A sweep restart no longer strands a presigned upload mid-transfer.**
  Lowering the presigned-URL timeout and restarting the sweep in the same
  window could orphan a job whose upload was still in flight; the sweep and
  the retry path now agree on the same margin, derived from S3's own
  single-PUT size ceiling rather than a client-declared file size (#1236).
- **A capped analysis preview now says so.** Previews that hit the row cap
  used to render like a failed query; the map now shows the partial result
  honestly, both in the preview list and as an on-map treatment, scoped to
  the bbox actually queried (#727).

### Changed

- **`/metrics` no longer resets when a worker recycles.** Multi-worker
  deployments (`UVICORN_WORKERS > 1`) previously served per-process counters
  that could step backward on scrape whenever a worker restarted, which twice
  produced false "site down" alerts in production. `/metrics` is now backed
  by prometheus_client's multiprocess mode: a `PROMETHEUS_MULTIPROC_DIR`
  tmpfs directory aggregates counters across workers, and a background sweep
  reclaims a recycled worker's files without racing an in-flight scrape
  (#1240, #651).
- **`quality_score_numeric` removed.** The column was never wired to
  anything; dropped via migration rather than carried forward unused (#1231).
- **Python SDK: `AnalysisPreviewRequest`'s positional constructor argument
  order shifted.** The new `bbox` field (#727) landed alphabetically before
  `distance_meters` in the regenerated model, so code calling
  `AnalysisPreviewRequest(operation, 500)` positionally now binds `500` to
  `bbox` instead of `distance_meters` and gets a 422 on the next request.
  Call with keyword arguments (`AnalysisPreviewRequest(operation=...,
  distance_meters=500)`) to avoid this and any similar future reordering;
  tracked for a permanent fix in #1257.

### Operations

- **New required-for-multiprocess env var: `PROMETHEUS_MULTIPROC_DIR`.**
  Set to a tmpfs-backed path in both the dev and prod Compose files. If you
  run a custom deployment with `UVICORN_WORKERS > 1`, set this to a writable,
  empty-on-boot directory or `/metrics` will serve single-process
  (non-aggregated) counters again. Recreating the `api` container to pick up
  this variable without also rebuilding the image will fail to boot: the
  entrypoint script that prepares the directory ships in the image, not the
  Compose file, so a deploy must rebuild/pull before it recreates.

## [1.9.0] - 2026-08-06

### Security

- **The presigned reupload door enforces the same completion contract as the
  upload door (#1207).** Dataset replacement via presigned upload now goes
  through the shared one-shot completion guard: a job whose bytes are already
  bound or whose status is terminal is refused with a clear restart hint
  instead of being silently re-completable. The frozen-copy discriminator keys
  off the `staging/` prefix, and a refused completion deletes both the frozen
  snapshot and the client-writable key.

### Fixed

- **A failed import keeps its source, so retry works.** Transient failures
  (an S3 blip during download, a mid-ingest error) no longer delete the
  staging object that `/jobs/{id}/retry` needs; only dataset-replacement
  jobs, which are never retryable, reap their source on failure. Terminal
  cleanup also drains through cancellation, so an interrupted worker cannot
  skip the sweep of a still-recreatable staging key (#1213).
- **A dropped connection during multipart completion no longer destroys the
  upload.** The assembled object is the record that assembly succeeded; it is
  now kept when the request is cancelled, so the client's natural retry
  completes instead of 502-looping until a full re-upload (#1233).
- **The stale-job sweep no longer races a finishing completion.** A job that
  bound its bytes moments before the sweep ran could be failed out from under
  a request that had just returned success; bound and unbound jobs now age on
  separate clocks, applied identically by the background sweep, the status
  poll, and worker startup recovery (#1234).
- **Presigned URLs expire exactly when their job does.** Part and PUT URLs
  used to carry fixed lifetimes measured from whenever they were signed; every
  URL is now signed against the job's deadline, computed inside the signing
  thread, and the new `PENDING_JOB_TIMEOUT_SECONDS` setting (61..604800)
  bounds both together (#1234, #1235).
- **Manifest sources declared under a `staging/`-shaped key are refused at
  declaration time** instead of being silently deleted after their first
  ingest by the staging sweep (#1216).

### Changed

- **react-router upgraded 7.18 -> 8.3** and the last `js-audit` allowlist
  entry removed — the advisory it waived (GHSA-qwww-vcr4-c8h2) no longer
  applies at 8.3.0 (#1205).

### Operations

- **Bundled MinIO aborts abandoned multipart uploads after 24 hours**
  (`MINIO_API_STALE_UPLOADS_EXPIRY`, operator-overridable), and RUNBOOK.md
  documents the equivalent AWS S3 lifecycle rule. Note for MinIO operators:
  S3 `AbortIncompleteMultipartUpload` lifecycle JSON is silently ignored by
  MinIO (minio/minio#19115) — the server-side stale-uploads sweep is the
  mechanism. The abort window must exceed the configured upload lifetime with
  headroom: if `PENDING_JOB_TIMEOUT_SECONDS` approaches or exceeds ~23 hours,
  raise the abort window above it (#1211).

## [1.8.0] - 2026-08-05

### Added

- **All four admin lists are sortable.** The Users list gained server-side
  sorting with clickable column headers (#1200), and Jobs, Audit Log, and
  Published Maps adopt the same pattern (#1204): closed-enum sort parameters
  (bad input is refused with a 422), NULLS LAST on nullable columns, and a
  stable tiebreak so paging never repeats a row. Sort state lives in the URL,
  so a sorted view can be bookmarked or shared.
- **Analysis results can be chained.** A materialized analysis output can be
  fed straight into another operation without leaving the builder (#1130).
- **The ephemeral analysis preview appears as a row in the layer stack**, so
  it can be toggled and inspected like any other layer while it exists (#1165).
- **Analysis-derived datasets surface inherited keywords** from their source
  datasets in catalog search and dataset detail (#1178).
- **A TITILER_WORKERS knob** sizes the raster tile sidecar's worker pool for
  larger deployments (#1197).

### Security

- **Presigned uploads get the same content validation as direct uploads
  (#1202).** The completion endpoint used to accept whatever bytes sat at the
  staging key; it now server-side copies the object to a frozen key no client
  URL has ever pointed at, and judges the frozen copy — size, quota, and the
  same content validation the direct door runs, returning the identical 422.
  Freezing first closes the swap window a still-valid presigned PUT URL
  otherwise has (upload clean bytes, complete, re-PUT garbage). Completion is
  one-shot and serialized per job, a failed completion is retryable without
  re-uploading, and staging objects are swept at job end plus once more after
  the URL expires, so a dead URL cannot leave bytes behind. The dataset
  **reupload** completion door has the same gaps and is NOT covered by this
  release; it is tracked as #1207.
- **URL credential redaction is bounded against quadratic backtracking
  (#1118)**, refuses unparsable authorities (#1162), and no longer raises on a
  malformed authority (#1131).
- **The titiler sidecar pins its GDAL rawband environment (#1197)** and is
  bumped 2.0.5 → 2.2.1 (#1198).
- Dependency advisories patched: cryptography, undici, brace-expansion
  (#1173), idna floors for CLI/SDK and cryptography 50 for MCP (#1179).
- The backend image ships a third-party NOTICE file (#1189).

### Fixed

- **Presigned uploads stamp raster metadata (#1196).** On S3 deployments every
  GeoTIFF uploaded through the browser fell through to the vector branch and
  failed at preview. This release also makes that path the validated one — see
  #1202 above.
- **Manifests accept extension-defined record statuses (#1201).**
  `record_status` is documented as extension-defined (#1194); the manifest
  layer now validates intent against the live extension's status order instead
  of a frozen four-value set, and the CLI schema follows.
- **The admin Jobs badge counts failed jobs, not all jobs (#1195).**
- **Keyword suggestions honor the counterfactual only for the record owner
  (#1184).**
- **The login page refreshes its provider list after admin OAuth/SAML changes
  (#1163).**
- **DEM terrain coverage is measured from the layer extent, not the token span
  (#1129)**, and small-DEM viewport coverage works across the antimeridian
  (#1124).
- **`dataset_extent_bbox` is served in the RFC 7946 spec form (#1125).**
- **Intersect carries JSON and XML overlay attributes through to the output
  (#1123).**

### Changed

- **Operators: API worker memory recycling guidance** is in the runbook
  (#1177) — the recommended mitigation for slow RSS growth under sustained
  raster proxy load (the #643 investigation continues).
- **The permission extension seam can answer who a record's audience is
  (#1126)**, groundwork for overlay-aware visibility guards.
- CI and local dev converge on Python 3.14 (#1168).

## [1.7.1] - 2026-08-02

### Fixed

- **Analysis provenance no longer names datasets the requester cannot see
  (#1103).** `lineage_summary` is now access-checked per requester on every
  read surface that serves it — dataset detail and lists, OGC records, STAC,
  and the three DCAT feeds, including the anonymous ones. A requester who can
  read every referenced dataset gets the stored sentence unchanged; anyone
  else gets a neutral placeholder rather than any part of the stored text.
- **Curved geometries work end to end (#1104).** `geom_4326` is now always
  linear: ingest densifies arcs in the source CRS before reprojecting,
  migration 0034 backfills existing rows for registered datasets, and
  registering a table with a pre-existing `geom_4326` linearizes it on the
  way in. Vector tiles, feature reads, and every analysis operation now work
  on MultiSurface/CompoundCurve sources; the curved original stays in `geom`.
  The migration skips columns it cannot rewrite (stored generated columns,
  legacy constraint declarations) and names each one in an operator warning
  instead of blocking the upgrade.
- **A malformed paint value can no longer break a shared map (#1069).**
  Legacy `stops` values are shape-checked at write time (422), and
  `GET /maps/{id}/style.json` drops a bad stored layer with a warning instead
  of failing the whole document. MapLibre expressions that merely contain a
  `stops` key as data are unaffected.
- **Dataset visibility changes are refused only when someone is actually
  stranded (#1073).** The guard now judges each shared audience on its own
  instead of over-refusing: narrowing visibility when every active user
  already holds a grant, or when no one else is active, goes through. Under a
  non-default permission extension the conservative refusal is kept, since
  the community query cannot see viewers an overlay admits.
- **Style copy/paste keeps fill-color and fill-pattern mutually exclusive
  (#923).** The paste merge resolves the fill pair through the same rule the
  editor applies, and the colour a pasted pattern displaces is stashed so a
  later switch back to "None" restores the pasted style's colour, not the
  target's old one.
- Registered tables with Socrata-style column names (`:id`) read correctly
  through feature endpoints, and registering a table whose generated
  `geom_4326` yields curved values is refused with the cause.

### Changed

- **The CLI can drive spatial joins (#1105).** `geolens analysis preview` and
  `materialize` gained `--join-dataset-id` and `--join-fields`, the
  `--operation` help lists every server operation (dissolve is
  materialize-only), and a missing `--join-dataset-id` fails fast with the
  server's wording. The CLI now requires the 1.7.0 SDK, the first whose
  analysis models carry the join fields.

## [1.7.0] - 2026-08-01

### Added

- **Four new analysis operations: spatial join, measure, select by location,
  and intersect.** They join buffer, centroid, clip, and dissolve in the
  builder's analysis panel: preview the result on the map, then materialize it
  as a new dataset. Spatial join and select by location match on intersection;
  measure adds computed `area_sqm` and `length_m` columns; intersect writes
  the pairwise overlay with attributes from both sides. (#1097)
- **Materialized analysis outputs record where they came from.** Each output
  dataset carries the operation, its parameters, and the source dataset ids it
  was derived from, visible in the dataset detail. (#1045)
- **An analysis job started in one tab is visible in all of them**, and its
  completion notifies once instead of once per tab. (#1043)
- **The CLI can run analyses**: `geolens analysis preview` and
  `geolens analysis materialize` drive buffer, centroid, clip, dissolve,
  measure, select by location, and intersect from scripts. Spatial join is
  not yet drivable from the CLI — it requires a join dataset the CLI has no
  flag for (#1105). (#1050)
- **Builder chat can clip a layer by another layer** ("clip roads to the city
  boundary") through the same analysis pipeline. (#1071)
- **API keys now carry a scope.** A key is minted as `full` or `read_only`;
  read-only keys can fetch data but not mutate it. Existing keys keep full
  access. (#1055)
- **Raster tiles work for API-key clients.** The tile template returned by the
  token endpoint is signed, so private rasters render outside a browser
  session (QGIS, scripts, embeds driven by a key). (#1059)
- **Datasets can be internal**: visible to any signed-in user without a
  per-user grant, sitting between private and public. Visibility is edited
  from the dataset's Access tab, and a change that would break a shared map
  is blocked with a message naming the map. (#1029, #976, #1056)
- **Fill patterns pick up the layer's fill color** instead of rendering only
  in their baked-in color, and the pattern shows on the legend chip and
  layer-list swatch. (#1091, #979)
- **Backups now capture cluster roles.** Each cycle writes a
  `globals-<timestamp>.sql` next to the dump (`pg_dumpall --globals-only`),
  which is what makes a restore onto a fresh cluster able to rebuild roles
  and their passwords. The backup service also warns at startup when offsite
  upload is disabled. (#1027, #1062)
- **Parquet ingest is bounded**: a file that expands past the total row or
  cell cap is refused up front instead of exhausting the worker. (#1038)

### Changed

- **Extents that cross the antimeridian are now served in RFC 7946 spec
  form** — a bbox with west > east (e.g. `[178, -19, -178, -17]` for Fiji)
  at the dataset and collection endpoints, instead of a flattened
  `[-180, …, 180]` span. Clients that assume west ≤ east need to handle the
  wrap. (#1040, #1060)
- **Antimeridian handling was reworked end to end**: ingest shifts 0..360
  sources into ±180 and reports Mercator-clamp drops in the job result
  (#899), crossing extents are stored as two rings (#901), extent rollups
  fold on the circle instead of across the globe (#925, #928, #980), exports
  filter a crossing bbox server-side (#898, #969), buffers project each
  component in its own planar projection and split output at ±180 (#883,
  #900, #990, #986), and COG/VRT bounds are normalized (#924).
- **Analysis is bounded under load**: a per-tenant cap on active materialize
  jobs (#1053), a global bound on concurrent previews (#1061), statement
  timeouts configurable via environment settings (#1057), materialize
  `work_mem` scoped to the session with a justified ceiling (#1048), and the
  per-user materialize slot held on a heartbeat lease so a dead worker frees
  it (#972).
- **A runaway query can no longer fill the database volume**: the bundled
  Postgres sets `temp_file_limit`, so a spill fails that query instead of
  the cluster. (#962)

### Removed

- **`GET /tiles/raster-auth-check/` is gone from the API contract and both
  SDKs.** It existed to answer an nginx `auth_request` subrequest back when
  nginx proxied raster tiles straight to Titiler. That topology was replaced by
  the api-side raster proxy, which enforces the same RBAC in-process, so the
  endpoint had no HTTP caller left. Anyone calling it directly should use the
  raster tile URL from `GET /tiles/token/{dataset_id}/` instead. (#957)

### Corrections

- **The 1.4.3 redirect mitigation for GDAL fetches did not work.** That
  release claimed raster preview and Titiler tile fetches "no longer follow
  HTTP redirects" via `GDAL_HTTP_FOLLOWLOCATION=NO`. The variable is not a
  GDAL configuration option and never had any effect: GDAL followed
  redirects with it set exactly as without, verified on GDAL 3.10.3 and
  3.12.1, and GDAL exposes no option that disables redirect-following. The
  inert variable has been removed everywhere so it cannot be mistaken for a
  defense. The protections that do apply are URL validation at the API
  layer (`validate_url_for_ssrf`, with per-redirect revalidation on httpx
  paths), the `CPL_VSIL_CURL_ALLOWED_EXTENSIONS` allow-list on GDAL
  fetches, and fetching only managed storage in the raster pipeline;
  deployments that need a hard redirect bound for user-supplied service
  URLs should enforce it with worker egress rules. (#937)

### Security

- **The SQL sandbox validator was tightened**: nested DML inside CTEs is
  rejected, `timeout_ms` is threaded through the execution wrapper (#1026),
  EXISTS subqueries are admitted rather than forcing raw-SQL fallbacks
  (#1024), and the canonical geodesic buffer template is matched whole
  (#1036).
- **A dataset owner setting restricted visibility no longer needs a grant to
  their own dataset** — the creator is exempt from the grant check that
  otherwise locks everyone out. (#970)

### Fixed

- **The style editor keeps fill color and fill pattern mutually exclusive in
  both directions** — picking one clears the other, instead of a pattern
  silently deleting the stored color. (#1022)
- **Clearing the builder actually clears it**: the style editor no longer
  resurrects the cleared layer's persisted state. (#1092)
- **The unsaved-changes flag tells the truth**: a style Revert that restores
  the saved state clears it, and four false-dirty verdicts in the clean-state
  recheck are fixed. (#988, #999)
- **Categorical styling reports the true category count** and scopes the
  color ramp correctly on mixed-geometry layers. (#1058)
- **Advanced JSON paint for symbol layers is validated as circle paint**
  (#977), its errors are announced to screen readers, and the style-editor
  selects have accessible names (#984). Per-value symbol icons are validated
  and empty entries dropped (#982).
- **Exports render a builtin fill pattern as a solid fill** instead of
  dropping the layer's styling. (#1054)
- **Map thumbnails update when the map changes** — the thumbnail carries its
  own timestamp instead of riding the map's. (#1052)
- **Tile tokens are re-minted when a backgrounded tab returns**, instead of
  after a burst of 403s, and raster tile auth failures surface instead of
  rendering blank. (#881, #897, #964)
- **Cluster popups report the real split zoom** (`expansion_zoom`), so
  click-to-expand lands where the cluster actually breaks apart. (#882)
- **Degree CRSs are classified from the stored WKT** rather than assuming
  only EPSG:4326 is geographic. (#963)
- **A single-point dataset gets a padded extent** instead of a zero-area
  ring that some consumers refused. (#1032)
- **Builder chat discloses when a preview is capped** and the total row
  count is unknown. (#1079)
- **The dev server answers CORS preflights behind a tunnel**, so remote
  development against the API works again. (#1102)

### Upgrade notes

- **Restart the backup container once after upgrading** (any full stack
  restart covers it). The backup daemon reads its entrypoint at container
  start, so an already-running daemon keeps the old cycle and will not
  produce the new `globals-*.sql` role dump until it restarts.
- Two endpoints changed shape as described above: antimeridian-crossing
  extent bboxes are now spec-form (west > east), and
  `GET /tiles/raster-auth-check/` is gone from the contract.

### Known issues

- Curved geometries (MultiSurface/CompoundCurve) break tiles, feature reads,
  and analysis operations; ingest-time normalization is planned. (#1104)
- `lineage_summary` on a materialized output can name a source layer the
  requester cannot see. (#1103)
- Intersect refuses layers with json/xml attribute columns instead of
  carrying them through the overlay. (#1099)
- Some frontend map surfaces still misrender a seam-crossing (west > east)
  extent; the dataset-preview guard is bypassed by large extents. (#903)
- Metrics report per-worker registries only; Prometheus multiprocess mode is
  not yet adopted. (#651)
- The CLI cannot run a spatial join (no flag for the required join dataset),
  and its analysis help text still lists only buffer, centroid, and clip.
  (#1105)

## [1.6.1] - 2026-07-29

### Added

- **Maps saved with a globe projection now render as globes everywhere.**
  The shared-map viewer, embeds, and dataset previews applied the default
  Mercator projection regardless of what the map was saved with; they now
  honor the saved projection. (#845)

### Security

- **API keys expire and go stale with their owner.** Keys now carry an
  expiry, are invalidated when the owner's key epoch rotates, and the
  deprecated query-parameter lane is scoped down. (#864)
- **react-router bumped to 7.18.2** for the upstream RSC CSRF backport.
- **Admin settings routes are gated mode-aware**, matching the backend's
  `require_settings_admin` — a route no longer renders for a role the API
  would reject. (#857)

### Fixed

- **Clusters no longer pile on top of each other.** The server-side cluster
  grid read the cluster radius in tile units instead of screen pixels,
  producing a grid roughly eight times finer than intended: overlapping
  cluster bubbles and single features leaking through at low zoom. The
  radius now converts to tile units correctly, the grid is anchored
  consistently across tiles, and each cluster is owned by exactly one
  tile. (#868)
- **A backup cycle no longer fails just because the instance was busy.**
  Anything writing to object storage while the backup archived it made tar
  report "file changed as we read it", and the cycle treated that warning
  as fatal: it deleted the (fully written) archive and left the backup
  container unhealthy under the new freshness probe. The warning now keeps
  the archive and the cycle; only a fatal tar error (exit 2+) fails it.
  (#843)
- **Silent frontend errors now reach the problem reporter.** Errors caught
  by boundary components used to disappear; they are included in problem
  reports, and the theme provider no longer throws when browser storage is
  blocked. (#818)
- **The builder's Ask-AI entry no longer flashes "unavailable" while
  permissions load** — it stays in a loading state until the answer is
  known. (#817)
- **Attribute tables no longer lock up with a screen reader attached.**
  Dynamic row measurement fed an accessibility-tree render loop; rows are
  fixed-height now. (#830)
- **Mid-edit admin settings survive a background refetch** instead of
  being clobbered by the incoming server state. (#823)
- **Exports validate their inputs**: a stray colon in a `where` filter or
  a bad layer name returns a clear 4xx instead of an ogr2ogr failure.
  (#832, #833)
- Assorted accessibility and UX follow-ups from the 1.6.0 pre-tag audit:
  keyboard and label fixes across admin and builder surfaces, plain layer
  names in Ask-AI suggestions, and a cleared token-refresh retry timer in
  the shared-map viewer's failure path. (#820, #831, #834)

## [1.6.0] - 2026-07-28

### Added

- **Cluster count labels can be turned off.** A "Show counts" toggle in the
  cluster style editor hides the numbers on cluster bubbles — they read as
  feature labels even with labels disabled — leaving size and color to carry
  magnitude. The count stays available in the cluster popup, and existing
  maps keep their counts. (#839)
- **Categorical layers are legible from the layer list.** A layer styled by
  category now shows its classes as distinct color bands instead of a single
  blurred gradient swatch, and the row names the styled column and class
  count (e.g. "fall · 2 categories"). (#840)

### Security

- **Map sharing surfaces are gated tighter.** The visibility-check
  endpoint now requires map ownership — its response names non-public
  dataset titles, which read access alone should not reveal — and
  creating or managing embed tokens requires the same `edit_metadata`
  capability as creating the share link the token accompanies.

### Fixed

- **Upgrading no longer reports a false "Upgrade FAILED".** The new backup
  freshness marker doesn't exist yet on a pre-upgrade install, and the
  upgrade script's 90-second health wait counted services still inside
  their declared start period as unhealthy — so any database that took
  longer than that to dump printed a failure banner and a rollback recipe
  while the stack was actually fine. Services still starting are now
  treated as converging.
- **A restored database keeps its read-only grants.** The single-server
  restore script granted the reader role before `pg_restore --clean`
  dropped and recreated the schema, silently revoking them again; tiles
  and sandbox queries then failed with permission errors. Grants now
  apply after the restore and are asserted before the script reports
  success.
- **A backup cycle whose staging archive fails is no longer reported as
  successful**, and several backup edge cases are closed: a zero-padded
  schedule minute never matching, a truncated dump left looking complete,
  blank S3 credentials counting as an upload, and a retention setting of
  0 deleting the dump it just wrote.
- **Layer rows are fully keyboard-operable.** Visibility eyes, group
  carets, inline delete confirms, and renames (including typing spaces
  and committing with Enter) now work from the keyboard on every row
  type, with focus returned where it was.
- **Raster tile errors are no longer misclassified as handled**, and an
  authentication failure that can't be recovered now surfaces the map's
  error state on the dataset preview and viewer instead of failing
  silently. Vector previews gained the same loading and error states
  rasters already had. A *recovering* session no longer trips that error
  state: every tile error in the burst that triggered a token re-mint
  used to count as a failed recovery, flashing "Preview unavailable"
  over a map that was about to render — errors now surface only if they
  persist after the re-mint had time to land.
- **Private raster layers render for signed-in users in the shared-map
  viewer**, which never attached the auth header raster tiles need
  (the builder and dataset preview already did).
- **Backups no longer accumulate orphaned temp files.** A dump
  interrupted mid-write left a `.dump.tmp` file no retention pass would
  ever delete; each cycle now clears leftovers at start.
- **Bulk delete announces the real count while deleting**, its
  confirmation prompt behaves as a proper dialog, selection no longer
  survives on rows hidden by search or a collapsed group, and a partial
  failure no longer discards layers added while the delete was in
  flight.
- **The Analysis panel keeps a drawing session intact**: Escape cancels
  the draw instead of closing the panel, converted buffer distances can
  no longer exceed the cap in the converted unit, Enter runs Preview,
  and the collision warning the backend already recorded is finally
  shown. Analysis jobs also record their completion time, so job lists
  and retention age on the right timestamp.
- **Switching a vector basemap to a raster one no longer stacks the old
  basemap on top** of the new one on dataset previews.
- **Clearing a max-zoom field no longer writes 0** (which hid the layer
  at every zoom), the last movement of an opacity slider isn't lost when
  the editor closes, Reset asks before destroying a configured style,
  and the "Reverse" ramp option actually reverses DEM and heatmap ramps.
- **Applying the Advanced JSON editor no longer resets the layer's zoom
  range.** Apply wrote the editor's copy of the layout back wholesale,
  and that copy has the zoom bounds stripped — so an Apply with no edits
  at all silently wiped a configured min/max zoom back to the defaults.
  (#770)
- **Folder groups no longer produce phantom legend entries**, on screen
  or in the PNG export. (#769)

### Changed

- **Crossing the public boundary on a shared map now asks first.** Making
  a map public shows which layers will stay hidden from the audience
  before committing, and leaving public warns that existing share links
  will stop working. Changes that don't cross that boundary keep their
  one-click behavior. (#778)
- **Admin AI status surfaces gate on the same capability the backend
  checks**, so operators who can read AI status always see the card, and
  users without that capability no longer fire requests the backend
  rejects. (#653)
- **The builder chat availability probe follows that same capability**:
  users who can read AI status get the detailed signal, everyone else
  with chat access uses the public one — previously the split keyed on
  the admin flag, which could probe an endpoint the backend rejects and
  skip users it would allow. Probes now also wait for the deployment
  mode to be known instead of guessing. The disabled-state Settings
  shortcut shows only for users who can open admin settings, and lands
  on the AI tab instead of General. (#815)
- **Feature popups open from the keyboard in the shared-map viewer**,
  matching the builder.
- **A cancelled or fenced-off analysis job cleans up its orphan output
  table** when no dataset adopted it — and never drops a table another
  actor did adopt.
- **The nightly CI run no longer gets cancelled by daily dependency
  merges**, and the runbook now states plainly that default local
  backups share the database host's disk, pointing at the offsite
  upload section. (#798)
- **The backup container reports unhealthy when backups stop
  succeeding**, not just when its loop dies — operators see a red
  container instead of discovering stale backups during a restore.
  Freshness is judged against the new `BACKUP_MAX_AGE_MINUTES` setting
  (default 1560 minutes = 26 hours, sized for the default daily
  schedule); operators on a non-daily `BACKUP_SCHEDULE` must set it to
  roughly 1.5× their backup interval. (#800)
- **Destructive confirms are consistently ordered** (safe action left,
  destructive right) across the builder, and revoking a share link asks
  first. (#809)
- **Builder accessibility batch**: accessible names on maps, sliders and
  rename inputs, live regions that announce reliably, translated drag
  announcements, and honest inline-confirm semantics. (#804, #810)
- **The Add Data dialog stays open across adds**, so several datasets
  can be added in one pass; the layer editor opens on the last added
  layer once the dialog closes instead of landing behind it. (#776)
- **The first-run empty state matches a stock install**: the copy no
  longer points at starter datasets and an Upload button a fresh
  install doesn't have, in all four languages. (#780)
- **Analysis correctness batch**: terminal job writes are fenced,
  renamed outputs surface correctly, the output size check measures the
  real output, the stack selection is honored, and a drawn clip mask
  survives a basemap style reload. (#802, #803, #807)
- **CI closes several audit gaps**: an aggregator check that fails when
  a required job fails instead of skipping, path filters that actually
  cover the files jobs read (including the root `package.json`, so a
  Playwright bump runs the suites again), and workflow hardening.

### Removed

- **The Demo Mode banner, in favor of the Site Banner.** The `demo_mode`
  setting showed one fixed "demo account" notice that the
  admin-configurable Site Banner (Settings → General) already covers,
  with custom text, a color choice, and per-session dismissal. A set
  `DEMO_MODE` environment variable is now ignored — deployments that
  relied on it should enable the Site Banner instead, which is now also
  configurable by environment (`BANNER_ENABLED`, `BANNER_TEXT`,
  `BANNER_COLOR`) so env-only deployments keep a banner path. The
  `/api/auth/config` response no longer includes the `demo_mode` field.

### Dependencies

- Routine runtime updates: anthropic, sqlglot, boto3, cachetools,
  prometheus-fastapi-instrumentator, and sse-starlette on the backend;
  the React and TanStack ecosystems, lucide-react, and Tailwind tooling
  on the frontend.

## [1.5.1] - 2026-07-27

### Security

- **Creating a dataset from an analysis now requires the `export`
  capability in addition to `upload`** — advisory `GHSA-8gvc-94m7-m462`
  (moderate): analysis materialize bypassed the export capability, enabling
  durable dataset copies that survive grant revocation. The download
  endpoints already enforced `export`; a materialized result is a
  caller-owned copy of the source's attributes, so the two paths now agree.
  Installations on the default role matrix are unaffected (editor and admin
  hold both capabilities); deployments that withhold `export` from a role
  should upgrade. Details:
  <https://github.com/geolens-io/geolens/security/advisories/GHSA-8gvc-94m7-m462>

### Fixed

- **Keyboard reorder works again on every stack row.** The shared drag grip
  set a key handler after spreading the dnd-kit listeners, which silently
  destroyed the keyboard drag activator on all rows — folder groups and the
  basemap group, which have no fallback, were pointer-only. The handlers are
  now composed, the row-level reorder mode exposes its armed state via
  `aria-pressed`, and arming, each successful move, and finishing are
  announced to screen readers like the pointer drag path already was. (#759)
- **A stale tracked analysis job no longer logs anonymous visitors out.** The
  job-status poll is now gated on having an auth token, so a persisted job id
  can't make a public page fire an authenticated request whose 401 ended the
  session. (#762)
- **Edits made while a save is in flight are no longer silently discarded.**
  Changing a layer, name, basemap, plugin, or any other map property during
  the save's network round-trip used to be absorbed into the saved baseline,
  overwritten on screen by the post-save refresh, and dropped from the
  unsaved-changes guard. The map now stays marked unsaved until those edits
  are actually saved. (#756)
- **The analysis completion notice no longer covers the panel's own "Add to
  map" button.** In the builder it now appears top-center, clear of the right
  rail; elsewhere it keeps the usual corner. (#725)
- **The viewer legend no longer runs down behind the Map data button and the
  basemap toggle.** Its height is capped against the map container instead of
  the browser window, so a tall legend scrolls internally above the
  bottom-left controls (embed pages included). (#731)
- **Four analysis errors now explain themselves.** "An analysis job is
  already running" no longer renders as generic rate-limit advice, and the
  vector-dataset, polygon-mask, and unknown-dissolve-column refusals surface
  their actual reason (translated) instead of "the submitted values are
  invalid". (#774)
- **Viewers are no longer offered Dissolve.** It is materialize-only and the
  creation controls are hidden without the upload permission, so picking it
  was a dead end whose hint named an invisible button. The clip mask picker
  also says "No polygon layers on this map" instead of showing a lone "None"
  entry. (#779)
- **Analysis outputs now keep every attribute column.** Columns whose names
  are not identifier-shaped (`Área`, `2020_pop`, `my field`) were silently
  dropped from buffer, centroid, and clip outputs; they are now carried
  through intact. (#763)
- **Dissolving by a non-groupable column is refused up front.** A `json`
  column (how nested GeoJSON attributes ingest) used to enqueue, wait out
  the queue, and fail with a generic database error; the request is now
  rejected immediately with the column named, and schema-shaped failures
  that do reach the worker report "a column can't be used for this
  operation" instead of "database error". (#766)

### Changed

- **The Analysis panel no longer loses its form to a panel switch.** Clicking
  Notes, History, or Ask AI (or crossing the mobile breakpoint) used to
  silently discard every field — including a hand-drawn clip mask and a typed
  dataset name. The form is now remembered per map for the session. (#757)
- **A stale analysis preview no longer outlives its inputs.** Changing the
  layer, operation, distance, unit, group-by field, or clip mask now clears
  the preview overlay and its result badge, and a preview response that
  arrives after its inputs changed is discarded instead of drawn and zoomed
  to. (#758)
- **A running analysis job stays visible after the panel closes.** Reopening
  the panel (or reloading) now restores the job's status line, explains a
  disabled Create button when another analysis is still running, and the
  mobile rail button shows the same running-job spinner the desktop rail has.
  (#760)
- **The post-run state resets when the inputs change.** After a successful
  run, switching the layer or operation cleared neither "Dataset created" nor
  the name field, so one more click created an identically-named dataset from
  different parameters. The run state and name now reset on any input change,
  and "Add to map" names the dataset it adds. (#764)

## [1.5.0] - 2026-07-26

### Added

- **Spatial analysis in the map builder: buffer, centroid, clip, and dissolve.**
  A new Analysis panel runs an operation against any vector layer. Buffer,
  centroid, and clip draw the result on the map as a preview, capped at 500
  features so it stays interactive; dissolve is materialize-only. **Create
  dataset** re-runs the same operation over every feature as a background job
  and registers the output as a new dataset, which then behaves like any other
  layer — styleable, exportable, and served through the OGC API endpoints.
  Buffer distances accept metres, kilometres, feet, or miles. Dissolve
  optionally groups by an attribute column.
- **Clip against another layer, not just a drawn area.** `mask_dataset_id` on
  the analysis endpoints clips a layer using the union of a polygon layer's
  geometries. The picker offers only polygonal layers; both the source and the
  mask dataset are access-checked independently.
- **Ask the assistant to run an analysis.** The chat assistant gained a
  `run_analysis` tool for buffer and centroid previews, so "buffer the fire
  hydrants by 100 m" produces a preview on the map. The tool returns only a
  summary to the model — counts and a bounding box, never geometry.
- **The OGC items page-size ceiling is administrator-configurable.** Admin →
  Settings → Network exposes **OGC Features Max Page Size**, the ceiling an
  over-maximum `limit` is clamped to on the per-dataset items route.
- **Analysis has blast-radius limits, and they explain themselves.** Dissolve
  (250,000 features), buffer (500,000), and clip-against-a-layer masks (1,000)
  are refused up front rather than accepted and left to exhaust the database.
  The refusal names the limit so it can be filtered down to.

### Changed

- **BREAKING (self-hosted): bundled database upgraded to PostgreSQL 18 +
  PostGIS 3.6** (from PostgreSQL 17 + PostGIS 3.5; GEOS 3.9 → 3.13, PROJ 7.2 →
  9.6, pgvector stays on 0.8.x). An existing PG 17 `pgdata` volume cannot be
  opened by PG 18 — the standard `scripts/upgrade.sh` flow does **not** apply
  to this release. Follow the dump → fresh volume → restore procedure in
  [RUNBOOK.md § 6](RUNBOOK.md#6-major-postgresql-version-upgrade-17--18).
  Managed/external-Postgres deployments: run your provider's PG 17 → 18
  upgrade, then deploy as usual (minimum supported external version remains
  PostgreSQL 13). Motivation: the upstream `postgis/postgis:17-3.5` image line
  is frozen on Debian bullseye (LTS ends 2026-08-31) at PostgreSQL 17.5, and
  GEOS 3.13 speeds up the analysis hot paths (dissolve/buffer/repair)
  1.5–2.3× in like-for-like benchmarks. The backup image's `pg_dump` moves to
  18 in lockstep (a v17 `pg_dump` cannot dump a PG 18 server).

- **Every backup verifies itself, and the RUNBOOK states the RPO.** Each cycle
  now reads its dump back end-to-end and discards it if unreadable, so a
  corrupt backup surfaces the night it happens rather than during a recovery.
  RUNBOOK § 1 states the default recovery point objective (up to 24 hours)
  outright instead of leaving it to be inferred from the cron schedule, and § 3
  is explicit that point-in-time recovery is a different mechanism rather than
  a finer setting — logical dumps cannot participate in WAL replay — including
  the failure mode a hand-rolled `archive_command` introduces.
- **`scripts/upgrade.sh` refuses to cross a PostgreSQL major version.** It now
  compares the running server's major against the one the target release
  bundles and stops **before** anything changes — no image pull, no version
  pin, no database write — printing the RUNBOOK § 6 procedure instead. This
  closes the gap where the one-command upgrade would otherwise leave an
  install silently on the old major, or crash-loop `db` against an
  incompatible data directory the moment that image was rebuilt.
  Deployments using an external database (`DATABASE_URL_OVERRIDE`) are
  unaffected — the check is skipped, since the bundled image's version says
  nothing about the database those installs actually use.

- **Analysis buffers accept feet, miles, and kilometres.** The buffer distance
  gains a unit picker instead of being metres-only; the conversion happens in
  the browser, so the API contract is unchanged.
- **A queued analysis job says so.** Analysis jobs are stamped `queued` when
  they are created, so a job waiting for a worker reads as queued instead of
  looking indistinguishable from a broken one. This matters more now that
  analysis is deliberately dispatched below uploads.
- **Clip-to-layer offers only polygon layers.** The mask picker filters to
  polygonal layers instead of letting the request fail server-side.
- **A capped preview points at Create dataset.** The truncation notice names
  the way to run the operation over every feature.
- **A wildcard CORS origin is now rejected at save time.** Responses carry
  `Access-Control-Allow-Credentials: true`, so the spec forbids `*` as the
  allow-origin value and the middleware treats a list containing `*` as "deny
  everything" — including any explicit origins listed alongside it. Saving `*`
  used to be accepted and then took the API down about 30 seconds later, once
  the middleware's cache refreshed. It now fails immediately with a 422 naming
  the correct form. **Upgrade note:** if `*` is already stored, cross-origin
  requests are *already* being denied — the new validator guards the write
  path, not the middleware, which has always turned an allowlist containing
  `*` into an empty set. Replace it with explicit origins to restore
  cross-origin access; Admin → Settings → Network will refuse to save the page
  until you do.
- **TiTiler's glibc malloc arenas are capped.** `MALLOC_ARENA_MAX` defaults to
  `2` for the `titiler` service, which slows resident-memory growth under
  sustained tile load. Override with `TITILER_MALLOC_ARENA_MAX`. This bounds
  arena-driven growth; it is not a fix for raster memory use in general.

### Fixed

- **Backup integrity checks now catch a truncated dump.** Both the pre-restore
  gate in `scripts/restore.sh` and the new per-cycle check validate the archive
  with `pg_restore -f /dev/null` instead of `--list`. A `-Fc` archive keeps its
  table of contents at the front, so `--list` accepts a dump truncated anywhere
  after it — the exact shape a disk filling mid-dump produces. This mattered
  most on restore, where the old check reported "validation passed" and then
  ran `--clean --if-exists`, dropping the live database before failing partway
  through repopulating it.
- **OGC: an over-maximum `limit` is clamped on the records collection.**
  `/collections/datasets/items` returned 400 for a `limit` above the page-size
  ceiling; OGC API Features Core `/req/core/fc-limit-response-1(C)` requires
  the server to use its maximum instead of erroring. It now clamps to 200 and
  echoes the applied value in the `self` link, matching the per-dataset items
  route and STAC item-search. `/search/datasets/`, which shares the same
  parameters and answered 422 for the same input, clamps identically — so
  clients no longer need per-route error handling.
- **Retrying a failed analysis job gives analysis advice.** Failed analysis
  jobs said "The source is no longer available. Start the import again" — copy
  written for imports, on a job that never was one.
- **Two analysis errors were untranslated.** A missing-layer error surfaced in
  English regardless of locale, and the panel's failure line concatenated the
  raw server message onto a translated prefix instead of using the existing
  template. The new dataset name field also enforces the server's length limit
  as you type rather than after submitting.
- **Drawing a clip area names its keyboard alternative.** The draw tool is
  pointer-only; the panel now points to clip-by-layer instead of leaving that
  to be discovered.
- **Drawing a clip area no longer opens a popup at every vertex.** Each click
  placed its vertex and then fell through to the map's own click handler, so
  drawing a mask over a layer with popups enabled left one popup behind per
  corner, the last of them sitting on top of the result. A draw mode now owns
  the pointer for as long as it runs, and any popup already open is dismissed
  when drawing starts.

## [1.4.13] - 2026-07-24

STAC conformance hardening: the STAC API now passes stac-api-validator for
the core, collections, and item-search conformance classes, and a CI gate
keeps it that way. Fresh installs with incomplete configuration now fail
loudly at boot instead of seeding a broken admin account.

### Added

- **STAC API conformance is verified in CI.** Every merge to main and a
  nightly run boot the full stack, seed a fixture catalog, and run
  stac-api-validator (v1.0.0 core, collections, and item-search classes)
  against it, so STAC regressions are caught before they ship.
- **Published images link back to the repository.** All published Docker
  images now carry the `org.opencontainers.image.source` label, so GHCR
  package pages link to the GeoLens repository.

### Changed

- **STAC collection licenses reflect their members.** A collection's
  `license` field aggregates from its member records (`various` when they
  mix) instead of hardcoding `proprietary`.
- **Empty STAC collections are hidden.** Collections with no visible STAC
  items no longer appear in the catalog with a fabricated global extent;
  they are omitted from listings and return 404 until they gain an item
  the requester can see.

### Fixed

- **STAC item-search conformance.** A `limit` above the maximum now clamps
  to 200 instead of returning an error; `bbox` and `intersects` together
  are rejected; inverted bounding boxes are rejected; open-ended datetime
  intervals and lowercase RFC 3339 forms are accepted while malformed
  datetimes are rejected; optional link fields are omitted instead of
  serialized as `null`; and the service description is served with its
  OpenAPI media type.
- **Empty admin credentials fail at boot.** The API refuses to start when
  `GEOLENS_ADMIN_USERNAME` or `GEOLENS_ADMIN_PASSWORD` is empty, instead of
  silently seeding an unusable admin account on a verbatim-template
  install. The error says exactly which variable to set.

## [1.4.12] - 2026-07-23

Launch-week hardening: cross-origin map embedding works again on every
production deployment, multi-tab sessions stop signing themselves out, and
the API gains memory observability plus a worker-recycling backstop.

### Added

- **Right-click context menus in the map builder.** Layers, groups, and
  basemaps in the layer stack expose their actions in a context menu with a
  unified grouping model; actions that don't apply are shown disabled with
  the reason instead of silently hidden.
- **"Test Connection" for AI providers.** Admin → Settings → AI can probe
  the configured inference and embeddings endpoints live on demand, with
  per-purpose results — a bad key or endpoint is visible to the operator
  before a user hits it.
- **API worker memory is observable and self-limiting.** Each API worker
  exports an RSS gauge (`geolens_worker_rss_bytes`), logs an hourly memory
  heartbeat, and warns at 60% of the container memory limit. Workers also
  recycle gracefully after `UVICORN_MAX_REQUESTS` requests (production
  compose default 10000; empty disables), so slow memory growth can no
  longer ride a single worker into the container OOM killer.
- **The audit log names things.** The admin audit-log viewer resolves
  resource IDs to current names instead of showing raw UUIDs.
- **Vite dev server behind a tunnel.** `FRONTEND_ALLOWED_HOSTS` allowlists
  tunnelled hostnames for the dev server. (thanks @giswqs for their first
  contribution, #619)

### Changed

- **The reference Prometheus alerts split interactive vs tile latency.**
  The bundled alert rules alert separately on interactive-request p95 and
  sustained tile latency, instead of one blended rule that reliably caught
  neither.
- **Updated dependencies.** anthropic 0.119, openai 2.48, boto3 1.43.55,
  tailwindcss 4.3.3, and refreshed nginx and postgres base images.

### Fixed

- **Cross-origin map embedding works again.** The `/m/` embed shell was
  served through the SPA fallback, which re-entered the root location and
  replaced each embed token's `frame-ancestors` policy with `SAMEORIGIN` —
  blocking token-scoped iframe embeds on every production deployment. The
  shell is now served in place, so the per-token frame policy reaches the
  browser.
- **Multi-tab sessions no longer sign themselves out.** Concurrent
  refresh-token rotation from two tabs invalidated one tab's session; a
  short rotation grace window (`REFRESH_ROTATION_GRACE_SECONDS`, default
  30) ends the strand. An expired session now also presents one global
  signed-out surface and re-mints tile auth once, instead of each map
  component failing separately.
- **SSO users are recorded as verified.** OAuth just-in-time provisioning
  dropped the identity provider's `email_verified` assertion, so every SSO
  user showed as unverified. New sign-ins persist the assertion, returning
  verified logins heal existing rows, and a migration backfills
  GitHub-linked accounts, whose provisioning path guarantees a verified
  email.
- **Ingest handles Socrata exports and 3D GeoParquet.** Colon-prefixed
  columns (`:id`, `:created_at`) in Socrata exports no longer collide with
  SQL bind parameters, and GeoParquet files with Z geometries load instead
  of failing against a 2D staging table. Dimension and Z metadata now also
  appear on the dataset detail page.
- **The map AI recovers from schema-invalid responses.** A model response
  that parses as JSON but fails schema validation now gets a repair round
  (with those tokens counted against the daily AI budget) instead of
  surfacing a raw validation error to the user.
- **Anonymous dataset pages stop spamming 401s.** The dataset detail page
  requested owner-only VRT status for every viewer, guaranteeing 401 noise
  on public raster datasets; the request is now gated to signed-in users.
  Stale cached app shells also self-heal with a one-shot reload when a
  hashed asset 404s after a deploy.
- **Job rows whose worker died mid-run are failed, not stuck.** A worker
  killed mid-job previously left its queue row running forever; those rows
  are now failed so the job can be retried.
- **Short search queries answer instantly.** Typeahead-length queries skip
  the semantic-embedding call entirely — no embedding-provider round-trip
  per keystroke.
- **OGC and STAC clients get a proper 401 on stale credentials.** Expired
  or revoked credentials on standards read paths now surface as 401 so
  clients re-authenticate, instead of being masked by a generic error.
- **Monitoring gauges zero out when a job queue drains.** Queue-depth
  gauges no longer hold their last value after the queue empties, ending a
  class of stale alerts.
- **The two dead API-docs links point somewhere real.** The frontend
  footer's API link targets the hosted API guide, and the OGC landing page
  omits its interactive-docs link in production, where those docs are
  disabled.

### Upgrade notes

- Database migration 0028 runs automatically on upgrade and backfills
  `email_verified` for GitHub-linked OAuth accounts.
- API workers now recycle after 10,000 requests by default in the
  production compose (`UVICORN_MAX_REQUESTS`). Recycling is graceful —
  in-flight requests complete — and setting the variable empty disables
  it. No operator action is required.

## [1.4.11] - 2026-07-19

### Fixed

- **Raster resolutions in geographic coordinate systems are reported honestly.**
  Resolution is stored in the dataset's own CRS units, but the catalog and
  search cards formatted every value as meters — so a 60-arc-second global DEM
  advertised a "2 cm" ground sample distance. Geographic datasets now render
  arc units alongside an approximate ground distance, e.g. `60″ (≈1.9 km)`, and
  sub-arcsecond imagery keeps meaningful precision instead of rounding to `0″`.
- **`geolens publish --tags` and `--collection` now apply.** Both flags were
  accepted and silently ignored. They are applied after the dataset commits,
  so a failure to tag or file the dataset reports which step failed and leaves
  the uploaded dataset in place rather than aborting before its URL is printed.
  The printed dataset URL also points at the web page instead of the JSON API.
- **The installer no longer probes ports it will not bind.** When `DB_PORT`,
  `API_PORT`, or `FRONTEND_PORT` was missing from `.env`, the installer
  defaulted only its own shell variables — so it health-checked and printed
  ports that differed from the ones Compose actually bound. The documented
  values are now persisted to `.env`, keeping the installer, Compose, and the
  printed URLs in agreement.

## [1.4.10] - 2026-07-19

### Added

- **Three deployment knobs for running GeoLens outside Docker Compose.** Each
  is a plain container environment variable with a byte-preserving default,
  so existing Compose deployments are unchanged:
  - GDAL now honors custom S3 endpoints. Reads against MinIO, R2, or any
    other non-AWS S3 backend derive `AWS_S3_ENDPOINT`, `AWS_HTTPS`, and
    `AWS_VIRTUAL_HOSTING` from the existing `S3_*` settings at api and worker
    start, and GDAL subprocesses inherit them. Explicit operator `AWS_*`
    environment — and ambient-credential setups — always wins.
  - `CLIENT_MAX_BODY_SIZE` replaces the frontend image's hardwired `500m`
    upload ceiling. Invalid values fail fast at boot with a clear error
    instead of crash-looping on an nginx config error.
  - `TRUSTED_PROXY_CIDRS` recovers the real client address from
    `X-Forwarded-For` behind a trusted load balancer, restoring accurate
    access logs and anonymous raster rate limiting. Left unset, the rendered
    configuration is equivalent to the previous overwrite behavior. Entries
    are charset-validated, so environment values cannot inject nginx
    directives.

### Fixed

- Dataset detail tabs are clickable again while the Ask AI panel is open. The
  fixed panel covered the Access tab at 1440px, and Structure as well at
  narrower widths; the page now reflows beside the panel.
- Popup custom fields appear as soon as they are configured. Editing a layer's
  popup fields rebuilt the tile request correctly, but maplibre-gl 5.x
  silently dropped the reload while the tile source was paused, so the map
  kept serving the pre-edit column set until a full page reload.
- Popup fields that are configured but null on the clicked feature render as
  `--` instead of vanishing, and the popup's empty state now reads "Zoom in to
  view attributes" when the dataset has columns that low zoom levels strip.

## [1.4.9] - 2026-07-18

### Changed

- **The frontend image can now front the API outside Docker Compose.** Its
  bundled nginx renders its proxy configuration at container start, taking
  the API upstream (`API_UPSTREAM`) and DNS resolver (`NGINX_RESOLVER`) from
  the environment instead of hardwiring Docker-only values. Compose
  deployments are unchanged (the defaults are identical); Kubernetes
  deployments set `API_UPSTREAM` to the api Service's fully qualified name —
  which the community Helm chart
  ([geolens-deployments](https://github.com/geolens-io/geolens-deployments)
  0.3.x) now does. Trailing slashes on `API_UPSTREAM` are stripped, and bare
  IPv6 resolvers are bracketed.
- The install script's ready banner now points at where the admin password
  was configured, and README/SECURITY polish landed alongside it (badge
  links, MCP server in the security-policy scope, an `/api/health` note).

### Fixed

- The public OpenAPI document no longer carries internal operation labels or
  compliance-implying wording.
- Post-1.4.8 audit follow-ups: geometry-only GeoParquet uploads fail with a
  clear ingestion error instead of publishing an empty dataset; primary-key
  rename migrations quote constraint identifiers; the admin sidebar clears
  the navbar on notched devices; the dataset Ask-AI button is no longer
  covered by the pending-edits bar; the public viewer's error page no longer
  overflows when the site banner is shown; Spanish AI-chat wording is
  consistent with the rest of the locale.

## [1.4.8] - 2026-07-18

### Added

- **Ask questions about a dataset in natural language, from its page.** The
  dataset page gains an AI chat panel that answers questions about that
  dataset — counts, statistics, attribute filters, and spatial analysis — and
  can hand a result straight into the map builder to visualize. It uses the
  same read-only, sandboxed NL→SQL path as the builder assistant and is
  scoped to the single dataset in view. Requires a configured AI provider.
- **GeoParquet files can be uploaded and ingested.** `.parquet` joins the
  accepted upload formats, so a GeoParquet dataset is added the same way as
  a GeoPackage, Shapefile, or GeoJSON. (Complements GeoParquet *export*,
  added in 1.4.6.)
- **Coding agents can work with a GeoLens instance through a Model Context
  Protocol (MCP) server.** The new `geolens-mcp` package exposes read-only
  tools — catalog search, dataset schema inspection, feature reads, and
  saved-map metadata — so assistants such as Claude Code, Cursor, and Codex
  can discover and read a catalog from inside a dev session. It authenticates
  with an existing API key (or runs anonymously against public data) and is
  scoped to exactly what that credential can see.
- **Site-wide announcement banner.** Administrators can show a banner across
  the app — enable/disable, message text, and color (info, warning, success,
  destructive) live in Admin → General settings. Disabled by default, and
  empty text means no banner, so existing deployments see no change.

### Changed

- **Accessibility and design-system pass.** A design audit closed contrast,
  color-token, and instrument-system findings across the frontend, including
  a dark-mode warning-text contrast fix.

### Fixed

- **Tile caches roll over after content edits, not only re-uploads.** A
  dedicated per-dataset cache-buster now advances on single-feature edits,
  column DDL, and tile-column changes, so CDN and browser caches stop
  serving stale tiles until max-age expiry.
- **Map builder correctness and polish.** Three builder-audit passes closed
  styling, filtering, viewer, and interaction findings, and adding a dataset
  to a brand-new map no longer leaves it looking unsaved before any edit.
- **Feature and schema editing hardening.** An editing audit tightened
  write-path validation and edit-flag enforcement across single-feature
  edits, column DDL, and record metadata updates.
- **The top navbar and admin sidebar stay pinned** while content scrolls,
  instead of scrolling away or overlapping one another.
- **Dataset quicklook thumbnails no longer crash their consumers on a
  cached 404 response.**
- **The OpenAPI document no longer contains unresolvable schema references.**
  GeoJSON response schemas on the feature and collection-items endpoints
  embedded `#/$defs/...` pointers that dangled at document scope, so strict
  OpenAPI consumers (documentation generators, reference bundlers) rejected
  the whole contract. Those schemas are now fully inlined, and a contract
  test guards every `$ref` in the exported document.

### Upgrade notes

- **PostgreSQL `max_connections` is raised to 80** in the bundled
  `db/postgresql.conf` to cover the API-side job-queue connector. Recreate
  or restart the `db` container after pulling so the new value takes
  effect.

## [1.4.7] - 2026-07-15

This release hardens the platform after a full portfolio audit — access
control, the extension boundary, containers, migrations, and the admin
control plane — and completes the internationalization pass across all four
locales.

### Added

- **Community administrators can download up to 100,000 audit events as CSV
  or JSON.** Share links can expire after 1, 7, 30, or 90 days, and
  non-expiring links remain available.

### Changed

- **Optional distributions now connect to GeoLens through typed extension
  interfaces.** Community images contain only the Apache-2.0 application, and
  the default single-tenant configuration does not load an extension.
- **An installed version covered by a valid commercial license keeps working
  after its maintenance date.** The date controls access to updates and
  support; it does not shut down the installation.
- **The AI assistant defaults to Anthropic's Claude Sonnet 5 model.**
  Deployments that set `LLM_MODEL` explicitly keep their configured model.
- **Updated dependencies across the backend and frontend**, including
  security releases of Pillow (12.3.0) and click (8.4.2).

### Fixed

- **Role-based grants on restricted records now take effect.** The visibility
  filter compared record identifiers against dataset identifiers, so a role
  grant could never surface a restricted record. The gap failed closed
  (nothing was over-exposed); granted users simply did not see the records
  they were entitled to.
- **Restored OGC API Features/Records, STAC, and DCAT conformance.**
  Conformance regressions found by the standards audit are fixed, and the
  suites gate CI again.
- **The published OpenAPI document matches runtime behavior again**, so
  generated SDKs and API clients reflect the deployed contract.
- **Accessibility and design-system fixes across the frontend**, from the
  frontend audit: keyboard navigation, contrast, and component-consistency
  issues.
- **Spanish, French, and German localizations are complete.** The
  internationalization audit closed the remaining untranslated and
  inconsistent strings in all four locales.
- **Workers with a commercial extension installed no longer refuse to
  boot.** The worker's startup assertion demanded extensions from a different
  distribution tier; each tier is now checked only for the extensions it
  actually provides.
- **Ingestion lifecycle hardening.** Stalled ingests are reaped reliably and
  ingest work is isolated per tenant context.

### Security

- **Admin control-plane governance and lifecycle hardened** following the
  admin audit, including tighter authorization on administrative operations.
- **Container images remediated against a Docker audit**, reducing the
  runtime attack surface of the published images.
- **Environment contracts aligned and validated**, so misconfigured
  deployments fail loudly at boot instead of running with silently ignored
  settings.
- **Migration rollback and online schema changes hardened**, with
  lock-sensitive steps bounded so they cannot stall a busy production
  database indefinitely.

### Upgrade notes

- **Database SSL modes now fail closed.** Undocumented `allow` and `verify-ca`
  values no longer boot; use `prefer` or `verify-full` before upgrading.
- **Back up before applying migrations `0018` through `0024`.** The standard
  `scripts/upgrade.sh` flow takes this backup automatically. The migrations add
  tenant identifiers, database roles, row security policies, and tenant data
  schema support. Default single-tenant deployments keep their current behavior
  and do not need an extension or commercial license.
- **Run these migrations with a database role that can create roles.** Managed
  PostgreSQL users may need a separate migration credential with `CREATEROLE`.
  Keep the API and worker on their existing least-privilege runtime credential.
  On a busy database, lock-sensitive steps stop after five seconds instead of
  waiting behind application traffic. Retry the migration during a quieter
  window if that happens.

## [1.4.6] - 2026-07-12

### Added

- **GeoParquet export.** Any spatial dataset can now be exported as GeoParquet
  (`GET /datasets/{id}/export?format=parquet`), and every spatial dataset now
  advertises a GeoParquet download in its DCAT distributions — including a
  backfill so existing datasets gain the distribution automatically.
- **AI-generated metadata on ingest.** Newly ingested datasets can have a
  summary and metadata drafted for them automatically, giving the catalog a
  head start on description quality.
- **`llms.txt`.** A machine-readable `llms.txt` now describes the API surface
  for LLM-based agents and crawlers.
- **Reference monitoring stack.** Ships a reference Prometheus + Grafana
  configuration so self-hosters can stand up metrics and dashboards without
  assembling them from scratch.

### Changed

- **The DCAT catalog is paginated.** Large catalogs no longer serialize every
  dataset into a single response.
- Clarified the distinction between `FRONTEND_TILE_BASE_URL` and
  `CDN_BASE_URL` for tile routing in the Compose documentation.

### Fixed

- **Feature and schema editing hardening.** A round of editing-correctness
  fixes: stricter validation on write paths, correct enforcement of
  per-dataset edit flags, and a clearer draft-editing experience.
- **The style editor no longer clobbers saved categorical symbology.** Opening
  the builder's style editor on a layer with categorical colors preserves the
  saved per-category styling.
- **The installer fails fast on terminal service states** instead of
  soft-passing a crashed or exited service as "still starting."

### Dependencies

- Bumped procrastinate (3.9.0), the SQLAlchemy ecosystem, the TanStack Query
  packages, pytest, `github/codeql-action`, and `docker/login-action`.

## [1.4.5] - 2026-07-11

### Security

- **AI-generated SQL runs under a stricter sandbox.** An explicit
  PostGIS/function allow-policy, rejection of recursive CTEs (at any nesting
  depth), set-generating and collection-amplifying functions, anchoring to
  data tables, a 10-second statement timeout, and a per-user execution lock.
- **Environment AI credentials and OAuth secrets bind to their configured
  destinations.** Operator-supplied keys can no longer be redirected to
  attacker-chosen endpoints via settings or config import; changing a
  provider origin or mode requires rotating the secret atomically, and
  provider fetches use SSRF-safe IP-pinned transports.
- **Feature writes and archive ingestion validate before parsing.** GeoJSON
  writes get a 1 MiB pre-parse cap plus depth/cardinality/coordinate
  validation, and ZIP/XLSX containers are preflighted before extraction.

### Changed

- **Hillshade shading and 3D terrain are now independent controls on a DEM
  layer.** The old either/or "render as" choice is gone: a DEM can paint
  hillshade (with an optional hypsometric elevation tint) and drive the 3D
  terrain mesh at the same time, from one layer. Terrain binds at the map
  level, so duplicating a DEM rendering can no longer accumulate extra
  terrain. Every DEM rendering is reachable in the layer stack, and a DEM
  that draws nothing says so with a "Not shown" badge.
- **Layer icons match everywhere.** The layer stack, the builder legend, and
  the shared-map legend now render the same type icon for every layer,
  including the DEM glyphs (hillshade, terrain, image).

### Fixed

- **Saving an unrelated layer change no longer erases DEM styling.** A
  partial layer update (for example toggling visibility) used to clear the
  layer's saved style metadata — hypsometric tint settings and render mode
  could vanish on the next save. Partial updates now leave untouched fields
  alone.
- **Hiding a DEM layer in the shared-map viewer hides all of it.** The
  legend's eye toggle used to leave the elevation tint painting, the 3D
  terrain mesh extruded, and a phantom legend entry behind; all three now
  follow the toggle, and re-showing the layer restores them.
- **3D terrain no longer intermittently fails to appear on load.** A terrain
  re-apply scheduled around a basemap style change could land mid-transition
  and be dropped silently, leaving a terrain-enabled map flat until an
  unrelated change; the re-apply now retries until the style settles.
- **Terrain status, legend entries, and the 3D mesh stay in lockstep** when
  the bound DEM layer is hidden, on both the builder and the shared-map
  viewer.
- **Maps with an inconsistent saved terrain configuration open normally**
  (terrain simply stays off) instead of failing to load.
- **The hypsometric elevation tint no longer paints areas outside the DEM's
  coverage.** Pixels beyond the data footprint used to render as a solid
  ramp-low band with a hard edge along the coverage boundary; they are now
  transparent.
- **Performance-profile follow-ups from the 2026-07-10 audit** landed:
  faster catalog search paging and reduced tile-request overhead on
  layer-heavy maps.

## [1.4.4] - 2026-07-10

### Changed

- **The "Powered by GeoLens" footer badge now links to getgeolens.com.**
- **Accessibility improvements across the interface.** Upload and export
  progress indicators announce themselves to screen readers, sortable table
  headers report their sort state, form-input borders meet the 3:1 contrast
  minimum, the destructive red is darkened in light mode so error badges and
  text meet the 4.5:1 minimum on tinted surfaces, and animations respect the
  reduced-motion preference.
- **Deleting a user now asks the administrator to type the username to
  confirm.**
- **Locale completeness checks now compare translated values and variables**,
  not just key presence, across all four languages.

### Fixed

- **Admin "Export emails (CSV)" downloads again.** The export opened a
  browser tab without credentials and showed an authentication error instead
  of the file; it now downloads through the authenticated path like the
  audit-log export.
- **Failed requests are easier to recover from.** Error panels gained a retry
  action, API requests time out instead of hanging indefinitely, and an
  in-flight upload can be aborted and retried.
- **Builder polish from the frontend audit.** Map label offsets apply
  correctly, raster styling inputs clamp when leaving the field instead of
  while typing, and a missing tile token surfaces as an error instead of
  rendering an empty layer.
- **A frontend audit pass closed 85 findings in total** across design-system
  consistency, interface resilience, and code health.

## [1.4.3] - 2026-07-10

### Security

- **Layer column changes now require write access.** The four layer-column
  endpoints gated schema-changing operations on read visibility; they now
  require dataset write access like every other mutation.
- **VRT ingestion rejects remote and virtual sources.** A crafted VRT file
  could reference URL or `/vsi`-prefixed sources and make the ingest worker
  fetch them. Source validation now walks the full XML and rejects both.
- **Raster preview and tile fetches no longer follow HTTP redirects.** Both
  the GDAL source-preview path and the bundled Titiler run with
  `GDAL_HTTP_FOLLOWLOCATION=NO`, so a redirect can no longer route an
  already-validated fetch to an internal address.
- **Search facets cap the geometry filter size.** The facets endpoint accepted
  unbounded geometry input that could pin PostGIS on a single request; input
  is now capped at 10,000 characters.

### Added

- **Six curated showcase maps.** The showcase seed now builds six themed maps
  (terrain, Sentinel-2 imagery, plate tectonics, and more) on a rebuilt
  Restless Earth dataset, replacing the older single-map demo seed.
- **Per-user daily AI token budget.** `MAX_AI_TOKENS_PER_USER_PER_DAY` caps
  what any one user can spend on AI calls per day; 0 keeps it unlimited.
- **Edition badge in the admin overview.** Administrators can see at a glance
  which edition a deployment runs.
- **`/api/health` reports the running version and build.** The health payload
  carries `version` and `build` fields so operators can verify what a
  deployment runs over HTTP; release images stamp the exact build commit.

### Changed

- **Unified interface design.** The UI moved to a single design language
  across the catalog, builder, viewer, and admin pages, including contrast
  fixes for accessibility.
- **Translation completeness.** Remaining hardcoded interface strings now go
  through the translation layer, and all four locales (en, es, fr, de) ship
  the full key set.
- **The installer waits longer and no longer cries wolf.** The startup health
  wait rose from 90 to 300 seconds, and a timeout now prints "still starting"
  guidance instead of failing the install while the stack is converging,
  which is common on Apple Silicon where the database image runs emulated.
  The installer also warns when Docker has less than about 8 GB of memory
  available.
- **Titiler updated to 2.0.5.**
- **A custom share-link expiration is now rejected with a validation error on
  the Community edition.** Setting `expires_at` on `POST /maps/{id}/share/`
  without the advanced-sharing entitlement returns 422 instead of 400, so it
  matches how embed tokens already report the same restriction.
- **The dataset rows endpoint returns 503 when the database is unavailable
  instead of an empty page.** An operational database failure (connection loss
  or statement timeout) on `GET /datasets/{id}/rows/` now returns 503 rather
  than a 200 with an empty result set that looked like the dataset had no rows.
  A dataset that is genuinely empty, or has no backing table, still returns 200.

### Fixed

- **Saving a map right after adding a layer no longer clears that layer's
  styling.**
- **Mixed-geometry datasets render fully.** Layers whose table mixes geometry
  families (points, lines, polygons) now render each family instead of
  drawing only one.
- **Files dropped during upload setup are no longer lost.** Dropping files
  onto the import dialog while it was still fetching its configuration
  silently discarded them; they now queue and validate once the
  configuration settles.
- **Anonymous viewers can load `features.geojson` on public datasets.**
- **PNG map exports draw their legend swatches.**
- **AI-assisted builder labels are readable, and active filters show a
  summary pill.**
- **The dataset-count quota is enforced atomically at record creation**, so
  concurrent uploads can no longer slip past the cap.
- **AI chat handles numeric query results reliably.** Provider calls
  serialize decimal values safely and return plain-text output.
- **The frontend container no longer crash-loops when `PUBLIC_APP_URL` is
  set.** The social-preview image rewrite ran at boot in a way the
  unprivileged nginx image could not execute.
- **Two map-builder audit passes** fixed styling, filtering, viewer, and
  export defects across the builder.
- **Interrupted exports clean up after themselves.** A failed export removes
  its temporary directory, and the boot-time sweeper only removes export
  staging entries older than an hour instead of everything it finds.
- **`ENVIRONMENT=production` in `.env` now reaches the containers.** Neither
  compose file passed the variable through, so an operator who set it still
  got the open posture: interactive docs exposed and the OAuth session cookie
  sent without the Secure flag. Both compose files now forward it, and an
  empty value keeps the old `LOG_JSON` fallback behavior.

## [1.4.2] - 2026-07-01

### Changed

- **Public API reference no longer lists the SAML-to-local conversion or
  audit-log-export operations.** Both endpoints are excluded from the published
  OpenAPI schema and the generated docs API reference. They still work at
  runtime for administrators; only their listing in the public schema is
  removed. The Python and TypeScript SDKs are regenerated to match.
- **The OpenAPI description drops the compliance-status wording for the OGC
  endpoints.** The published API summary now says the API implements the OGC
  API building blocks; formal conformance is reported by the `/conformance`
  endpoint itself.

### Fixed

- **New collections appear in the catalog immediately.** The collection
  create endpoint now invalidates the catalog list cache like every other
  collection mutation, so a just-created collection no longer looks like it
  silently failed until the cache expired.
- **The dataset page's AI metadata assist is easier to spot.** The Generate
  summary, keyword assist, lineage, and quality-statement buttons no longer
  use the lowest-emphasis styling that made them read as decorative.

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

[Unreleased]: https://github.com/geolens-io/geolens/compare/v1.18.1...HEAD
[1.18.1]: https://github.com/geolens-io/geolens/compare/v1.18.0...v1.18.1
[1.18.0]: https://github.com/geolens-io/geolens/compare/v1.17.0...v1.18.0
[1.17.0]: https://github.com/geolens-io/geolens/compare/v1.16.1...v1.17.0
[1.16.1]: https://github.com/geolens-io/geolens/compare/v1.16.0...v1.16.1
[1.16.0]: https://github.com/geolens-io/geolens/compare/v1.15.1...v1.16.0
[1.15.1]: https://github.com/geolens-io/geolens/compare/v1.15.0...v1.15.1
[1.15.0]: https://github.com/geolens-io/geolens/compare/v1.14.2...v1.15.0
[1.14.2]: https://github.com/geolens-io/geolens/compare/v1.14.1...v1.14.2
[1.14.1]: https://github.com/geolens-io/geolens/compare/v1.14.0...v1.14.1
[1.14.0]: https://github.com/geolens-io/geolens/compare/v1.13.1...v1.14.0
[1.13.1]: https://github.com/geolens-io/geolens/compare/v1.13.0...v1.13.1
[1.13.0]: https://github.com/geolens-io/geolens/compare/v1.12.0...v1.13.0
[1.12.0]: https://github.com/geolens-io/geolens/compare/v1.11.1...v1.12.0
[1.11.1]: https://github.com/geolens-io/geolens/compare/v1.11.0...v1.11.1
[1.11.0]: https://github.com/geolens-io/geolens/compare/v1.10.0...v1.11.0
[1.10.0]: https://github.com/geolens-io/geolens/compare/v1.9.0...v1.10.0
[1.9.0]: https://github.com/geolens-io/geolens/compare/v1.8.0...v1.9.0
[1.8.0]: https://github.com/geolens-io/geolens/compare/v1.7.1...v1.8.0
[1.7.1]: https://github.com/geolens-io/geolens/compare/v1.7.0...v1.7.1
[1.7.0]: https://github.com/geolens-io/geolens/compare/v1.6.1...v1.7.0
[1.6.1]: https://github.com/geolens-io/geolens/compare/v1.6.0...v1.6.1
[1.6.0]: https://github.com/geolens-io/geolens/compare/v1.5.1...v1.6.0
[1.5.1]: https://github.com/geolens-io/geolens/compare/v1.5.0...v1.5.1
[1.5.0]: https://github.com/geolens-io/geolens/compare/v1.4.13...v1.5.0
[1.4.13]: https://github.com/geolens-io/geolens/compare/v1.4.12...v1.4.13
[1.4.12]: https://github.com/geolens-io/geolens/compare/v1.4.11...v1.4.12
[1.4.11]: https://github.com/geolens-io/geolens/compare/v1.4.10...v1.4.11
[1.4.10]: https://github.com/geolens-io/geolens/compare/v1.4.9...v1.4.10
[1.4.9]: https://github.com/geolens-io/geolens/compare/v1.4.8...v1.4.9
[1.4.8]: https://github.com/geolens-io/geolens/compare/v1.4.7...v1.4.8
[1.4.7]: https://github.com/geolens-io/geolens/compare/v1.4.6...v1.4.7
[1.4.6]: https://github.com/geolens-io/geolens/compare/v1.4.5...v1.4.6
[1.4.5]: https://github.com/geolens-io/geolens/compare/v1.4.4...v1.4.5
[1.4.4]: https://github.com/geolens-io/geolens/compare/v1.4.3...v1.4.4
[1.4.3]: https://github.com/geolens-io/geolens/compare/v1.4.2...v1.4.3
[1.4.2]: https://github.com/geolens-io/geolens/compare/v1.4.1...v1.4.2
[1.4.1]: https://github.com/geolens-io/geolens/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/geolens-io/geolens/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/geolens-io/geolens/compare/v1.2.4...v1.3.0
[1.2.4]: https://github.com/geolens-io/geolens/compare/v1.2.3...v1.2.4
[1.2.3]: https://github.com/geolens-io/geolens/compare/v1.2.0...v1.2.3
[1.2.0]: https://github.com/geolens-io/geolens/releases/tag/v1.2.0
