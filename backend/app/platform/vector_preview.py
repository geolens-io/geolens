"""The 422 mapping shared by the import preview and the re-upload preview.

In ``platform/`` because the re-upload preview may not import
``app.processing``; each caller passes the preview function it reaches.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import structlog
from fastapi import HTTPException, status

from app.core.upload_errors import (
    IngestCeilingError,
    UnsafeUploadError,
    refusal_detail,
)

logger = structlog.get_logger(__name__)

PreviewFn = Callable[..., Awaitable[dict[str, Any]]]


async def preview_vector_file(
    preview: PreviewFn,
    path: str | None,
    layer_name: str | None,
    *,
    job_id: uuid.UUID,
    downloaded: Path | None,
) -> dict[str, Any]:
    """Run ``preview(path, layer_name=layer_name)`` and return what it reads.

    A ceiling or content refusal answers 422 with its coded detail; any other
    failure answers 422 ``preview_failed``. ``downloaded``, the local copy of
    a stored upload, is removed on every path.
    """
    try:
        return await preview(path, layer_name=layer_name)
    except (IngestCeilingError, UnsafeUploadError) as exc:
        # Server-authored text that names the limit or the blocked content and
        # the way out; the generic answer below would call the file malformed.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=refusal_detail(exc),
        ) from exc
    except Exception as exc:  # broad: GDAL subprocess can raise various errors on unsupported/malformed files
        logger.exception("ogrinfo_preview failed", job_id=str(job_id), error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "preview_failed",
                "message": "Unable to preview file. The file may be malformed or unsupported.",
            },
        ) from exc
    finally:
        if downloaded is not None:
            downloaded.unlink(missing_ok=True)
