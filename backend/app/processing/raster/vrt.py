"""VRT build module: gdalbuildvrt subprocess wrappers and source path resolver."""

import math
import os
import subprocess
from contextlib import ExitStack
from xml.etree.ElementTree import Element, ElementTree, SubElement

from app.core.geo import (
    LON_EPSILON_DEGREES,
    crs_has_degree_unit,
    wrap_longitude,
)

# fix(#1857): re-export. The clamps live in platform/ so
# modules/catalog/ can reach them; both import paths are credited by the
# Rule 2 gate's canonical-module map.
from app.platform.gdal_env import (  # noqa: F401
    gdal_service_safe_env,
    gdal_vector_safe_env,
)


# IA-P1-03 (Phase 1068): clamp the GDAL VSI surface — CPL_VSIL_CURL_ALLOWED_
# EXTENSIONS gates fetchable extensions; VRT_VIRTUAL_OVERVIEWS=NO blocks
# implicit overview expansion pulling in more remote sources.
#
# fix(#937): GDAL_HTTP_FOLLOWLOCATION is NOT a GDAL option and is a no-op
# (measured, GDAL 3.10.3/3.12.1) — never re-add it. Redirect safety must be
# structural: never hand a caller-controlled host to GDAL.
#
# fix(#1778): GDAL_HTTP_* clamps bound a single VSI read's stall time.
# GDAL_SUBPROCESS_TIMEOUT_SECONDS bounds only subprocesses; an unbounded
# in-process read pinned a pool thread forever, starving the worker.
_VRT_SAFE_ENV: dict[str, str] = {
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": "tif,tiff,vrt",
    "VRT_VIRTUAL_OVERVIEWS": "NO",
    "GDAL_HTTP_CONNECTTIMEOUT": "30",
    "GDAL_HTTP_TIMEOUT": "300",
    "GDAL_HTTP_MAX_RETRY": "3",
}


def gdal_safe_env(*, extras: dict[str, str] | None = None) -> dict[str, str]:
    """Return os.environ overlaid with the raster-pipeline GDAL safety clamps.

    Shared by every GDAL CLI subprocess (gdaladdo, gdalwarp, gdal_translate,
    gdalbuildvrt). CPL_VSIL_CURL_ALLOWED_EXTENSIONS defends against the
    /vsicurl/ side-channel; VRT_VIRTUAL_OVERVIEWS blocks implicit remote
    expansion. fix(#937): no redirect clamp exists as a GDAL option — never
    add one; redirect safety must be structural (validate URLs, fetch only
    managed storage).

    Args:
        extras: Optional per-call additions. Must not collide with
            ``_VRT_SAFE_ENV`` keys — raises ``ValueError`` so callers can't
            silently disable the security clamps.

    Returns:
        A new dict suitable for ``subprocess.run(..., env=...)``.

    Raises:
        ValueError: If any key in ``extras`` collides with a security clamp key.
    """
    if extras:
        overlap = set(extras) & set(_VRT_SAFE_ENV)
        if overlap:
            raise ValueError(
                f"gdal_safe_env: extras may not override security clamps: {overlap}"
            )
    env = {**os.environ, **_VRT_SAFE_ENV}
    if extras:
        env.update(extras)
    return env


def gdal_safe_open_env():
    """In-process twin of :func:`gdal_safe_env`, for ``rasterio.open`` calls.

    ``gdal_safe_env`` clamps SUBPROCESS environments only. Built from the
    same ``_VRT_SAFE_ENV`` so the two can't drift. Used by
    :func:`_write_python_vrt`, the only in-process source access in this
    module.
    """
    import rasterio

    return rasterio.Env(**_VRT_SAFE_ENV)


# fix(#430): raster GDAL CLIs run synchronously inside asyncio.to_thread, and
# Python threads aren't killable — a hung child (malformed TIFF, stalled /vsi
# read) would pin a ThreadPoolExecutor thread forever and eventually starve every
# other to_thread across the worker. A wall-clock timeout with kill-on-hang bounds
# it, mirroring the vector-ingest _communicate_with_timeout.
GDAL_SUBPROCESS_TIMEOUT_SECONDS = 3600  # 1h — large rasters legitimately take a while


def run_gdal(cmd: list[str], *, env: dict[str, str], tool: str):
    """``subprocess.run`` with a wall-clock timeout; kills a hung GDAL child.

    ``subprocess.run`` kills the child on timeout; we translate ``TimeoutExpired``
    into ``RuntimeError`` so the ingest task surfaces it as a failure.
    """
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=GDAL_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{tool} timed out after {GDAL_SUBPROCESS_TIMEOUT_SECONDS}s"
        ) from exc


# KNOWN-04 (Phase 1071): VSI prefix allow-list for internally generated
# managed-storage VRT content. User-uploaded VRTs reject all VSI paths
# (ingest/validation.py). Import this constant, don't re-declare it.
#
#   /vsiaz/ Azure, /vsicurl/ HTTPS, /vsigs/ GCS, /vsimem/ in-memory,
#   /vsis3/ AWS S3 (primary), /vsitar/ tar members, /vsizip/ zip members
VRT_VSI_ALLOWED_PREFIXES: tuple[str, ...] = (
    "/vsiaz/",
    "/vsicurl/",
    "/vsigs/",
    "/vsimem/",
    "/vsis3/",
    "/vsitar/",
    "/vsizip/",
)


# Maps VrtCreateRequest resolution_strategy values to gdalbuildvrt -resolution values.
_RES_MAP: dict[str, str] = {
    "finest": "highest",
    "coarsest": "lowest",
    "average": "average",
}

_GDAL_DTYPE_MAP = {
    "uint8": "Byte",
    "int16": "Int16",
    "uint16": "UInt16",
    "int32": "Int32",
    "uint32": "UInt32",
    "float32": "Float32",
    "float64": "Float64",
}


# fix(#887): the absolute noise floor for a DstRect value, in PIXELS. Distinct
# from LON_EPSILON_DEGREES, which is a longitude tolerance -- these are different
# units and must not share a constant just because they share a magnitude.
_PIXEL_EPSILON = 1e-9


def _offset_text(value: float) -> str:
    """Render a DstRect offset or size, keeping a fractional pixel fractional.

    fix(#887): ``gdalbuildvrt`` emits sub-pixel geometry for misaligned
    sources (``xOff="17751.5"``); rounding to whole pixels slides the
    source by up to half a pixel and changes resampling. Shared by both
    writers (codex round 7 caught them disagreeing).

    ``rel_tol=0`` is load-bearing: the default grows the tolerance with the
    offset (0.1 at 1e8 pixels, 1.0 at 1e9), silently rounding a real
    0.49-pixel offset — only the absolute noise floor may be ignored.

    Fixed-point, not ``repr``: settles at 1e-10 of a pixel, absorbing
    arithmetic noise (248.49999999999852) that ``repr`` would round-trip
    into the file.
    """
    if math.isclose(value, round(value), rel_tol=0.0, abs_tol=_PIXEL_EPSILON):
        return str(int(round(value)))
    return f"{value:.10f}".rstrip("0").rstrip(".")


def _containing_pixels(span_px: float) -> int:
    """Pixel count that CONTAINS a span — round UP, never to nearest.

    fix(#887): a mosaic ending at pixel 298.5 needs 299 pixels; 298 clips
    the last half pixel (measured: GDAL sizes its own mosaics the same way,
    298.5->299, 440.51->441). ``round`` first so float noise can't add a
    stray pixel. Shared by both writers, same reasoning as
    :func:`_offset_text`.
    """
    return max(1, math.ceil(round(span_px, 6)))


def _resolve_target_resolution(values: list[float], resolution_strategy: str) -> float:
    if resolution_strategy == "finest":
        return min(values)
    if resolution_strategy == "coarsest":
        return max(values)
    if resolution_strategy == "average":
        return sum(values) / len(values)
    raise KeyError(resolution_strategy)


# fix(#887): seam logic is degree-based throughout — EPSG:4807 (NTF Paris)
# is geographic but in GRADS (turn = 400, seam at 200), so a 360 shift
# would misplace it. Compare the CRS's own unit factor, not a name.


def _is_degree_based(crs) -> bool:
    """True only for a geographic CRS whose angular unit is degrees.

    fix(#961): the unit check is shared with :func:`core.geo.
    crs_has_degree_unit`, which takes a CRS OBJECT so this site avoids
    round-tripping through WKT.

    "Unknown" reads as False here — the opposite of the tile path's
    ``wkt_has_degree_unit(...) is not False``, which keeps the historical
    degrees assumption. Same question, opposite safe answer.

    fix(#887): the shared helper's ``rel_tol`` is correct there and wrong
    in :func:`_offset_text` — don't "fix" that one by symmetry.
    """
    if crs is None or not crs.is_geographic:
        return False
    return crs_has_degree_unit(crs) is True


def normalize_lon_span(left: float, right: float) -> tuple[float, float]:
    """Fold a span's origin into a single turn, preserving its width.

    fix(#887): :func:`_seam_frame_origin` shifts a source by exactly ONE
    turn — sound only within one turn of the others. Unnormalized, spans
    ``535..540`` / ``-180..-175`` (adjacent at the seam, 535≡175) shift to
    a 360°/720°/1080° hull instead of the true 10°, scaling with distance.

    Normalizing restores the invariant the frame chooser's proof needs
    (every source at or east of the origin after one turn); a no-op for
    any raster already inside a single turn (every real one).
    """
    folded = wrap_longitude(math.fmod(left, 360.0))
    return (folded, folded + (right - left))


def _seam_frame_origin(spans: list[tuple[float, float]]) -> float | None:
    """Pick the longitude frame origin for a seam-straddling geographic mosaic.

    fix(#887): ``min(left)``/``max(right)`` across ±180 allocated a
    near-global raster with a huge empty middle (a 10°-wide Pacific mosaic
    came out 360° wide). Re-frame so the seam falls *inside* the frame:
    every source west of the origin shifts +360.

    Returns ``None`` when the plain -180..180 fold is already tightest.

    Two guards, both required (see #883): (1) the plain hull must be wider
    than 180°; (2) the shifted hull must be narrower *by a real margin* —
    ``left + 360`` isn't bit-exact, so a global mosaic can win a bare ``<``
    on noise alone (the trap #886/#928 hit) without one.

    Candidate origins are the source left edges — exhaustive, since the
    tightest circular hull of a set of intervals always starts at one.
    """
    plain_span = max(right for _, right in spans) - min(left for left, _ in spans)
    if plain_span <= 180.0 + LON_EPSILON_DEGREES:
        return None

    best_origin: float | None = None
    best_span = plain_span
    for origin, _ in spans:
        shifted_span = (
            max(
                right + 360.0 if left < origin - LON_EPSILON_DEGREES else right
                for left, right in spans
            )
            - origin
        )
        if shifted_span < best_span - LON_EPSILON_DEGREES:
            best_origin, best_span = origin, shifted_span
    return best_origin


def _write_python_vrt(
    source_paths: list[str],
    output_path: str,
    resolution_strategy: str,
    *,
    separate: bool = False,
) -> str:
    import rasterio

    if not source_paths:
        raise ValueError("At least one source raster is required to build a VRT")

    # fix(#887): same clamp as the seam probe — this builder opens every source
    # in-process, and on a CLI-less host it is the ONLY thing that touches them,
    # so there is no clamped subprocess behind it (AGENTS.md Rule 2).
    with gdal_safe_open_env(), ExitStack() as stack:
        datasets = [stack.enter_context(rasterio.open(path)) for path in source_paths]
        first = datasets[0]
        first_crs = first.crs.to_wkt() if first.crs is not None else None

        res_x = _resolve_target_resolution(
            [abs(ds.transform.a) for ds in datasets], resolution_strategy
        )
        res_y = _resolve_target_resolution(
            [abs(ds.transform.e) for ds in datasets], resolution_strategy
        )

        # fix(#887): only a degree-based geographic CRS wraps at ±180 — a
        # projected CRS's numbers are metres (a +360 shift would move a
        # source 360m), and a grads CRS turns at 400, not 360.
        raw_spans = [(ds.bounds.left, ds.bounds.right) for ds in datasets]
        # fix(#887): normalized into a single turn for the seam decision, because
        # the frame chooser shifts by exactly one (see normalize_lon_span).
        normalized_spans = [
            normalize_lon_span(left, right) for left, right in raw_spans
        ]
        seam_origin = (
            _seam_frame_origin(normalized_spans)
            if all(_is_degree_based(ds.crs) for ds in datasets)
            else None
        )
        # Only a mosaic actually being re-framed adopts the normalized
        # longitudes; every other build keeps the coordinates its sources carry.
        spans = normalized_spans if seam_origin is not None else raw_spans
        lon_offsets = [
            360.0
            if seam_origin is not None and left < seam_origin - LON_EPSILON_DEGREES
            else 0.0
            for left, _ in spans
        ]
        placed = [
            (left + offset, right + offset)
            for (left, right), offset in zip(spans, lon_offsets, strict=True)
        ]
        shifted = list(zip(datasets, [left for left, _ in placed], strict=True))

        left = min(left for left, _ in placed)
        right = max(right for _, right in placed)
        bottom = min(ds.bounds.bottom for ds in datasets)
        top = max(ds.bounds.top for ds in datasets)
        # fix(#887): same containment rule as the gdalbuildvrt rewrite. Rounding
        # to nearest sized a 298.5-pixel hull at 298 and clipped the edge.
        width = _containing_pixels((right - left) / res_x)
        height = _containing_pixels((top - bottom) / res_y)

        root = Element("VRTDataset", rasterXSize=str(width), rasterYSize=str(height))
        if first_crs is not None:
            SubElement(root, "SRS").text = first_crs
        SubElement(
            root, "GeoTransform"
        ).text = f"{left}, {res_x}, 0.0, {top}, 0.0, {-res_y}"

        def add_simple_source(
            parent: Element,
            dataset,
            *,
            band_index: int,
            placed_left: float,
        ) -> None:
            source = SubElement(parent, "SimpleSource")
            # STOR-03 (Phase 1210): writes logical key + relativeToVRT="1"
            # so the stored XML is provider-agnostic; rewrite_vrt_sources
            # (tasks_vrt.py) is the enforcement gate that normalises it.
            SubElement(source, "SourceFilename", relativeToVRT="1").text = dataset.name
            SubElement(source, "SourceBand").text = str(band_index)
            block_height, block_width = dataset.block_shapes[band_index - 1]
            SubElement(
                source,
                "SourceProperties",
                RasterXSize=str(dataset.width),
                RasterYSize=str(dataset.height),
                DataType=_GDAL_DTYPE_MAP.get(
                    dataset.dtypes[band_index - 1], dataset.dtypes[band_index - 1]
                ),
                BlockXSize=str(block_width),
                BlockYSize=str(block_height),
            )
            SubElement(
                source,
                "SrcRect",
                xOff="0",
                yOff="0",
                xSize=str(dataset.width),
                ySize=str(dataset.height),
            )
            # fix(#887): destination geometry stays fractional (via
            # _offset_text) — integer rounding put xOff 248.5 at 248,
            # sliding the source half a pixel and changing its resampling.
            dst_width = dataset.width * abs(dataset.transform.a) / res_x
            dst_height = dataset.height * abs(dataset.transform.e) / res_y
            # `placed_left` is in the SAME frame as `left` (normalized,
            # then shifted). Mixing frames here put a seam-straddling
            # source half a world from its own pixels.
            dst_x_off = (placed_left - left) / res_x
            dst_y_off = (top - dataset.bounds.top) / res_y
            SubElement(
                source,
                "DstRect",
                xOff=_offset_text(dst_x_off),
                yOff=_offset_text(dst_y_off),
                xSize=_offset_text(dst_width),
                ySize=_offset_text(dst_height),
            )

        if separate:
            band_number = 1
            for dataset, placed_left in shifted:
                for source_band in range(1, dataset.count + 1):
                    band = SubElement(
                        root,
                        "VRTRasterBand",
                        dataType=_GDAL_DTYPE_MAP.get(
                            dataset.dtypes[source_band - 1],
                            dataset.dtypes[source_band - 1],
                        ),
                        band=str(band_number),
                    )
                    add_simple_source(
                        band,
                        dataset,
                        band_index=source_band,
                        placed_left=placed_left,
                    )
                    band_number += 1
        else:
            band_count = first.count
            for dataset in datasets[1:]:
                if dataset.count != band_count:
                    raise ValueError(
                        "All mosaic sources must have the same number of bands"
                    )
            for band_number in range(1, band_count + 1):
                band = SubElement(
                    root,
                    "VRTRasterBand",
                    dataType=_GDAL_DTYPE_MAP.get(
                        first.dtypes[band_number - 1], first.dtypes[band_number - 1]
                    ),
                    band=str(band_number),
                )
                for dataset, placed_left in shifted:
                    add_simple_source(
                        band,
                        dataset,
                        band_index=band_number,
                        placed_left=placed_left,
                    )

        ElementTree(root).write(output_path, encoding="utf-8", xml_declaration=True)
        return output_path


def resolve_vrt_source_path(asset_uri: str, *, tenant_id: str | None = None) -> str:
    """Delegate to the storage seam's resolve_open_path (STOR-01 / Phase 1210).

    Kept for backward compatibility with existing callers; new callers
    should import resolve_open_path from app.platform.storage.titiler_url
    directly.

    tenant_id: when provided (multi_tenant), prepend tenants/{tenant_id}/ to
        the object key. Always None in single_tenant; the returned path is
        byte-identical to the pre-1210 inline code.
    """
    from app.platform.storage.titiler_url import resolve_open_path

    return resolve_open_path(asset_uri, tenant_id=tenant_id)


def shift_vrt_longitude_frame(vrt_path: str) -> None:
    """Re-anchor a built VRT's longitude frame so the seam falls inside it.

    fix(#887): ``gdalbuildvrt`` gets everything right except the geometry;
    correcting via XML rewrite (not rebuilding with
    :func:`_write_python_vrt`) preserves ``NoDataValue``/``ColorInterp``/
    mask bands — without the ``<NODATA>`` inside a ``ComplexSource``, an
    overlapping source's fill pixels overwrite valid ones (measured: an
    overlap that should read 7 read 0).

    Rewrites exactly three things — ``rasterXSize``, the ``GeoTransform``
    origin, and every ``DstRect`` ``xOff`` (including inside a
    ``<MaskBand>``). A non-crossing build stays byte-identical.

    Each source's left edge is recoverable from its own ``xOff``
    (``old_left + xOff * res_x``), so this needs no second source pass.

    It DECIDES, from the XML alone, opening nothing (fix(#887), codex
    round 9) — the previous version probed every source with
    ``rasterio.open``, and a stalled object-storage read pinned a pool
    thread forever (Python threads aren't killable; no ``run_gdal``
    timeout applied to the probe).

    fix(#1778): the hazard isn't gone from the pipeline — later steps open
    every ``/vsis3`` source in-thread for metadata + quicklook, bounded by
    the ``GDAL_HTTP_*`` clamps via :func:`gdal_safe_open_env` INSIDE the
    worker thread (a rasterio ``Env`` is thread-local).

    Returns without writing when the VRT isn't a degree-based geographic
    mosaic, doesn't straddle the seam, or lacks the geometry this needs —
    that last case can't hide a real crossing, since detecting one needs
    the same values the rewrite consumes. Verified against GDAL 3.10.3 and
    3.13.0.
    """
    from xml.etree.ElementTree import parse

    from rasterio.crs import CRS

    try:
        tree = parse(vrt_path)
    except Exception:  # broad: a post-build correction must never turn a build gdalbuildvrt reported as successful into a crash — an unreadable or absent output is that subprocess's business, not this function's
        return
    root = tree.getroot()

    gt_node = root.find("GeoTransform")
    if gt_node is None or not gt_node.text:
        return
    geotransform = [float(v) for v in gt_node.text.split(",")]
    if len(geotransform) != 6:
        return
    old_left, res_x = geotransform[0], geotransform[1]
    if res_x <= 0.0:
        return
    # fix(#887): a rotated GeoTransform makes gt[0] not a pure longitude
    # origin — translating it would shear the mosaic. Decline rather than
    # assume, even though gdalbuildvrt never emits rotation terms.
    if geotransform[2] or geotransform[4]:
        return

    # Parsing the SRS text is pure string work -- CRS.from_wkt does no I/O -- so
    # the degree-based gate costs nothing and still rejects grads (EPSG:4807,
    # which turns at 400) and every projected CRS.
    srs_node = root.find("SRS")
    if srs_node is None or not srs_node.text:
        return
    try:
        crs = CRS.from_wkt(srs_node.text)
    except Exception:  # broad: an SRS PROJ cannot parse is one we must not re-frame
        return
    if not _is_degree_based(crs):
        return

    sources = [
        el
        for el in root.iter()
        if el.tag in ("SimpleSource", "ComplexSource", "AveragedSource")
    ]
    rects = [el.find("DstRect") for el in sources]
    if not sources or any(rect is None for rect in rects):
        return

    # A source's longitude span is recoverable from GDAL's own offset, so
    # no second pass or filename matching is needed. Duplicate spans (one
    # DstRect per band, plus mask) are harmless — same hull either way.
    #
    # fix(#887): normalized into a single turn first (see
    # normalize_lon_span). Placement is pixel-space, so re-expressing a
    # source's longitude changes where the mosaic sits, never its pixels.
    reconstructed = []
    for rect in rects:
        raw_left = old_left + float(rect.get("xOff", "0")) * res_x
        x_size = float(rect.get("xSize", "0"))
        left, _ = normalize_lon_span(raw_left, raw_left)
        reconstructed.append((rect, left, x_size))

    seam_origin = _seam_frame_origin(
        [(left, left + size * res_x) for _, left, size in reconstructed]
    )
    if seam_origin is None:
        return

    placements = []
    for rect, src_left, x_size in reconstructed:
        # fix(#887): DEFENSIVE — codex round 6 found this comparison
        # shifting the origin source via two derivations of one edge
        # disagreeing by ~1e-14 (mosaic stayed 17998px instead of 300);
        # epsilon stays in case a second derivation returns.
        shift = 360.0 if src_left < seam_origin - LON_EPSILON_DEGREES else 0.0
        placements.append((rect, src_left + shift, x_size))

    new_left = min(left for _, left, _ in placements)
    offsets = [((left - new_left) / res_x, size) for _, left, size in placements]

    # The raster must CONTAIN every source -- see _containing_pixels, shared with
    # the fallback writer so the two cannot disagree about this rule.
    span_px = max(offset + size for offset, size in offsets)
    root.set("rasterXSize", str(_containing_pixels(span_px)))
    geotransform[0] = new_left
    gt_node.text = ", ".join(repr(v) for v in geotransform)
    for (rect, _, _), (offset, _) in zip(placements, offsets, strict=True):
        rect.set("xOff", _offset_text(offset))

    tree.write(vrt_path, encoding="utf-8", xml_declaration=True)


def _build_vrt(
    source_paths: list[str],
    output_path: str,
    resolution_strategy: str,
    *,
    separate: bool = False,
) -> str:
    """Core VRT builder wrapping gdalbuildvrt.

    Args:
        source_paths: Absolute filesystem or GDAL VSI paths to source COG files.
        output_path: Destination .vrt file path (must be writable).
        resolution_strategy: One of "finest", "coarsest", or "average".
        separate: If True, pass ``-separate`` to produce a band-stack VRT.

    Raises:
        RuntimeError: If gdalbuildvrt exits with a non-zero return code.
        KeyError: If an unrecognised resolution_strategy is supplied.
    """
    gdal_res = _RES_MAP[resolution_strategy]
    cmd = ["gdalbuildvrt"]
    if separate:
        cmd.append("-separate")
    cmd.extend(["-resolution", gdal_res, output_path, *source_paths])
    try:
        result = run_gdal(cmd, env=gdal_safe_env(), tool="gdalbuildvrt")
    except FileNotFoundError:
        return _write_python_vrt(
            source_paths,
            output_path,
            resolution_strategy,
            separate=separate,
        )
    if result.returncode != 0:
        raise RuntimeError(f"gdalbuildvrt failed: {result.stderr}")
    # fix(#887): corrects the antimeridian frame AFTER the build, from the
    # XML gdalbuildvrt wrote — opens nothing, no-ops unless sources
    # straddle ±180.
    shift_vrt_longitude_frame(output_path)
    return output_path


def build_vrt(
    vrt_type: str,
    source_paths: list[str],
    output_path: str,
    resolution_strategy: str,
) -> str:
    """Build a VRT file. Dispatches to mosaic or band-stack based on vrt_type."""
    return _build_vrt(
        source_paths,
        output_path,
        resolution_strategy,
        separate=(vrt_type == "band_stack"),
    )
