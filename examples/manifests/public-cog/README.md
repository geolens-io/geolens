# Public COG Manifest Example

This example registers a public Sentinel-2 Cloud-Optimized GeoTIFF without requiring local sample data.

```bash
geolens validate examples/manifests/public-cog/geolens.yaml
geolens apply examples/manifests/public-cog/geolens.yaml --dry-run
geolens apply examples/manifests/public-cog/geolens.yaml
```

The COG URL returns `Content-Type: image/tiff; application=geotiff; profile=cloud-optimized` and supports HTTP byte ranges. Attribution: contains modified Copernicus Sentinel data 2023, hosted by the public `sentinel-cogs` AWS Open Data dataset.
