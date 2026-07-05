# Third-party data sources

The `scripts/seed-showcase.py` seeder builds the marketing "showcase" maps from
public, openly-licensed data fetched at seed time. GeoLens does not redistribute
any of these datasets — the script pulls them live from each provider when you
run it. The licenses and attribution requirements below belong to their
respective providers; consult each source for the authoritative, current terms.

| Dataset | Source / URL | License | Attribution | Version / pin | Retrieved | Transformations |
| --- | --- | --- | --- | --- | --- | --- |
| Building footprints (Manhattan) | NYC Open Data — Socrata `5zhs-2jue` (`data.cityofnewyork.us`) | NYC Open Data terms (public) | "NYC Open Data" | Live query | At seed-run time | bbox filter, coerce Socrata string-numbers to floats, `height_roof` ft→m (×0.3048), derive construction era |
| Subway lines & stations (NYC) | MTA via `data.ny.gov` (`s692-irgq`, `39hk-dx4f`) | NY State / MTA open data | "Metropolitan Transportation Authority (MTA)" | Live query | At seed-run time | property trim; official MTA route colors applied in-style |
| County median household income | USDA ERS Atlas of Rural & Small-Town America (`gisportal.ers.usda.gov`) | U.S. Government — public domain | "USDA Economic Research Service" | Live query | At seed-run time | NY filter (catalog dataset for the AI demos) |
| swissALTI3D 2m DEM | swisstopo via `data.geo.admin.ch` STAC (`ch.swisstopo.swissalti3d`) | swisstopo OGD (open) | "Federal Office of Topography swisstopo" | 2024 product, AOI tiles | At seed-run time | VRT mosaic of COG tiles, `is_dem=true`, hillshade + hypsometric tint |
| Global relief (bathymetry + topography) | NOAA NCEI ETOPO 2022, 60″ (`ngdc.noaa.gov`) | U.S. Government — public domain | "NOAA NCEI" | ETOPO 2022 | At seed-run time | server-side download → COG, colormap + percentile stretch |
| Earthquakes (M4.5+) | USGS Earthquake Hazards Program (`earthquake.usgs.gov` M4.5+ 30-day feed) | U.S. Government — public domain | "USGS" | 30-day rolling feed | At seed-run time | property trim + enrich (depth/felt/tsunami/sig) |
| Significant volcanic eruptions | NOAA NCEI Significant Volcanic Eruptions (`ngdc.noaa.gov` HazEL API) | U.S. Government — public domain | "NOAA NCEI" | 4360 BC–present | At seed-run time | paginated fetch → GeoJSON points, BCE year labels |
| Tectonic plate boundaries | PB2002 (Peter Bird 2003) via `fraxen/tectonicplates` | Open data (attribution) | "Peter Bird (2003), PB2002; Hugo Ahlenius / Nordpil" | Static | At seed-run time | collapse step classes to 4 boundary types |
| Atlantic hurricane tracks | NOAA NHC HURDAT2 (`nhc.noaa.gov/data/hurdat`) | U.S. Government — public domain | "NOAA NHC" | 1851–2024 revision | At seed-run time | parse text → per-6h LineString segments, Saffir-Simpson per leg |
| Meteorite landings | NASA Open Data / The Meteoritical Society (`data.nasa.gov`) | U.S. Government — public domain | "NASA / The Meteoritical Society" | Live CSV | At seed-run time | CSV → GeoJSON, drop null/off-planet coords, mass g→kg |
| Countries / Places / Admin-1 | Natural Earth via `nvkelso/natural-earth-vector` | Public domain | "Natural Earth" | Pinned tag `v5.1.2` | At seed-run time | column trim; major-cities subset (500k+) |
| Sentinel-2 L2A true-color (TCI) | AWS Earth Search / Element84 (`earth-search.aws.element84.com`), ESA Copernicus | Copernicus Sentinel data — free and open, with attribution | "Contains modified Copernicus Sentinel data [year]" | Live STAC query (Collection-1) | At seed-run time | imported by-reference as COGs (no download) |
| Trails / Peaks (Matterhorn) | OpenStreetMap via Overpass (`overpass-api.de`) | ODbL 1.0 | "© OpenStreetMap contributors" | Live query | At seed-run time | clipped to the DEM bbox |

> Note: the NYC Open Data and Sentinel-2 / Copernicus license phrasing above is
> summarized for convenience; verify the current terms with the provider before
> redistributing any derived data.
