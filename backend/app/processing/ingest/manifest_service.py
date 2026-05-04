"""Service entry point for applying manifest v1 payloads."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.processing.ingest.manifest_schemas import (
    ManifestApplyEntryResult,
    ManifestApplyRequest,
    ManifestApplyResponse,
)


async def apply_manifest(
    db: AsyncSession,
    request: ManifestApplyRequest,
    user: Identity,
) -> ManifestApplyResponse:
    """Return a typed placeholder response until Plan 02 adds ingest behavior."""
    _ = db, user
    return ManifestApplyResponse(
        accepted=False,
        dry_run=request.dry_run,
        results=[
            ManifestApplyEntryResult(
                dataset_key=dataset.key,
                action="error",
                message="Manifest apply service is not implemented yet.",
                errors=["manifest apply service is not implemented yet"],
            )
            for dataset in request.datasets
        ],
    )
