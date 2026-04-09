"""Per-theme dataset registries for the GeoLens thematic demo seeder.

Each theme module is owned by exactly one plan in Phase 218:
- theme1.py — Plan 218-02 (Planet Earth)
- theme2.py — Plan 218-03 (Global Development & People)
- theme3.py — Plan 218-04 (Borders, Boundaries & Contested Space)

The split exists to let those three plans run in parallel without file conflicts.
Do NOT consolidate these modules — the per-file ownership is the parallelism contract.
"""

from __future__ import annotations

from typing import Literal, TypedDict


class ThemeDataset(TypedDict, total=False):
    """One dataset registration inside a theme module's ``DATASETS`` list.

    Field presence varies by (type, source) combination — this TypedDict is
    intentionally ``total=False`` so a single type can describe all of:

    - Natural Earth CDN vectors (``type=vector, source=ne_cdn``): carries
      ``ne_theme``, no ``local_path``.
    - Local vectors (``type=vector, source=local``): carries ``local_path``,
      no ``ne_theme``.
    - Local rasters (``type=raster, source=local``): carries ``local_path``,
      optional ``ne_theme=None``.

    The orchestrator's dispatcher at ``seed-thematic-demo.py:ingest_theme``
    is the authoritative consumer — the (type, source) pair determines which
    ingest helper receives the entry.
    """

    stem: str
    type: Literal["vector", "raster"]
    source: Literal["ne_cdn", "local"]
    ne_theme: str | None
    local_path: str | None
    summary: str
    snapshot_date: str
    license: str
