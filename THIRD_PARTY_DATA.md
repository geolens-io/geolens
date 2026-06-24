# Third-party data sources

The `scripts/seed-showcase.py` seeder builds the marketing "showcase" maps from
public, openly-licensed data fetched at seed time. GeoLens does not redistribute
any of these datasets — the script pulls them live from each provider when you
run it. The licenses and attribution requirements below belong to their
respective providers; consult each source for the authoritative, current terms.

| Dataset | Source / URL | License | Attribution | Version / pin | Retrieved | Transformations |
| --- | --- | --- | --- | --- | --- | --- |
| Building footprints (Manhattan) | NYC Open Data — Socrata `5zhs-2jue` (`data.cityofnewyork.us`) | NYC Open Data terms (public) | "NYC Open Data" | Live query | At seed-run time | bbox filter, coerce Socrata string-numbers to floats, `height_roof` ft→m (×0.3048) |
| County median household income | USDA ERS Atlas of Rural & Small-Town America (`gisportal.ers.usda.gov`) | U.S. Government — public domain | "USDA Economic Research Service" | Live query | At seed-run time | NY filter, quantile (sextile) breaks |
| swissALTI3D 2m DEM | swisstopo via `data.geo.admin.ch` STAC (`ch.swisstopo.swissalti3d`) | swisstopo OGD (open) | "Federal Office of Topography swisstopo" | 2024 product, AOI tiles | At seed-run time | VRT mosaic of COG tiles, `is_dem=true` |
| World airports | OurAirports (`davidmegginson.github.io/ourairports-data`) | Public domain | "OurAirports" | Live CSV | At seed-run time | large + medium airports with scheduled service only |
| Earthquakes (M4.5+) | USGS Earthquake Hazards Program (`earthquake.usgs.gov` M4.5+ 30-day feed) | U.S. Government — public domain | "USGS" | 30-day rolling feed | At seed-run time | property trim (mag/place/time) |
| Countries / Places / Rivers / Admin-1 | Natural Earth via `nvkelso/natural-earth-vector` | Public domain | "Natural Earth" | Pinned tag `v5.1.2` | At seed-run time | column trim, quantile breaks |
| Sentinel-2 L2A true-color (TCI) | AWS Earth Search / Element84 (`earth-search.aws.element84.com`), ESA Copernicus | Copernicus Sentinel data — free and open, with attribution | "Contains modified Copernicus Sentinel data [year]" | Live STAC query | At seed-run time | imported by-reference as COGs (no download) |
| Trails / Peaks (Matterhorn) | OpenStreetMap via Overpass (`overpass-api.de`) | ODbL 1.0 | "© OpenStreetMap contributors" | Live query | At seed-run time | clipped to the DEM bbox |

> Note: the NYC Open Data and Sentinel-2 / Copernicus license phrasing above is
> summarized for convenience; verify the current terms with the provider before
> redistributing any derived data.
