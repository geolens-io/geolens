"""Theme 3 — Borders, Boundaries & Contested Space dataset registry. Owned by Plan 218-04."""

from typing import Any

THEME_NAME = "Lines on the Map (2024 Snapshot)"
THEME_DESCRIPTION = "Every line on a world map was drawn by someone. Some are settled, some are not."
THEME_IDX = 2

# NOTE: the conflict-events dataset in this Theme is intentionally the Uppsala
# Conflict Data Program's Georeferenced Event Dataset (UCDP GED), NOT the
# alternative dataset that has the three-EULA conflict (governmental use,
# commercial use, AI training restrictions per CONTEXT.md). UCDP GED is CC-BY 4.0
# with no AI restriction. The substitution is locked — see 260408-lnq-PROPOSAL.md
# "Geopolitics Safety Notes" for the rationale.

DATASETS: list[dict[str, Any]] = [
    # ---- NE administrative layers ----
    {
        "stem": "ne_10m_admin_0_countries",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m, version 5.1.2. Disputed boundaries policy: https://www.naturalearthdata.com/about/disputed-boundaries-policy. Contents shown per Natural Earth's editorial stance, not GeoLens. License: Public Domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_admin_1_states_provinces",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m admin 1 states and provinces, version 5.1.2. License: Public Domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_admin_0_boundary_lines_land",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m admin 0 boundary lines (land), version 5.1.2. Disputed boundaries policy: https://www.naturalearthdata.com/about/disputed-boundaries-policy. Contents shown per Natural Earth's editorial stance, not GeoLens. License: Public Domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_time_zones",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m time zones, version 5.1.2. License: Public Domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_geographic_lines",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "physical",
        "summary": "Source: Natural Earth 1:10m geographic lines (equator, tropics, polar circles), version 5.1.2. License: Public Domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_playas",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "physical",
        "summary": "Source: Natural Earth 1:10m playas (dry lakebeds and salt flats), version 5.1.2. License: Public Domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },

    # ---- NE disputed/contested layers ----
    {
        "stem": "ne_10m_admin_0_disputed_areas",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m admin 0 disputed areas, version 5.1.2. Disputed boundaries policy: https://www.naturalearthdata.com/about/disputed-boundaries-policy. Contents shown per Natural Earth's editorial stance, not GeoLens. License: Public Domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_admin_0_breakaway_disputed_areas",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m admin 0 breakaway disputed areas (de-facto control regions), version 5.1.2. Disputed boundaries policy: https://www.naturalearthdata.com/about/disputed-boundaries-policy. Contents shown per Natural Earth's editorial stance, not GeoLens. License: Public Domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_admin_0_boundary_lines_disputed_areas",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m admin 0 disputed boundary lines, version 5.1.2. Disputed boundaries policy: https://www.naturalearthdata.com/about/disputed-boundaries-policy. Contents shown per Natural Earth's editorial stance, not GeoLens. License: Public Domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_admin_0_antarctic_claims",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m antarctic territorial claims (7 sectors), version 5.1.2. Disputed boundaries policy: https://www.naturalearthdata.com/about/disputed-boundaries-policy. Contents shown per Natural Earth's editorial stance, not GeoLens. License: Public Domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_admin_0_antarctic_claim_limit_lines",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m antarctic claim limit lines, version 5.1.2. License: Public Domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },

    # ---- The 9 NE country-specific shapefiles — Kashmir conversation starter dataset ----
    # Each shapefile is rendered as published by Natural Earth without editorial framing from GeoLens.
    {
        "stem": "ne_10m_admin_0_countries_arg",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m admin 0 countries (Argentine view), version 5.1.2. Contents shown per Natural Earth's editorial stance, not GeoLens. License: Public Domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_admin_0_countries_chn",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m admin 0 countries (Chinese view), version 5.1.2. Contents shown per Natural Earth's editorial stance, not GeoLens. License: Public Domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_admin_0_countries_ind",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m admin 0 countries (Indian view), version 5.1.2. Contents shown per Natural Earth's editorial stance, not GeoLens. License: Public Domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_admin_0_countries_isr",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m admin 0 countries (Israeli view), version 5.1.2. Contents shown per Natural Earth's editorial stance, not GeoLens. License: Public Domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_admin_0_countries_pak",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m admin 0 countries (Pakistani view), version 5.1.2. Contents shown per Natural Earth's editorial stance, not GeoLens. License: Public Domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_admin_0_countries_rus",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m admin 0 countries (Russian view), version 5.1.2. Contents shown per Natural Earth's editorial stance, not GeoLens. License: Public Domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_admin_0_countries_tur",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m admin 0 countries (Turkish view), version 5.1.2. Contents shown per Natural Earth's editorial stance, not GeoLens. License: Public Domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_admin_0_countries_ukr",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m admin 0 countries (Ukrainian view), version 5.1.2. Contents shown per Natural Earth's editorial stance, not GeoLens. License: Public Domain. snapshot_date=2025-01-01.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (Natural Earth)",
    },
    {
        "stem": "ne_10m_admin_0_countries_usa",
        "type": "vector",
        "source": "ne_cdn",
        "ne_theme": "cultural",
        "summary": "Source: Natural Earth 1:10m admin 0 countries (US view), version 5.1.2. Contents shown per Natural Earth's editorial stance, not GeoLens. License: Public Domain. snapshot_date=2025-01-01.",
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
            "License: CC-BY 4.0. snapshot_date=2025-01-01. "
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
            "License: CC-BY 4.0. "
            "Joined to Natural Earth ADM0 polygons by country of origin (iso_o) via csv_to_choropleth helper. "
            "Stable value column: properties._value (refugees under UNHCR mandate). "
            "snapshot_date=2024-06-15."
        ),
        "snapshot_date": "2024-06-15",
        "license": "CC-BY 4.0 (UNHCR)",
    },
]
