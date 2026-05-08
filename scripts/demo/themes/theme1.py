"""Theme 1 — When the Land Speaks. Three 3D-rendered terrain + extrusion maps."""
from __future__ import annotations
from themes import ThemeDataset

THEME_NAME = "When the Land Speaks"
THEME_DESCRIPTION = "Land in three dimensions: canyon walls, city skylines, and population density rendered as terrain you can tilt and rotate."
THEME_IDX = 0

DATASETS: list[ThemeDataset] = [
    {
        "stem": "grand_canyon_dem",
        "type": "raster",
        "source": "local",
        "local_path": "/data/demo/external/grand_canyon_dem.tif",
        "summary": (
            "USGS 3DEP 1/3 arc-second DEM (~10m), cropped to the Grand Canyon AOI "
            "(-113 to -111.5 lon, 36 to 37 lat). Float32 elevation in meters, GCS WGS84. "
            "Source: USGS 3D Elevation Program."
        ),
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (USGS 3DEP)",
    },
    {
        "stem": "grand_canyon_hillshade",
        "type": "raster",
        "source": "local",
        "local_path": "/data/demo/external/grand_canyon_hillshade.tif",
        "summary": (
            "Hillshade derived from the 3DEP DEM via gdaldem hillshade -z 1.5 "
            "-s 111120 -multidirectional. uint8 grayscale, COG/DEFLATE. Pairs "
            "with grand_canyon_dem as a stacked render. Source: derivative of USGS 3DEP."
        ),
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (USGS 3DEP, derivative)",
    },
    {
        "stem": "nyc_pluto_zoning",
        "type": "vector",
        "source": "local",
        "local_path": "/data/demo/external/nyc_pluto_zoning.geojson",
        "summary": (
            "NYC Building Footprints (5zhs-2jue) joined with PLUTO (64uk-42ks) via "
            "mappluto_bbl. Manhattan + Brooklyn waterfront subset, EPSG:4326. "
            "Properties: height (m), landuse, zonedist1, numfloors. "
            "Source: NYC Open Data."
        ),
        "snapshot_date": "2026-04-01",
        "license": "NYC Open Data (public use with attribution)",
    },
    {
        "stem": "pop_density_tracts",
        "type": "vector",
        "source": "local",
        "local_path": "/data/demo/external/pop_density_tracts.geojson",
        "summary": (
            "Census 2024 cb_2024_us_tract_500k tracts for CA+TX+NY+FL "
            "(~16k polygons), joined with ACS 2023 5-year B01003_001E "
            "(population) and B19013_001E (median household income). "
            "Density = pop / ALAND_sq_km. Reprojected to EPSG:4326. "
            "Source: US Census Bureau."
        ),
        "snapshot_date": "2024-12-01",
        "license": "Public Domain (US Census Bureau)",
    },
]
