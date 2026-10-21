"""What the upload door accepts, as clients are told."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.persistent_config import UPLOAD_ALLOWED_EXTENSIONS, UPLOAD_MAX_SIZE_MB
from app.processing.ingest.manifest_schemas import MANIFEST_SOURCE_EXTENSIONS
from app.processing.ingest.schemas import UploadConfigResponse

_MANIFEST_PUBLISHABLE_EXTENSIONS = frozenset().union(
    *MANIFEST_SOURCE_EXTENSIONS.values()
)


def without_standalone_vrt(extensions: str) -> str:
    """Keep legacy persistent config from advertising a disabled file type."""
    return ",".join(
        extension.strip()
        for extension in extensions.split(",")
        if extension.strip() and extension.strip().lower() != ".vrt"
    )


def manifest_publishable_extensions(allowed_csv: str) -> list[str]:
    """The allowed upload extensions a publish manifest can also carry, sorted."""
    return sorted(
        ext
        for ext in (e.strip().lower() for e in allowed_csv.split(","))
        if ext in _MANIFEST_PUBLISHABLE_EXTENSIONS
    )


async def build_upload_config(
    db: AsyncSession, remaining_dataset_quota: int | None
) -> UploadConfigResponse:
    """Upload limits, with the caller's remaining dataset quota passed in."""
    max_size_mb = await UPLOAD_MAX_SIZE_MB.get(db)
    allowed_exts = without_standalone_vrt(await UPLOAD_ALLOWED_EXTENSIONS.get(db))
    return UploadConfigResponse(
        presigned_uploads=settings.storage_provider == "s3",
        presigned_threshold_bytes=settings.presigned_multipart_threshold_mb
        * 1024
        * 1024,
        max_file_size_bytes=max_size_mb * 1024 * 1024,
        allowed_extensions=allowed_exts,
        remaining_dataset_quota=remaining_dataset_quota,
    )
