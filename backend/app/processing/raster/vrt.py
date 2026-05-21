"""VRT build module: gdalbuildvrt subprocess wrappers and source path resolver."""

import os
import subprocess
from contextlib import ExitStack
from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, SubElement

from app.core.config import settings


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
            Extras win over both ``os.environ`` and ``_VRT_SAFE_ENV`` for
            keys they define. Pass ``None`` (the default) for the base clamp.

    Returns:
        A new dict suitable for ``subprocess.run(..., env=...)``.
    """
    env = {**os.environ, **_VRT_SAFE_ENV}
    if extras:
        env.update(extras)
    return env

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
        left = min(ds.bounds.left for ds in datasets)
        right = max(ds.bounds.right for ds in datasets)
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
        ) -> None:
            source = SubElement(parent, "SimpleSource")
            SubElement(source, "SourceFilename", relativeToVRT="0").text = dataset.name
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
            dst_x_off = int(round((dataset.bounds.left - left) / res_x))
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
            for dataset in datasets:
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
                    add_simple_source(band, dataset, band_index=source_band)
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
                for dataset in datasets:
                    add_simple_source(band, dataset, band_index=band_number)

        ElementTree(root).write(output_path, encoding="utf-8", xml_declaration=True)
        return output_path


def resolve_vrt_source_path(asset_uri: str) -> str:
    """Resolve a catalog asset_uri to the absolute path gdalbuildvrt should use.

    For local storage: returns an absolute filesystem path under upload_staging_dir.
    For S3: returns a /vsis3/ virtual path (permanent, not presigned — presigned
    URLs expire and would break the VRT after creation).
    """
    if settings.storage_provider == "local":
        return str(Path(settings.upload_staging_dir) / asset_uri)
    # S3 or any other provider: use GDAL's /vsis3/ virtual filesystem prefix.
    return f"/vsis3/{settings.s3_bucket}/{asset_uri}"


def _build_vrt(
    source_paths: list[str],
    output_path: str,
    resolution_strategy: str,
    *,
    separate: bool = False,
) -> str:
    """Core VRT builder wrapping gdalbuildvrt.

    Args:
        source_paths: Absolute filesystem or /vsis3/ paths to source COG files.
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
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=gdal_safe_env(),
        )
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
