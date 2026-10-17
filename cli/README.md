# geolens (CLI)

Apache-2.0 command-line interface for the [GeoLens](https://github.com/geolens-io/geolens) API.

Log in, scan local directories of spatial data, publish files, apply manifest-driven catalogs, replace and refresh datasets, inspect source status, run PostGIS analysis operations, export STAC metadata and plan an ArcGIS migration against any GeoLens instance.

## Install

```bash
pip install geolens-cli      # installs the `geolens` command; Python 3.11 or newer
```

## Quick start

```bash
geolens login https://geolens.example.com/api
geolens publish ./data/cities.geojson
geolens status DATASET_ID        # the ID that publish printed
```

The CLI wraps the [`geolens`](https://pypi.org/project/geolens/) Python SDK package.

## Documentation

The full command reference, manifest schema, exit codes and CI setup are in the [CLI guide](https://docs.getgeolens.com/guides/cli/).
