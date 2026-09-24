"""The URL import door: check a file URL and queue its download."""

import asyncio
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.identity import Identity
from app.modules.auth.dependencies import require_permission
from app.modules.quota.service import check_upload_quota
from app.platform.jobs import ledger
from app.processing.ingest.ogr import IngestionError
from app.processing.ingest.router import (
    _get_allowed_extensions_safely,
    _reject_standalone_vrt,
)
from app.processing.ingest.schemas import UploadResponse, UrlUploadRequest
from app.processing.ingest.service import (
    safe_upload_basename,
    validate_file_extension,
)
from app.processing.ingest.tileset import require_tileset_archive, tileset_job_metadata
from app.processing.ingest.url_fetch import (
    PREFLIGHT_DNS_MAX_SECONDS,
    clamp_filename_bytes,
    filename_from_url,
)
from app.standards.ogc.errors import (
    BAD_GATEWAY_RESPONSE,
    ERROR_RESPONSES_WRITE,
    PAYLOAD_TOO_LARGE_RESPONSE,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/ingest",
    tags=["Datasets"],
    responses=ERROR_RESPONSES_WRITE,
)


def _url_import_filename(body: UrlUploadRequest) -> str:
    """The staging filename for a URL import, or the endpoint's 400/422.

    fix(#1708): both name sources go through the byte clamp (filesystems cap
    NAME_MAX in BYTES, not the schema's 255 characters). Callers must invoke
    this INSIDE their guarded block — urlparse can raise ValueError on a
    malformed authority.
    """
    try:
        filename = (
            clamp_filename_bytes(safe_upload_basename(body.filename))
            if body.filename
            else filename_from_url(body.url)
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid URL: {exc}",
        ) from exc
    # fix(#1708): NUL and other control characters survive percent-
    # decoding ('/roads%00.geojson') or arrive verbatim in the override, and
    # pass every suffix/allowlist check — the filesystem refuses them only at
    # open(), which sits AFTER the running-commit, and the failed open's
    # cleanup unlink then raised on the same invalid path. Refuse them here,
    # before any job row exists.
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in filename):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Filename contains control characters that are not allowed.",
        )
    if not filename or not Path(filename).suffix:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Could not determine a filename with an extension from the "
                "URL path. Provide 'filename' explicitly."
            ),
        )
    return filename


@router.post(
    "/upload/url",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        # fix(#1710): 413 stays documented. The download moved to the worker,
        # but `check_upload_quota` still refuses an over-quota caller here,
        # and dropping it took the branch out of both SDKs.
        413: PAYLOAD_TOO_LARGE_RESPONSE,
        502: BAD_GATEWAY_RESPONSE,
    },
)
async def upload_from_url(
    body: UrlUploadRequest,
    request: Request,
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    """Start importing a geospatial file from an HTTP(S) URL.

    The server fetches the file and sends the staged bytes through the same
    preview and commit pipeline as a direct upload. With ``kind`` set to
    ``tiles3d`` the URL names a 3D Tiles tileset archive, which the worker
    checks as the upload door does before the job becomes previewable.

    The download runs as a background job. This call validates the URL and
    returns a job id immediately; poll ``GET /jobs/{job_id}`` and
    preview once the job reaches ``pending``. While the file is downloading
    the job reports status ``running`` with step ``downloading``.

    URL validation, connection-time IP pinning, and per-hop redirect checks
    protect the download from SSRF. The worker enforces the size cap while
    streaming, validates the staged file like a direct upload, and gives GDAL
    only the local staged file.
    """
    from app.core.db.tenant_session import defer_async_with_tenant
    from app.core.url_redaction import redact_url_credentials
    from app.platform.jobs.defer_guard import (
        defer_with_orphan_guard,
        make_ingest_job_failed_rollback,
    )
    from app.platform.jobs.models import URL_DOWNLOAD_IN_FLIGHT_METADATA_KEY
    from app.platform.security import SSRFError, validate_url_for_ssrf
    from app.processing.ingest.tasks import fetch_url

    # Exception-safe on malformed input by design (fix(#1119)) — safe to run
    # before the guarded block below.
    safe_url = redact_url_credentials(body.url)
    try:
        filename = _url_import_filename(body)
        _reject_standalone_vrt(filename)
        require_tileset_archive(body.kind, filename)

        # fix(#1708): commit here to END the auth-phase transaction before the
        # DNS await — getaddrinfo has no bound of its own, and holding a
        # connection through it could exhaust the pool under concurrent imports.
        await db.commit()

        # Rule 2, submission gate: refuse private/link-local/reserved targets
        # before anything is queued. The worker's safe client re-validates at
        # connect time and per redirect hop during the download.
        #
        # fix(#1708): bounded at the call site — getaddrinfo has no deadline
        # of its own; wait_for cancels the to_thread wrapper immediately and
        # the abandoned resolver thread ends when the OS resolver gives up.
        try:
            await asyncio.wait_for(
                validate_url_for_ssrf(body.url),
                timeout=PREFLIGHT_DNS_MAX_SECONDS,
            )
        except TimeoutError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "DNS resolution for this URL did not finish within "
                    f"{PREFLIGHT_DNS_MAX_SECONDS} seconds."
                ),
            ) from exc
        except SSRFError as exc:
            logger.warning(
                "url_import_ssrf_blocked",
                event_type="security",
                url=safe_url,
                reason=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

        allowed_list = await _get_allowed_extensions_safely(db)
        validate_file_extension(filename, allowed_list)

        # Refuse at the dataset-count cap before queueing anything. The byte
        # half runs in the worker with the size that actually landed, since
        # Content-Length may be absent or dishonest.
        await check_upload_quota(db, user.id, 0, request)

        # feat(#1710): the row is committed 'running', not 'pending'. The
        # success state of a URL import IS 'pending' (previewable), so a
        # pending row would tell the UI the download had finished; and the
        # stale-PENDING sweep may legally fire at 61s while a download is
        # allowed url_import_fetch_max_seconds. Running rows are judged by
        # the worker lease instead, which the task's heartbeat renews.
        job = ledger.create(
            db,
            created_by=user.id,
            status="running",
            source_filename=filename,
            file_path="",
            current_step="downloading",
            progress=0.0,
            # While set, `file_path` names a destination, not a finished file,
            # so retry is refused; the staged transition clears it.
            user_metadata={
                URL_DOWNLOAD_IN_FLIGHT_METADATA_KEY: True,
                **tileset_job_metadata(body.kind),
            },
        )
        await db.flush()
        job_id = job.id
        await db.commit()

        async def _defer_fetch() -> None:
            await defer_async_with_tenant(
                fetch_url,
                job_id=str(job_id),
                attempt_id=str(job.attempt_id),
                url=body.url,
                user_id=str(user.id),
                filename=filename,
            )

        # The URL crosses to the worker as a task argument rather than on the
        # job row: `user_metadata` is served by GET /jobs/{id}, and a URL can
        # carry userinfo credentials.
        await defer_with_orphan_guard(
            _defer_fetch,
            rollback=make_ingest_job_failed_rollback(
                job,
                message_prefix="Failed to queue the download",
                expected_status="running",
            ),
            db=db,
            job=job,
        )

        logger.info("url_import_queued", url=safe_url, job_id=str(job_id))
        return UploadResponse(
            job_id=job_id,
            status="running",
            message="Downloading the file",
        )
    # N4 (mirrors upload_file): HTTPException before the ValueError fallback,
    # or every deliberate 4xx above is rewritten as a 400/500.
    except HTTPException:
        raise
    except (IngestionError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception:  # broad: submission involves DNS, config lookups, DB and the queue — any can throw
        logger.exception(
            "Unexpected error during URL import",
            url=safe_url,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during URL import",
        )
