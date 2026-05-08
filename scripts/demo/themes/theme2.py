"""Theme 2 — When the Earth Moves. Time-driven hazard maps."""
from __future__ import annotations
from themes import ThemeDataset

THEME_NAME = "When the Earth Moves"
THEME_DESCRIPTION = "Five years of seismic energy and a half-decade of fire scars across the western US. Each feature is one event."
THEME_IDX = 1

DATASETS: list[ThemeDataset] = [
    {
        "stem": "usgs_quakes_m5",
        "type": "vector",
        "source": "local",
        "local_path": "/data/demo/external/usgs_quakes_m5.geojson",
        "summary": (
            "USGS FDSN earthquake catalog, magnitude >= 5, 2021-05-08 to "
            "2026-05-08 (~9000 events). Point geometries with depth flattened "
            "into properties.depth_km for paint expressions. "
            "Source: USGS Earthquake Hazards Program."
        ),
        "snapshot_date": "2026-05-08",
        "license": "Public Domain (USGS)",
    },
    {
        "stem": "nifc_fires_2020_2024",
        "type": "vector",
        "source": "local",
        "local_path": "/data/demo/external/nifc_fires_2020_2024.geojson",
        "summary": (
            "NIFC WFIGS Interagency Perimeters, 2020-2024, 10 western states "
            "(CA, OR, WA, ID, NV, AZ, UT, MT, CO, NM). ~12k fire perimeters with "
            "derived properties.fire_year for paint expressions. "
            "Source: National Interagency Fire Center."
        ),
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (NIFC/WFIGS)",
    },
]
