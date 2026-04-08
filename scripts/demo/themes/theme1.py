"""Theme 1 — Planet Earth dataset registry. Owned by Plan 218-02."""

from typing import Any

THEME_NAME = "Planet Earth (2025 Snapshot)"
THEME_DESCRIPTION = "The stage on which everything else happens. Land, water, elevation, ice — one screen."
THEME_IDX = 0

DATASETS: list[dict[str, Any]] = [
    # ---- Vector NE physical layers (NACIS CDN download) ----
    {
        "stem": "ne_10m_land",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "physical",
        "local_path": None,
        "summary": "Natural Earth 1:10m land polygons. Source: Natural Earth (NACIS CDN), public domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_ocean",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "physical",
        "local_path": None,
        "summary": "Natural Earth 1:10m ocean polygons. Source: Natural Earth (NACIS CDN), public domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_coastline",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "physical",
        "local_path": None,
        "summary": "Natural Earth 1:10m coastline lines. Source: Natural Earth (NACIS CDN), public domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_rivers_lake_centerlines",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "physical",
        "local_path": None,
        "summary": "Natural Earth 1:10m river and lake centerlines with scalerank. Source: Natural Earth (NACIS CDN), public domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_lakes",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "physical",
        "local_path": None,
        "summary": "Natural Earth 1:10m lake polygons. Source: Natural Earth (NACIS CDN), public domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_glaciated_areas",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "physical",
        "local_path": None,
        "summary": "Natural Earth 1:10m glaciated area polygons. Source: Natural Earth (NACIS CDN), public domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_reefs",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "physical",
        "local_path": None,
        "summary": "Natural Earth 1:10m coral reef polygons. Source: Natural Earth (NACIS CDN), public domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_geography_regions_polys",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "physical",
        "local_path": None,
        "summary": "Natural Earth 1:10m named geography regions (deserts, plains, plateaus). Source: Natural Earth (NACIS CDN), public domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },

    # ---- Raster COGs (read from /data/demo/ — Plan 05 Dockerfile creates them) ----
    {
        "stem": "gebco_2024_30arcmin",
        "type": "raster",
        "source": "local",
        "ne_theme": None,
        "local_path": "/data/demo/gebco_2024_30arcmin.tif",
        "summary": (
            "GEBCO 2024 Grid bathymetry, downsampled to 30 arc-minute resolution. "
            "Source: GEBCO/NERC/BODC, public domain. snapshot_date=2024-12-01. "
            "Forward-compat note: this dataset is 3D-ready — when Phase 999.1 Terrain+Extrusions ships, "
            "this same raster can be served via Titiler ?algorithm=terrainrgb without re-ingest."
        ),
        "snapshot_date": "2024-12-01",
        "license": "Public Domain (GEBCO/NERC/BODC)",
    },
    {
        "stem": "ne_10m_shaded_relief",
        "type": "raster",
        "source": "local",
        "ne_theme": None,
        "local_path": "/data/demo/ne_10m_shaded_relief.tif",
        "summary": (
            "Natural Earth 1:10m shaded relief raster, converted to COG at seeder build time. "
            "Source: Natural Earth (NACIS), public domain. snapshot_date=2025-01-01."
        ),
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "srtm_himalayas",
        "type": "raster",
        "source": "local",
        "ne_theme": None,
        "local_path": "/data/demo/srtm_himalayas.tif",
        "summary": (
            "SRTM GL1 30m elevation tile covering the Himalayan region, served as a 2D elevation visualization. "
            "Source: NASA JPL via OpenTopography, public domain. snapshot_date=2014-01-01. "
            "Forward-compat note: 3D-ready DEM — Phase 999.1 Terrain+Extrusions will reuse this dataset for terrain rendering "
            "via Titiler's ?algorithm=terrainrgb URL pattern without re-ingest."
        ),
        "snapshot_date": "2014-01-01",
        "license": "Public Domain (NASA JPL)",
    },
]
