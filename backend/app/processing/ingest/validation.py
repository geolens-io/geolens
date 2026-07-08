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

from defusedxml import ElementTree as ET
import puremagic
import structlog

from app.core.url_redaction import redact_url_credentials

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

# Maximum uploaded VRT XML size. User-provided VRTs are control-plane XML, not
# raster payloads; fail closed instead of partially scanning a prefix.
VRT_BODY_MAX_BYTES = 2 * 1024 * 1024
VRT_BODY_SCAN_LIMIT = VRT_BODY_MAX_BYTES  # backward-compatible exported name

_URL_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")

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


def _xml_local_name(tag: object) -> str:
    text = str(tag)
    return text.rsplit("}", 1)[-1]


def _reject_uploaded_vrt_source(raw_path: str) -> None:
    """Reject SourceFilename values that can escape the staged upload bundle."""
    if not raw_path:
        raise ValueError("VRT <SourceFilename> is empty.")
    if "\x00" in raw_path:
        raise ValueError("VRT <SourceFilename> contains a null byte.")
    if ".." in raw_path:
        logger.warning(
            "VRT body contains path-traversal marker",
            event_type="security",
            reason="vrt_path_traversal",
            source_filename=redact_url_credentials(raw_path)[:200],
        )
        raise ValueError(
            "VRT <SourceFilename> contains a path-traversal marker. "
            "Use relative paths without '..' segments."
        )
    if (
        raw_path.startswith("/")
        or raw_path.startswith("\\\\")
        or _WINDOWS_ABSOLUTE_RE.match(raw_path)
    ):
        logger.warning(
            "VRT body contains absolute source path",
            event_type="security",
            reason="vrt_absolute_path",
            source_filename=redact_url_credentials(raw_path)[:200],
        )
        raise ValueError(
            "VRT <SourceFilename> uses an absolute path. "
            "Uploaded VRTs may only reference relative files in the upload bundle."
        )
    if _URL_SCHEME_RE.match(raw_path) or raw_path.lower().startswith("/vsi"):
        logger.warning(
            "VRT body contains remote or VSI source",
            event_type="security",
            reason="vrt_remote_source",
            source_filename=redact_url_credentials(raw_path)[:200],
        )
        raise ValueError(
            "VRT <SourceFilename> uses a remote or GDAL VSI source. "
            "Uploaded VRTs may only reference relative files in the upload bundle."
        )


def validate_vrt_body(file_path: str) -> None:
    """Validate a user-uploaded .vrt file's XML body.

    IA-P1-03 (Phase 1068): the GDAL VRT driver follows `<SourceFilename>`
    body content as if it were a path/URL. A malicious VRT can declare
    `<SourceFilename>../../etc/hostname</SourceFilename>` and GDAL will
    happily open the resolved path, leaking host content into the raster
    pipeline. Defense-in-depth alongside the staging-dir resolution check
    in `manifest_sources.classify_manifest_source`.

    Rejects:
    - VRTs whose XML body doesn't start with `<VRTDataset`
    - `<SourceFilename>` containing any `..` segment
    - `<SourceFilename>` resolving to an absolute path, URL, or GDAL VSI path.
      Internally generated managed-storage VRTs are produced by the raster/VRT
      pipeline and do not pass through this user-upload validator.

    Raises ValueError with user-friendly message on any violation.
    """
    with open(file_path, "rb") as f:
        body = f.read(VRT_BODY_MAX_BYTES + 1)

    if not body:
        raise ValueError("The uploaded VRT file is empty.")
    if len(body) > VRT_BODY_MAX_BYTES:
        raise ValueError(
            f"Uploaded VRT XML exceeds the {VRT_BODY_MAX_BYTES // (1024 * 1024)} MB limit."
        )

    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise ValueError(
            "File has .vrt extension but is not a valid VRT XML document "
            f"(missing <VRTDataset root element or invalid XML: {exc})."
        ) from exc

    if _xml_local_name(root.tag) != "VRTDataset":
        raise ValueError(
            "File has .vrt extension but is not a valid VRT XML document "
            "(missing <VRTDataset root element)."
        )

    for elem in root.iter():
        if _xml_local_name(elem.tag) == "SourceFilename":
            _reject_uploaded_vrt_source((elem.text or "").strip())


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
