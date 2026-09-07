"""COG compliance check, conversion, and raster metadata extraction."""

import hashlib
import math
import tempfile
from pathlib import Path

from app.core.geo import (
    LON_EPSILON_DEGREES,
    bbox_to_extent_wkt,
    pixel_size_from_affine,
    wrap_longitude,
)
from app.processing.raster.vrt import gdal_safe_env, run_gdal


_FLOAT_DTYPES = {"float32", "float64", "float16", "float", "complex"}

# fix(#887): a footprint that wraps the whole world puts its left and right
# edges on the SAME meridian, so transform_bounds can only report a zero-width
# longitude range for it. Recognizing that needs an equality test, and the
# tolerance is deliberately tight: a 2 m-wide sliver in EPSG:3832 still reports
# 1.8e-5° of width, four orders of magnitude above this.
_LON_DEGENERATE_TOL = 1e-9

# fix(#887): second condition on the same check. A wrapping footprint puts the
# raster centre a long way from that edge meridian (exactly 180° for a full
# 360° wrap); a genuine zero-width sliver puts it right on top of it. Any
# threshold between the two works -- 1° is comfortably clear of both.
_WRAP_PROBE_MIN_DEGREES = 1.0


# fix(#1290): compression profiles that reproduce every input sample
# exactly. An ALLOWLIST: an unrecognized `compression` value (from
# RasterCommitRequest, no server-side check) must fall on "assume lossy,
# keep the original" — the wrong direction deletes the only lossless copy.
#
# LERC is here because `convert_to_cog` never passes MAX_Z_ERROR (default
# 0, exact); verified against GDAL 3.10.3 and a round-trip. Pinned by
# `test_lerc_stays_lossless_only_while_no_error_bound_is_set` so a future
# nonzero MAX_Z_ERROR is caught, not discovered after an original is gone.
LOSSLESS_COG_COMPRESSIONS: frozenset[str] = frozenset(
    {"NONE", "DEFLATE", "LZW", "ZSTD", "PACKBITS", "LZMA", "LERC"}
)


def cog_preserves_source(
    cog_status: str | None,
    compression: str | None,
    *,
    reprojected: bool = False,
) -> bool:
    """True when the stored COG carries the samples the uploaded file did.

    fix(#1290): ADR-002 Decision 7 licenses deleting the
    pre-conversion upload on "conversion is lossless" — more than one way
    for that claim to be false.

    - **compression**: JPEG/WEBP discard detail; LERC doesn't, at the zero
      error bound this pipeline leaves in place.
    - **assign_crs** (fix(#1291)): ``-a_srs`` only writes a CRS tag, bands
      pass through untouched — NOT sample-altering (unlike the old
      ``gdalwarp -t_srs``, which resampled onto a new grid; hence
      ``reprojected``).
    - **resampling**: feeds ``gdaladdo`` only (overviews), never the base band.
    - **nodata**: ``-a_nodata`` writes a metadata tag, not sample-altering.
    - **overviews/tiling/COPY_SRC_OVERVIEWS**: add or rearrange, never discard.

    Predicate: "no lossy codec AND no warp". A wrong True permanently loses
    the only faithful copy; a wrong False only retains extra bytes — that
    asymmetry is why #1291 moved ``assign_crs`` rather than changing it: a
    relabel is REVERSIBLE (another ``-a_srs`` corrects it; the catalog keeps
    the original in ``Dataset.original_srid``), a warp is not.

    ``cog_status == "verified"`` short-circuits: nothing ran, so the stored
    bytes ARE the uploaded bytes. ``check_and_prepare_cog`` always converts
    when ``assign_crs`` is set, so the two states can't coexist.
    """
    if cog_status == "verified":
        return True
    if reprojected:
        return False
    return (compression or "").upper() in LOSSLESS_COG_COMPRESSIONS


def resolve_crs_assignment(
    *, crs_wkt: str | None, srid_override: int | None
) -> int | None:
    """The EPSG code the conversion must apply, or None to keep the source's.

    Since fix(#1291) "apply" means assignment (``-a_srs``), not
    reprojection — no sample is touched.

    fix(#1290): an override applies whenever the caller supplies
    one, not only when the source declares nothing — ``RasterCommitRequest``
    documents "missing **or incorrect**", and the old ``if crs_missing``
    guard silently ignored a correction.

    Raises ``ValueError`` when the source declares no CRS and no override
    was given.
    """
    if srid_override:
        return srid_override
    if not crs_wkt:
        raise ValueError(
            "Missing CRS: raster has no coordinate reference system. "
            "Provide a CRS override (EPSG code) at import time."
        )
    return None


def _is_float_dtype(dtype: str) -> bool:
    return any(f in dtype.lower() for f in _FLOAT_DTYPES)


def is_dem_candidate(band_count: int | None, dtype: str | None) -> bool:
    """Whether a raster of this shape is elevation data rather than imagery.

    One band of floating-point values is what a DEM looks like. Must be
    the SAME heuristic everywhere: ``raster_tile_proxy`` branches on the
    stored flag, so a mismatch serves the wrong renderer (terrainrgb over
    imagery, or vice versa).

    feat(#1266): shared with the STAC refresh strategy, which reads band
    count/dtype through Titiler rather than rasterio — hence taking values,
    not a dataset handle.
    """
    return bool(band_count == 1 and dtype and _is_float_dtype(dtype))


def _scratch_dir() -> str | None:
    """Directory for COG temp copies (fix #448).

    tempfile's default (/tmp) is a 512MB RAM-backed tmpfs, so a large
    raster can OOM or ENOSPC; prefer the disk-backed upload_staging volume.
    None falls back to the tempfile default when staging doesn't exist.
    """
    from pathlib import Path as _Path

    from app.core.config import settings

    staging = settings.upload_staging_dir
    return staging if _Path(staging).is_dir() else None


def validate_raster_crs(file_path: str) -> None:
    """Raise ValueError if the raster file has no valid CRS."""
    import rasterio

    with rasterio.open(file_path) as src:
        if src.crs is None:
            raise ValueError(
                "Missing CRS: raster has no coordinate reference system. "
                "Ensure the GeoTIFF includes an embedded CRS."
            )


def _fold_geographic_bbox(
    west: float, south: float, east: float, north: float
) -> tuple[float, float, float, float]:
    """Fold a geographic-CRS longitude range into the RFC 7946 §5.2 form.

    fix(#887): a raster in the 0..360 domain keeps an east past +180; wrap
    it, letting east fall *below* west at a seam crossing, for
    ``bbox_to_extent_wkt`` to turn into the two-ring extent.
    """
    span = east - west
    if span >= 360.0 - LON_EPSILON_DEGREES:
        # The footprint wraps the whole world. -180..180 is the honest answer
        # and the only one a single ring can express. The tolerance matters: a
        # 0..360 global raster whose span measures 359.99999999999994 would
        # otherwise fall through and be re-expressed as a west > east pair, i.e.
        # a domain flip decided by last-bit noise.
        return (-180.0, south, 180.0, north)
    # fix(#887): reduce ARBITRARY wrap counts before folding — a raster
    # georeferenced multiple turns out (e.g. 720..730) would otherwise
    # inflate or misplace the footprint (measured: 37x true area).
    west = wrap_longitude(math.fmod(west, 360.0))
    # `span` is under 360 by the branch above, so one step settles east.
    east = wrap_longitude(west + span)
    return (west, south, east, north)


def _wgs84_bbox(src) -> tuple[float, float, float, float]:
    """Reproject a raster's bounds to a WGS84 RFC 7946 §5.2 bbox.

    Returns ``(west, south, east, north)`` with ``west > east`` at an
    antimeridian crossing — feed to :func:`app.core.geo.bbox_to_extent_wkt`,
    never a hand-built ring.

    fix(#887): GDAL's ``OCTTransformBounds`` reports a crossing footprint
    as ``west > east``; a naive ring over that pair covers the wrong 350°
    of the world (measured 35x the real footprint).
    """
    from rasterio.warp import transform, transform_bounds

    crs = src.crs
    bounds = (
        src.bounds.left,
        src.bounds.bottom,
        src.bounds.right,
        src.bounds.top,
    )
    if crs is None:
        # Without a CRS these are not longitudes at all (validate_raster_crs
        # rejects such rasters at ingest), so there is nothing to normalize.
        return bounds

    if crs.to_epsg() == 4326:
        return _fold_geographic_bbox(*bounds)

    west, south, east, north = transform_bounds(crs, "EPSG:4326", *bounds)

    # The one footprint transform_bounds cannot express is one that wraps the
    # whole world: its left and right edges land on the same meridian, so the
    # longitude range comes back zero-width (a global EPSG:3832 raster reads
    # -30..-30) and the globe would register as a line. TWO conditions gate the
    # repair, because either alone misfires: the range must be degenerate AND
    # the raster centre must sit far from that edge meridian, which only a wrap
    # produces -- a genuine zero-width source has its centre on the meridian.
    if abs(east - west) <= _LON_DEGENERATE_TOL and bounds[2] > bounds[0]:
        (center_lon,), _ = transform(
            crs,
            "EPSG:4326",
            [(bounds[0] + bounds[2]) / 2],
            [(bounds[1] + bounds[3]) / 2],
        )
        if abs(wrap_longitude(center_lon - west)) > _WRAP_PROBE_MIN_DEGREES:
            return (-180.0, south, 180.0, north)

    return _fold_geographic_bbox(west, south, east, north)


def extract_raster_metadata(file_path: str) -> dict:
    """Extract all raster metadata from a file using a single rasterio open pass.

    ``bounds_wgs84`` is an RFC 7946 §5.2 bbox: ``west > east`` for a footprint
    that crosses the antimeridian (fix(#887)). Callers that need a monotonic
    span must close it the short way round, not subtract blindly.
    """
    import rasterio

    with rasterio.open(file_path) as src:
        crs = src.crs
        # fix(#1376): explicitly WKT2 — RasterAsset.to_stac_properties()
        # publishes this as STAC's `proj:wkt2`, and rasterio's default
        # WKT1_GDAL may be rejected by a strict consumer of that field.
        crs_wkt = crs.to_wkt(version="WKT2_2019") if crs else None
        epsg = crs.to_epsg() if crs else None

        bounds_wgs84 = _wgs84_bbox(src)
        bbox_wkt = bbox_to_extent_wkt(*bounds_wgs84)

        # fix(#1375): the pixel VECTOR lengths, not their world-axis
        # components. Identical to the old abs(a)/abs(e) for the axis-aligned
        # rasters that are almost all of them, and correct for the rotated
        # ones those two silently understated. The remote-asset probe
        # (catalog/sources/cog_info.py) derives its pair through the same
        # helper, so one scene reports one resolution either way in.
        res_x, res_y = pixel_size_from_affine(
            src.transform.a, src.transform.b, src.transform.d, src.transform.e
        )
        is_rotated = src.transform.b != 0.0 or src.transform.d != 0.0

        dtype = src.dtypes[0] if src.dtypes else None
        dtypes = list(src.dtypes)

        nodata = src.nodata
        profile = src.profile
        compression = profile.get("compress")
        blockxsize = profile.get("blockxsize")
        blockysize = profile.get("blockysize")
        tiled = profile.get("tiled", False)

        overview_levels = src.overviews(1) if src.count >= 1 else []

        band_info = []
        src_units = src.units or ()
        for i in range(1, src.count + 1):
            entry: dict = {
                "index": i,
                "dtype": src.dtypes[i - 1],
                "nodata": str(src.nodata) if src.nodata is not None else None,
                "color_interp": src.colorinterp[i - 1].name,
            }
            unit = src_units[i - 1] if i - 1 < len(src_units) else None
            if unit and isinstance(unit, str) and unit.strip():
                entry["unit"] = unit.strip()
            band_info.append(entry)

        is_dem = is_dem_candidate(src.count, src.dtypes[0])

        # Extract temporal metadata from TIFF tags
        temporal_start = None
        tags = src.tags() or {}
        for tag_name in ("TIFFTAG_DATETIME", "datetime", "DATE", "acquisition_date"):
            raw = tags.get(tag_name)
            if raw:
                try:
                    # TIFFTAG_DATETIME format: "YYYY:MM:DD HH:MM:SS"
                    cleaned = raw.strip().replace(":", "-", 2).split(" ")[0]
                    from datetime import date as _date

                    _date.fromisoformat(cleaned)
                    temporal_start = cleaned
                    break
                except (ValueError, IndexError):
                    continue

        return {
            "crs_wkt": crs_wkt,
            "epsg": epsg,
            "width": src.width,
            "height": src.height,
            "band_count": src.count,
            "dtype": dtype,
            "dtypes": dtypes,
            "nodata": nodata,
            "res_x": res_x,
            "res_y": res_y,
            "compression": compression,
            "blockxsize": blockxsize,
            "blockysize": blockysize,
            "tiled": tiled,
            "overview_levels": overview_levels,
            "bounds_wgs84": bounds_wgs84,
            "bbox_wkt": bbox_wkt,
            "driver": profile.get("driver"),
            "band_info": band_info,
            "is_rotated": is_rotated,
            "is_dem_candidate": is_dem,
            "temporal_start": temporal_start,
        }


def check_cog_compliance(
    file_path: str, *, expected_compression: str | None = None
) -> tuple[bool, str]:
    """Check if a file matches the GeoLens COG profile.

    Returns (True, "") if compliant or (False, reason) if not.
    If expected_compression is provided, validates against that instead of DEFLATE.
    """
    import rasterio

    with rasterio.open(file_path) as src:
        if src.crs is None:
            return False, "No CRS"

        profile = src.profile
        tiled = profile.get("tiled", False)
        if not tiled:
            return False, "Not tiled"

        blockxsize = profile.get("blockxsize", 0)
        blockysize = profile.get("blockysize", 0)
        if blockxsize != 512 or blockysize != 512:
            return False, f"Block size is {blockxsize}x{blockysize}, expected 512x512"

        compression = (profile.get("compress") or "").lower()
        target = (expected_compression or "deflate").lower()
        if compression != target:
            return False, f"Compression is '{compression}', expected '{target}'"

        overviews = src.overviews(1) if src.count >= 1 else []
        if not overviews:
            return False, "No internal overviews"

    return True, ""


def prepare_with_overviews(
    input_path: str,
    dtype: str,
    *,
    resampling: str | None = None,
    compression: str = "DEFLATE",
) -> str:
    """Copy file to a temp path and add compressed overviews.

    If the source already has internal overviews, `gdaladdo` is skipped:
    GDAL refuses to add external ones when internal are present.
    `gdal_translate COPY_SRC_OVERVIEWS=YES` picks up existing overviews.
    """
    import rasterio
    import shutil

    suffix = Path(input_path).suffix
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir=_scratch_dir())
    tmp.close()
    tmp_path = tmp.name

    shutil.copy2(input_path, tmp_path)

    # fix(#430): run_gdal raises on timeout (BA-29), which bypassed
    # the old returncode-only unlink and leaked the staged temp copy; a
    # corrupt source raising inside rasterio.open leaked it the same way.
    # Any exception past this point must remove tmp_path.
    try:
        with rasterio.open(input_path) as src:
            has_internal_overviews = bool(src.overviews(1)) if src.count >= 1 else False
        if has_internal_overviews:
            return tmp_path

        # Choose resampling based on dtype if not provided
        if resampling is None:
            resampling = "average" if _is_float_dtype(dtype) else "nearest"

        # KNOWN-03 (Phase 1071): apply the raster-pipeline GDAL safety clamps
        # (CPL_VSIL_CURL_ALLOWED_EXTENSIONS, VRT_VIRTUAL_OVERVIEWS) on top of
        # the per-call extras. v1015 Phase 1068 originally scoped these to
        # _build_vrt only.
        env = gdal_safe_env(
            extras={"GDAL_CACHEMAX": "200", "COMPRESS_OVERVIEW": compression}
        )
        cmd = [
            "gdaladdo",
            "-r",
            resampling,
            "--config",
            "COMPRESS_OVERVIEW",
            compression,
            "--config",
            "GDAL_CACHEMAX",
            "200",
            tmp_path,
            "2",
            "4",
            "8",
            "16",
            "32",
        ]
        result = run_gdal(cmd, env=env, tool="gdaladdo")  # fix(#430)
        if result.returncode != 0:
            raise RuntimeError(f"gdaladdo failed: {result.stderr}")

        return tmp_path
    except (
        Exception
    ):  # broad: cleanup-and-reraise — tmp copy must not survive any failure
        Path(tmp_path).unlink(missing_ok=True)
        raise


def _predictor_for_dtype(dtype: str, compression: str = "DEFLATE") -> str | None:
    """Return predictor based on dtype and compression.

    Only DEFLATE/ZSTD/LZW support one; JPEG/WEBP/LERC get None. See
    ``_predictor_supported`` for the sample-width check layered on top.
    """
    if compression.upper() not in ("DEFLATE", "ZSTD", "LZW"):
        return None
    return "3" if _is_float_dtype(dtype) else "2"


def _predictor_supported(file_path: str) -> bool:
    """Whether every band's actual sample width supports a GDAL PREDICTOR.

    A rasterio dtype like ``uint8`` doesn't reveal a sub-byte NBITS pack
    (1/2/4-bit LULC/palette rasters, or 12/14-bit sensor data): gdal_
    translate's PREDICTOR=2/3 hard-refuses anything outside {8,16,32,64}
    bits, failing the whole conversion (observed on an NBITS=4 raster).

    The tag lives at the BAND level — probed per band via
    ``src.tags(band, ns="IMAGE_STRUCTURE")``, since the dataset-level call
    never sees NBITS on a packed source.

    Fails closed: an incomplete probe reports "not supported" — a wrong
    False costs a slightly larger COG, a wrong True costs a failed job.
    """
    import rasterio

    try:
        with rasterio.open(file_path) as src:
            for band in range(1, src.count + 1):
                raw = src.tags(band, ns="IMAGE_STRUCTURE").get("NBITS")
                if raw is not None and int(raw) not in (8, 16, 32, 64):
                    return False
    except Exception:  # broad: best-effort probe -- fail closed (see docstring)
        return False
    return True


def convert_to_cog(
    input_path: str,
    output_path: str,
    dtype: str,
    *,
    compression: str = "DEFLATE",
    resampling: str | None = None,
    nodata: float | str | None = None,
    assign_crs: int | None = None,
) -> None:
    """Convert input file to GeoLens COG profile using gdal_translate.

    Adds overviews first via gdaladdo, then translates with COPY_SRC_OVERVIEWS.

    ``assign_crs`` ASSIGNS an EPSG code (``-a_srs``) — relabels in place,
    reprojects nothing (fix(#1291)); ``resampling`` only affects ``gdaladdo``
    overviews, never the base band.

    ``dtype`` alone isn't enough to pick a PREDICTOR: see
    ``_predictor_supported``.

    Raises RuntimeError on failure.
    """
    # fix(#1291): overviews are built from the SOURCE grid, which is also the
    # output grid — a `-a_srs` relabel moves no pixel, so `COPY_SRC_OVERVIEWS`
    # below carries them across intact. When a gdalwarp step ran first, this
    # had to consume the warped intermediate instead.
    tmp_path = prepare_with_overviews(
        input_path, dtype, resampling=resampling, compression=compression
    )
    try:
        predictor = _predictor_for_dtype(dtype, compression)
        if predictor is not None and not _predictor_supported(tmp_path):
            predictor = None
        # KNOWN-03 (Phase 1071): apply the raster-pipeline GDAL safety clamps
        # on top of GDAL_CACHEMAX=200.
        env = gdal_safe_env(extras={"GDAL_CACHEMAX": "200"})
        cmd = [
            "gdal_translate",
            "-of",
            "GTiff",
            "-co",
            f"COMPRESS={compression}",
        ]
        if predictor is not None:
            cmd.extend(["-co", f"PREDICTOR={predictor}"])
        cmd.extend(
            [
                "-co",
                "BLOCKXSIZE=512",
                "-co",
                "BLOCKYSIZE=512",
                "-co",
                "TILED=YES",
                "-co",
                "COPY_SRC_OVERVIEWS=YES",
            ]
        )
        if nodata is not None:
            cmd.extend(["-a_nodata", str(nodata)])
        if assign_crs is not None:
            # fix(#1291): -a_srs, not a gdalwarp -t_srs prepend. Both cases the
            # field documents want the samples relabelled where they are: a
            # source with no CRS has nothing to reproject FROM, and a source
            # whose declared CRS is wrong reprojects from a lie — the output
            # coordinates are wrong by construction, so nobody was served by
            # that. It sits beside -a_nodata deliberately; the two are the same
            # kind of flag, writing a tag while every band passes through.
            cmd.extend(["-a_srs", f"EPSG:{assign_crs}"])
        cmd.extend([tmp_path, output_path])
        result = run_gdal(cmd, env=env, tool="gdal_translate")  # fix(#430)
        if result.returncode != 0:
            raise RuntimeError(f"gdal_translate failed: {result.stderr}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def check_and_prepare_cog(
    file_path: str,
    output_dir: str,
    *,
    compression: str = "DEFLATE",
    resampling: str | None = None,
    nodata: float | str | None = None,
    assign_crs: int | None = None,
) -> tuple[str, str]:
    """Check compliance; convert if needed.

    Returns (path_to_use, cog_status) where cog_status is 'verified' or 'converted'.
    """
    # If user specified non-default options, always convert.
    # fix(#1291): `assign_crs` stays on this list. Assignment is metadata-only
    # in what it does to the SAMPLES, but the tag still has to be written, and
    # `-a_srs` is an argument to the translate run — there is no path that
    # relabels an already-compliant COG in place. A `verified` return here
    # would publish the source untouched, still carrying the CRS the caller
    # asked us to replace, which is the #1186 failure with a different cause.
    has_custom_opts = (
        compression != "DEFLATE"
        or resampling is not None
        or nodata is not None
        or assign_crs is not None
    )
    if not has_custom_opts:
        compliant, reason = check_cog_compliance(
            file_path, expected_compression=compression
        )
        if compliant:
            return file_path, "verified"

    meta = extract_raster_metadata(file_path)
    dtype = meta.get("dtype", "uint8")
    output_path = str(Path(output_dir) / "source.cog.tif")
    convert_to_cog(
        file_path,
        output_path,
        dtype,
        compression=compression,
        resampling=resampling,
        nodata=nodata,
        assign_crs=assign_crs,
    )
    return output_path, "converted"


def sha256_file(file_path: str) -> str:
    """Compute SHA256 hex digest of a file using 64KB chunks."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()
