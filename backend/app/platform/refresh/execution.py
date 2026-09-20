"""Core-neutral scheduled refresh execution identities and request DTOs.

The actual refresh executor remains in the ingest domain. This module owns
only the durable values which callers may persist or place in queue payloads.
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.failure_reason import coded_failure_reason
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import (
    claim_admitted_run_for_job,
    create_pending_run,
    expire_unclaimed_admitted_runs,
    fail_claimed_admitted_refresh,
    reject_pending_admitted_refresh,
    record_refresh_failure,
)

SCHEDULED_REFRESH_TASK_NAME = "scheduled-refresh-v1"
ARC_GIS_ID_SET_VERIFICATION_POLICY = "arcgis_id_set_v1"

RefreshTrigger = Literal["manual", "scheduled"]


@dataclass(frozen=True, slots=True)
class RefreshAdmissionRequest:
    """Values captured before an admitted refresh becomes asynchronous work."""

    source_binding_fingerprint: str
    local_edit_baseline: datetime | None
    origin_kind: str
    source_filename: str | None = None
    source_url: str | None = None
    source_layer: str | None = None
    job_metadata: Mapping[str, object] = field(default_factory=dict)
    feature_count_before: int | None = None
    verification_policy: str = ARC_GIS_ID_SET_VERIFICATION_POLICY
    credential_reference: str | None = None
    credential_version: str | None = None


@dataclass(frozen=True, slots=True)
class RefreshAdmission:
    """Identity and fences created atomically with a refresh job and run."""

    dataset_id: UUID
    job_id: UUID
    run_id: UUID
    tenant_id: UUID | None
    trigger: RefreshTrigger
    source_binding_fingerprint: str
    local_edit_baseline: datetime | None
    verification_policy: str
    execution_key: str
    claim_deadline: datetime | None
    scheduled_for: datetime | None = None
    occurrence_key: str | None = None


@dataclass(frozen=True, slots=True)
class RefreshExecutionResult:
    """Result returned by a claim-fenced worker execution attempt."""

    job_id: UUID
    run_id: UUID
    status: Literal["completed", "rejected", "already_settled"]


CredentialResolver = Callable[[str, str | None], Awaitable[str]]
ScheduledRefreshTaskExecutor = Callable[[str, str, str | None], Awaitable[None]]
_REJECTION_CODE_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


def register_scheduled_refresh_task(
    task_app: object,
    *,
    execute: ScheduledRefreshTaskExecutor,
) -> object:
    """Register the versioned scheduled task around an overlay-owned callback.

    The core owns the task identity, queue, and retry behavior. The callback
    owns tenant validation, outbox state, and in-memory credential resolution,
    which keeps Community independent of paid configuration.
    """
    task_factory = getattr(task_app, "task", None)
    if not callable(task_factory):
        raise TypeError("task_app must provide a callable task decorator")

    @task_factory(queue="ingest", retry=0, name=SCHEDULED_REFRESH_TASK_NAME)
    async def scheduled_refresh_task(
        job_id: str, execution_key: str, tenant_id: str | None = None
    ) -> None:
        await execute(job_id, execution_key, tenant_id)

    return scheduled_refresh_task


async def prepare_admitted_refresh(
    session: AsyncSession,
    *,
    dataset: object,
    actor: object,
    request: RefreshAdmissionRequest,
    trigger: RefreshTrigger,
    scheduled_for: datetime | None = None,
    occurrence_key: str | None = None,
) -> RefreshAdmission:
    """Create the job and refresh run in the caller's transaction.

    Authorization belongs to the caller's domain guard. This facade requires
    a user-bound actor and refuses malformed identities before writing. It never
    commits, defers queue work, or accepts a credential value.
    """
    dataset_id = getattr(dataset, "id", None)
    actor_id = getattr(actor, "id", None)
    if not isinstance(dataset_id, UUID):
        raise ValueError("dataset must expose a UUID id")
    if not isinstance(actor_id, UUID):
        raise ValueError("actor must expose a UUID id")
    if not request.source_binding_fingerprint:
        raise ValueError("source_binding_fingerprint is required")
    if trigger == "scheduled" and (scheduled_for is None or not occurrence_key):
        raise ValueError(
            "scheduled admission requires scheduled_for and occurrence_key"
        )

    execution_key = uuid.uuid4()
    job = IngestJob(
        dataset_id=dataset_id,
        created_by=actor_id,
        status="pending",
        source_filename=request.source_filename,
        source_url=request.source_url,
        source_layer=request.source_layer,
        user_metadata={
            **dict(request.job_metadata),
            "refresh": True,
            "dataset_id": str(dataset_id),
            "origin_kind": request.origin_kind,
            "verification_policy": request.verification_policy,
        },
    )
    session.add(job)
    await session.flush()
    run = await create_pending_run(
        session,
        dataset_id=dataset_id,
        origin_kind=request.origin_kind,
        trigger=trigger,
        triggered_by=actor_id,
        ingest_job_id=job.id,
        feature_count_before=request.feature_count_before,
        scheduled_for=scheduled_for,
        occurrence_key=occurrence_key,
        execution_key=execution_key,
        source_binding_fingerprint=request.source_binding_fingerprint,
        local_edit_baseline=request.local_edit_baseline,
        verification_policy=request.verification_policy,
        credential_reference=request.credential_reference,
        credential_version=request.credential_version,
    )
    return RefreshAdmission(
        dataset_id=dataset_id,
        job_id=job.id,
        run_id=run.id,
        tenant_id=run.tenant_id,
        trigger=trigger,
        source_binding_fingerprint=request.source_binding_fingerprint,
        local_edit_baseline=request.local_edit_baseline,
        verification_policy=request.verification_policy,
        execution_key=str(execution_key),
        claim_deadline=run.claim_deadline,
        scheduled_for=scheduled_for,
        occurrence_key=occurrence_key,
    )


async def reject_admitted_refresh(
    session: AsyncSession,
    job_id: UUID,
    execution_key: str,
    reason: str,
) -> UUID | None:
    """Terminalize an unclaimed admitted job/run without touching claimed work.

    Callers pass a stable, non-secret reason code after an authorization or
    source fence rejects queued work. The caller owns the surrounding
    transaction; ``None`` means a worker already claimed or settled it.
    """
    try:
        claim_key = UUID(execution_key)
    except ValueError as exc:
        raise ValueError("execution_key must be a UUID") from exc
    if (
        not reason
        or len(reason) > 64
        or not set(reason).issubset(_REJECTION_CODE_CHARACTERS)
    ):
        raise ValueError("reason must be a lowercase underscore-delimited code")
    return await reject_pending_admitted_refresh(
        session,
        ingest_job_id=job_id,
        execution_key=claim_key,
        error_code=reason,
        error_message=f"Refresh was rejected before execution: {reason}.",
    )


async def execute_admitted_refresh(
    job_id: UUID,
    execution_key: str,
    *,
    credential_resolver: CredentialResolver | None = None,
) -> RefreshExecutionResult:
    """Claim and invoke the registered verified-refresh task for one admission.

    This is intentionally the only cross-domain execution entry: it invokes
    the public CatalogPort task, never a router or a private ingest helper.
    """
    from app.core.db import async_session
    from app.platform.extensions import get_catalog_port

    try:
        claim_key = UUID(execution_key)
    except ValueError:
        return RefreshExecutionResult(
            job_id=job_id, run_id=UUID(int=0), status="rejected"
        )

    async with async_session() as session:
        run = await session.scalar(
            select(DatasetRefreshRun).where(
                DatasetRefreshRun.ingest_job_id == job_id,
                DatasetRefreshRun.execution_key == claim_key,
            )
        )
        if run is None:
            return RefreshExecutionResult(
                job_id=job_id, run_id=UUID(int=0), status="already_settled"
            )
        claimed_run_id = await claim_admitted_run_for_job(
            session, job_id, execution_key=claim_key
        )
        if claimed_run_id is None:
            await expire_unclaimed_admitted_runs(session)
            await session.commit()
            return RefreshExecutionResult(
                job_id=job_id, run_id=run.id, status="already_settled"
            )
        job = await session.get(IngestJob, job_id)
        if job is None:
            await record_refresh_failure(
                session,
                ingest_job_id=job_id,
                error_code="scheduled_job_missing",
                error_message="The admitted refresh job no longer exists.",
                contacted_origin=False,
            )
            await session.commit()
            return RefreshExecutionResult(
                job_id=job_id, run_id=claimed_run_id, status="rejected"
            )
        task_args = {
            "job_id": str(job.id),
            "dataset_id": str(job.dataset_id),
            "source_url": job.source_url or "",
            "source_layer": job.source_layer or "",
            "user_id": str(job.created_by),
            "attempt_id": str(job.attempt_id),
            "tenant_id": str(run.tenant_id) if run.tenant_id is not None else None,
        }
        await session.commit()
        credential_reference = run.credential_reference
        credential_version = run.credential_version

    token: str | None = None
    if credential_reference is not None:
        if credential_resolver is None:
            resolver_error: BaseException = RuntimeError(
                "No credential resolver is available for this scheduled refresh."
            )
        else:
            try:
                token = await credential_resolver(
                    credential_reference, credential_version
                )
                resolver_error = (
                    None
                    if token
                    else RuntimeError(
                        "Credential resolver returned no credential for this refresh."
                    )
                )
            except Exception as exc:  # broad: vault implementations surface provider-specific credential failures
                resolver_error = exc
        if resolver_error is not None:
            async with async_session() as session:
                await fail_claimed_admitted_refresh(
                    session,
                    ingest_job_id=job_id,
                    execution_key=claim_key,
                    error_code="scheduled_credential_unavailable",
                    error_message=coded_failure_reason(
                        "Scheduled refresh credential resolution failed",
                        resolver_error,
                    ),
                )
                await session.commit()
            return RefreshExecutionResult(
                job_id=job_id, run_id=claimed_run_id, status="rejected"
            )

    task = get_catalog_port().verified_refresh_service_task()
    try:
        result = task.func(
            **task_args,
            token=token,
            credential_ref=None,
            verification_policy=run.verification_policy,
            credential_version=credential_version,
            scheduled_execution_key=execution_key,
        )
        if inspect.isawaitable(result):
            await result
    except (
        Exception
    ) as exc:  # broad: task implementations own provider-specific failures
        async with async_session() as session:
            await record_refresh_failure(
                session,
                ingest_job_id=job_id,
                error_code="scheduled_executor_failed",
                error_message=exc,
                contacted_origin=False,
            )
            await session.commit()
        return RefreshExecutionResult(
            job_id=job_id, run_id=claimed_run_id, status="rejected"
        )

    async with async_session() as session:
        settled = await session.get(DatasetRefreshRun, claimed_run_id)
        status = (
            "completed"
            if settled is not None and settled.status == "succeeded"
            else "rejected"
        )
    return RefreshExecutionResult(job_id=job_id, run_id=claimed_run_id, status=status)
