"""VRT build module: gdalbuildvrt subprocess wrappers and source path resolver."""

import logging
import math
import os
import posixpath
import shutil
import subprocess

from app.core.geo import LON_EPSILON_DEGREES, wrap_longitude

# Re-exported. The clamps live in platform/ so modules/catalog/ can reach them;
# both import paths are credited by the Rule 2 gate's canonical-module map.
from app.platform.gdal_env import (  # noqa: F401
    gdal_service_safe_env,
    gdal_vector_safe_env,
)

logger = logging.getLogger(__name__)


# Clamp the GDAL VSI surface: CPL_VSIL_CURL_ALLOWED_EXTENSIONS gates fetchable
# extensions; VRT_VIRTUAL_OVERVIEWS=NO blocks implicit overview expansion
# pulling in more remote sources.
#
# GDAL_HTTP_FOLLOWLOCATION is not a GDAL option and is a no-op (measured, GDAL
# 3.10.3/3.12.1); never add it. Redirect safety must be structural: never hand
# a caller-controlled host to GDAL.
#
# GDAL_HTTP_* clamps bound a single VSI read's stall time.
# GDAL_SUBPROCESS_TIMEOUT_SECONDS bounds only subprocesses, so an in-process
# read needs its own bound or it pins a pool thread forever and starves the
# worker.
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
    expansion. No redirect clamp exists as a GDAL option; redirect safety must
    be structural (validate URLs, fetch only managed storage).

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

    ``gdal_safe_env`` clamps subprocess environments only. Built from the
    same ``_VRT_SAFE_ENV`` so the two can't drift. The raster probe child
    enters it around every read.
    """
    import rasterio

    return rasterio.Env(**_VRT_SAFE_ENV)


# Raster GDAL CLIs run synchronously inside asyncio.to_thread, and Python
# threads aren't killable: a hung child (malformed TIFF, stalled /vsi read)
# would pin a ThreadPoolExecutor thread forever and eventually starve every
# other to_thread across the worker. A wall-clock timeout with kill-on-hang
# bounds it, like the vector-ingest _communicate_with_timeout.
GDAL_SUBPROCESS_TIMEOUT_SECONDS = 3600  # 1h: large rasters legitimately take a while


def run_gdal(cmd: list[str], *, env: dict[str, str], tool: str):
    """``subprocess.run`` with a wall-clock timeout; kills a hung GDAL child.

    ``subprocess.run`` kills the child on timeout; ``TimeoutExpired`` becomes
    ``RuntimeError`` so the ingest task surfaces it as a failure.
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


# VSI prefix allow-list for internally generated managed-storage VRT content.
# User-uploaded VRTs reject all VSI paths (ingest/validation.py).
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

# The absolute noise floor for a DstRect value, in pixels. Distinct from
# LON_EPSILON_DEGREES, a longitude tolerance: different units, so no shared
# constant.
_PIXEL_EPSILON = 1e-9


def _offset_text(value: float) -> str:
    """Render a DstRect offset or size, keeping a fractional pixel fractional.

    ``gdalbuildvrt`` emits sub-pixel geometry for misaligned sources
    (``xOff="17751.5"``); rounding to whole pixels slides the source by up to
    half a pixel and changes resampling.

    ``rel_tol=0`` is load-bearing: the default grows the tolerance with the
    offset (0.1 at 1e8 pixels, 1.0 at 1e9), rounding away a real 0.49-pixel
    offset. Only the absolute noise floor may be ignored.

    Fixed-point, not ``repr``: it settles at 1e-10 of a pixel, absorbing
    arithmetic noise (248.49999999999852) that ``repr`` would write into the
    file.
    """
    if math.isclose(value, round(value), rel_tol=0.0, abs_tol=_PIXEL_EPSILON):
        return str(int(round(value)))
    return f"{value:.10f}".rstrip("0").rstrip(".")


def _containing_pixels(span_px: float) -> int:
    """Pixel count that contains a span: round up, never to nearest.

    A mosaic ending at pixel 298.5 needs 299 pixels; 298 clips the last half
    pixel (GDAL sizes its own mosaics the same way). ``round`` first so float
    noise can't add a stray pixel.
    """
    return max(1, math.ceil(round(span_px, 6)))


# Seam logic is degree-based throughout: EPSG:4807 (NTF Paris) is geographic
# but in grads (turn = 400, seam at 200), so a 360 shift would misplace it.
# The CRS's own unit factor is compared, not a name.


def _is_degree_based(facts: dict) -> bool:
    """True only for a geographic CRS whose angular unit is degrees.

    ``facts`` is :func:`app.processing.raster.probe.crs_facts`'s answer, whose
    unit check is :func:`core.geo.crs_has_degree_unit`.

    "Unknown" reads as False here, the opposite of the tile path's
    ``crs_has_degree_unit is not False``, which keeps the historical degrees
    assumption: same question, opposite safe answer.

    The shared helper's ``rel_tol`` is correct there and wrong in
    :func:`_offset_text`.
    """
    return facts["crs_is_geographic"] is True and facts["crs_has_degree_unit"] is True


def normalize_lon_span(left: float, right: float) -> tuple[float, float]:
    """Fold a span's origin into a single turn, preserving its width.

    :func:`_seam_frame_origin` shifts a source by exactly one turn, which is
    sound only within one turn of the others. Unnormalized, spans
    ``535..540`` / ``-180..-175`` (adjacent at the seam, 535≡175) shift to a
    360°/720°/1080° hull instead of the true 10°.

    Normalizing restores the invariant the frame chooser's proof needs (every
    source at or east of the origin after one turn); it is a no-op for any
    raster already inside a single turn.
    """
    folded = wrap_longitude(math.fmod(left, 360.0))
    return (folded, folded + (right - left))


def _seam_frame_origin(spans: list[tuple[float, float]]) -> float | None:
    """Pick the longitude frame origin for a seam-straddling geographic mosaic.

    ``min(left)``/``max(right)`` across ±180 would allocate a near-global
    raster with a huge empty middle (a 10°-wide Pacific mosaic came out 360°
    wide). Re-frame so the seam falls *inside* the frame: every source west of
    the origin shifts +360.

    Returns ``None`` when the plain -180..180 fold is already tightest.

    Two guards, both required: (1) the plain hull must be wider than 180°;
    (2) the shifted hull must be narrower *by a real margin*, because
    ``left + 360`` isn't bit-exact and a global mosaic could otherwise win a
    bare ``<`` on noise alone.

    Candidate origins are the source left edges, which is exhaustive since the
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


def resolve_vrt_source_path(asset_uri: str, *, tenant_id: str | None = None) -> str:
    """The storage path a VRT names for one member, via ``resolve_open_path``.

    tenant_id: when provided (multi_tenant), prepend tenants/{tenant_id}/ to
        the object key. Always None in single_tenant.

    Raises ValueError for a remote member: the VRT file would name its URL,
    and every later read of the VRT would fetch it without the relay.
    """
    from app.platform.storage.titiler_url import (
        RemoteRasterPathError,
        resolve_open_path,
    )

    try:
        return resolve_open_path(asset_uri, tenant_id=tenant_id)
    except RemoteRasterPathError:
        raise ValueError(
            "A remote (by-reference) raster can't be a VRT member; rebuild the "
            "VRT without it or import a copy of the raster"
        ) from None


def shift_vrt_longitude_frame(vrt_path: str) -> None:
    """Re-anchor a built VRT's longitude frame so the seam falls inside it.

    ``gdalbuildvrt`` gets everything right except the geometry; correcting
    via XML rewrite (not rebuilding the VRT by hand) preserves
    ``NoDataValue``/``ColorInterp``/mask bands. Without the ``<NODATA>`` inside
    a ``ComplexSource``, an overlapping source's fill pixels overwrite valid
    ones.

    Rewrites exactly three things: ``rasterXSize``, the ``GeoTransform``
    origin, and every ``DstRect`` ``xOff`` (including inside a
    ``<MaskBand>``). A non-crossing build stays byte-identical.

    Each source's left edge is recoverable from its own ``xOff``
    (``old_left + xOff * res_x``), so this needs no second source pass.

    It decides from the XML alone and opens no source. The one question it
    can't answer from the XML, whether the SRS is in degrees, goes to the
    probe child, since PROJ may open files while parsing a CRS. A probe that
    fails raises ``RasterProbeError``, failing the build, because the frame
    it would have checked may be wrong.

    Returns without writing when the VRT isn't a degree-based geographic
    mosaic, doesn't straddle the seam, or lacks the geometry this needs —
    that last case can't hide a real crossing, since detecting one needs
    the same values the rewrite consumes. Verified against GDAL 3.10.3 and
    3.13.0.
    """
    from xml.etree.ElementTree import parse

    from app.processing.raster.probe import crs_facts

    try:
        tree = parse(vrt_path)
    except Exception:  # broad: a post-build correction must not crash a build gdalbuildvrt reported as successful
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
    # A rotated GeoTransform makes gt[0] not a pure longitude origin, and
    # translating it would shear the mosaic. Decline rather than assume, even
    # though gdalbuildvrt never emits rotation terms.
    if geotransform[2] or geotransform[4]:
        return

    # The degree-based gate rejects grads (EPSG:4807, which turns at 400) and
    # every projected CRS.
    srs_node = root.find("SRS")
    if srs_node is None or not srs_node.text:
        return
    if not _is_degree_based(crs_facts(srs_node.text)):
        return

    sources = [
        el
        for el in root.iter()
        if el.tag in ("SimpleSource", "ComplexSource", "AveragedSource")
    ]
    rects = [el.find("DstRect") for el in sources]
    if not sources or any(rect is None for rect in rects):
        return

    # A source's longitude span is recoverable from GDAL's own offset, so no
    # second pass or filename matching is needed. Duplicate spans (one DstRect
    # per band, plus mask) give the same hull. Normalized into a single turn
    # first (see normalize_lon_span): placement is pixel-space, so
    # re-expressing a source's longitude changes where the mosaic sits, never
    # its pixels.
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
        # The epsilon guards against two derivations of one edge disagreeing
        # by ~1e-14 and shifting the origin source.
        shift = 360.0 if src_left < seam_origin - LON_EPSILON_DEGREES else 0.0
        placements.append((rect, src_left + shift, x_size))

    new_left = min(left for _, left, _ in placements)
    offsets = [((left - new_left) / res_x, size) for _, left, size in placements]

    # The raster must contain every source; _containing_pixels is shared with
    # the fallback writer so the two agree on this rule.
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
    result = run_gdal(cmd, env=gdal_safe_env(), tool="gdalbuildvrt")
    if result.returncode != 0:
        raise RuntimeError(f"gdalbuildvrt failed: {result.stderr}")
    # Corrects the antimeridian frame after the build, from the XML
    # gdalbuildvrt wrote; opens nothing and no-ops unless sources straddle ±180.
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


OVERVIEW_SUFFIX = ".ovr.tif"


# Levels past the half-resolution image are plain files beside it, so the
# reprojecting reader can pick a level near the one it needs.
MAX_OVERVIEW_LEVELS = 10
_LEVEL_FLOOR_PX = 512


def overview_key_for(vrt_key: str) -> str:
    """The object beside a VRT that holds its half-resolution overview COG."""
    return posixpath.splitext(vrt_key)[0] + OVERVIEW_SUFFIX


def overview_keys_for(vrt_key: str) -> list[str]:
    """Every object a VRT's overview levels can occupy, finest level first."""
    stem = posixpath.splitext(vrt_key)[0]
    return [
        overview_key_for(vrt_key),
        *(f"{stem}.ovr{2**level}.tif" for level in range(2, MAX_OVERVIEW_LEVELS + 1)),
    ]


def mosaic_needs_overview(source_paths: list[str]) -> bool:
    """Whether a low-zoom read of the VRT would decode a member at full size.

    True when any member has no internal overviews, or when the members'
    pixel sizes differ: the VRT grid then resamples some members, and GDAL
    derives no overviews for it from theirs. Stops at the first such member.
    A member the probe cannot read counts as needing one: a broken member
    fails the translate safely, and skipping would hide it from every
    low-zoom read.
    """
    from app.processing.raster.probe import RasterProbeError, read_raster_metadata

    first_res: tuple[float, float] | None = None
    for path in source_paths:
        try:
            meta = read_raster_metadata(path)
        except RasterProbeError:
            return True
        if not meta.get("overview_levels"):
            return True
        res = (abs(meta["res_x"]), abs(meta["res_y"]))
        if first_res is None:
            first_res = res
        elif not all(map(math.isclose, res, first_res)):
            return True
    return False


# Bytes per sample by VRT data type, for the scratch-space estimate.
_SAMPLE_BYTES = {
    "Byte": 1,
    "Int8": 1,
    "UInt16": 2,
    "Int16": 2,
    "UInt32": 4,
    "Int32": 4,
    "Float32": 4,
    "CInt16": 4,
    "UInt64": 8,
    "Int64": 8,
    "Float64": 8,
    "CInt32": 8,
    "CFloat32": 8,
    "CFloat64": 16,
}


def _unshareable_reason(root, bands) -> str | None:
    """Why one shared overview image cannot stand in for these bands, if so.

    One COG carries one data type and one nodata value, and a mask band stays
    backed by the full-resolution members.
    """
    if len({band.get("dataType") for band in bands}) > 1:
        return "the bands have different data types"
    if len({band.findtext("NoDataValue") for band in bands}) > 1:
        return "the bands carry different nodata values"
    if root.find(".//MaskBand") is not None:
        return "the VRT carries a mask band"
    return None


def _overview_exceeds_free_space(vrt_path: str, root, bands) -> bool:
    """Whether the half-resolution image, uncompressed, would not fit beside the VRT."""
    estimate = sum(
        (int(root.get("rasterXSize")) // 2)
        * (int(root.get("rasterYSize")) // 2)
        * _SAMPLE_BYTES.get(band.get("dataType", ""), 8)
        for band in bands
    )
    free = shutil.disk_usage(posixpath.dirname(vrt_path) or ".").free
    if estimate > free:
        logger.info(
            "VRT overview skipped: %d bytes needed, %d free beside the VRT",
            estimate,
            free,
        )
    return estimate > free


def add_vrt_overview(vrt_path: str, source_paths: list[str]) -> list[str] | None:
    """Build overview images beside a VRT and reference each from every band.

    Returns the files, finest first, or None when the members' own overviews
    serve low zooms or the build was skipped or failed (the VRT is then left as
    it was). The first is a half-resolution COG; each next one halves the previous
    until the longer side is at most 512 px, resampled by ``nearest`` for integer
    data and ``average`` for float. GDAL lists only the levels named by
    ``<Overview>`` elements, and TiTiler opens with
    ``GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR``, so a ``.ovr`` sidecar is never found.
    """
    from xml.etree.ElementTree import SubElement, parse

    try:
        tree = parse(vrt_path)
    except Exception:  # broad: an optimisation must not fail a build gdalbuildvrt reported as successful
        return None
    root = tree.getroot()
    bands = root.findall("VRTRasterBand")
    if (
        not bands
        or int(root.get("rasterXSize", "0")) < 2
        or int(root.get("rasterYSize", "0")) < 2
    ):
        return None
    reason = _unshareable_reason(root, bands)
    if reason:
        logger.info("VRT overview skipped: %s", reason)
        return None
    if not mosaic_needs_overview(source_paths):
        return None

    from app.processing.raster.cog import _is_float_dtype

    if _overview_exceeds_free_space(vrt_path, root, bands):
        return None

    # The COG driver would resample integer classes with cubic and invent
    # values; averaging only suits continuous data.
    resampling = (
        "average"
        if any(_is_float_dtype(band.get("dataType", "")) for band in bands)
        else "nearest"
    )
    overview_path = overview_key_for(vrt_path)
    if not _translate(
        [
            "-of",
            "COG",
            "-co",
            "BIGTIFF=IF_SAFER",
            "-co",
            f"OVERVIEW_RESAMPLING={resampling}",
        ],
        resampling,
        vrt_path,
        overview_path,
    ):
        return None
    paths = [overview_path]
    for key in overview_keys_for(vrt_path)[1:]:
        if not _longer_side_exceeds_floor(paths[-1]):
            break
        if not _translate(
            ["-of", "GTiff", "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE"]
            + ["-co", "BIGTIFF=IF_SAFER"],
            resampling,
            paths[-1],
            key,
        ):
            break
        paths.append(key)

    for position, band in enumerate(bands, start=1):
        for path in paths:
            overview = SubElement(band, "Overview")
            name = SubElement(overview, "SourceFilename", relativeToVRT="1")
            name.text = posixpath.basename(path)
            SubElement(overview, "SourceBand").text = band.get("band", str(position))
    staged = vrt_path + ".staged"
    try:
        tree.write(staged, encoding="utf-8", xml_declaration=True)
        os.replace(staged, vrt_path)
    except OSError:
        logger.warning("VRT overview skipped: the VRT could not be rewritten")
        for leftover in (staged, *paths):
            if os.path.exists(leftover):
                os.remove(leftover)
        return None
    return paths


def _translate(options: list[str], resampling: str, source: str, target: str) -> bool:
    """Halve ``source`` into ``target``; a failure or timeout leaves no file."""
    try:
        result = run_gdal(
            ["gdal_translate", "-q", *options, "-r", resampling]
            + ["-outsize", "50%", "50%", source, target],
            env=gdal_safe_env(),
            tool="gdal_translate",
        )
        failure = result.stderr if result.returncode != 0 else None
    except RuntimeError as exc:  # an optional overview timing out must not fail the VRT
        failure = str(exc)
    if failure is not None:
        logger.warning("VRT overview build failed: %s", failure)
        if os.path.exists(target):
            os.remove(target)
        return False
    return True


def _longer_side_exceeds_floor(path: str) -> bool:
    from app.processing.raster.probe import RasterProbeError, read_raster_metadata

    try:
        meta = read_raster_metadata(path)
    except RasterProbeError:
        return False
    return max(meta["width"], meta["height"]) > _LEVEL_FLOOR_PX


def strip_vrt_overview(vrt_path: str, overview_paths: list[str]) -> None:
    """Undo ``add_vrt_overview``: remove the ``Overview`` elements and the files."""
    from xml.etree.ElementTree import parse

    tree = parse(vrt_path)
    for band in tree.getroot().findall("VRTRasterBand"):
        for overview in band.findall("Overview"):
            band.remove(overview)
    tree.write(vrt_path, encoding="utf-8", xml_declaration=True)
    for path in overview_paths:
        os.remove(path)
