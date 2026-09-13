# geolens (CLI)

Apache-2.0 command-line interface for the [GeoLens](https://github.com/geolens-io/geolens) API.

Login, scan local directories of spatial data, apply manifest-driven catalogs, publish vector or raster files, replace an uploaded dataset's data from a file, refresh remote service datasets, inspect source status, run PostGIS analysis operations, and export STAC metadata against any GeoLens instance.

See [docs.getgeolens.com](https://docs.getgeolens.com/) for the full command reference.

## Quickstart

```bash
pip install geolens-cli
geolens login https://geolens.example.com/api
geolens scan ./data
geolens init
geolens validate geolens.yaml
geolens schema --output geolens-manifest-v1.schema.json
geolens apply --dry-run geolens.yaml
geolens apply geolens.yaml
geolens publish ./data/cities.geojson
geolens replace <dataset-id> ./data/cities-updated.geojson --wait
geolens status <dataset-id>
geolens refresh <dataset-id> --wait
geolens analysis preview <dataset-id> --operation buffer --distance 500 > ring.geojson
geolens analysis materialize <dataset-id> --operation buffer --distance 500 --title "500 m ring"  # waits for the job; --timeout to bound it
geolens export stac <dataset-id> -o cities.stac.json
```

For a one-command quickstart, run `geolens publish examples/manifests/first-catalog/city-parks.geojson` against a running stack. See the full walkthrough at [docs.getgeolens.com](https://docs.getgeolens.com/).

The CLI consumes the [`geolens`](https://pypi.org/project/geolens/) Python SDK package. Manifest apply posts to the generated `POST /ingest/manifest/apply` contract through the SDK-owned client transport rather than a hand-rolled HTTP client.

## Apply, replace, and refresh

`geolens apply` reconciles declared catalog configuration. It re-imports a
manifest entry only when that entry's fingerprint changes; applying an
unchanged manifest returns `skip_complete` and does not re-fetch a remote
source whose data changed independently.

A vector source can carry an optional `checksum: sha256:<64 lowercase hex>`
field. It is declared, not verified: apply never fetches the source bytes to
check it, and folds it into the entry fingerprint like any other field. That
makes it the way to force a re-import under a stable URI, such as
`latest.gpkg` or a path an ETL job overwrites in place, where the entry
itself never changes but the file underneath it does. Bump `checksum` when
the file changes and the next apply reclassifies the entry as an update
instead of skipping it. This does not apply to `raster_cog` sources: manifest
raster updates are not supported, so do not set or change `checksum` on a
raster entry. A changed checksum there still reclassifies the entry the same
way, but the update then fails with an error result ("Manifest raster
updates are not supported; create a new raster dataset instead."), not a
skip. An unchanged raster entry, checksum included, still skips normally.
Replace raster data by creating a new raster dataset instead.

`geolens replace <dataset-id> <file>` replaces this dataset's data from a
local file, the CLI equivalent of the Re-upload dialog in the web app. It
prints the preview (layer, feature count, detected SRID) before committing
and asks for confirmation once; pass `--yes` to skip the prompt for scripted
use, and `--wait` to poll the job to a terminal state and fail loudly on a
bad import. A file with more than one layer needs `--layer`, since omitting
it would otherwise commit the first layer without telling you. A raster
dataset has no layer to preview, so `replace` uploads and commits it directly
and `--layer` is rejected. `replace` only accepts a local file. A dataset
whose data comes from a remote service origin, or a registered database
table, cannot be replaced this way; use `geolens refresh` for that instead.
`--json` never prompts, so it requires `--yes`.

`geolens refresh <dataset-id>` re-pulls data from the origin binding stored by
GeoLens. It does not accept a URL, layer, or client-selected trigger. Add
`--wait` to poll the durable refresh run; pass `--timeout` when automation needs
a finite bound. JSON output includes the verification result. Use `apply` when
the declared source configuration itself changes.

Service refresh compares the staged row count with the source count when the
provider supplies one. A mismatch fails without changing live data. A missing
source count, an empty replacement for a non-empty dataset, or a removed or
retyped column blocks publication for review. After checking the Source panel,
use `--accept-blocked-run <run-id>` to accept that source and staged content
once. The retry must match the reviewed attributes and geometries. A later or
different result blocks again. Matching counts still do not prove that a mutable
provider served every page from one snapshot.

Registered PostGIS refresh measures the registered live relation; it does not
copy or preserve that relation. Referenced STAC refresh updates the remote item
and asset pointer; it does not copy the asset bytes. A failed or blocked service
refresh retains the current managed table. After a successful replacement,
restoring earlier data requires a backup or re-import because refresh history
does not retain the previous table.

Protected services can receive bearer credentials with `--token`. Use bare
`--token` for a hidden prompt. Use `--auth-file` with a protected JSON file for
bearer, Basic, or named-header credentials. The server needs a reachable shared
credential store (`REDIS_URL`) to hand the single-use secret to the worker; the
configuration validation endpoint reports this separately from ordinary cache
health. GeoLens does not store the credential in the dataset binding.

`geolens status <dataset-id>` reports the catalog status together with source
origin, freshness, health, and the last successful refresh time. Use `--json`
before the command for a machine-readable status payload.

## Manifest schema distribution

The versioned manifest JSON Schema is intentionally distributed inside
`geolens-cli`, rather than as a separate package. A second artifact would add a
release/version-skew surface without a demonstrated independent consumer; the
CLI is already the canonical manifest authoring and validation tool. Editors and
non-Python tooling can obtain the exact installed schema with `geolens schema`
or `geolens schema -o schema.json`. Its stable `$id` identifies manifest v1.

This decision should be revisited if multiple consumers need schema releases on
a cadence independent from the CLI. Until then, schema changes and CLI versions
ship atomically and the wheel test locks resource inclusion.

## Environment variables

The CLI normally stores its active instance through `geolens login` and keeps
tokens in the OS keyring. Ephemeral CI jobs can avoid persistent state with:

| Variable | Purpose |
|---|---|
| `GEOLENS_INSTANCE` | GeoLens instance URL. The CLI normalizes the URL and appends `/api` when needed. An explicit `--instance` option takes precedence. |
| `GEOLENS_TOKEN` | Bearer token used instead of the keyring/credentials file. Treat it as a secret and inject it from the CI secret store. |

For load-test and seed-script variables, use the documented Tooling / Load
Tests section in the repository's `.env.example`.
