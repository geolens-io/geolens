"""Upload file validation: magic bytes, zip safety, size limits.

Validates uploaded files beyond extension checks:
- Content-type verification via magic byte detection (puremagic)
- ZIP archive safety (compression ratio, nested archives, decompressed size)
- File size enforcement against configured limits
- VRT XML sniff + path-traversal guard on `<SourceFilename>` body (IA-P1-03)
"""

import re
import struct
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
MAX_ARCHIVE_ENTRIES = 10_000
MAX_CENTRAL_DIRECTORY_BYTES = 32 * 1024 * 1024
ZIP_CONTAINER_EXTENSIONS = frozenset({".zip", ".xlsx"})

_EOCD_SIGNATURE = b"PK\x05\x06"
_ZIP64_EOCD_SIGNATURE = b"PK\x06\x06"
_ZIP64_LOCATOR_SIGNATURE = b"PK\x06\x07"
_CENTRAL_FILE_SIGNATURE = b"PK\x01\x02"
_CENTRAL_DIGITAL_SIGNATURE = b"PK\x05\x05"
_EOCD = struct.Struct("<4s4H2LH")
_ZIP64_LOCATOR = struct.Struct("<4sLQL")
_ZIP64_EOCD = struct.Struct("<4sQ2H2L4Q")
_CENTRAL_FILE_HEADER = struct.Struct("<4s6H3L5H2L")

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


def _zip_directory_metadata(file_path: str) -> tuple[int, int, int]:
    """Return member count, central-directory offset, and size without parsing members."""
    path = Path(file_path)
    file_size = path.stat().st_size
    tail_size = min(file_size, _EOCD.size + 65_535)

    with path.open("rb") as archive:
        archive.seek(file_size - tail_size)
        tail = archive.read(tail_size)

        search_end = len(tail)
        eocd_offset = -1
        eocd: tuple | None = None
        while search_end > 0:
            candidate = tail.rfind(_EOCD_SIGNATURE, 0, search_end)
            if candidate < 0:
                break
            if candidate + _EOCD.size <= len(tail):
                unpacked = _EOCD.unpack_from(tail, candidate)
                comment_length = unpacked[7]
                if candidate + _EOCD.size + comment_length == len(tail):
                    eocd_offset = file_size - tail_size + candidate
                    eocd = unpacked
                    break
            search_end = candidate

        if eocd is None:
            raise zipfile.BadZipFile("End of central directory not found")

        (
            _signature,
            disk_number,
            directory_disk,
            entries_on_disk,
            total_entries,
            directory_size,
            directory_offset,
            _comment_length,
        ) = eocd

        uses_zip64 = (
            entries_on_disk == 0xFFFF
            or total_entries == 0xFFFF
            or directory_size == 0xFFFFFFFF
            or directory_offset == 0xFFFFFFFF
        )
        if uses_zip64:
            locator_offset = eocd_offset - _ZIP64_LOCATOR.size
            if locator_offset < 0:
                raise zipfile.BadZipFile("ZIP64 locator not found")
            archive.seek(locator_offset)
            locator = archive.read(_ZIP64_LOCATOR.size)
            if len(locator) != _ZIP64_LOCATOR.size:
                raise zipfile.BadZipFile("Truncated ZIP64 locator")
            locator_signature, zip64_disk, zip64_offset, total_disks = (
                _ZIP64_LOCATOR.unpack(locator)
            )
            if locator_signature != _ZIP64_LOCATOR_SIGNATURE:
                raise zipfile.BadZipFile("ZIP64 locator not found")
            if zip64_disk != 0 or total_disks != 1:
                raise zipfile.BadZipFile("Multi-disk ZIP archives are not supported")

            archive.seek(zip64_offset)
            record = archive.read(_ZIP64_EOCD.size)
            if len(record) != _ZIP64_EOCD.size:
                raise zipfile.BadZipFile("Truncated ZIP64 end record")
            values = _ZIP64_EOCD.unpack(record)
            if values[0] != _ZIP64_EOCD_SIGNATURE:
                raise zipfile.BadZipFile("ZIP64 end record not found")
            disk_number = values[4]
            directory_disk = values[5]
            entries_on_disk = values[6]
            total_entries = values[7]
            directory_size = values[8]
            directory_offset = values[9]

        if disk_number != 0 or directory_disk != 0 or entries_on_disk != total_entries:
            raise zipfile.BadZipFile("Multi-disk ZIP archives are not supported")
        if directory_offset + directory_size > eocd_offset:
            raise zipfile.BadZipFile("Invalid central directory bounds")

        return int(total_entries), int(directory_offset), int(directory_size)


def _validate_zip_directory_cardinality(file_path: str) -> None:
    """Bound ZIP metadata before ZipFile materializes a ZipInfo per member."""
    reported_entries, directory_offset, directory_size = _zip_directory_metadata(
        file_path
    )
    if reported_entries > MAX_ARCHIVE_ENTRIES:
        raise ValueError(
            f"ZIP contains {reported_entries} entries; the maximum is "
            f"{MAX_ARCHIVE_ENTRIES}."
        )
    if directory_size > MAX_CENTRAL_DIRECTORY_BYTES:
        raise ValueError(
            "ZIP central directory exceeds the "
            f"{MAX_CENTRAL_DIRECTORY_BYTES // (1024 * 1024)} MB metadata limit."
        )

    count = 0
    remaining = directory_size
    saw_digital_signature = False
    with open(file_path, "rb") as archive:
        archive.seek(directory_offset)
        while remaining:
            signature = archive.read(4)
            if len(signature) != 4:
                raise zipfile.BadZipFile("Truncated central directory")

            if signature == _CENTRAL_FILE_SIGNATURE:
                rest = archive.read(_CENTRAL_FILE_HEADER.size - 4)
                if len(rest) != _CENTRAL_FILE_HEADER.size - 4:
                    raise zipfile.BadZipFile("Truncated central directory entry")
                fields = _CENTRAL_FILE_HEADER.unpack(signature + rest)
                variable_size = fields[10] + fields[11] + fields[12]
                entry_size = _CENTRAL_FILE_HEADER.size + variable_size
                if entry_size > remaining:
                    raise zipfile.BadZipFile("Invalid central directory entry size")
                archive.seek(variable_size, 1)
                remaining -= entry_size
                count += 1
                if count > MAX_ARCHIVE_ENTRIES:
                    raise ValueError(
                        f"ZIP contains more than {MAX_ARCHIVE_ENTRIES} entries."
                    )
                continue

            if signature == _CENTRAL_DIGITAL_SIGNATURE:
                if saw_digital_signature or count != reported_entries:
                    raise zipfile.BadZipFile(
                        "Invalid central-directory digital signature placement"
                    )
                length_bytes = archive.read(2)
                if len(length_bytes) != 2:
                    raise zipfile.BadZipFile("Truncated central-directory signature")
                signature_size = struct.unpack("<H", length_bytes)[0]
                record_size = 6 + signature_size
                if record_size > remaining:
                    raise zipfile.BadZipFile("Invalid central-directory signature size")
                if record_size != remaining:
                    raise zipfile.BadZipFile(
                        "Central-directory digital signature must be the final record"
                    )
                archive.seek(signature_size, 1)
                remaining -= record_size
                saw_digital_signature = True
                continue

            raise zipfile.BadZipFile("Invalid central directory signature")

    if count != reported_entries:
        raise zipfile.BadZipFile("ZIP member count does not match central directory")


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
        _validate_zip_directory_cardinality(file_path)
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
        raise ValueError("File is not a valid ZIP container.")


def validate_archive_safety(file_path: str, filename: str) -> None:
    """Apply ZIP safety checks to every accepted ZIP-container source format."""
    if Path(filename).suffix.lower() in ZIP_CONTAINER_EXTENSIONS:
        validate_zip_safety(file_path)


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
