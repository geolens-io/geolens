"""Source compatibility validation for VRT creation.

Validates candidate COG sources by running a series of checks (CRS, dtype,
nodata, rotation, band count, grid alignment, pixel geometry) and returning
structured per-source errors. All checks always run — no fail-fast.

Called by the VRT creation and add-source endpoints.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from pydantic import BaseModel

from app.processing.raster.probe import RasterProbeError, crs_matches


class SourceValidationError(BaseModel):
    """Structured per-source validation error."""

    source_id: uuid.UUID
    code: str
    message: str
    field: str
    severity: str = "error"


def compare_crs(crs_wkts: list[str | None]) -> dict[str, bool | None]:
    """Whether each stored CRS text names the reference CRS, keyed by text.

    The reference is the first text PROJ can read. Identical text is the same
    CRS without asking PROJ; differing texts are compared in the raster probe
    child, since PROJ may open files named in them. None marks a text PROJ
    refused, or every text when the child gave no answer.
    """
    distinct = list(dict.fromkeys(wkt for wkt in crs_wkts if wkt is not None))
    if len(distinct) < 2:
        return dict.fromkeys(distinct, True)
    try:
        return dict(zip(distinct, crs_matches(distinct)))
    except RasterProbeError:
        return dict.fromkeys(distinct)


def _check_crs(
    sources: list[Any], same_crs: dict[str, bool | None]
) -> list[SourceValidationError]:
    """VAL-01: All sources must share the same CRS.

    ``same_crs`` is :func:`compare_crs` of the sources' text, so a source whose
    text PROJ refused is the one reported, whatever its position. Sources with
    crs_wkt=None are skipped.
    """
    errors: list[SourceValidationError] = []
    for src in sources:
        if src.crs_wkt is None:
            continue
        same = same_crs.get(src.crs_wkt)
        if same is None:
            errors.append(
                SourceValidationError(
                    source_id=src.id,
                    code="crs_unverified",
                    message="CRS could not be compared with the other sources",
                    field="crs_wkt",
                )
            )
        elif not same:
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
    """VAL-07: Rotated rasters are rejected.

    fix(#1385): `is_rotated` is `NOT NULL DEFAULT false`, so it cannot
    represent "never measured" — a source whose geometry probe never ran
    looks identical to one confirmed unrotated. `_check_pixel_geometry_known`
    (VAL-08) catches that case via the NULL `res_x`/`res_y` it leaves behind.
    """
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


def _check_pixel_geometry_known(sources: list[Any]) -> list[SourceValidationError]:
    """VAL-08: Pixel geometry (resolution) must have been measured.

    fix(#1385): a source with NULL `res_x` or `res_y` was never probed, so
    it cannot be proven unrotated (VAL-07) or grid-aligned (VAL-05) — both
    checks silently treat "unknown" as "passing" without this. Raise a
    distinct code instead of letting an unverifiable source through.
    """
    errors: list[SourceValidationError] = []
    for src in sources:
        if src.res_x is None or src.res_y is None:
            errors.append(
                SourceValidationError(
                    source_id=src.id,
                    code="unknown_pixel_geometry",
                    message=(
                        "Pixel resolution was never measured for this source; "
                        "cannot verify it is unrotated and grid-aligned"
                    ),
                    field="res_x" if src.res_x is None else "res_y",
                )
            )
    return errors


def _check_grid_alignment(sources: list[Any]) -> list[SourceValidationError]:
    """VAL-05: Band-stack sources must share identical grid dimensions and resolution.

    res_x/res_y compared with 1e-10 absolute tolerance; one error per
    mismatched dimension. fix(#1385): a NULL res_x/res_y skips comparison
    here, but `_check_pixel_geometry_known` (VAL-08) now raises for it
    instead of letting it pass.
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


async def validate_sources_async(
    vrt_type: str, sources: list[Any]
) -> list[SourceValidationError]:
    """:func:`validate_sources`, with the CRS comparison run in a thread."""
    same_crs = await asyncio.to_thread(compare_crs, [src.crs_wkt for src in sources])
    return validate_sources(vrt_type, sources, same_crs)


def validate_sources(
    vrt_type: str,
    sources: list[Any],
    same_crs: dict[str, bool | None],
) -> list[SourceValidationError]:
    """Validate candidate sources for VRT creation.

    Args:
        vrt_type: "mosaic" or "band_stack"
        sources: list of RasterAsset (or compatible objects) to validate
        same_crs: :func:`compare_crs` of the sources' CRS text, which may wait
            on the probe child; handlers go through :func:`validate_sources_async`

    Returns:
        list of SourceValidationError — empty list means all sources compatible.

    Notes:
        - 0 or 1 sources always returns empty (minimum-count is the
          caller's responsibility)
        - All checks run exhaustively — no fail-fast
    """
    if len(sources) < 2:
        return []

    errors: list[SourceValidationError] = []

    # Checks that apply to both vrt_types
    errors.extend(_check_crs(sources, same_crs))
    errors.extend(_check_dtype(sources))
    errors.extend(_check_nodata_consistency(sources))
    errors.extend(_check_rotation(sources))
    errors.extend(_check_pixel_geometry_known(sources))

    # Mosaic-only checks
    if vrt_type == "mosaic":
        errors.extend(_check_band_count_mosaic(sources))

    # Band-stack-only checks
    if vrt_type == "band_stack":
        errors.extend(_check_single_band_requirement(sources))
        errors.extend(_check_grid_alignment(sources))

    return errors
