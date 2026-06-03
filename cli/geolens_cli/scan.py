# SPDX-License-Identifier: Apache-2.0
"""Filesystem scan + format detection — pure local I/O, no HTTP.

Hand-maintained — NOT regenerated. Detection is extension-only per
CONTEXT.md D-15; the server re-validates content via puremagic on upload,
so client-side spoofing is not a security concern. This module makes ZERO
HTTP calls and therefore inherits OCCLI-06 trivially.

Allowlist is a subset of backend/app/processing/ingest/validation.py
(the canonical EXTENSION_CONTENT_MAP). The server-side allowlist also
includes .csv (with text-content fallback), .xls, .xlsx, and .zip; the
CLI MVP intentionally excludes those per D-15:
- .csv: brittle without --csv flag (deferred lat/lon column detection)
- .xls/.xlsx: not geospatial primaries
- .zip: shapefile bundles handled via sidecar grouping on extracted .shp
If a future server release adds new vector/raster primaries, mirror them
here as well.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

VECTOR_EXTS = {".geojson", ".gpkg", ".shp"}
RASTER_EXTS = {".tif", ".tiff"}
SHAPEFILE_REQUIRED_SIDECARS = {".dbf", ".shx"}
# .prj is recommended-but-optional per gdal/ogr semantics — its absence
# does not block ingest (the server defaults to EPSG:4326 if missing) but
# is reported to the user via the sidecar_files list.
SHAPEFILE_OPTIONAL_SIDECARS = {".prj", ".cpg", ".qix", ".sbn", ".sbx"}
RASTER_OPTIONAL_SIDECARS = {".aux.xml", ".ovr", ".tfw"}
HIDDEN_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "node_modules",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".ruff_cache",
}


@dataclass
class ScanItem:
    """One row in the scan report — one dataset (shapefiles grouped)."""

    path: Path
    format: str
    ingest: bool
    reason: str = ""
    sidecar_files: Optional[list[Path]] = None

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "format": self.format,
            "ingest": self.ingest,
            "reason": self.reason,
            "sidecar_files": [str(p) for p in (self.sidecar_files or [])],
        }


def walk(
    root: Path,
    *,
    max_depth: Optional[int] = None,
    include_exts: Optional[set[str]] = None,
) -> Iterator[ScanItem]:
    """Yield one ScanItem per dataset (shapefiles grouped by .shp parent).

    Args:
        root: directory to walk (must be a directory).
        max_depth: cap recursion at this many levels below root (None = unlimited).
            ``max_depth=0`` scans only the top-level directory (no recursion).
        include_exts: if provided, only emit ScanItems for files whose extension
            is in this set. Sidecar files are still grouped, just not emitted as
            their own rows. Exts must include the leading dot.

    Yields ScanItems in deterministic (sorted-by-path) order for testability.
    Symlink loops are detected via canonical-path visited-set and do not
    cause infinite recursion.
    """
    visited: set[Path] = set()
    yield from _sorted_iter(_walk(root, root, visited, max_depth, include_exts))


def _sorted_iter(items: Iterator[ScanItem]) -> Iterator[ScanItem]:
    """Sort ScanItems by path for deterministic output."""
    return iter(sorted(items, key=lambda s: str(s.path)))


def _walk(
    root: Path,
    current: Path,
    visited: set[Path],
    max_depth: Optional[int],
    include_exts: Optional[set[str]],
) -> Iterator[ScanItem]:
    try:
        canon = current.resolve()
    except OSError:
        return
    if canon in visited:
        return
    visited.add(canon)
    if not current.is_dir():
        return
    if max_depth is not None:
        try:
            rel_parts = current.relative_to(root).parts
        except ValueError:
            rel_parts = ()
        if len(rel_parts) > max_depth:
            return

    try:
        children = sorted(current.iterdir())
    except (PermissionError, OSError):
        return

    files_by_stem: dict[Path, dict[str, Path]] = {}
    for child in children:
        if child.is_dir():
            if child.name in HIDDEN_DIRS or child.name.startswith("."):
                continue
            yield from _walk(root, child, visited, max_depth, include_exts)
            continue
        if child.name.startswith("."):
            continue
        ext = child.suffix.lower()
        stem_path = child.with_suffix("")
        files_by_stem.setdefault(stem_path, {})[ext] = child

    for _stem, exts in files_by_stem.items():
        yield from _classify_group(exts, include_exts)


def _classify_group(
    exts: dict[str, Path],
    include_exts: Optional[set[str]],
) -> Iterator[ScanItem]:
    # Shapefile grouping (D-18): one row for .shp, sidecars listed
    if ".shp" in exts:
        shp = exts[".shp"]
        siblings = [p for ext, p in exts.items() if ext != ".shp"]
        missing = SHAPEFILE_REQUIRED_SIDECARS - set(exts.keys())
        if include_exts is not None and ".shp" not in include_exts:
            return
        if missing:
            yield ScanItem(
                path=shp,
                format="shapefile",
                ingest=False,
                reason=f"missing required sidecar(s): {', '.join(sorted(missing))}",
                sidecar_files=siblings,
            )
        else:
            yield ScanItem(
                path=shp,
                format="shapefile",
                ingest=True,
                sidecar_files=siblings,
            )
        return

    for ext, path in exts.items():
        if include_exts is not None and ext not in include_exts:
            continue
        if ext == ".geojson":
            yield ScanItem(path=path, format="geojson", ingest=True)
        elif ext == ".gpkg":
            yield ScanItem(path=path, format="geopackage", ingest=True)
        elif ext in RASTER_EXTS:
            yield ScanItem(path=path, format="cog-candidate", ingest=True)
        elif ext == ".json":
            if _looks_like_geojson(path):
                yield ScanItem(path=path, format="geojson", ingest=True)
            else:
                yield ScanItem(
                    path=path,
                    format="unsupported",
                    ingest=False,
                    reason="json file but not GeoJSON",
                )
        elif ext in SHAPEFILE_OPTIONAL_SIDECARS or ext in SHAPEFILE_REQUIRED_SIDECARS:
            # Only ever yielded grouped under .shp — silently skip orphans.
            continue
        elif ext in RASTER_OPTIONAL_SIDECARS:
            continue
        else:
            yield ScanItem(
                path=path,
                format="unsupported",
                ingest=False,
                reason=f"unknown extension {ext}",
            )


def _looks_like_geojson(path: Path, *, peek_bytes: int = 1024) -> bool:
    """Peek-read up to ``peek_bytes`` bytes to disambiguate GeoJSON from generic JSON."""
    try:
        head = path.read_bytes()[:peek_bytes].lstrip()
        return head.startswith(b"{") and (b'"type"' in head[:200])
    except OSError:
        return False
