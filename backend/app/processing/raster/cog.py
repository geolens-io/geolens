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


# fix(#1290 review): compression profiles that reproduce every input sample
# exactly. An ALLOWLIST, and the direction is the point: `compression` reaches
# the worker straight off `RasterCommitRequest` with no server-side vocabulary
# check, so a value nothing here recognises has to fall on the "assume lossy,
# keep the original" side. Getting that backwards deletes the only lossless
# copy of a raster. The import UI currently offers four of these plus JPEG and
# WEBP, which are the two that must NOT appear here.
#
# LERC is here on a condition, and the condition is a fact about our own argv
# rather than about the codec. LERC's error bound is the GTiff creation option
# MAX_Z_ERROR, whose default is 0 — exact — and `convert_to_cog` never passes
# it, so a LERC conversion reproduces the base samples bit for bit. Verified
# three ways: the GDAL docs
# (https://gdal.org/en/stable/drivers/raster/gtiff.html#creation-options), the
# deployed GDAL 3.10.3's own declaration (`gdalinfo --format GTiff` reports
# MAX_Z_ERROR and MAX_Z_ERROR_OVERVIEW with default="0"), and a float32
# round-trip through this module's exact argv, which came back identical.
# The moment someone passes a nonzero MAX_Z_ERROR this entry is wrong, so it
# is pinned: `test_lerc_stays_lossless_only_while_no_error_bound_is_set` fails
# on that edit rather than leaving it to be discovered after an original has
# already been deleted.
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

    fix(#1290 review). ADR-002 Decision 7 licenses deleting the pre-conversion
    upload on the stated grounds that "conversion is lossless". That is a claim
    about what the conversion DID, and there is more than one way for it to be
    false.

    The audit of everything ``convert_to_cog`` can apply, so the next reader
    does not have to redo it:

    - **compression** — JPEG and WEBP discard detail. Sample-altering. LERC
      does not, at the zero error bound this pipeline leaves in place; the
      condition that keeps that true is spelled out on
      ``LOSSLESS_COG_COMPRESSIONS``.
    - **assign_crs** — fix(#1291): ``gdal_translate -a_srs``, which writes a
      CRS tag and nothing else. Exactly like ``-a_nodata`` below: the bands
      pass through the translate untouched, so under a lossless codec the
      output carries the uploaded samples bit for bit. Measured on the
      deployed GDAL: a 32x32 source relabelled 4326 -> 3857 comes back 32x32,
      same bounds numbers, array-equal to the input. NOT sample-altering.
      Until #1291 this ran ``gdalwarp -t_srs``, which resampled onto a new
      grid (the same 32x32 source came back 42x42 with different values) —
      hence ``reprojected``, and hence this bullet's earlier reading.
    - **resampling** — feeds ``gdaladdo`` only now (overviews are additional
      data, the base band is untouched). It used to also feed ``gdalwarp -r``;
      with the warp gone, no ``resampling`` value can reach the base samples.
    - **nodata** — ``gdal_translate -a_nodata`` writes a metadata tag. Pixel
      values are byte-identical, so this is not sample-altering; it changes how
      the samples are interpreted, not what they are.
    - **overviews / tiling / COPY_SRC_OVERVIEWS** — add or rearrange, never
      discard.

    So the predicate is "no lossy codec AND no warp". Anything not proven
    sample-preserving must return False: the cost of a wrong True is the
    permanent loss of the only faithful copy, and the cost of a wrong False is
    some retained bytes. That asymmetry is why #1291 argues the assign_crs move
    rather than just making it: a relabel is the one conversion step that is
    REVERSIBLE from the stored artifact. If the caller assigns the wrong EPSG,
    every sample is still there and another ``-a_srs`` corrects it; the
    catalog also keeps what the upload declared, in ``Dataset.original_srid``.
    A warp is not reversible, which is what made the retained upload the only
    faithful copy while one ran.

    ``reprojected`` stays as the switch for that second axis even though no
    pipeline path sets it today: a deliberate reproject-at-ingest field
    (``target_srid``, if demand ever appears — #1291) has to pass it, and a
    parameter that is already here and already tested is one fewer thing for
    that change to forget. ``convert_to_cog`` running no ``gdalwarp`` is what
    licenses the callers passing nothing, and that is pinned by
    ``test_cog_subprocess_env.py``.

    ``cog_status == "verified"`` short-circuits because nothing ran at all —
    the bytes written to storage ARE the uploaded bytes, whatever codec they
    already carried. A conversion cannot coexist with it:
    ``check_and_prepare_cog`` treats any ``assign_crs`` as a custom option and
    always converts.
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

    Which code, only. What "apply" DOES belongs to ``convert_to_cog``, and
    since fix(#1291) it is assignment: the returned code is written onto the
    output as a label (``-a_srs``) and no sample is touched. This function did
    not change with that — it never knew whether the code would be warped to
    or stamped on — but its callers' comments did.

    fix(#1290 review): an override applies whenever the caller supplies one,
    not only when the source declares nothing. ``RasterCommitRequest``
    documents this field as "EPSG code to use when source CRS is missing **or
    incorrect**", and correcting a wrong declaration was precisely the case the
    old ``if crs_missing`` guard dropped on the floor — the conversion ran
    without the override and published a raster still carrying the CRS the
    caller had just told us was wrong, with no error to say so.

    Shared by first ingest and replace deliberately. The two tails held
    identical copies of the old predicate and were wrong in identical ways;
    leaving them as two copies is how the next fix lands on one of them.

    Raises ``ValueError`` when the source declares no CRS and no override was
    given — the one case where the pipeline genuinely cannot proceed.
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
    """Check if a raster dtype string represents a floating-point type."""
    return any(f in dtype.lower() for f in _FLOAT_DTYPES)


def is_dem_candidate(band_count: int | None, dtype: str | None) -> bool:
    """Whether a raster of this shape is elevation data rather than imagery.

    One band of floating-point values is what a DEM looks like and what
    imagery does not. The rule is a heuristic, but it has to be the SAME
    heuristic everywhere: ``raster_tile_proxy`` branches on the stored flag
    before it looks at anything else, so a raster classified one way here and
    another way there is served through the wrong renderer — terrainrgb over
    RGB imagery, or ordinary imagery over an elevation model.

    feat(#1266): named and shared because a second caller needs it. The STAC
    refresh strategy adopts a COG the publisher moved to, and the shape of
    that object is a property of the object rather than of the row it
    replaces. It reads band count and dtype through Titiler rather than
    rasterio, which is why this takes the two values instead of a dataset
    handle.
    """
    return bool(band_count == 1 and dtype and _is_float_dtype(dtype))


def _scratch_dir() -> str | None:
    """Directory for COG temp copies (fix #448).

    tempfile's default lands in /tmp — a 512 MB RAM-backed tmpfs in the
    worker container — so a large raster both eats the memory cap and can
    ENOSPC mid-conversion. Prefer the upload_staging volume (disk-backed,
    shared mount). None falls back to the tempfile default for host runs
    and tests where the staging dir doesn't exist.
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

    fix(#887): GDAL passes geographic bounds through ``transform_bounds``
    untouched, so a raster stored in the 0..360 longitude domain -- what plenty
    of published global grids use, and what the seam-aware VRT builder in
    ``vrt.py`` now emits for a straddling mosaic -- keeps an east past +180.
    Wrap it, and let east fall *below* west when the footprint crosses the seam;
    ``bbox_to_extent_wkt`` turns that pair into the two-ring extent.
    """
    span = east - west
    if span >= 360.0 - LON_EPSILON_DEGREES:
        # The footprint wraps the whole world. -180..180 is the honest answer
        # and the only one a single ring can express. The tolerance matters: a
        # 0..360 global raster whose span measures 359.99999999999994 would
        # otherwise fall through and be re-expressed as a west > east pair, i.e.
        # a domain flip decided by last-bit noise.
        return (-180.0, south, 180.0, north)
    # fix(#887): reduce ARBITRARY wrap counts before folding. GDAL accepts a
    # raster georeferenced well outside the adjacent domains, and wrap_longitude
    # subtracts a single turn by design (#886), so a 720..730 source folded to
    # 360..10 -- which bbox_to_extent_wkt reads as a crossing pair, drops the
    # impossible 360..180 half from, and records as -180..10: a 10-degree
    # footprint inflated to 190. The negative direction was worse: -730..-720
    # recorded 37x its true area. fmod first, then the shared single-step fold,
    # which keeps +180 as +180 -- bbox_to_extent_wkt relies on that to drop the
    # zero-width 180..180 half and emit the -180..east ring alone.
    west = wrap_longitude(math.fmod(west, 360.0))
    # `span` is under 360 by the branch above, so one step settles east.
    east = wrap_longitude(west + span)
    return (west, south, east, north)


def _wgs84_bbox(src) -> tuple[float, float, float, float]:
    """Reproject a raster's bounds to a WGS84 RFC 7946 §5.2 bbox.

    Returns ``(west, south, east, north)`` with ``west > east`` when the
    footprint crosses the antimeridian -- feed it to
    :func:`app.core.geo.bbox_to_extent_wkt`, never to a hand-built ring.

    fix(#887): the old code folded the reprojected bounds straight into a single
    ``POLYGON``. GDAL's ``OCTTransformBounds`` already reports a seam-crossing
    footprint as ``west > east`` (a Pacific COG in EPSG:3832 comes back as
    175..-175), and a naive ring over that pair is a *valid* rectangle covering
    the 350° on the wrong side of the world -- 35x the real footprint, not even
    containing the data it describes.
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
        # fix(#1376): explicitly WKT2, because this value is what
        # RasterAsset.to_stac_properties() publishes as the STAC Projection
        # Extension's `proj:wkt2`. rasterio's default is WKT1_GDAL
        # (`PROJCS[...]`), which a strict consumer of a wkt2-named field may
        # reject. The remote-asset probe (catalog/sources/cog_info.py) asks
        # for the same version, so the column is one dialect regardless of
        # how the raster was ingested. WKT2 also expresses strictly more than
        # WKT1 — nothing GDAL can open exports here but not there — so this
        # narrows no input.
        crs_wkt = crs.to_wkt(version="WKT2_2019") if crs else None
        epsg = crs.to_epsg() if crs else None

        bounds_wgs84 = _wgs84_bbox(src)
        bbox_wkt = bbox_to_extent_wkt(*bounds_wgs84)

        # fix(#1375 review): the pixel VECTOR lengths, not their world-axis
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

    Returns the temp path with overviews added. If the source already has
    internal overviews (e.g. an upstream COG produced by `-of COG` or by a
    user pipeline that built them), `gdaladdo` is skipped: GDAL refuses to
    add external overviews when internal overviews are present
    ("ERROR 6: Cannot add external overviews when there are already
    internal overviews"). `gdal_translate ... COPY_SRC_OVERVIEWS=YES`
    downstream still picks up the existing overviews, so the COG output is
    correct either way.
    """
    import rasterio
    import shutil

    suffix = Path(input_path).suffix
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir=_scratch_dir())
    tmp.close()
    tmp_path = tmp.name

    shutil.copy2(input_path, tmp_path)

    # fix(#430 codex r15): run_gdal raises on timeout (BA-29), which bypassed
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
        result = run_gdal(cmd, env=env, tool="gdaladdo")  # fix(#430 BA-29)
        if result.returncode != 0:
            raise RuntimeError(f"gdaladdo failed: {result.stderr}")

        return tmp_path
    except Exception:  # broad: cleanup-and-reraise — tmp copy must not survive ANY failure (run_gdal timeout, corrupt-source rasterio error)
        Path(tmp_path).unlink(missing_ok=True)
        raise


def _predictor_for_dtype(dtype: str, compression: str = "DEFLATE") -> str | None:
    """Return predictor based on dtype and compression.

    Predictors only work for DEFLATE, ZSTD, and LZW.
    Returns None for JPEG, WEBP, LERC (no predictor applicable).

    A rasterio dtype string alone is not the whole story: see
    ``_predictor_supported`` for the sample-width check ``convert_to_cog``
    layers on top of this before it lets a predictor onto the argv.
    """
    if compression.upper() not in ("DEFLATE", "ZSTD", "LZW"):
        return None
    return "3" if _is_float_dtype(dtype) else "2"


def _predictor_supported(file_path: str) -> bool:
    """Whether every band's actual sample width supports a GDAL PREDICTOR.

    A rasterio dtype like ``uint8`` does not say how many bits a sample
    occupies: GDAL's ``IMAGE_STRUCTURE`` ``NBITS`` tag sub-byte-packs 1/2/4-bit
    samples (common for LULC/palette rasters) or non-standard widths (e.g.
    12/14-bit sensor data) into a wider dtype container. gdal_translate's
    ``PREDICTOR=2``/``PREDICTOR=3`` creation options hard-refuse anything
    outside {8, 16, 32, 64} bits -- ``ERROR 1: ... PREDICTOR=2 is only
    supported with 8/16/32/64 bit samples`` -- which fails the whole COG
    conversion (observed in production on an NBITS=4 LULC raster).

    The tag lives at the BAND level, not the dataset level: calling
    ``src.tags(ns="IMAGE_STRUCTURE")`` with no band index returns only
    ``INTERLEAVE`` for a packed source and never sees ``NBITS`` at all, so
    every band is probed individually via
    ``src.tags(band, ns="IMAGE_STRUCTURE")``. A source that declares no
    NBITS on any band is trusted at its rasterio dtype, which is always one
    of 8/16/32/64; this only disables the predictor when a band explicitly
    declares a narrower one.

    Fails closed: a probe that cannot complete (unreadable file, unexpected
    tag value) reports "not supported" rather than risk reproducing the
    gdal_translate failure this exists to prevent -- the cost of a wrong
    False here is a slightly larger COG, the cost of a wrong True is a
    failed ingest job.
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

    ``assign_crs`` ASSIGNS an EPSG code to the output (``-a_srs``) — it
    relabels the raster where it already sits and reprojects nothing
    (fix(#1291); see the decision on that issue). ``resampling`` therefore
    reaches ``gdaladdo`` and nothing else: it decides how overviews are
    built, never what the base band contains.

    ``dtype`` alone is not enough to pick a PREDICTOR: see
    ``_predictor_supported`` for why a low-bit-depth source (NBITS < 8, e.g.
    LULC/palette rasters) must skip it or gdal_translate refuses to run at
    all.

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
        result = run_gdal(cmd, env=env, tool="gdal_translate")  # fix(#430 BA-29)
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
