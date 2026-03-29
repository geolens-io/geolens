"""COG compliance check, conversion, and raster metadata extraction."""

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path


_FLOAT_DTYPES = {"float32", "float64", "float16", "float", "complex"}


def _is_float_dtype(dtype: str) -> bool:
    """Check if a raster dtype string represents a floating-point type."""
    return any(f in dtype.lower() for f in _FLOAT_DTYPES)


def validate_raster_crs(file_path: str) -> None:
    """Raise ValueError if the raster file has no valid CRS."""
    import rasterio

    with rasterio.open(file_path) as src:
        if src.crs is None:
            raise ValueError(
                "Missing CRS: raster has no coordinate reference system. "
                "Ensure the GeoTIFF includes an embedded CRS."
            )


def extract_raster_metadata(file_path: str) -> dict:
    """Extract all raster metadata from a file using a single rasterio open pass."""
    import rasterio
    from rasterio.warp import transform_bounds

    with rasterio.open(file_path) as src:
        crs = src.crs
        crs_wkt = crs.to_wkt() if crs else None
        epsg = crs.to_epsg() if crs else None

        # Transform bounds to WGS84
        if crs and crs.to_epsg() != 4326:
            bounds_wgs84 = transform_bounds(crs, "EPSG:4326", *src.bounds)
        else:
            bounds_wgs84 = (
                src.bounds.left,
                src.bounds.bottom,
                src.bounds.right,
                src.bounds.top,
            )

        left, bottom, right, top = bounds_wgs84
        bbox_wkt = (
            f"POLYGON(({left} {bottom}, {right} {bottom}, "
            f"{right} {top}, {left} {top}, {left} {bottom}))"
        )

        res_x = abs(src.transform.a)
        res_y = abs(src.transform.e)
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
        for i in range(1, src.count + 1):
            band_info.append(
                {
                    "index": i,
                    "dtype": src.dtypes[i - 1],
                    "nodata": str(src.nodata) if src.nodata is not None else None,
                    "color_interp": src.colorinterp[i - 1].name,
                }
            )

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

    Returns the temp path with overviews added.
    """
    suffix = Path(input_path).suffix
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.close()
    tmp_path = tmp.name

    # Copy original to temp
    import shutil

    shutil.copy2(input_path, tmp_path)

    # Choose resampling based on dtype if not provided
    if resampling is None:
        resampling = "average" if _is_float_dtype(dtype) else "nearest"

    env = {**os.environ, "GDAL_CACHEMAX": "200", "COMPRESS_OVERVIEW": compression}
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
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        Path(tmp_path).unlink(missing_ok=True)
        raise RuntimeError(f"gdaladdo failed: {result.stderr}")

    return tmp_path


def _predictor_for_dtype(dtype: str, compression: str = "DEFLATE") -> str | None:
    """Return predictor based on dtype and compression.

    Predictors only work for DEFLATE, ZSTD, and LZW.
    Returns None for JPEG, WEBP, LERC (no predictor applicable).
    """
    if compression.upper() not in ("DEFLATE", "ZSTD", "LZW"):
        return None
    return "3" if _is_float_dtype(dtype) else "2"


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
    Optionally reprojects via gdalwarp if assign_crs is provided.
    Raises RuntimeError on failure.
    """
    actual_input = input_path

    # If CRS assignment requested, prepend a gdalwarp step
    warp_tmp: str | None = None
    if assign_crs is not None:
        warp_tmp_file = tempfile.NamedTemporaryFile(suffix=".tif", delete=False)
        warp_tmp_file.close()
        warp_tmp = warp_tmp_file.name
        warp_cmd = [
            "gdalwarp",
            "-t_srs",
            f"EPSG:{assign_crs}",
        ]
        if resampling:
            warp_cmd.extend(["-r", resampling])
        warp_cmd.extend([input_path, warp_tmp])
        warp_result = subprocess.run(warp_cmd, capture_output=True, text=True)
        if warp_result.returncode != 0:
            Path(warp_tmp).unlink(missing_ok=True)
            raise RuntimeError(f"gdalwarp failed: {warp_result.stderr}")
        actual_input = warp_tmp

    tmp_path = prepare_with_overviews(
        actual_input, dtype, resampling=resampling, compression=compression
    )
    try:
        predictor = _predictor_for_dtype(dtype, compression)
        env = {**os.environ, "GDAL_CACHEMAX": "200"}
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
        cmd.extend([tmp_path, output_path])
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if result.returncode != 0:
            raise RuntimeError(f"gdal_translate failed: {result.stderr}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        if warp_tmp:
            Path(warp_tmp).unlink(missing_ok=True)


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
    # If user specified non-default options, always convert
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
