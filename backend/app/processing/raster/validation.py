"""Source compatibility validation for VRT creation.

Validates candidate COG sources for VRT creation by running a series of
checks (CRS, dtype, nodata, rotation, band count, grid alignment) and
returning structured per-source errors.  All checks always run — no fail-fast.

Usage::

    from app.processing.raster.validation import validate_sources, SourceValidationError

    errors = validate_sources("mosaic", list_of_raster_assets)
    if errors:
        raise SomeHTTPException(errors)

Called by:
- Phase 173: VRT creation endpoint
- Phase 174: add-source endpoint
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel

try:
    import rasterio
except ImportError:  # pragma: no cover
    rasterio = None  # type: ignore[assignment]


class SourceValidationError(BaseModel):
    """Structured per-source validation error."""

    source_id: uuid.UUID
    code: str
    message: str
    field: str
    severity: str = "error"


# ---------------------------------------------------------------------------
# Private helpers — each returns list[SourceValidationError]
# ---------------------------------------------------------------------------


def _check_crs(sources: list[Any]) -> list[SourceValidationError]:
    """VAL-01: All sources must share the same CRS.

    Reference = first source with a non-None crs_wkt.
    Sources with crs_wkt=None are skipped.
    """
    errors: list[SourceValidationError] = []

    # Find reference source (first with a known CRS)
    ref_crs = None
    for src in sources:
        if src.crs_wkt is not None:
            ref_crs = rasterio.CRS.from_wkt(src.crs_wkt)
            break

    if ref_crs is None:
        return errors  # nothing to compare

    for src in sources[1:]:
        if src.crs_wkt is None:
            continue
        src_crs = rasterio.CRS.from_wkt(src.crs_wkt)
        if not ref_crs.equals(src_crs):
            errors.append(
                SourceValidationError(
                    source_id=src.id,
                    code="crs_mismatch",
                    message="CRS does not match reference source",
                    field="crs_wkt",
                )
            )

    return errors


def _check_band_count_mosaic(sources: list[Any]) -> list[SourceValidationError]:
    """VAL-02: All mosaic sources must share the same band count."""
    errors: list[SourceValidationError] = []
    ref = sources[0].band_count
    for src in sources[1:]:
        if src.band_count != ref:
            errors.append(
                SourceValidationError(
                    source_id=src.id,
                    code="band_count_mismatch",
                    message=f"Band count {src.band_count} does not match reference {ref}",
                    field="band_count",
                )
            )
    return errors


def _check_single_band_requirement(sources: list[Any]) -> list[SourceValidationError]:
    """VAL-03: Each band-stack source must have exactly 1 band."""
    errors: list[SourceValidationError] = []
    for src in sources:
        if src.band_count != 1:
            errors.append(
                SourceValidationError(
                    source_id=src.id,
                    code="single_band_required",
                    message=f"Band stack requires single-band sources; got {src.band_count}",
                    field="band_count",
                )
            )
    return errors


def _check_dtype(sources: list[Any]) -> list[SourceValidationError]:
    """VAL-04: All sources must share the same dtype."""
    errors: list[SourceValidationError] = []
    ref = sources[0].dtype
    for src in sources[1:]:
        if src.dtype != ref:
            errors.append(
                SourceValidationError(
                    source_id=src.id,
                    code="dtype_mismatch",
                    message=f"dtype '{src.dtype}' does not match reference '{ref}'",
                    field="dtype",
                )
            )
    return errors


def _check_nodata_consistency(sources: list[Any]) -> list[SourceValidationError]:
    """VAL-06: Either all sources define nodata or none do."""
    errors: list[SourceValidationError] = []
    ref_has_nodata = sources[0].nodata is not None
    for src in sources[1:]:
        src_has_nodata = src.nodata is not None
        if src_has_nodata != ref_has_nodata:
            errors.append(
                SourceValidationError(
                    source_id=src.id,
                    code="nodata_inconsistent",
                    message="Nodata presence does not match reference source",
                    field="nodata",
                )
            )
    return errors


def _check_rotation(sources: list[Any]) -> list[SourceValidationError]:
    """VAL-07: Rotated rasters are rejected."""
    errors: list[SourceValidationError] = []
    for src in sources:
        if src.is_rotated:
            errors.append(
                SourceValidationError(
                    source_id=src.id,
                    code="rotated_raster",
                    message="Rotated rasters cannot be used as VRT sources",
                    field="is_rotated",
                )
            )
    return errors


def _check_grid_alignment(sources: list[Any]) -> list[SourceValidationError]:
    """VAL-05: Band-stack sources must share identical grid dimensions and resolution.

    Float comparison for res_x/res_y uses 1e-10 absolute tolerance.
    Returns one error per mismatched dimension per source.
    """
    _FLOAT_TOL = 1e-10
    errors: list[SourceValidationError] = []
    ref = sources[0]

    for src in sources[1:]:
        if src.width != ref.width:
            errors.append(
                SourceValidationError(
                    source_id=src.id,
                    code="grid_misaligned",
                    message=f"width {src.width} != reference {ref.width}",
                    field="width",
                )
            )
        if src.height != ref.height:
            errors.append(
                SourceValidationError(
                    source_id=src.id,
                    code="grid_misaligned",
                    message=f"height {src.height} != reference {ref.height}",
                    field="height",
                )
            )
        if src.res_x is not None and ref.res_x is not None:
            if abs(src.res_x - ref.res_x) > _FLOAT_TOL:
                errors.append(
                    SourceValidationError(
                        source_id=src.id,
                        code="grid_misaligned",
                        message=f"res_x {src.res_x} != reference {ref.res_x}",
                        field="res_x",
                    )
                )
        if src.res_y is not None and ref.res_y is not None:
            if abs(src.res_y - ref.res_y) > _FLOAT_TOL:
                errors.append(
                    SourceValidationError(
                        source_id=src.id,
                        code="grid_misaligned",
                        message=f"res_y {src.res_y} != reference {ref.res_y}",
                        field="res_y",
                    )
                )

    return errors


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_sources(vrt_type: str, sources: list[Any]) -> list[SourceValidationError]:
    """Validate candidate sources for VRT creation.

    Args:
        vrt_type: "mosaic" or "band_stack"
        sources: list of RasterAsset (or compatible objects) to validate

    Returns:
        list of SourceValidationError — empty list means all sources compatible.

    Notes:
        - 0 or 1 sources: always returns empty list (minimum-count enforcement
          is the responsibility of the caller, not the validator)
        - All checks run exhaustively — no fail-fast
        - CRS comparison uses rasterio.CRS equality; requires rasterio installed
    """
    if len(sources) < 2:
        return []

    errors: list[SourceValidationError] = []

    # Checks that apply to both vrt_types
    errors.extend(_check_crs(sources))
    errors.extend(_check_dtype(sources))
    errors.extend(_check_nodata_consistency(sources))
    errors.extend(_check_rotation(sources))

    # Mosaic-only checks
    if vrt_type == "mosaic":
        errors.extend(_check_band_count_mosaic(sources))

    # Band-stack-only checks
    if vrt_type == "band_stack":
        errors.extend(_check_single_band_requirement(sources))
        errors.extend(_check_grid_alignment(sources))

    return errors
