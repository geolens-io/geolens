#!/usr/bin/env python3
"""Pre-join helper: indicator CSV → ADM0 GeoJSON choropleth.

STABLE CONTRACT: The output field `_value` is a stable contract that downstream
fixtures reference. Do NOT rename it. Every feature that survives the join will
have `properties._value` set to the numeric indicator value and
`properties._value_col` set to the column name for human readability.

WARNING — DO NOT remove this helper and switch to ingesting raw CSVs as table
records. Adding a `record_type=table` dataset to a map produces a silent blank
layer (tile endpoint 503) — see 260408-mgg-FINDINGS.md. The only correct path
for CSV-sourced choropleth data is to pre-join it to an ADM0 polygon layer here
and ingest the resulting GeoJSON as a vector dataset.

Usage:
    python3 csv_to_choropleth.py \\
        --csv <path> \\
        --adm0 <path.geojson or .shp or .zip> \\
        --csv-join-col <col> \\
        --adm0-join-col <col> \\
        --value-col <col> \\
        --output <path> \\
        [--year-filter YYYY] \\
        [--log-level INFO]

Exit codes:
    0 — success (at least one match produced)
    1 — zero matches (treat as join-column mismatch or wrong CSV)
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger("csv_to_choropleth")


# ---------------------------------------------------------------------------
# shapefile / GeoJSON loader
# ---------------------------------------------------------------------------


def shapefile_to_geojson(adm0_path: Path | str) -> dict[str, Any]:
    """Load an ADM0 boundary file as a GeoJSON dict.

    If the path ends with `.geojson` or `.json`, read it directly.
    Otherwise, shell out to `ogr2ogr -f GeoJSON` to convert it.
    Supports `.shp`, `.zip` (shapefile ZIP), or any OGR-readable format.

    Args:
        adm0_path: Path to the ADM0 file (str or Path).

    Returns:
        Parsed GeoJSON FeatureCollection dict.

    Raises:
        RuntimeError: If ogr2ogr conversion fails.
        FileNotFoundError: If the file does not exist.
    """
    p = Path(adm0_path)
    if not p.exists():
        raise FileNotFoundError(f"ADM0 file not found: {p}")

    suffix = p.suffix.lower()
    if suffix in (".geojson", ".json"):
        return json.loads(p.read_text())

    # Shell out to ogr2ogr for shapefile / zip conversion
    with tempfile.NamedTemporaryFile(suffix=".geojson", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        # For ZIP shapefiles, construct the /vsizip/ path
        if suffix == ".zip":
            src = f"/vsizip/{p}"
        else:
            src = str(p)

        # Delete the empty placeholder so ogr2ogr can create the file fresh
        # (GeoJSON driver cannot overwrite an existing file, even an empty one)
        tmp_path.unlink(missing_ok=True)

        result = subprocess.run(
            ["ogr2ogr", "-f", "GeoJSON", str(tmp_path), src],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ogr2ogr failed (exit {result.returncode}): {result.stderr[:500]}"
            )
        return json.loads(tmp_path.read_text())
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# CSV loader with World Bank header detection
# ---------------------------------------------------------------------------

_WORLDBANK_METADATA_MARKERS = (
    '"Data Source"',
    "Data Source",
    "Last Updated Date",
    '"Last Updated Date"',
)


def _looks_like_metadata(line: str) -> bool:
    """Return True if a line looks like a World Bank metadata header."""
    stripped = line.strip()
    if not stripped:
        return True
    return any(stripped.startswith(m) for m in _WORLDBANK_METADATA_MARKERS)


def _find_data_start(lines: list[str]) -> int:
    """Scan up to 10 lines to find the first non-metadata row.

    Returns the 0-based index of the first data line (the header row of the
    actual CSV table). World Bank CSVs have 4 metadata lines followed by an
    empty line, then the real header.
    """
    for i, line in enumerate(lines[:10]):
        stripped = line.strip()
        if not stripped:
            continue
        if not _looks_like_metadata(line):
            return i
    return 0


def load_indicator_csv(
    csv_path: Path | str,
    join_col: str,
    value_col: str,
    year_filter: str | None = None,
) -> dict[str, float]:
    """Load an indicator CSV and return a ``{iso3: float}`` dict.

    - Scans up to 10 lines to skip World Bank-style metadata header.
    - Last value wins on duplicate join-column values (logged at WARNING).
    - Skips rows where value is empty or non-numeric.
    - Optionally filters by a ``year`` column if ``year_filter`` is provided.

    Args:
        csv_path: Path to the indicator CSV.
        join_col: Column name to use as the join key (e.g. ``"iso3"``).
        value_col: Column name holding the numeric value.
        year_filter: If given, only rows with ``year == year_filter`` are kept.

    Returns:
        Mapping from join key → float value.
    """
    p = Path(csv_path)
    raw_lines = p.read_text(encoding="utf-8-sig").splitlines(keepends=True)

    # Find where the actual CSV data starts (skip World Bank metadata)
    start_idx = _find_data_start(raw_lines)
    data_text = "".join(raw_lines[start_idx:])

    reader = csv.DictReader(data_text.splitlines())
    values: dict[str, float] = {}
    seen: set[str] = set()

    for row in reader:
        key = row.get(join_col, "").strip()
        if not key:
            continue

        # Year filter
        if year_filter is not None:
            row_year = row.get("year", row.get("Year", "")).strip()
            if row_year != year_filter:
                continue

        raw_val = row.get(value_col, "").strip()
        if not raw_val:
            continue
        try:
            val = float(raw_val)
        except ValueError:
            logger.debug("Skipping non-numeric value for %s: %r", key, raw_val)
            continue

        if key in seen:
            logger.warning(
                "Duplicate join key %r in %s — last value (%s) wins",
                key,
                p.name,
                raw_val,
            )
        seen.add(key)
        values[key] = val

    return values


# ---------------------------------------------------------------------------
# Join + write
# ---------------------------------------------------------------------------


def _match_features(
    adm0_geojson: dict[str, Any],
    values: dict[str, float],
    adm0_join_col: str,
    value_col: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Iterate ADM0 features and split into (matched, unmatched_keys).

    Matched features carry the STABLE CONTRACT fields ``_value`` and
    ``_value_col`` in their properties. Unmatched feature keys are returned
    as a flat list so the caller can log a sample.
    """
    matched: list[dict[str, Any]] = []
    unmatched: list[str] = []
    for feature in adm0_geojson.get("features", []):
        props = feature.get("properties") or {}
        key = props.get(adm0_join_col, "")
        if key in values:
            new_props = dict(props)
            new_props["_value"] = values[key]
            new_props["_value_col"] = value_col
            matched.append(
                {
                    "type": "Feature",
                    "geometry": feature.get("geometry"),
                    "properties": new_props,
                }
            )
        else:
            unmatched.append(key)
    return matched, unmatched


def join_and_write(
    adm0_geojson: dict[str, Any],
    values: dict[str, float],
    adm0_join_col: str,
    value_col: str,
    output_path: Path | str,
) -> int:
    """Join indicator values onto ADM0 GeoJSON features and write the result.

    For each ADM0 feature, if its ``adm0_join_col`` property is in ``values``,
    add ``properties._value`` (STABLE CONTRACT) and ``properties._value_col``.
    Features without a match are DROPPED from the output (not carried through).

    Args:
        adm0_geojson: Parsed GeoJSON FeatureCollection dict.
        values: Mapping from join key → float (from :func:`load_indicator_csv`).
        adm0_join_col: Property name in ADM0 features to join on.
        value_col: Human-readable column name stored in ``_value_col``.
        output_path: Path to write the output GeoJSON.

    Returns:
        0 on success (at least one feature matched), 1 if zero features matched.
    """
    matched_features, unmatched_keys = _match_features(
        adm0_geojson, values, adm0_join_col, value_col
    )

    if unmatched_keys:
        sample = unmatched_keys[:20]
        logger.warning(
            "ADM0 features with no matching CSV value (first %d): %s",
            len(sample),
            sample,
        )

    if not matched_features:
        logger.error(
            "Zero matches produced. Check that --adm0-join-col (%s) refers "
            "to the same code space as the CSV join column.",
            adm0_join_col,
        )
        return 1

    output = {
        "type": "FeatureCollection",
        "features": matched_features,
    }
    Path(output_path).write_text(json.dumps(output, indent=2))
    logger.info("Wrote %d matched features to %s", len(matched_features), output_path)
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Join an indicator CSV to ADM0 polygons and produce a choropleth GeoJSON."
    )
    parser.add_argument("--csv", required=True, help="Path to the indicator CSV")
    parser.add_argument(
        "--adm0",
        required=True,
        help="Path to the ADM0 boundary file (.geojson, .shp, .zip)",
    )
    parser.add_argument(
        "--csv-join-col",
        required=True,
        help="Column in the CSV to join on (e.g. iso3)",
    )
    parser.add_argument(
        "--adm0-join-col",
        required=True,
        help="Property in the ADM0 GeoJSON to join on (e.g. ISO_A3)",
    )
    parser.add_argument("--value-col", required=True, help="Numeric value column name")
    parser.add_argument("--output", required=True, help="Output GeoJSON path")
    parser.add_argument("--year-filter", default=None, help="Filter CSV to this year")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level.upper(), format="%(levelname)s: %(message)s")

    adm0_geojson = shapefile_to_geojson(args.adm0)
    values = load_indicator_csv(args.csv, args.csv_join_col, args.value_col, args.year_filter)
    exit_code = join_and_write(adm0_geojson, values, args.adm0_join_col, args.value_col, args.output)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
