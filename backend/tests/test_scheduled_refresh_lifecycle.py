"""Focused contracts for optional scheduled-refresh worker lifecycle hooks."""

from __future__ import annotations

import pytest

from app.platform.extensions.scheduled_refresh import (
    DefaultScheduledRefreshLifecycle,
    ScheduledRefreshLifecycle,
    supervised_scheduled_refresh_lifecycle,
)
from app.platform.refresh.execution import (
    ARC_GIS_ID_SET_VERIFICATION_POLICY,
    SCHEDULED_REFRESH_TASK_NAME,
    RefreshAdmissionRequest,
)


@pytest.mark.asyncio
async def test_default_lifecycle_is_a_safe_community_noop() -> None:
    lifecycle = DefaultScheduledRefreshLifecycle()

    assert isinstance(lifecycle, ScheduledRefreshLifecycle)
    await lifecycle.start(task_app=object())  # type: ignore[arg-type]
    await lifecycle.stop()


@pytest.mark.asyncio
async def test_supervised_lifecycle_stops_before_its_connector_closes() -> None:
    events: list[tuple[str, object | None]] = []
    task_app = object()

    class Lifecycle:
        async def start(self, *, task_app: object) -> None:
            events.append(("start", task_app))

        async def stop(self) -> None:
            events.append(("stop", None))

    async with supervised_scheduled_refresh_lifecycle(
        Lifecycle(),
        task_app=task_app,  # type: ignore[arg-type]
    ):
        events.append(("worker", None))

    assert events == [("start", task_app), ("worker", None), ("stop", None)]


@pytest.mark.asyncio
async def test_supervised_lifecycle_stops_after_worker_error() -> None:
    events: list[str] = []

    class Lifecycle:
        async def start(self, *, task_app: object) -> None:
            del task_app
            events.append("start")

        async def stop(self) -> None:
            events.append("stop")

    with pytest.raises(RuntimeError, match="worker failed"):
        async with supervised_scheduled_refresh_lifecycle(
            Lifecycle(),
            task_app=object(),  # type: ignore[arg-type]
        ):
            raise RuntimeError("worker failed")

    assert events == ["start", "stop"]


def test_scheduled_task_identity_and_stronger_policy_are_explicit() -> None:
    request = RefreshAdmissionRequest(
        source_binding_fingerprint="fingerprint",
        local_edit_baseline=None,
        origin_kind="service",
    )

    assert SCHEDULED_REFRESH_TASK_NAME == "scheduled-refresh-v1"
    assert request.verification_policy == ARC_GIS_ID_SET_VERIFICATION_POLICY


def test_public_refresh_schema_accepts_arcgis_verification_evidence() -> None:
    from app.modules.catalog.datasets.domain.schemas import (
        DatasetRefreshRequest,
        RefreshVerification,
    )

    assert DatasetRefreshRequest().verification_policy == "standard"
    assert (
        DatasetRefreshRequest(
            verification_policy="arcgis_id_set_v1"
        ).verification_policy
        == "arcgis_id_set_v1"
    )
    verification = RefreshVerification.model_validate(
        {
            "decision": "rejected",
            "source_binding": {"policy": "arcgis_id_set_v1"},
            "source_count": 2,
            "fetched_count": 2,
            "count_status": "matched",
            "identity_check": "arcgis_id_set",
            "arcgis_id_coverage": {"membership": "changed"},
            "review_reasons": ["arcgis_source_membership_changed"],
            "review_fingerprint": None,
            "accepted_blocked_run_id": None,
        }
    )

    assert verification.arcgis_id_coverage == {"membership": "changed"}
