"""A status change refuses with 409 when another status change commits between its plan and its lock.

Requirements: the docker database must be running with migrations applied.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.api import router_data
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.extensions.defaults import DefaultWorkflowExtension
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


class _RecordingWorkflow(DefaultWorkflowExtension):
    def __init__(self) -> None:
        self.transitions: list[tuple[str, str]] = []

    async def on_transition(self, context) -> None:  # type: ignore[no-untyped-def]
        self.transitions.append((context.from_status, context.to_status))
        await super().on_transition(context)


@pytest.fixture
def workflow(monkeypatch: pytest.MonkeyPatch) -> _RecordingWorkflow:
    recording = _RecordingWorkflow()
    monkeypatch.setattr(router_data, "get_workflow_extension", lambda: recording)
    return recording


async def _published_dataset(session: AsyncSession) -> Dataset:
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(
        session, created_by=admin_id, visibility="private", record_status="published"
    )
    await session.commit()
    return dataset


async def _stored(session: AsyncSession, dataset_id: uuid.UUID) -> tuple[str, int]:
    row = (
        await session.execute(
            select(Record.record_status, Dataset.publication_version)
            .join(Dataset, Dataset.record_id == Record.id)
            .where(Dataset.id == dataset_id)
        )
    ).one()
    return row.record_status, row.publication_version


@pytest.mark.parametrize(
    ("path", "requested", "committed_meanwhile"),
    [("status", "internal", "draft"), ("target-status", "draft", "internal")],
)
async def test_status_change_overtaken_before_the_lock_is_refused(
    client: AsyncClient,
    test_db_session: AsyncSession,
    admin_auth_header: dict,
    workflow: _RecordingWorkflow,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    requested: str,
    committed_meanwhile: str,
) -> None:
    dataset = await _published_dataset(test_db_session)
    dataset_id, record_id = dataset.id, dataset.record_id
    original = router_data._refuse_stranding

    # Runs after the handler has planned from `published`, before it locks the rows.
    async def commit_another_change_then_continue(db, ds, target):
        await test_db_session.execute(
            update(Record)
            .where(Record.id == record_id)
            .values(record_status=committed_meanwhile)
        )
        await test_db_session.commit()
        await original(db, ds, target)

    monkeypatch.setattr(
        router_data, "_refuse_stranding", commit_another_change_then_continue
    )
    _, version_before = await _stored(test_db_session, dataset_id)

    resp = await client.patch(
        f"/datasets/{dataset_id}/{path}/",
        json={"status": requested},
        headers=admin_auth_header,
    )

    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["code"] == "publication_status_changed"
    assert body["detail"]["code"] == "publication_status_changed"
    assert workflow.transitions == []
    assert await _stored(test_db_session, dataset_id) == (
        committed_meanwhile,
        version_before,
    )


@pytest.mark.parametrize(
    ("path", "requested", "expected_transitions"),
    [
        ("status", "internal", [("published", "internal")]),
        (
            "target-status",
            "draft",
            [("published", "internal"), ("internal", "ready"), ("ready", "draft")],
        ),
    ],
)
async def test_uncontended_status_change_still_writes_its_plan(
    client: AsyncClient,
    test_db_session: AsyncSession,
    admin_auth_header: dict,
    workflow: _RecordingWorkflow,
    path: str,
    requested: str,
    expected_transitions: list[tuple[str, str]],
) -> None:
    dataset = await _published_dataset(test_db_session)

    resp = await client.patch(
        f"/datasets/{dataset.id}/{path}/",
        json={"status": requested},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    assert workflow.transitions == expected_transitions
    status, _ = await _stored(test_db_session, dataset.id)
    assert status == requested
