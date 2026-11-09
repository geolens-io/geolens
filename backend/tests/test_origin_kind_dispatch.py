"""Each dispatcher names the kinds it runs and refuses any other.

A kind added to ``classify_origin`` later must not reach the service task
by falling through.
"""

from __future__ import annotations

import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.catalog.datasets.api import router_refresh
from app.platform.dataset_origin import set_dataset_origin
from app.platform.jobs.models import IngestJob
from app.platform.refresh.execution import execute_admitted_refresh
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import create_pending_run
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio

_WFS = "https://maps.example.org/wfs"


async def test_refresh_refuses_a_kind_it_has_no_strategy_for(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """A complete service binding under another kind never reaches the service path."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(
        test_db_session, created_by=admin_id, source_format="wfs"
    )
    set_dataset_origin(
        dataset,
        "service",
        uri=f"{_WFS}/topp:parcels",
        service_type="wfs",
        url=_WFS,
        layer_id="topp:parcels",
    )
    await test_db_session.commit()

    port = MagicMock()
    with (
        patch.object(router_refresh, "classify_origin", return_value="database"),
        patch.object(
            router_refresh,
            "_resolve_service_origin",
            wraps=router_refresh._resolve_service_origin,
        ) as service_resolver,
        patch.object(router_refresh, "validate_url_for_ssrf", AsyncMock()),
        patch.object(router_refresh, "get_catalog_port", return_value=port),
    ):
        resp = await client.post(
            f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
        )

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "refresh_not_applicable"
    assert detail["origin_kind"] == "database"
    service_resolver.assert_not_called()
    port.verified_refresh_service_task.assert_not_called()
    run = await test_db_session.scalar(
        select(DatasetRefreshRun).where(DatasetRefreshRun.dataset_id == dataset.id)
    )
    assert run is None


async def test_admitted_execution_runs_only_service_refreshes(
    test_db_session,
) -> None:
    actor_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(test_db_session, created_by=actor_id)
    job = IngestJob(
        dataset_id=dataset.id,
        created_by=actor_id,
        status="pending",
        source_filename="item.tif",
        user_metadata={"refresh": True, "dataset_id": str(dataset.id)},
    )
    test_db_session.add(job)
    await test_db_session.flush()
    run = await create_pending_run(
        test_db_session,
        dataset_id=dataset.id,
        origin_kind="stac",
        trigger="scheduled",
        triggered_by=actor_id,
        ingest_job_id=job.id,
        feature_count_before=dataset.feature_count,
        scheduled_for=datetime.now(timezone.utc),
        occurrence_key=f"occurrence:{uuid.uuid4()}",
        execution_key=uuid.uuid4(),
        source_binding_fingerprint="a" * 64,
        verification_policy="arcgis_id_set_v1",
    )
    run.credential_reference = "credential-1"
    await test_db_session.commit()
    run_id, job_id = run.id, job.id

    @asynccontextmanager
    async def session_factory():
        yield test_db_session

    resolver = AsyncMock(return_value=secrets.token_urlsafe(16))
    with (
        patch("app.core.db.async_session", session_factory),
        patch("app.platform.extensions.get_catalog_port") as catalog_port,
    ):
        result = await execute_admitted_refresh(
            job_id, str(run.execution_key), credential_resolver=resolver
        )

    assert result.status == "rejected"
    assert result.run_id == run_id
    catalog_port.assert_not_called()
    resolver.assert_not_awaited()
    test_db_session.expire_all()
    persisted_run = await test_db_session.get(DatasetRefreshRun, run_id)
    persisted_job = await test_db_session.get(IngestJob, job_id)
    assert persisted_run.status == "failed"
    assert persisted_run.error_code == "refresh_origin_unsupported"
    assert persisted_job.status == "failed"
