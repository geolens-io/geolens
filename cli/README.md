# geolens (CLI)

Apache-2.0 command-line interface for the [GeoLens](https://github.com/geolens-io/geolens) API.

Login, scan local directories of spatial data, apply manifest-driven catalogs, publish vector or raster files, refresh remote service datasets, inspect source status, run PostGIS analysis operations, and export STAC metadata against any GeoLens instance.

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
geolens status <dataset-id>
geolens refresh <dataset-id> --wait
geolens analysis preview <dataset-id> --operation buffer --distance 500 > ring.geojson
geolens analysis materialize <dataset-id> --operation buffer --distance 500 --title "500 m ring"  # waits for the job; --timeout to bound it
geolens export stac <dataset-id> -o cities.stac.json
```

For a one-command quickstart, run `geolens publish examples/manifests/first-catalog/city-parks.geojson` against a running stack. See the full walkthrough at [docs.getgeolens.com](https://docs.getgeolens.com/).

The CLI consumes the [`geolens`](https://pypi.org/project/geolens/) Python SDK package. Manifest apply posts to the generated `POST /ingest/manifest/apply` contract through the SDK-owned client transport rather than a hand-rolled HTTP client.

## Apply versus refresh

`geolens apply` reconciles declared catalog configuration. It re-imports a
manifest entry only when that entry's fingerprint changes; applying an
unchanged manifest returns `skip_complete` and does not re-fetch a remote
source whose data changed independently.

`geolens refresh <dataset-id>` is the explicit data-refresh path. It re-pulls
the dataset from the origin binding stored by GeoLens, without accepting a URL,
layer, or client-selected trigger. Add `--wait` to poll the refresh job to a
terminal state without an implicit deadline; pass `--timeout` when automation
needs a finite bound. Use `apply` when the declared source configuration itself
changes.

Unattended refresh is not supported yet. GeoLens does not verify that a
re-pulled source is complete, and schema drift is reported but does not block
the swap, so the person who triggers a refresh and reads the result is the only
thing standing between a truncated or reshaped source and live data. Nothing in
the API stops you calling this from a scheduler, but until completeness
verification ships, you are the check.

Protected services can receive a transient credential with `--token`. Use bare
`--token` to open a hidden-input prompt, which keeps the value out of terminal
output and shell history. Supplying a token value directly is supported for
automation but can expose it through process arguments or shell history, so
inject it only through an appropriately protected runner. GeoLens never stores
the credential in the dataset binding.

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
