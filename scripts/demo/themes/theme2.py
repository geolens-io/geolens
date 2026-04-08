"""Theme 2 — Global Development & People dataset registry. Owned by Plan 218-03."""

from typing import Any

THEME_NAME = "How the World Lives (2024)"
THEME_DESCRIPTION = "Seven billion people, 200 countries. Population, income, life expectancy."
THEME_IDX = 1

# Plan 218-03 will populate this with the Theme 2 datasets:
# 6 NE cultural vectors + gdp_per_capita_ppp_2023 (pre-joined GeoJSON) +
# life_expectancy_2021 (pre-joined GeoJSON) + manhattan_buildings (forward-compat for 999.1)
# SEDAC GPWv4 is intentionally omitted per CONTEXT.md decision (NASA Earthdata auth blocks public Dockerfile).
DATASETS: list[dict[str, Any]] = []
