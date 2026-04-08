"""Theme 1 — Planet Earth dataset registry. Owned by Plan 218-02."""

from typing import Any

THEME_NAME = "Planet Earth (2025 Snapshot)"
THEME_DESCRIPTION = "The stage on which everything else happens. Land, water, elevation, ice — one screen."
THEME_IDX = 0

# Plan 218-02 will populate this with the Theme 1 datasets:
# NE physical vectors (8) + GEBCO COG + NE shaded relief COG + SRTM forward-compat DEM
# Each entry shape:
# {
#   "stem": str,
#   "type": "vector" | "raster",
#   "source": "ne_cdn" | "local",
#   "ne_theme": "cultural" | "physical" | None,
#   "local_path": str | None,
#   "summary": str,
#   "snapshot_date": str,
#   "license": str,
# }
DATASETS: list[dict[str, Any]] = []
