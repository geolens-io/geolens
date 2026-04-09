"""Theme 3 — Borders, Boundaries & Contested Space dataset registry. Owned by Plan 218-04."""

from themes import ThemeDataset

THEME_NAME = "Lines on the Map (2024 Snapshot)"
THEME_DESCRIPTION = "Every line on a world map was drawn by someone. Some are settled, some are not."
THEME_IDX = 2

# NOTE: the conflict-events dataset in this Theme is intentionally the Uppsala
# Conflict Data Program's Georeferenced Event Dataset (UCDP GED), NOT the
# alternative dataset that has the three-EULA conflict (governmental use,
# commercial use, AI training restrictions per CONTEXT.md). UCDP GED is CC-BY 4.0
# with no AI restriction. The substitution is locked — see 260408-lnq-PROPOSAL.md
# "Geopolitics Safety Notes" for the rationale.

DATASETS: list[ThemeDataset] = [
    # ---- NE administrative layers ----
    # Only layers actually referenced by a shipped fixture are registered here.
    # Removed 2026-04-09: ne_10m_admin_1_states_provinces, ne_10m_time_zones,
    # ne_10m_geographic_lines, ne_10m_playas — ingested but never used.
    {
        "stem": "ne_10m_admin_0_countries",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m admin 0 countries, version 5.1.2. Contents shown per Natural Earth's editorial stance, not GeoLens. Disputed boundaries policy: https://www.naturalearthdata.com/about/disputed-boundaries-policy.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_admin_0_boundary_lines_land",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m admin 0 boundary lines (land), version 5.1.2. Contents shown per Natural Earth's editorial stance, not GeoLens. Disputed boundaries policy: https://www.naturalearthdata.com/about/disputed-boundaries-policy.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },

    # ---- NE disputed/contested layers ----
    {
        "stem": "ne_10m_admin_0_disputed_areas",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m admin 0 disputed areas, version 5.1.2. Contents shown per Natural Earth's editorial stance, not GeoLens. Disputed boundaries policy: https://www.naturalearthdata.com/about/disputed-boundaries-policy.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    # NOTE: ne_10m_admin_0_breakaway_disputed_areas is NOT available on the NACIS CDN
    # (403 Forbidden) and is NOT in the seed-natural-earth.py manifest. Removed from
    # DATASETS to avoid runtime failure. Map 3.1 omits the breakaway layer. Documented
    # in 218-04-SUMMARY.md as a planning error in the plan's interfaces section.
    {
        "stem": "ne_10m_admin_0_boundary_lines_disputed_areas",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m admin 0 disputed boundary lines, version 5.1.2. Contents shown per Natural Earth's editorial stance, not GeoLens. Disputed boundaries policy: https://www.naturalearthdata.com/about/disputed-boundaries-policy.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_admin_0_antarctic_claims",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m antarctic territorial claims (7 sectors), version 5.1.2. Contents shown per Natural Earth's editorial stance, not GeoLens. Disputed boundaries policy: https://www.naturalearthdata.com/about/disputed-boundaries-policy.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },

    # ---- Country-specific admin_0 shapefiles (Kashmir toggle Map 3.2) ----
    # Each shapefile is rendered as published by Natural Earth without editorial
    # framing from GeoLens. Only the chn/ind/pak variants referenced by Map 3.2
    # are registered here; Natural Earth publishes ~9 regional variants total —
    # add back on demand if a future fixture needs arg/isr/rus/tur/ukr/usa views.
    {
        "stem": "ne_10m_admin_0_countries_chn",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m admin 0 countries (Chinese view), version 5.1.2. Contents shown per Natural Earth's editorial stance, not GeoLens.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_admin_0_countries_ind",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m admin 0 countries (Indian view), version 5.1.2. Contents shown per Natural Earth's editorial stance, not GeoLens.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_admin_0_countries_pak",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m admin 0 countries (Pakistani view), version 5.1.2. Contents shown per Natural Earth's editorial stance, not GeoLens.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },

    # ---- UCDP GED v25.1 — point vector_dataset ----
    # CSV with lat/lon columns, auto-detected as spatial by the ingest pipeline.
    {
        "stem": "ucdp_ged_v25_1",
        "type": "vector",
        "source": "local",
        "local_path": "/data/demo/ucdp_ged_v25_1.csv",
        "summary": (
            "Source: Uppsala Conflict Data Program (UCDP) Georeferenced Event Dataset v25.1, released 2025. "
            "Codebook and editorial policy: https://ucdp.uu.se/downloads. "
            "Contents shown per UCDP's editorial stance, not GeoLens. "
            "Subset: 2015-2024 events with confirmed lat/lon coordinates."
        ),
        "snapshot_date": "2025-01-01",
        "license": "CC-BY 4.0 (Uppsala Conflict Data Program)",
    },

    # ---- UNHCR refugees pre-joined to ADM0 polygons via csv_to_choropleth (origin = iso_o) ----
    {
        "stem": "refugees_by_origin_2023",
        "type": "vector",
        "source": "local",
        "local_path": "/data/demo/refugees_by_origin_2023.geojson",
        "summary": (
            "Source: UNHCR Refugee Population Statistics, end-year 2023, released 2024. "
            "UNHCR data terms: https://www.unhcr.org/refugee-statistics. "
            "Contents shown per UNHCR's reporting framework, not GeoLens. "
            "Joined to Natural Earth ADM0 polygons by country of origin (iso_o) via csv_to_choropleth helper. "
            "Stable value column: properties._value (refugees under UNHCR mandate)."
        ),
        "snapshot_date": "2024-06-15",
        "license": "CC-BY 4.0 (UNHCR)",
    },
]
