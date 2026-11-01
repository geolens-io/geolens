# Third-party data sources

The `scripts/seed-showcase.py` seeder builds the marketing "showcase" maps from
public, openly-licensed data. GeoLens does not redistribute any of these
datasets. Most are fetched live from each provider when the script runs; the
`--showcase-121` inputs (the canopy archive, the 3D Tiles sample and the COPC
file) are downloaded first by a preparation script or by you, as each row's
Retrieved column says, and passed to the seeder. The licenses and attribution requirements below belong to their
respective providers; consult each source for the authoritative, current terms.

| Dataset | Source / URL | License | Attribution | Version / pin | Retrieved | Transformations |
| --- | --- | --- | --- | --- | --- | --- |
| Building footprints (Manhattan) | NYC Open Data — Socrata `5zhs-2jue` (`data.cityofnewyork.us`) | NYC Open Data terms (public) | "NYC Open Data" | Live query | At seed-run time | bbox filter, coerce Socrata string-numbers to floats, `height_roof` ft→m (×0.3048), derive construction era |
| Subway lines & stations (NYC) | MTA via `data.ny.gov` (`s692-irgq`, `39hk-dx4f`) | NY State / MTA open data | "Metropolitan Transportation Authority (MTA)" | Live query | At seed-run time | property trim; official MTA route colors applied in-style |
| Tree canopy change 2010-2017 (East Village) | NYC Open Data, Socrata `by9k-vhck` (`Tree_Canopy_Change.zip`), from NYC OTI and the University of Vermont | NYC Open Data terms (public) | "NYC Open Data" | SHA-256-pinned archive (`scripts/prepare-showcase-canopy.sh`) | When the prepare script runs | `NYC_TreeCanopyChange_2010_2017` layer clipped to an East Village rectangle |
| County median household income | USDA ERS Atlas of Rural & Small-Town America (`gisportal.ers.usda.gov`) | U.S. Government — public domain | "USDA Economic Research Service" | Live query | At seed-run time | NY filter (catalog dataset for the AI demos) |
| swissALTI3D 2m DEM | swisstopo via `data.geo.admin.ch` STAC (`ch.swisstopo.swissalti3d`) | swisstopo OGD (open) | "Federal Office of Topography swisstopo" | 2024 product, AOI tiles | At seed-run time | VRT mosaic of COG tiles, `is_dem=true`, hillshade + hypsometric tint |
| Global relief (bathymetry + topography) | NOAA NCEI ETOPO 2022, 60″ (`ngdc.noaa.gov`) | U.S. Government — public domain | "NOAA NCEI" | ETOPO 2022 | At seed-run time | server-side download → COG, colormap + percentile stretch |
| Earthquakes (M2.5+) | USGS Earthquake Hazards Program — ArcGIS REST service (`earthquake.usgs.gov/arcgis/rest/services/eq/Recent_Earthquakes/MapServer`, layer 0 "M2.5+ Recent Earthquakes") | U.S. Government — public domain | "USGS" | 30-day rolling window | Bound as a live service; re-pulled server-side by `--refresh-quakes` | none — the layer is bound whole (the connector applies no attribute filter) and styling reads the service's own column names |
| Significant volcanic eruptions | NOAA NCEI Significant Volcanic Eruptions (`ngdc.noaa.gov` HazEL API) | U.S. Government — public domain | "NOAA NCEI" | 4360 BC–present | At seed-run time | paginated fetch → GeoJSON points, BCE year labels |
| Tectonic plate boundaries | PB2002 (Peter Bird 2003) via `fraxen/tectonicplates` | Open data (attribution) | "Peter Bird (2003), PB2002; Hugo Ahlenius / Nordpil" | Static | At seed-run time | collapse step classes to 4 boundary types |
| Atlantic hurricane tracks | NOAA NHC HURDAT2 (`nhc.noaa.gov/data/hurdat`) | U.S. Government — public domain | "NOAA NHC" | 1851–2025 revision (`hurdat2-1851-2025-02272026.txt`) | At seed-run time | parse text → per-6h LineString segments, Saffir-Simpson per leg |
| Meteorite landings | NASA Open Data / The Meteoritical Society (`data.nasa.gov`) | U.S. Government — public domain | "NASA / The Meteoritical Society" | Live CSV | At seed-run time | CSV → GeoJSON, drop null/off-planet coords, mass g→kg |
| Countries / Places / Admin-1 | Natural Earth via `nvkelso/natural-earth-vector` | Public domain | "Natural Earth" | Pinned tag `v5.1.2` | At seed-run time | column trim; major-cities subset (500k+) |
| Sentinel-2 L2A true-color (TCI) | AWS Earth Search / Element84 (`earth-search.aws.element84.com`), ESA Copernicus | Copernicus Sentinel data — free and open, with attribution | "Contains modified Copernicus Sentinel data [year]" | Live STAC query (Collection-1) | At seed-run time | imported by-reference as COGs (no download) |
| Trails / Peaks (Matterhorn) | OpenStreetMap via Overpass (`overpass-api.de`) | ODbL 1.0 | "© OpenStreetMap contributors" | Live query | At seed-run time | clipped to the DEM bbox |
| Midtown Manhattan skyline photograph (skyline story image) | Library of Congress, Prints & Photographs Division, FSA/OWI Collection, LC-DIG-fsa-8b16269, December 1941 (`loc.gov/pictures/item/2017775111/`, file `cdn.loc.gov/service/pnp/fsa/8b16000/8b16200/8b16269v.jpg`) | No known restrictions on publication (the item's rights statement, U.S. Farm Security Administration/Office of War Information photographs) | "Library of Congress, Prints & Photographs Division, FSA/OWI Collection, LC-DIG-fsa-8b16269" | SHA-256-pinned file (`SKYLINE_PHOTO_SHA256` in `scripts/seed-showcase.py`) | At seed-run time | uploaded unchanged to the story as an image block; GeoLens stores it as WebP without metadata |
| Autzen Stadium classified point cloud (COPC sample) | PDAL/data `autzen/autzen-classified.copc.laz` (`github.com/PDAL/data`) | CC BY 4.0 | "PDAL/data contributors, CC BY 4.0", with a link to the [PDAL/data license](https://github.com/PDAL/data/blob/main/LICENSE) | Checksum-pinned file | Downloaded by the operator and passed to `--showcase-121` as `--copc-file` | none; the real COPC file is imported as is |
| Central Amsterdam buildings (3D Tiles sample) | 3DBAG release `v20250903`, LoD 1.2 (`docs.3dbag.nl`) | CC BY 4.0 | "© 3DBAG by tudelft3d and 3DGI", with a link to the [3DBAG copyright page](https://docs.3dbag.nl/en/copyright/); bottom right in a browsable map | Release `v20250903` | Prepared by `scripts/prepare-showcase-tiles3d.py`, then imported by `--showcase-121` | one hierarchy branch and its four GLBs selected, geometry unchanged; extraction disclosed in the dataset attribution |

> Note: the NYC Open Data and Sentinel-2 / Copernicus license phrasing above is
> summarized for convenience; verify the current terms with the provider before
> redistributing any derived data.
