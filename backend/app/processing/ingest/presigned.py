"""Shared presigned-upload completion checks."""

from __future__ import annotations

import asyncio
import uuid

import structlog
from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.persistent_config import UPLOAD_MAX_SIZE_MB
from app.modules.quota.service import check_upload_quota
from app.platform.storage import StorageProvider

logger = structlog.get_logger(__name__)


async def _cleanup_presigned_object(
    storage: StorageProvider, key: str, job_id: uuid.UUID
) -> None:
    try:
        await storage.delete(key)
    except Exception:  # broad: cleanup is best-effort after a rejected upload
        logger.warning(
            "presigned_upload_cleanup_failed",
            s3_key=key,
            job_id=str(job_id),
        )


async def abort_presigned_multipart_upload(
    storage: StorageProvider,
    *,
    key: str,
    upload_id: object,
    job_id: uuid.UUID,
) -> None:
    """Best-effort abort for rejected multipart presigned uploads."""
    if not upload_id:
        return
    try:
        await asyncio.to_thread(storage.abort_multipart_upload, key, str(upload_id))
    except Exception:  # broad: cleanup is best-effort after a rejected upload
        logger.warning(
            "presigned_multipart_abort_failed",
            s3_key=key,
            job_id=str(job_id),
        )


async def verify_completed_presigned_upload(
    *,
    db: AsyncSession,
    storage: StorageProvider,
    key: str,
    expected_size: object,
    user_id: uuid.UUID,
    request: Request,
    job_id: uuid.UUID,
) -> int:
    """Verify a completed direct-to-object-storage upload before accepting it."""
    actual_size = await storage.size(key)
    max_size_mb = await UPLOAD_MAX_SIZE_MB.get(db)
    max_size_bytes = max_size_mb * 1024 * 1024

    if actual_size > max_size_bytes:
        await _cleanup_presigned_object(storage, key, job_id)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Uploaded file size ({actual_size / (1024 * 1024):.1f} MB) exceeds "
                f"the maximum allowed ({max_size_mb} MB)."
            ),
        )

    if expected_size is not None:
        try:
            declared_size = int(expected_size)
        except (TypeError, ValueError):
            declared_size = -1
        if actual_size != declared_size:
            await _cleanup_presigned_object(storage, key, job_id)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Uploaded file size ({actual_size} bytes) does not match "
                    f"the declared size ({expected_size} bytes)."
                ),
            )

    try:
        await check_upload_quota(db, user_id, actual_size, request)
    except HTTPException:
        await _cleanup_presigned_object(storage, key, job_id)
        raise

    return actual_size
