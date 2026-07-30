"""VRT build module: gdalbuildvrt subprocess wrappers and source path resolver."""

import os
import subprocess
from contextlib import ExitStack
from xml.etree.ElementTree import Element, ElementTree, SubElement


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


def _resolve_target_resolution(values: list[float], resolution_strategy: str) -> float:
    if resolution_strategy == "finest":
        return min(values)
    if resolution_strategy == "coarsest":
        return max(values)
    if resolution_strategy == "average":
        return sum(values) / len(values)
    raise KeyError(resolution_strategy)


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
    2. the shifted hull must be *strictly* narrower than the plain one. A
       genuinely global mosaic measures 360° in every frame, so it ties and
       keeps -180..180 rather than being re-framed to an arbitrary origin.

    Candidate origins are the source left edges, which is exhaustive: the
    tightest circular hull of a set of intervals always starts at one of them.
    """
    plain_span = max(right for _, right in spans) - min(left for left, _ in spans)
    if plain_span <= 180.0:
        return None

    best_origin: float | None = None
    best_span = plain_span
    for origin, _ in spans:
        shifted_span = (
            max(right + 360.0 if left < origin else right for left, right in spans)
            - origin
        )
        if shifted_span < best_span:
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

    with ExitStack() as stack:
        datasets = [stack.enter_context(rasterio.open(path)) for path in source_paths]
        first = datasets[0]
        first_crs = first.crs.to_wkt() if first.crs is not None else None

        res_x = _resolve_target_resolution(
            [abs(ds.transform.a) for ds in datasets], resolution_strategy
        )
        res_y = _resolve_target_resolution(
            [abs(ds.transform.e) for ds in datasets], resolution_strategy
        )

        # fix(#887): only a geographic CRS wraps at ±180. Projected easting runs
        # continuously across the seam, and its numbers are metres -- a 40 000 km
        # wide EPSG:3857 pair clears the >180 guard trivially and a +360 shift
        # would move a source by 360 *metres*. So gate the whole thing on EVERY
        # source being geographic before computing any of the geometry.
        all_geographic = all(
            ds.crs is not None and ds.crs.is_geographic for ds in datasets
        )
        seam_origin = (
            _seam_frame_origin([(ds.bounds.left, ds.bounds.right) for ds in datasets])
            if all_geographic
            else None
        )
        lon_offsets = [
            360.0 if seam_origin is not None and ds.bounds.left < seam_origin else 0.0
            for ds in datasets
        ]
        shifted = list(zip(datasets, lon_offsets, strict=True))

        left = min(ds.bounds.left + offset for ds, offset in shifted)
        right = max(ds.bounds.right + offset for ds, offset in shifted)
        bottom = min(ds.bounds.bottom for ds in datasets)
        top = max(ds.bounds.top for ds in datasets)
        width = max(1, int(round((right - left) / res_x)))
        height = max(1, int(round((top - bottom) / res_y)))

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
            dst_width = max(
                1, int(round(dataset.width * abs(dataset.transform.a) / res_x))
            )
            dst_height = max(
                1, int(round(dataset.height * abs(dataset.transform.e) / res_y))
            )
            # fix(#887): lon_offset places the source in the same re-framed
            # longitude frame as `left`. Mixing frames here is how a
            # seam-straddling source ended up half a world from its own pixels.
            dst_x_off = int(round((dataset.bounds.left + lon_offset - left) / res_x))
            dst_y_off = int(round((top - dataset.bounds.top) / res_y))
            SubElement(
                source,
                "DstRect",
                xOff=str(dst_x_off),
                yOff=str(dst_y_off),
                xSize=str(dst_width),
                ySize=str(dst_height),
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


def sources_straddle_seam(source_paths: list[str]) -> bool:
    """True when the sources form a geographic mosaic that crosses ±180.

    fix(#887): ``gdalbuildvrt`` has no antimeridian handling. It takes the plain
    min/max hull of the source extents, so two 5°-wide tiles either side of the
    seam come out as a 3600 x 50 px mosaic anchored at -180 with the eastern tile
    at ``dst_x_off`` 3550 -- byte-for-byte the same defect the Python writer had,
    verified against the GDAL 3.10 in the worker image and GDAL 3.13 locally.

    Nor can the subprocess be nudged into the right answer. ``-te 175 0 185 5``
    sizes the mosaic correctly but places each source at its own coordinates, so
    every source outside that window is dropped: the run exits 0 and half the
    mosaic comes back empty, which is worse than the bug. Pre-shifting each
    source through its own intermediate VRT would work geometrically, but those
    intermediates are temp files that never get stored, so ``rewrite_vrt_sources``
    (STOR-03) would leave the outer VRT pointing at paths that do not survive
    ingest.

    So the seam case belongs to :func:`_write_python_vrt`, which computes the
    mosaic geometry in a shifted frame, and this predicate is the deliberate
    branch into it -- not the ``FileNotFoundError`` fallback, which never fires in
    a deployed worker because the image installs ``gdal-bin``.
    """
    import rasterio

    try:
        with ExitStack() as stack:
            datasets = [
                stack.enter_context(rasterio.open(path)) for path in source_paths
            ]
            if not all(ds.crs is not None and ds.crs.is_geographic for ds in datasets):
                return False
            spans = [(ds.bounds.left, ds.bounds.right) for ds in datasets]
    except Exception:  # broad: a source that cannot be opened is gdalbuildvrt's error to report, with its own message — never this predicate's
        return False
    return _seam_frame_origin(spans) is not None


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
    # fix(#887): the seam-crossing mosaic is the one shape gdalbuildvrt cannot
    # express -- see sources_straddle_seam for why neither -te nor pre-shifted
    # intermediates work. Branch before spawning it, or the normalization only
    # ever runs on hosts that lack the GDAL CLI.
    if sources_straddle_seam(source_paths):
        return _write_python_vrt(
            source_paths,
            output_path,
            resolution_strategy,
            separate=separate,
        )
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
