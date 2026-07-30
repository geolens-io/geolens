"""VRT build module: gdalbuildvrt subprocess wrappers and source path resolver."""

import math
import os
import subprocess
from contextlib import ExitStack
from xml.etree.ElementTree import Element, ElementTree, SubElement

from app.core.geo import LON_EPSILON_DEGREES


# IA-P1-03 (Phase 1068): clamp the GDAL VSI surface that VRT processing
# can reach. CPL_VSIL_CURL_ALLOWED_EXTENSIONS gates which URL-fetched
# extensions GDAL will open; VRT_VIRTUAL_OVERVIEWS=NO blocks the implicit
# overview-pyramid expansion that could pull additional remote sources
# during a VRT build.
_VRT_SAFE_ENV: dict[str, str] = {
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": "tif,tiff,vrt",
    "VRT_VIRTUAL_OVERVIEWS": "NO",
    "GDAL_HTTP_FOLLOWLOCATION": "NO",
}


def gdal_safe_env(*, extras: dict[str, str] | None = None) -> dict[str, str]:
    """Return os.environ overlaid with the raster-pipeline GDAL safety clamps.

    Shared by every GDAL CLI subprocess the raster pipeline spawns
    (gdaladdo, gdalwarp, gdal_translate, gdalbuildvrt). Applies:

    - CPL_VSIL_CURL_ALLOWED_EXTENSIONS="tif,tiff,vrt" — gates which
      URL-fetched extensions GDAL will open (defense against the
      classic /vsicurl/ side-channel that can fetch arbitrary remote
      content when an attacker plants a SourceFilename with an
      unexpected extension).
    - VRT_VIRTUAL_OVERVIEWS="NO" — blocks the implicit overview-pyramid
      expansion that could pull additional remote sources during a
      build.
    - GDAL_HTTP_FOLLOWLOCATION="NO" — pinned with the SEC-S04 SSRF
      redirect-bypass defense; libcurl will not follow 3xx hops out
      of the explicitly-validated source URL.

    Phase 1071 KNOWN-03 (v1015 Phase 1068 tech-debt followup): the
    clamps were originally scoped to _build_vrt only; they now apply
    uniformly across the raster subprocess surface.

    Args:
        extras: Optional per-call additions (e.g. ``{"GDAL_CACHEMAX": "200"}``).
            extras MUST NOT collide with security clamp keys in ``_VRT_SAFE_ENV``
            (``CPL_VSIL_CURL_ALLOWED_EXTENSIONS``, ``VRT_VIRTUAL_OVERVIEWS``,
            ``GDAL_HTTP_FOLLOWLOCATION``). A ``ValueError`` is raised on collision
            so callers cannot silently disable the security clamps.
            Pass ``None`` (the default) for the base clamp only.

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

    ``gdal_safe_env`` clamps SUBPROCESS environments only; an in-process
    ``rasterio.open`` gets none of it. Built from the same ``_VRT_SAFE_ENV``
    constant so the two cannot drift when a clamp is added. Used by
    :func:`_write_python_vrt`, which must open the sources it is asked to build
    from -- the only in-process source access left in this module.

    fix(#887): note what this does NOT buy. Measured on GDAL 3.12.1,
    ``GDAL_HTTP_FOLLOWLOCATION`` is not a GDAL configuration option at all --
    ``gdalinfo --config GDAL_HTTP_FOLLOWLOCATION NO --debug ON`` answers
    ``Warning 1: Unknown configuration option 'GDAL_HTTP_FOLLOWLOCATION'`` and
    follows the 302 anyway, in-process and in the subprocess alike. So this env
    carries the two clamps that ARE real (the ``/vsicurl`` extension allow-list
    and ``VRT_VIRTUAL_OVERVIEWS``) and provides no redirect protection to
    anybody.
    """
    import rasterio

    return rasterio.Env(**_VRT_SAFE_ENV)


# fix(#430 BA-29): raster GDAL CLIs run synchronously inside asyncio.to_thread, and
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
# managed-storage VRT <SourceFilename> body content. User-uploaded VRTs are
# validated by ingest/validation.py and intentionally reject all VSI paths.
# Any internal module that needs to know which GDAL virtual-filesystem handlers
# managed VRT processing accepts must import this constant, not re-declare it.
#
# The seven prefixes here cover the GDAL VSI handlers that the COG
# ingest path legitimately uses for managed-storage VRTs:
#
#   /vsiaz/   — Azure Blob Storage
#   /vsicurl/ — generic HTTPS sources
#   /vsigs/   — Google Cloud Storage
#   /vsimem/  — in-memory (testing scaffolds)
#   /vsis3/   — AWS S3 (primary production backend)
#   /vsitar/  — tar archive members
#   /vsizip/  — zip archive members
#
# When adding a new managed-storage VSI scheme: add it HERE only. Future
# internal consumers (env-overlay extensions, source classifiers, OpenAPI
# examples) must import from the same constant rather than copy-pasting.
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

    fix(#887): ``gdalbuildvrt`` emits sub-pixel geometry whenever a source is not
    aligned to the chosen output grid -- a mixed-resolution mosaic produced
    ``xOff="17751.5"`` and ``xOff="349.51"`` here. Rounding those to whole pixels
    slides the source by up to half an output pixel and changes how GDAL
    resamples it, so keep the fraction and only drop a trailing ``.0`` so the
    common whole-pixel case still reads like GDAL's own output.

    Shared by BOTH writers on purpose: the ``gdalbuildvrt`` frame rewrite and the
    CLI-less :func:`_write_python_vrt` fallback. They disagreeing about this rule
    is what codex round 7 caught, and two copies is how it would diverge again.

    ``rel_tol=0`` is load-bearing. ``math.isclose`` compares against
    ``max(rel_tol * max(|a|, |b|), abs_tol)``, so leaving the 1e-9 default alive
    makes the tolerance GROW with the offset: at 1e8 pixels it reaches 0.1, and
    at 1e9 it reaches 1.0, which silently rounded a real 0.49-pixel offset to a
    whole number -- reintroducing at scale exactly the defect this function
    exists to prevent. Only the absolute noise floor should ever be ignored.

    The fixed-point rendering is deliberate rather than ``repr``: it settles the
    value at 1e-10 of a pixel, which absorbs the accumulated arithmetic noise
    that makes an exact half-pixel arrive as 248.49999999999852. ``repr`` would
    round-trip that noise into the file. Ten decimal places is fourteen orders
    of magnitude finer than anything GDAL resamples on.
    """
    if math.isclose(value, round(value), rel_tol=0.0, abs_tol=_PIXEL_EPSILON):
        return str(int(round(value)))
    return f"{value:.10f}".rstrip("0").rstrip(".")


def _containing_pixels(span_px: float) -> int:
    """Pixel count that CONTAINS a span -- round UP, never to nearest.

    fix(#887): a mosaic whose sources end at pixel 298.5 needs 299 pixels; 298
    leaves the last half pixel outside the dataset and GDAL clips it, which no
    pixel-count assertion catches because a 50-pixel source still reads back as
    50 pixels. GDAL sizes its own mosaics this way (measured: max xOff+xSize
    298.5 -> rasterXSize 299, and 440.51 -> 441). ``round`` first so float noise
    on an exact boundary cannot add a stray pixel.

    Shared by both writers, same reasoning as :func:`_offset_text`.
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


# fix(#887): the seam logic is written in degrees throughout -- the >180 guard,
# the +360 shift, the ±180 rings. `is_geographic` is NOT enough to guarantee
# that: EPSG:4807 (NTF Paris) is geographic with an angular unit of GRADS, where
# a full turn is 400 and the seam sits at 200. Feeding it a 360 shift moves the
# eastern tile to the wrong place entirely -- a 195..200 / -200..-195 pair comes
# out as a 40-grad hull instead of the intended 10. Compare the CRS's own
# radians-per-unit factor rather than a unit name, which varies by PROJ build.
_RADIANS_PER_DEGREE = math.pi / 180.0


def _is_degree_based(crs) -> bool:
    """True only for a geographic CRS whose angular unit is degrees.

    fix(#887): ``rel_tol`` is correct HERE and wrong in :func:`_offset_text`, so
    do not "fix" this one by symmetry. This compares two fixed physical
    constants of the same tiny magnitude (0.01745 radians per degree against
    whatever PROJ reports), where proportional agreement is the meaningful test
    and the nearest wrong answer -- grads, at 0.01571 -- is 10% away. An offset
    is an unbounded pixel count whose noise floor does not scale with it.
    """
    if crs is None or not crs.is_geographic:
        return False
    try:
        _, radians_per_unit = crs.units_factor
    except Exception:  # broad: units_factor raises CRSError on exotic/!undefined CRSs, which are exactly the ones to exclude
        return False
    return math.isclose(radians_per_unit, _RADIANS_PER_DEGREE, rel_tol=1e-9)


def _seam_frame_origin(spans: list[tuple[float, float]]) -> float | None:
    """Pick the longitude frame origin for a seam-straddling geographic mosaic.

    fix(#887): ``min(left)`` / ``max(right)`` across sources sitting on both
    sides of ±180 allocated a near-global raster with a huge empty middle -- a
    10°-wide Pacific mosaic came out 360° wide, and every source landed at the
    wrong ``dst_x_off``, so the VRT was both enormous and misregistered.
    Re-frame the mosaic so the seam falls *inside* the frame instead of
    splitting it: every source starting west of the returned origin is shifted
    +360, which makes the hull contiguous again.

    Returns the origin, or ``None`` when the plain -180..180 fold is already the
    tightest hull and the geometry must be left exactly as it was.

    Two guards, and BOTH are required -- either one alone is a coin flip
    (see #883):

    1. the plain hull must be wider than 180°. Nothing narrower can be improved
       by a shift, and this is what leaves a mosaic ending flush at +180, and
       one spanning -10..170 (exactly 180), in the plain frame.
    2. the shifted hull must be narrower than the plain one *by a real margin*.
       A genuinely global mosaic measures 360° in every frame, so it ties and
       keeps -180..180 rather than being re-framed to an arbitrary origin. The
       margin matters: ``left + 360`` is not bit-exact for an arbitrary mantissa,
       so a global mosaic on non-round tile boundaries can measure
       359.99999999999994 shifted against 360.00000000000006 plain and win a
       bare ``<`` on nothing but noise (the same trap #886/#928 hit in the
       rollup folds). ``_SPAN_MARGIN`` is far above that noise and far below any
       real gain.

    Candidate origins are the source left edges, which is exhaustive: the
    tightest circular hull of a set of intervals always starts at one of them.
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

        # fix(#887): only a degree-based geographic CRS wraps at ±180. Projected
        # easting runs continuously across the seam and its numbers are metres --
        # a 40 000 km wide EPSG:3857 pair clears the >180 guard trivially and a
        # +360 shift would move a source by 360 *metres* -- and a grads-based
        # geographic CRS turns at 400, not 360. Gate the whole thing on EVERY
        # source before computing any of the geometry.
        seam_origin = (
            _seam_frame_origin([(ds.bounds.left, ds.bounds.right) for ds in datasets])
            if all(_is_degree_based(ds.crs) for ds in datasets)
            else None
        )
        lon_offsets = [
            360.0
            if seam_origin is not None
            and ds.bounds.left < seam_origin - LON_EPSILON_DEGREES
            else 0.0
            for ds in datasets
        ]
        shifted = list(zip(datasets, lon_offsets, strict=True))

        left = min(ds.bounds.left + offset for ds, offset in shifted)
        right = max(ds.bounds.right + offset for ds, offset in shifted)
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
            lon_offset: float = 0.0,
        ) -> None:
            source = SubElement(parent, "SimpleSource")
            # STOR-03 (Phase 1210): write logical key + relativeToVRT="1" so the stored
            # VRT XML is provider-agnostic.  dataset.name here is the resolve_open_path
            # output (an absolute VSI path like /vsis3/bucket/key or a local filesystem
            # path).  rewrite_vrt_sources, called at the store site in tasks_vrt.py
            # AFTER metadata extraction + quicklook generation, normalises both to the
            # logical key.  Setting relativeToVRT="1" here is a forward declaration of
            # intent; the rewrite pass at the store site is the enforcement gate.
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
            # fix(#887): destination geometry stays fractional, exactly as the
            # gdalbuildvrt rewrite keeps it -- both go through _offset_text. The
            # integer rounding this replaces put a source needing xOff 248.5 at
            # 248, sliding it half an output pixel and changing its resampling.
            dst_width = dataset.width * abs(dataset.transform.a) / res_x
            dst_height = dataset.height * abs(dataset.transform.e) / res_y
            # lon_offset places the source in the same re-framed longitude frame
            # as `left`. Mixing frames here is how a seam-straddling source ended
            # up half a world from its own pixels.
            dst_x_off = (dataset.bounds.left + lon_offset - left) / res_x
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
            for dataset, lon_offset in shifted:
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
                        band, dataset, band_index=source_band, lon_offset=lon_offset
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
                for dataset, lon_offset in shifted:
                    add_simple_source(
                        band, dataset, band_index=band_number, lon_offset=lon_offset
                    )

        ElementTree(root).write(output_path, encoding="utf-8", xml_declaration=True)
        return output_path


def resolve_vrt_source_path(asset_uri: str, *, tenant_id: str | None = None) -> str:
    """Delegate to the storage seam's resolve_open_path (STOR-01 / Phase 1210).

    This function is kept for backward compatibility with existing callers.
    New callers should import resolve_open_path from
    app.platform.storage.titiler_url directly.

    tenant_id: when provided (multi_tenant mode), prepend tenants/{tenant_id}/
               to the object key.  In single_tenant this is always None and the
               returned path is byte-identical with the pre-1210 inline code.
    """
    from app.platform.storage.titiler_url import resolve_open_path

    return resolve_open_path(asset_uri, tenant_id=tenant_id)


def shift_vrt_longitude_frame(vrt_path: str) -> None:
    """Re-anchor a built VRT's longitude frame so the seam falls inside it.

    fix(#887): ``gdalbuildvrt`` gets everything about a seam-crossing mosaic
    right except the geometry, so correct the geometry and keep the rest.
    Rebuilding with :func:`_write_python_vrt` instead would throw the rest away
    -- that writer emits bare ``SimpleSource`` elements with no ``NoDataValue``,
    ``ColorInterp``, ``UseMaskBand`` or mask band, so the mosaic reads back
    ``nodata=None`` with undefined colour interpretation and all-valid masks, and
    ``extract_raster_metadata`` then persists a null nodata. Worse, without the
    ``<NODATA>`` GDAL puts inside a ``ComplexSource``, an overlapping source's
    fill pixels overwrite valid pixels from an earlier source (measured: an
    overlap that should read 7 read 0).

    Rewrites exactly three things -- ``rasterXSize``, the ``GeoTransform``
    origin, and every ``DstRect`` ``xOff``, including the ones inside a
    ``<MaskBand>``, which ``iter()`` reaches. Everything else is untouched, and a
    non-crossing build is left byte-identical to plain ``gdalbuildvrt``.

    Each source's own left edge is recoverable from the ``xOff`` GDAL already
    wrote (``old_left + xOff * res_x``), so this needs no second pass over the
    sources and no filename matching.

    It also DECIDES, from the same XML, opening nothing. That is deliberate
    (fix(#887), codex round 9): the previous version probed every source with
    ``rasterio.open`` before the build, and ``build_vrt`` runs inside
    ``asyncio.to_thread`` (``tasks_vrt.py``). Python threads are not killable, so
    a stalled object-storage read pinned a pool thread forever with none of
    ``run_gdal``'s wall-clock timeout and kill-on-hang applying to it -- enough
    stalled VRT jobs would starve every other ``to_thread`` in the worker. The
    module comment on ``GDAL_SUBPROCESS_TIMEOUT_SECONDS`` names that hazard
    already; the probe reintroduced it.

    ``gdalbuildvrt`` has already opened every source, under that timeout, and
    written what this needs: per-source ``DstRect`` geometry, the hull
    ``GeoTransform``, and the ``SRS``. Deriving the decision from those closes the
    timeout gap and removes the SSRF question entirely rather than fencing it off
    by URL prefix -- nothing here ever touches a source.

    Returns without writing when the VRT is not a degree-based geographic mosaic,
    when its sources do not straddle the seam, or when the XML lacks the geometry
    this needs. That last case cannot hide a real crossing: detecting one requires
    exactly the same ``GeoTransform`` and per-source ``DstRect`` values the
    rewrite consumes, so a VRT this cannot read is one it also cannot have
    detected. Verified against GDAL 3.10.3 (worker image) and 3.13.0, which emit
    identical structure.
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

    # A source's own longitude span is recoverable from the offset GDAL already
    # wrote, so the seam decision needs no second pass over the sources and no
    # filename matching. Duplicate spans (one DstRect per band, plus any mask
    # band) are harmless: they change neither the hull nor the candidate origins.
    reconstructed = [
        (
            rect,
            old_left + float(rect.get("xOff", "0")) * res_x,
            float(rect.get("xSize", "0")),
        )
        for rect in rects
    ]
    seam_origin = _seam_frame_origin(
        [(left, left + size * res_x) for _, left, size in reconstructed]
    )
    if seam_origin is None:
        return

    placements = []
    for rect, src_left, x_size in reconstructed:
        # fix(#887): DEFENSIVE here, and deliberately kept. Codex round 6 found
        # this comparison shifting the origin source itself, because `src_left`
        # was reconstructed from a serialized pixel offset while `seam_origin`
        # had been read straight off the source -- two derivations of one edge,
        # disagreeing by ~1e-14, and the whole mosaic stayed 17998 px wide
        # instead of 300. Round 9 removed the source-opening probe, so both
        # values now come from THIS reconstruction and `seam_origin` is
        # bit-identical to one of them; the mismatch is structurally impossible.
        # The epsilon stays so that reintroducing a second derivation cannot
        # quietly bring the bug back. (The load-bearing one is in
        # _seam_frame_origin's hull contest.)
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

    Returns:
        ``output_path`` on success.

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
    # fix(#887): correct the antimeridian frame AFTER the build, from the XML
    # gdalbuildvrt just wrote. It opens nothing itself and no-ops unless the
    # sources really straddle ±180 -- so nothing in this function touches a
    # source outside the timed, killable subprocess above.
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
