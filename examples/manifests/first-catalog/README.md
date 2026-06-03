# First Catalog — sample data

Sample dataset used by the README quickstart.

## One-command local ingest (recommended)

`city-parks.geojson` is a small GeoJSON FeatureCollection. Publish it directly:

```bash
geolens publish city-parks.geojson --name "City Parks"
```

`geolens publish` uploads the file and runs the ingest (upload → preview → commit) in a single step.

## Manifest structure (`geolens.yaml`)

`geolens.yaml` shows the shape of a catalog manifest for use with `geolens apply`.

> **Note:** `geolens apply` submits a manifest to the API but does **not** upload local
> files — its `staging/city-parks.geojson` source resolves against the server's staging
> area, so applying this manifest against a fresh stack queues an ingest job that fails
> (nothing was staged). For local files use `geolens publish` (above). For `geolens apply`,
> point sources at a reachable HTTP(S)/S3 URI — see the sibling [`url-source.yaml`](../url-source.yaml)
> and [`s3-source.yaml`](../s3-source.yaml) — or pre-stage the file on the server.
