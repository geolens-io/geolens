"""Upload file validation: magic bytes, zip safety, size limits.

Validates uploaded files beyond extension checks:
- Content-type verification via magic byte detection (puremagic)
- ZIP archive safety (compression ratio, nested archives, decompressed size)
- File size enforcement against configured limits
- VRT XML sniff + path-traversal guard on `<SourceFilename>` body (IA-P1-03)
"""

import re
import zipfile
from pathlib import Path

import puremagic
import structlog

from app.processing.raster.vrt import VRT_VSI_ALLOWED_PREFIXES

logger = structlog.get_logger()

# --- Constants ---

HEADER_READ_SIZE = 8192

# Maps file extension to set of acceptable puremagic-detected extensions
EXTENSION_CONTENT_MAP: dict[str, set[str]] = {
    ".zip": {".zip"},
    ".gpkg": {".gpkg", ".sqlite", ".db", ".sqlite3"},
    ".geojson": {".json", ".geojson"},
    ".json": {".json", ".geojson"},
    ".csv": {".csv", ".txt", ""},
    ".tif": {".tif", ".tiff"},
    ".tiff": {".tif", ".tiff"},
    ".xlsx": {".xlsx", ".zip", ".docx"},  # OOXML shares ZIP container
    ".xls": {".xls", ".doc"},  # Old BIFF format
}

# Maximum bytes to read when scanning a .vrt body for path-traversal markers.
VRT_BODY_SCAN_LIMIT = 256 * 1024  # 256 KiB

# Regex to extract <SourceFilename> body content from VRT XML. The VRT
# driver supports both relative paths and absolute paths; we reject any
# `..` segment or absolute path that escapes the staging directory.
_VRT_SOURCEFILENAME_RE = re.compile(
    rb"<SourceFilename(?:[^>]*)>([^<]*)</SourceFilename>",
    re.IGNORECASE,
)

# ZIP bomb thresholds
MAX_COMPRESSION_RATIO = 500
MAX_DECOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB

ARCHIVE_EXTENSIONS = frozenset(
    {
        ".zip",
        ".tar",
        ".gz",
        ".tgz",
        ".rar",
        ".7z",
        ".bz2",
        ".xz",
    }
)


def _is_text_content(header: bytes) -> bool:
    """Check if header bytes appear to be text (no null bytes)."""
    return b"\x00" not in header


def validate_vrt_body(file_path: str) -> None:
    """Validate a .vrt file's XML body for path-traversal markers.

    IA-P1-03 (Phase 1068): the GDAL VRT driver follows `<SourceFilename>`
    body content as if it were a path/URL. A malicious VRT can declare
    `<SourceFilename>../../etc/hostname</SourceFilename>` and GDAL will
    happily open the resolved path, leaking host content into the raster
    pipeline. Defense-in-depth alongside the staging-dir resolution check
    in `manifest_sources.classify_manifest_source`.

    Rejects:
    - VRTs whose XML body doesn't start with `<VRTDataset`
    - `<SourceFilename>` containing any `..` segment
    - `<SourceFilename>` resolving to an absolute path (`/etc/x` etc.)
      EXCEPT recognized GDAL VSI prefixes listed in
      ``VRT_VSI_ALLOWED_PREFIXES`` (raster/vrt.py) which the COG ingest
      path legitimately uses for managed-storage VRTs.

    Raises ValueError with user-friendly message on any violation.
    """
    # Cap read size — VRTs should be small XML. Anything beyond a few KB
    # is suspicious in itself, but we cap at 256 KiB for safety while
    # still allowing legitimate large band-stacks (~thousands of sources).
    with open(file_path, "rb") as f:
        body = f.read(VRT_BODY_SCAN_LIMIT)

    if not body:
        raise ValueError("The uploaded VRT file is empty.")

    # Strip leading whitespace + XML declaration; the root element must
    # be VRTDataset for this to be a valid VRT.
    stripped = body.lstrip()
    if stripped.startswith(b"<?xml"):
        # Skip past the XML declaration
        idx = stripped.find(b"?>")
        if idx != -1:
            stripped = stripped[idx + 2 :].lstrip()
    if not stripped.startswith(b"<VRTDataset"):
        raise ValueError(
            "File has .vrt extension but is not a valid VRT XML document "
            "(missing <VRTDataset root element)."
        )

    # Scan every <SourceFilename> for path-traversal markers.
    # VSI prefix allow-list lives in raster/vrt.py as the single source
    # of truth — KNOWN-04 (Phase 1071).
    for match in _VRT_SOURCEFILENAME_RE.finditer(body):
        raw_path = match.group(1).decode("utf-8", errors="replace").strip()
        # Reject `..` segments anywhere in the path
        if ".." in raw_path:
            logger.warning(
                "VRT body contains path-traversal marker",
                event_type="security",
                reason="vrt_path_traversal",
                source_filename=raw_path[:200],
            )
            raise ValueError(
                f"VRT <SourceFilename> contains path-traversal marker: {raw_path!r}. "
                "Use relative paths without '..' segments or VSI URIs."
            )
        # Reject absolute paths unless they're GDAL VSI prefixes
        if raw_path.startswith("/") and not raw_path.startswith(
            VRT_VSI_ALLOWED_PREFIXES
        ):
            logger.warning(
                "VRT body contains absolute filesystem path",
                event_type="security",
                reason="vrt_absolute_path",
                source_filename=raw_path[:200],
            )
            raise ValueError(
                f"VRT <SourceFilename> uses absolute path: {raw_path!r}. "
                "Use relative paths or VSI URIs (e.g., /vsis3/, /vsicurl/)."
            )


def validate_file_content(file_path: str, filename: str) -> None:
    """Verify file content matches declared extension via magic bytes.

    Raises ValueError with user-friendly message on mismatch or empty file.
    """
    suffix = Path(filename).suffix.lower()

    # IA-P1-03: .vrt gets its own XML+traversal check (magic bytes are
    # XML which puremagic doesn't reliably distinguish from generic text).
    if suffix == ".vrt":
        validate_vrt_body(file_path)
        return

    with open(file_path, "rb") as f:
        header = f.read(HEADER_READ_SIZE)

    if len(header) == 0:
        raise ValueError("The uploaded file is empty.")

    # Skip magic-byte validation for extensions without known content rules
    if suffix not in EXTENSION_CONTENT_MAP:
        return

    try:
        detected = puremagic.from_string(header, filename=filename)
    except puremagic.PureError:
        detected = ""

    allowed = EXTENSION_CONTENT_MAP.get(suffix, set())

    if detected in allowed:
        return

    # Text-based formats may not be detected by puremagic.
    # Allow if content appears to be text (no null bytes).
    if suffix in (".geojson", ".json", ".csv") and _is_text_content(header):
        return

    logger.warning(
        "Upload content mismatch",
        event_type="security",
        reason="content_mismatch",
        filename=filename,
        declared_extension=suffix,
        detected_type=detected,
    )
    raise ValueError(
        f"File content detected as '{detected or 'unknown'}' "
        f"but extension is '{suffix}'. "
        f"Please upload with the correct extension."
    )


def validate_zip_safety(file_path: str) -> None:
    """Check ZIP archive for bomb indicators without extracting.

    Raises ValueError if:
    - File is not a valid ZIP
    - Any entry has compression ratio > MAX_COMPRESSION_RATIO
    - Any entry is a nested archive
    - Total decompressed size > MAX_DECOMPRESSED_BYTES
    """
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            total_uncompressed = 0

            for info in zf.infolist():
                total_uncompressed += info.file_size

                # Per-entry compression ratio check
                if info.compress_size > 0:
                    ratio = info.file_size / info.compress_size
                    if ratio > MAX_COMPRESSION_RATIO:
                        logger.warning(
                            "ZIP bomb indicator: high compression ratio",
                            event_type="security",
                            reason="zip_bomb_indicator",
                            filename=Path(file_path).name,
                            entry=info.filename,
                            ratio=f"{ratio:.0f}:1",
                        )
                        raise ValueError(
                            f"ZIP entry '{info.filename}' has suspicious compression "
                            f"ratio ({ratio:.0f}:1). Maximum allowed is "
                            f"{MAX_COMPRESSION_RATIO}:1."
                        )

                # Nested archive check
                entry_ext = Path(info.filename).suffix.lower()
                if entry_ext in ARCHIVE_EXTENSIONS:
                    logger.warning(
                        "ZIP contains nested archive",
                        event_type="security",
                        reason="nested_archive",
                        filename=Path(file_path).name,
                        nested_entry=info.filename,
                    )
                    raise ValueError(
                        f"ZIP contains nested archive '{info.filename}'. "
                        f"Nested archives are not supported for geospatial uploads."
                    )

            # Total decompressed size check
            if total_uncompressed > MAX_DECOMPRESSED_BYTES:
                size_gb = total_uncompressed / (1024**3)
                limit_gb = MAX_DECOMPRESSED_BYTES // (1024**3)
                logger.warning(
                    "ZIP bomb indicator: excessive decompressed size",
                    event_type="security",
                    reason="zip_bomb_indicator",
                    filename=Path(file_path).name,
                    decompressed_gb=f"{size_gb:.1f}",
                )
                raise ValueError(
                    f"ZIP total decompressed size ({size_gb:.1f} GB) exceeds "
                    f"the {limit_gb} GB limit."
                )

    except zipfile.BadZipFile:
        raise ValueError("File has .zip extension but is not a valid ZIP archive.")


def validate_file_size(file_path: str, max_size_bytes: int) -> None:
    """Verify file does not exceed configured size limit.

    Raises ValueError with user-friendly message if exceeded.
    """
    file_size = Path(file_path).stat().st_size
    if file_size > max_size_bytes:
        size_mb = file_size / (1024 * 1024)
        limit_mb = max_size_bytes / (1024 * 1024)
        raise ValueError(
            f"File size ({size_mb:.1f} MB) exceeds the maximum allowed ({limit_mb:.0f} MB)."
        )
