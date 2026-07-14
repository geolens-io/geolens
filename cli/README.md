# geolens (CLI)

Apache-2.0 command-line interface for the [GeoLens](https://github.com/geolens-io/geolens) API.

Login, scan local directories of spatial data, apply manifest-driven catalogs, publish vector or raster files, and export STAC metadata against any GeoLens instance.

See [docs.getgeolens.com](https://docs.getgeolens.com/) for the full command reference.

## Quickstart

```bash
pip install geolens-cli
geolens login https://geolens.example.com/api
geolens scan ./data
geolens init
geolens validate geolens.yaml
geolens apply --dry-run geolens.yaml
geolens apply geolens.yaml
geolens publish ./data/cities.geojson
geolens export stac <dataset-id> -o cities.stac.json
```

For a one-command quickstart, run `geolens publish examples/manifests/first-catalog/city-parks.geojson` against a running stack. See the full walkthrough at [docs.getgeolens.com](https://docs.getgeolens.com/).

The CLI consumes the [`geolens`](https://pypi.org/project/geolens/) Python SDK package. Manifest apply posts to the generated `POST /ingest/manifest/apply` contract through the SDK-owned client transport rather than a hand-rolled HTTP client.

## Environment variables

The CLI normally stores its active instance through `geolens login` and keeps
tokens in the OS keyring. Ephemeral CI jobs can avoid persistent state with:

| Variable | Purpose |
|---|---|
| `GEOLENS_INSTANCE` | GeoLens instance URL. The CLI normalizes the URL and appends `/api` when needed. An explicit `--instance` option takes precedence. |
| `GEOLENS_TOKEN` | Bearer token used instead of the keyring/credentials file. Treat it as a secret and inject it from the CI secret store. |

For load-test and seed-script variables, use the documented Tooling / Load
Tests section in the repository's `.env.example`.
