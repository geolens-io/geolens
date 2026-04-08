"""Theme 2 — Global Development & People dataset registry. Owned by Plan 218-03."""

from typing import Any

THEME_NAME = "How the World Lives (2024)"
THEME_DESCRIPTION = "Seven billion people, 200 countries. Population, income, life expectancy."
THEME_IDX = 1

# SEDAC GPWv4 is intentionally omitted per CONTEXT.md decision.
# Rationale: NASA Earthdata account requirement blocks external contributors and
# cannot be scripted in a public Dockerfile (per 218-RESEARCH.md G1). Theme 2
# tells the population story via ne_10m_populated_places_simple proportional
# symbols on Map 2.1 instead. The raster-COG story is already exercised by
# Theme 1 (GEBCO + NE shaded relief).
DATASETS: list[dict[str, Any]] = [
    # ---- NE cultural vectors (NACIS CDN download) ----
    {
        "stem": "ne_10m_populated_places_simple",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Natural Earth 1:10m populated places (simple) with POP_MAX attribute. Source: Natural Earth (NACIS CDN), public domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_urban_areas",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Natural Earth 1:10m urban area polygons. Source: Natural Earth (NACIS CDN), public domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_airports",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Natural Earth 1:10m airport points. Source: Natural Earth (NACIS CDN), public domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_ports",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Natural Earth 1:10m port points. Source: Natural Earth (NACIS CDN), public domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_roads",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Natural Earth 1:10m road lines. Source: Natural Earth (NACIS CDN), public domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_railroads",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Natural Earth 1:10m railroad lines. Source: Natural Earth (NACIS CDN), public domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },

    # ---- Pre-joined indicator GeoJSONs (Plan 05 Dockerfile produces these via csv_to_choropleth.py) ----
    # The stable value column for these is properties._value (locked in Plan 01).
    {
        "stem": "gdp_per_capita_ppp_2023",
        "type": "vector",
        "source": "local",
        "local_path": "/data/demo/gdp_per_capita_ppp_2023.geojson",
        "summary": (
            "GDP per capita PPP (current international $) 2023, joined to Natural Earth ADM0 polygons "
            "via the csv_to_choropleth helper. Source: World Bank Open Data (api.worldbank.org), CC-BY 4.0. "
            "snapshot_date=2024-12-15. Indicator: NY.GDP.PCAP.PP.CD. Stable value column: properties._value."
        ),
        "snapshot_date": "2024-12-15",
        "license": "CC-BY 4.0 (World Bank Open Data)",
    },
    {
        "stem": "life_expectancy_2021",
        "type": "vector",
        "source": "local",
        "local_path": "/data/demo/life_expectancy_2021.geojson",
        "summary": (
            "Life expectancy at birth (years), 2021, joined to Natural Earth ADM0 polygons via csv_to_choropleth. "
            "Source: Our World in Data (ourworldindata.org/grapher/life-expectancy), CC-BY 4.0. "
            "snapshot_date=2024-12-15. Stable value column: properties._value."
        ),
        "snapshot_date": "2024-12-15",
        "license": "CC-BY 4.0 (Our World in Data)",
    },

    # ---- Manhattan OSM buildings (forward-compat for Phase 999.1 fill-extrusion) ----
    {
        "stem": "manhattan_buildings",
        "type": "vector",
        "source": "local",
        "local_path": "/data/demo/manhattan_buildings.geojson",
        "summary": (
            "OpenStreetMap building footprints for Manhattan, clipped from the Geofabrik New York extract. "
            "Includes the `height` attribute where present in OSM (~40-60% coverage). "
            "Source: © OpenStreetMap contributors, ODbL 1.0. snapshot_date=2026-04-01. "
            "Forward-compat note: 3D-ready — Phase 999.1 Terrain+Extrusions will add a fill-extrusion map "
            "keyed on the `height` attribute without re-ingest."
        ),
        "snapshot_date": "2026-04-01",
        "license": "ODbL 1.0 (© OpenStreetMap contributors)",
    },
]
