# geolens (CLI)

Apache-2.0 command-line interface for the [GeoLens](https://github.com/geolens-io/geolens) API.

Login, scan local directories of spatial data, apply manifest-driven catalogs, publish vector or raster files, and export STAC metadata against any GeoLens instance — community or enterprise.

See `docs/cli.md` in the GeoLens repo for the full command reference.

## Quickstart

```bash
pip install geolens-cli
geolens login https://geolens.example.com
geolens scan ./data
geolens init
geolens validate geolens.yaml
geolens apply --dry-run geolens.yaml
geolens apply geolens.yaml
geolens publish ./data/cities.geojson
geolens export stac <dataset-id> -o cities.stac.json
```

For the Docker Compose first-catalog walkthrough using `examples/manifests/first-catalog/geolens.yaml`, see `docs/cli.md` in the GeoLens repo.

The CLI consumes the [`geolens`](https://github.com/geolens-io/geolens/blob/main/docs/sdks.md) Python SDK package. Manifest apply posts to the generated `POST /ingest/manifest/apply` contract through the SDK-owned client transport; there is no hand-rolled HTTP client.
