"""fix(#1327): how a staged source mutation is written, delivered, and skewed.

Three things that only mean something together:

1. The endpoints write the member set to `VrtGeneration.staged_source_ids` and
   leave `vrt_source_links` alone (database-backed, over HTTP, because the
   staged set is a JSONB column written by a real session and a mocked db
   cannot show that a request wrote one column and left a table alone).
2. They deliver it under the STAGED task name, while a plain regenerate keeps
   the legacy name.
3. That name is what makes a version skew loud. fix(#1327 codex P1): during a
   rolling upgrade the API can be new while a worker is still pre-#1327; the
   old worker would ignore `staged_source_ids`, rebuild from the live links and
   report success, silently dropping an accepted add or remove. Procrastinate
   fails a job whose task name the worker does not have, and the test below
   measures that against the pinned version rather than assuming it.

Deliberately its own module: `test_vrt_source_management_174.py` carries an
autouse fixture that patches authorization helpers, and a client-backed test
living there can bind those mocks permanently into a router module that imports
for the first time mid-patch.
"""

import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy import func, select, text

from app.processing.raster.models import VrtGeneration
from tests.test_vrt_source_authz_1172 import (
    _create_raster_dataset,
    _create_vrt_dataset,
    _get_admin_id,
    _link_source,
)


async def _vrt_link_ids(session, vrt_id) -> list[uuid.UUID]:
    result = await session.execute(
        text(
            "SELECT source_dataset_id FROM catalog.vrt_source_links "
            "WHERE vrt_dataset_id = :id ORDER BY position ASC"
        ),
        {"id": str(vrt_id)},
    )
    return [row.source_dataset_id for row in result.fetchall()]


async def _only_generation(session, vrt_id):
    result = await session.execute(
        select(VrtGeneration).where(VrtGeneration.vrt_dataset_id == vrt_id)
    )
    return result.scalar_one()


# ---------------------------------------------------------------------------
# What the request writes
# ---------------------------------------------------------------------------


async def test_add_source_stages_the_set_and_leaves_links_alone(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    deferred = _capture_defer(monkeypatch)

    admin_id = await _get_admin_id(test_db_session)
    vrt_id = await _create_vrt_dataset(test_db_session, created_by=admin_id)
    first = await _create_raster_dataset(test_db_session, created_by=admin_id)
    second = await _create_raster_dataset(test_db_session, created_by=admin_id)
    incoming = await _create_raster_dataset(test_db_session, created_by=admin_id)
    await _link_source(test_db_session, vrt_id, first, 0)
    await _link_source(test_db_session, vrt_id, second, 1)

    resp = await client.post(
        f"/ingest/vrt/{vrt_id}/sources/",
        json={"source_dataset_id": str(incoming)},
        headers=admin_auth_header,
    )

    assert resp.status_code == 202, resp.text
    assert await _vrt_link_ids(test_db_session, vrt_id) == [first, second]
    generation = await _only_generation(test_db_session, vrt_id)
    assert generation.staged_source_ids == [str(first), str(second), str(incoming)]
    assert generation.status == "pending"
    assert deferred[0]["task"].name.endswith("regenerate_vrt_staged")


async def test_remove_source_stages_the_set_and_leaves_links_alone(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    deferred = _capture_defer(monkeypatch)

    admin_id = await _get_admin_id(test_db_session)
    vrt_id = await _create_vrt_dataset(test_db_session, created_by=admin_id)
    linked = [
        await _create_raster_dataset(test_db_session, created_by=admin_id)
        for _ in range(3)
    ]
    for position, source_id in enumerate(linked):
        await _link_source(test_db_session, vrt_id, source_id, position)

    resp = await client.delete(
        f"/ingest/vrt/{vrt_id}/sources/{linked[1]}/", headers=admin_auth_header
    )

    assert resp.status_code == 202, resp.text
    assert await _vrt_link_ids(test_db_session, vrt_id) == linked
    generation = await _only_generation(test_db_session, vrt_id)
    assert generation.staged_source_ids == [str(linked[0]), str(linked[2])]
    assert deferred[0]["task"].name.endswith("regenerate_vrt_staged")


async def test_remove_source_404s_without_staging_anything(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    """A rejected request leaves no intent behind — the 404 path included."""
    deferred = _capture_defer(monkeypatch)

    admin_id = await _get_admin_id(test_db_session)
    vrt_id = await _create_vrt_dataset(test_db_session, created_by=admin_id)
    linked = [
        await _create_raster_dataset(test_db_session, created_by=admin_id)
        for _ in range(3)
    ]
    for position, source_id in enumerate(linked):
        await _link_source(test_db_session, vrt_id, source_id, position)
    stranger = await _create_raster_dataset(test_db_session, created_by=admin_id)

    resp = await client.delete(
        f"/ingest/vrt/{vrt_id}/sources/{stranger}/", headers=admin_auth_header
    )

    assert resp.status_code == 404, resp.text
    assert await _vrt_link_ids(test_db_session, vrt_id) == linked
    generations = await test_db_session.execute(
        select(func.count())
        .select_from(VrtGeneration)
        .where(VrtGeneration.vrt_dataset_id == vrt_id)
    )
    assert generations.scalar() == 0
    assert deferred == []


# ---------------------------------------------------------------------------
# Which task name carries it
# ---------------------------------------------------------------------------


def _capture_defer(monkeypatch) -> list[dict]:
    """Record every (task, kwargs) the endpoints hand to Procrastinate.

    fix(#1327 codex P1): the task NAME is the compatibility gate, so the tests
    that care about skew assert on the delivery itself rather than on a mocked
    task object standing in for it.
    """
    captured: list[dict] = []

    async def _fake_defer(task, **kwargs):
        captured.append({"task": task, "kwargs": kwargs})

    monkeypatch.setattr(
        "app.processing.ingest.router.defer_async_with_tenant", _fake_defer
    )
    monkeypatch.setattr(
        "app.modules.catalog.datasets.api.router_vrt.defer_async_with_tenant",
        _fake_defer,
    )
    return captured


async def test_plain_regenerate_keeps_the_legacy_task_name(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    """The other half of the compatibility story.

    A plain regeneration changes no membership, so a pre-#1327 worker runs it
    correctly. Keeping the legacy name is what lets those deliveries keep
    flowing while a rolling upgrade is in progress, instead of failing every
    regeneration for the duration of the roll.
    """
    deferred = _capture_defer(monkeypatch)

    admin_id = await _get_admin_id(test_db_session)
    vrt_id = await _create_vrt_dataset(test_db_session, created_by=admin_id)
    for position in range(2):
        source_id = await _create_raster_dataset(test_db_session, created_by=admin_id)
        await _link_source(test_db_session, vrt_id, source_id, position)

    resp = await client.post(
        f"/datasets/{vrt_id}/vrt/regenerate/", headers=admin_auth_header
    )

    assert resp.status_code == 202, resp.text
    assert len(deferred) == 1
    task_name = deferred[0]["task"].name
    assert task_name.endswith("regenerate_vrt")
    assert not task_name.endswith("regenerate_vrt_staged")
    generation = await _only_generation(test_db_session, vrt_id)
    assert generation.staged_source_ids is None


async def test_both_task_names_run_the_same_pipeline():
    """One implementation, two registered names.

    The staged name is a delivery gate, not a second code path — if it ever
    became one, the staged set would be applied by only half the entrypoints.
    """
    from app.processing.ingest.tasks import regenerate_vrt, regenerate_vrt_staged

    assert regenerate_vrt.name != regenerate_vrt_staged.name
    assert regenerate_vrt.queue == regenerate_vrt_staged.queue == "raster"

    seen: list[dict] = []

    async def _fake_body(**kwargs):
        seen.append(kwargs)

    original = regenerate_vrt.func
    try:
        regenerate_vrt.func = _fake_body
        await regenerate_vrt_staged.func(
            job_id="j", vrt_dataset_id="d", generation_id="g"
        )
    finally:
        regenerate_vrt.func = original

    assert seen == [{"job_id": "j", "vrt_dataset_id": "d", "generation_id": "g"}]


# ---------------------------------------------------------------------------
# The skew itself
# ---------------------------------------------------------------------------


async def test_a_worker_without_the_staged_task_fails_the_job_loudly():
    """The mechanism, measured against the pinned Procrastinate.

    A pre-#1327 worker is exactly a worker whose registry lacks
    ``regenerate_vrt_staged``. It must not silently do something else with the
    delivery, because "something else" is rebuilding from the live links and
    reporting success — the accepted mutation lost with every state machine
    green.

    A marker KWARG could not have done this: the pre-#1327 task signature ends
    in ``**kwargs`` (so does ``tenant_task``'s wrapper), so an unknown keyword
    is swallowed, not rejected. The name is resolved by the worker's registry,
    which is the one thing an old worker cannot fake.

    Also pins that the failure is terminal rather than retried: a missing task
    means there is no task object to ask for a retry strategy, so nothing
    reschedules the job behind the operator's back.
    """
    from procrastinate import App, testing
    from procrastinate.worker import Worker

    connector = testing.InMemoryConnector()
    app = App(connector=connector)

    @app.task(name="app.processing.ingest.tasks_vrt.regenerate_vrt", queue="raster")
    async def legacy_regenerate(**kwargs):
        return "ran"

    async with app.open_async():
        await app.configure_task(
            name="app.processing.ingest.tasks_vrt.regenerate_vrt", queue="raster"
        ).defer_async(job_id="j", vrt_dataset_id="d")
        await app.configure_task(
            name="app.processing.ingest.tasks_vrt.regenerate_vrt_staged",
            queue="raster",
        ).defer_async(job_id="j2", vrt_dataset_id="d2")

        await Worker(
            app,
            queues=["raster"],
            wait=False,
            listen_notify=False,
            install_signal_handlers=False,
        ).run()

    by_name = {row["task_name"]: row for row in connector.jobs.values()}
    legacy = by_name["app.processing.ingest.tasks_vrt.regenerate_vrt"]
    staged = by_name["app.processing.ingest.tasks_vrt.regenerate_vrt_staged"]

    assert legacy["status"] == "succeeded", (
        "a plain regeneration must keep running on a pre-#1327 worker"
    )
    assert staged["status"] == "failed", (
        "a staged mutation must be refused by a worker that cannot apply it"
    )
    assert staged["attempts"] == 1, "no retry may reschedule it silently"


async def test_a_refused_staged_delivery_converges_to_the_handled_state(
    test_db_session,
):
    """Where the skew failure lands: an already-handled state, not a new one.

    The refused delivery never ran, so the links are untouched, the generation
    stays 'pending' with a NULL heartbeat, and the asset stays 'regenerating'.
    The existing stale sweep then reconciles exactly that shape — composition
    preserved, so the asset returns to 'ready' with the requested change simply
    not applied, and the operator re-issues it after the roll.
    """
    from datetime import timedelta

    from app.platform.jobs.router import sweep_stale_vrt_assets
    from app.processing.raster.models import RasterAsset
    from tests.factories import create_dataset, get_user_id

    admin_id = await get_user_id(test_db_session, "admin")
    member = await create_dataset(test_db_session, created_by=admin_id)
    requested = await create_dataset(test_db_session, created_by=admin_id)
    vrt_dataset = await create_dataset(test_db_session, created_by=admin_id)

    started = datetime.now(timezone.utc) - timedelta(hours=2)
    generation = VrtGeneration(
        vrt_dataset_id=vrt_dataset.id,
        status="pending",  # claimed by nobody: the worker refused the delivery
        started_at=started,
        heartbeat_at=None,
        source_count=2,
        staged_source_ids=[str(member.id), str(requested.id)],
    )
    test_db_session.add(generation)
    await test_db_session.flush()
    asset = RasterAsset(
        dataset_id=vrt_dataset.id,
        asset_uri=f"rasters/{vrt_dataset.id}/source.vrt",
        status="regenerating",
        current_generation_id=generation.id,
        built_from={str(member.id): "rasters/member/source.cog.tif"},
    )
    test_db_session.add(asset)
    await test_db_session.execute(
        text(
            "INSERT INTO catalog.vrt_source_links"
            "(vrt_dataset_id, source_dataset_id, position) VALUES (:v, :s, 0)"
        ),
        {"v": str(vrt_dataset.id), "s": str(member.id)},
    )
    await test_db_session.commit()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    await sweep_stale_vrt_assets(test_db_session, cutoff)
    await test_db_session.commit()

    await test_db_session.refresh(asset)
    await test_db_session.refresh(generation)
    assert asset.status == "ready"
    assert asset.current_generation_id is None
    assert generation.status == "failed"
    assert await _vrt_link_ids(test_db_session, vrt_dataset.id) == [member.id]
