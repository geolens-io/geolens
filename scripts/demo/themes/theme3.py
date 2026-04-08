"""Theme 3 — Borders, Boundaries & Contested Space dataset registry. Owned by Plan 218-04."""

from typing import Any

THEME_NAME = "Lines on the Map (2024 Snapshot)"
THEME_DESCRIPTION = "Every line on a world map was drawn by someone. Some are settled, some are not."
THEME_IDX = 2

# Plan 218-04 will populate this with the Theme 3 datasets:
# 5 NE administrative + 5 NE disputed/antarctic + 9 NE country-specific shapefiles +
# ucdp_ged_v25_1 (point CSV) + refugees_by_origin_2023 (pre-joined GeoJSON via UNHCR iso_o)
# ACLED is intentionally NOT used (three-EULA-conflict per CONTEXT.md).
DATASETS: list[dict[str, Any]] = []
