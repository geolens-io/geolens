# geolens (CLI)

Apache-2.0 command-line interface for the [GeoLens](https://github.com/geolens-io/geolens) API.

Login, scan local directories of spatial data, publish vector or raster files, and export STAC metadata against any GeoLens instance — community or enterprise.

See `docs/cli.md` in the GeoLens repo for the full command reference.

## Quickstart

```bash
pip install geolens-cli
geolens login https://geolens.example.com
geolens scan ./data
geolens publish ./data/cities.geojson
geolens export stac <dataset-id> -o cities.stac.json
```

The CLI consumes the [`geolens`](https://github.com/geolens-io/geolens/blob/main/docs/sdks.md) Python SDK package — there is no hand-rolled HTTP client.
