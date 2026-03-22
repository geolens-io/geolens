"""VRT build module: gdalbuildvrt subprocess wrappers and source path resolver."""

import subprocess
from pathlib import Path

from app.config import settings

# Maps VrtCreateRequest resolution_strategy values to gdalbuildvrt -resolution values.
_RES_MAP: dict[str, str] = {
    "finest": "highest",
    "coarsest": "lowest",
    "average": "average",
}


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
    result = subprocess.run(cmd, capture_output=True, text=True)
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
        source_paths, output_path, resolution_strategy,
        separate=(vrt_type == "band_stack"),
    )
