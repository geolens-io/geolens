"""Upload file validation: magic bytes, zip safety, size limits.

Validates uploaded files beyond extension checks:
- Content-type verification via magic byte detection (puremagic)
- ZIP archive safety (compression ratio, nested archives, decompressed size)
- File size enforcement against configured limits
"""

import zipfile
from pathlib import Path

import puremagic
import structlog

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
}

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


def validate_file_content(file_path: str, filename: str) -> None:
    """Verify file content matches declared extension via magic bytes.

    Raises ValueError with user-friendly message on mismatch or empty file.
    """
    suffix = Path(filename).suffix.lower()

    with open(file_path, "rb") as f:
        header = f.read(HEADER_READ_SIZE)

    if len(header) == 0:
        raise ValueError("The uploaded file is empty.")

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
