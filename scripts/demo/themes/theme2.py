"""Theme 2 — Global Development & People dataset registry. Owned by Plan 218-03."""

from themes import ThemeDataset

THEME_NAME = "How the World Lives (2024)"
THEME_DESCRIPTION = "Seven billion people, 200 countries. Population, income, life expectancy."
THEME_IDX = 1

# SEDAC GPWv4 is intentionally omitted per CONTEXT.md decision.
# Rationale: NASA Earthdata account requirement blocks external contributors and
# cannot be scripted in a public Dockerfile (per 218-RESEARCH.md G1). Theme 2
# tells the population story via ne_10m_populated_places_simple proportional
# symbols on Map 2.1 instead. The raster-COG story is already exercised by
# Theme 1 (GEBCO + NE shaded relief).
DATASETS: list[ThemeDataset] = [
    # ---- NE cultural vectors (NACIS CDN download) ----
    # Only layers actually referenced by a shipped fixture are registered here.
    # Removed 2026-04-09: ne_10m_urban_areas, ne_10m_airports, ne_10m_ports,
    # ne_10m_roads, ne_10m_railroads — ingested but never used by any fixture.
    {
        "stem": "ne_10m_populated_places_simple",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Natural Earth 1:10m populated places (simple) with POP_MAX attribute. Source: Natural Earth (NACIS CDN).",
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
            "via the csv_to_choropleth helper. Source: World Bank Open Data (api.worldbank.org). "
            "Indicator: NY.GDP.PCAP.PP.CD. Stable value column: properties._value."
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
            "Source: Our World in Data (ourworldindata.org/grapher/life-expectancy). "
            "Stable value column: properties._value."
        ),
        "snapshot_date": "2024-12-15",
        "license": "CC-BY 4.0 (Our World in Data)",
    },

    # ---- Manhattan buildings with real heights (NYC Open Data) ----
    {
        "stem": "manhattan_buildings",
        "type": "vector",
        "source": "local",
        "local_path": "/data/demo/manhattan_buildings.geojson",
        "summary": (
            "NYC building footprints for Manhattan with photogrammetric roof heights (HEIGHT_ROOF). "
            "Source: NYC Office of Technology and Innovation (data.cityofnewyork.us). "
            "Used by the Manhattan Skyline (3D) map for fill-extrusion rendering "
            "keyed on the `height` column (meters, converted from feet at build time)."
        ),
        "snapshot_date": "2026-04-12",
        "license": "NYC Open Data (public use with attribution)",
    },
]
