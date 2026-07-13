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
geolens schema --output geolens-manifest-v1.schema.json
geolens apply --dry-run geolens.yaml
geolens apply geolens.yaml
geolens publish ./data/cities.geojson
geolens export stac <dataset-id> -o cities.stac.json
```

For a one-command quickstart, run `geolens publish examples/manifests/first-catalog/city-parks.geojson` against a running stack. See the full walkthrough at [docs.getgeolens.com](https://docs.getgeolens.com/).

The CLI consumes the [`geolens`](https://pypi.org/project/geolens/) Python SDK package. Manifest apply posts to the generated `POST /ingest/manifest/apply` contract through the SDK-owned client transport rather than a hand-rolled HTTP client.

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
