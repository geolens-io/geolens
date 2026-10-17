"""POST /datasets/{id}/features/dry-run/ checks a feature create and stores nothing.

Requires the Docker test database.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

from app.modules.audit.models import AuditLog
from app.modules.catalog.features.models import FeatureCreateKey

from tests.factories import get_user_id
from tests.test_api_key_dataset_scope import (  # noqa: F401 - owner, datasets and the key cleanup are fixtures
    _assert_refused_like_an_invalid_key,
    _editing_off,
    _mint,
    _remove_keys_minted_by_the_test,
    datasets,
    owner,
)
from tests.test_features_crud import _cleanup_table, _create_test_table_and_dataset

POINT_A = {"type": "Point", "coordinates": [-73.9857, 40.7484]}
POINT_B = {"type": "Point", "coordinates": [-118.2437, 34.0522]}
POINT_C = {"type": "Point", "coordinates": [-87.6298, 41.8781]}
POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [[-73.99, 40.74], [-73.98, 40.74], [-73.98, 40.75], [-73.99, 40.74]]
    ],
}
BOWTIE = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]],
}


def _feature(geometry: dict, **properties) -> dict:
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def _collection(*features: dict) -> dict:
    return {"type": "FeatureCollection", "features": list(features)}


async def _drop_dataset(session, table_name: str, record_id) -> None:
    await _cleanup_table(session, table_name)
    await session.execute(
        text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
    )
    await session.commit()


@pytest.fixture
async def point_layer(test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_test_table_and_dataset(
        test_db_session, created_by=admin_id, geometry_type="POINT"
    )
    dataset_id, table_name, record_id = (
        dataset.id,
        dataset.table_name,
        dataset.record_id,
    )
    yield dataset_id, table_name
    await _drop_dataset(test_db_session, table_name, record_id)


@pytest.fixture
async def dated_layer(client: AsyncClient, admin_auth_header: dict, test_db_session):
    """A dataset made through the create endpoint, with a date column."""
    resp = await client.post(
        "/datasets/create/",
        json={
            "title": f"Dry run {uuid.uuid4().hex[:8]}",
            "columns": [
                {"name": "name", "type": "text"},
                {"name": "seen_on", "type": "date"},
            ],
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, resp.text
    dataset_id = uuid.UUID(resp.json()["id"])
    table_name, record_id = (
        await test_db_session.execute(
            text("SELECT table_name, record_id FROM catalog.datasets WHERE id = :id"),
            {"id": dataset_id},
        )
    ).one()
    yield dataset_id, table_name
    await _drop_dataset(test_db_session, table_name, record_id)


async def _stored_state(session, dataset_id, table_name: str) -> dict:
    """Everything a create changes, for comparing before and after a dry run."""
    session.expire_all()
    catalog = (
        await session.execute(
            text(
                "SELECT d.feature_count, d.tile_cache_version, d.data_revision, "
                "d.geometry_type, ST_AsText(r.spatial_extent) AS extent, "
                "r.updated_at, r.updated_by "
                "FROM catalog.datasets d JOIN catalog.records r ON r.id = d.record_id "
                "WHERE d.id = :id"
            ),
            {"id": dataset_id},
        )
    ).one()
    rows = await session.scalar(text(f"SELECT count(*) FROM data.{table_name}"))
    audit = await session.scalar(
        select(func.count()).where(AuditLog.resource_id == dataset_id)
    )
    keys = await session.scalar(
        select(func.count()).where(FeatureCreateKey.dataset_id == dataset_id)
    )
    return {**catalog._asdict(), "rows": rows, "audit": audit, "keys": keys}


def _dry(dataset_id) -> str:
    return f"/datasets/{dataset_id}/features/dry-run/"


def _real(dataset_id) -> str:
    return f"/datasets/{dataset_id}/features/"


async def test_dry_run_of_one_feature_answers_200_and_stores_nothing(
    client: AsyncClient, admin_auth_header: dict, test_db_session, dated_layer
):
    dataset_id, table_name = dated_layer
    before = await _stored_state(test_db_session, dataset_id, table_name)

    resp = await client.post(
        _dry(dataset_id),
        json=_feature(POINT_A, name="a", seen_on="2026-10-17"),
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    assert "location" not in resp.headers
    assert resp.headers["content-type"] == "application/geo+json"
    assert resp.json() == {
        "type": "Feature",
        "geometry": POINT_A,
        "properties": {"name": "a", "seen_on": "2026-10-17"},
    }
    assert await _stored_state(test_db_session, dataset_id, table_name) == before


async def test_dry_run_of_a_collection_answers_200_and_stores_nothing(
    client: AsyncClient, admin_auth_header: dict, test_db_session, point_layer
):
    dataset_id, table_name = point_layer
    before = await _stored_state(test_db_session, dataset_id, table_name)

    resp = await client.post(
        _dry(dataset_id),
        json=_collection(
            _feature(POINT_A, name="a"),
            _feature(POINT_B, name="b", status="open"),
            _feature(POINT_C),
        ),
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    assert "location" not in resp.headers
    assert resp.json() == {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": POINT_A,
                "properties": {"name": "a", "status": None},
            },
            {
                "type": "Feature",
                "geometry": POINT_B,
                "properties": {"name": "b", "status": "open"},
            },
            {
                "type": "Feature",
                "geometry": POINT_C,
                "properties": {"name": None, "status": None},
            },
        ],
    }
    assert await _stored_state(test_db_session, dataset_id, table_name) == before


@pytest.fixture
def request_session_commits(client: AsyncClient):
    """Make every request's session commit when the request ends."""
    import tests.conftest as conftest
    from app.api.main import app
    from app.core.dependencies import get_db

    async def committing_get_db():
        async with conftest._client_session_factory() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = committing_get_db
    yield
    app.dependency_overrides[get_db] = conftest._override_get_db


@pytest.mark.parametrize(
    "body",
    [_feature(POINT_A, name="a"), _collection(_feature(POINT_A), _feature(POINT_B))],
    ids=["feature", "collection"],
)
async def test_a_dry_run_leaves_nothing_for_a_later_commit_to_store(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    point_layer,
    request_session_commits,
    body,
):
    """The inserts are undone inside the request, not only when its session closes."""
    dataset_id, table_name = point_layer
    resp = await client.post(_dry(dataset_id), json=body, headers=admin_auth_header)

    assert resp.status_code == 200, resp.text
    rows = await test_db_session.scalar(text(f"SELECT count(*) FROM data.{table_name}"))
    assert rows == 0


async def _both(client, headers, dataset_id, body) -> tuple[tuple, tuple]:
    dry = await client.post(_dry(dataset_id), json=body, headers=headers)
    real = await client.post(_real(dataset_id), json=body, headers=headers)
    return (dry.status_code, dry.json()), (real.status_code, real.json())


@pytest.mark.parametrize("as_collection", [False, True], ids=["feature", "collection"])
@pytest.mark.parametrize(
    "feature",
    [
        _feature(POINT_A, seen_on="2026-02-30"),
        _feature(POINT_A, seen_on=20261017),
        _feature(POINT_A, typoed_column="x"),
        _feature(BOWTIE, name="bowtie"),
    ],
    ids=["impossible-date", "number-for-date", "unknown-column", "invalid-geometry"],
)
async def test_a_refused_dry_run_is_refused_as_a_real_create_is(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    dated_layer,
    feature,
    as_collection,
):
    dataset_id, table_name = dated_layer
    body = _collection(_feature(POINT_B), feature) if as_collection else feature

    dry, real = await _both(client, admin_auth_header, dataset_id, body)

    assert dry[0] >= 400, dry
    assert dry == real
    assert (await _stored_state(test_db_session, dataset_id, table_name))["rows"] == 0


@pytest.mark.parametrize("as_collection", [False, True], ids=["feature", "collection"])
async def test_a_dry_run_of_the_wrong_geometry_type_is_refused_as_a_real_create_is(
    client: AsyncClient, admin_auth_header: dict, point_layer, as_collection
):
    dataset_id, _ = point_layer
    feature = _feature(POLYGON, name="square")
    body = _collection(_feature(POINT_A), feature) if as_collection else feature

    dry, real = await _both(client, admin_auth_header, dataset_id, body)

    assert dry[0] == 400, dry
    assert dry == real


async def test_a_dry_run_is_refused_with_editing_off_as_a_real_create_is(
    client: AsyncClient, admin_auth_header: dict, point_layer, monkeypatch
):
    import app.core.persistent_config as pc

    dataset_id, _ = point_layer

    class _AlwaysOff:
        async def get(self, _db):
            return False

    monkeypatch.setattr(pc, "ENABLE_DATASET_EDITING", _AlwaysOff())

    dry, real = await _both(client, admin_auth_header, dataset_id, _feature(POINT_A))

    assert dry[0] == 403, dry
    assert dry == real


async def test_a_dry_run_by_a_stranger_is_refused_as_a_real_create_is(
    client: AsyncClient, editor_auth_header: dict, test_db_session, point_layer
):
    dataset_id, table_name = point_layer
    dry, real = await _both(client, editor_auth_header, dataset_id, _feature(POINT_A))

    assert dry[0] == 403, dry
    assert dry == real
    assert (await _stored_state(test_db_session, dataset_id, table_name))["rows"] == 0


async def test_a_dry_run_on_a_missing_dataset_is_404(
    client: AsyncClient, admin_auth_header: dict
):
    dry, real = await _both(client, admin_auth_header, uuid.uuid4(), _feature(POINT_A))

    assert dry[0] == 404, dry
    assert dry == real


@pytest.mark.parametrize("path", ["features/dry-run/", "features/dry-run"])
async def test_the_dry_run_path_reaches_the_dry_run(
    client: AsyncClient, admin_auth_header: dict, test_db_session, point_layer, path
):
    """Neither spelling is taken for a feature id by the routes under features/."""
    dataset_id, table_name = point_layer

    resp = await client.post(
        f"/datasets/{dataset_id}/{path}",
        json=_feature(POINT_A, name="a"),
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["properties"] == {"name": "a", "status": None}
    assert (await _stored_state(test_db_session, dataset_id, table_name))["rows"] == 0


async def test_a_dry_run_body_over_the_feature_write_limit_is_refused_as_a_create_is(
    client: AsyncClient, admin_auth_header: dict, point_layer
):
    from app.api.middleware.body_limit import FEATURE_WRITE_BODY_LIMIT_BYTES

    dataset_id, _ = point_layer
    body = _feature(POINT_A, name="x" * FEATURE_WRITE_BODY_LIMIT_BYTES)

    dry, real = await _both(client, admin_auth_header, dataset_id, body)

    assert dry[0] == 413, dry
    assert dry == real


@pytest.fixture
async def name_unique_deferred(test_db_session, point_layer):
    """A deferred unique name on the point layer's table, and one row named taken."""
    _, table_name = point_layer
    await test_db_session.execute(
        text(
            f"ALTER TABLE data.{table_name} ADD CONSTRAINT {table_name}_name_key "
            "UNIQUE (name) DEFERRABLE INITIALLY DEFERRED"
        )
    )
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{table_name} (geom, geom_4326, name) VALUES "
            "(ST_SetSRID(ST_MakePoint(0, 0), 4326), "
            "ST_SetSRID(ST_MakePoint(0, 0), 4326), 'taken')"
        )
    )
    await test_db_session.commit()
    return point_layer


@pytest.mark.parametrize("as_collection", [False, True], ids=["feature", "collection"])
async def test_a_dry_run_is_refused_by_a_deferred_constraint(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    name_unique_deferred,
    as_collection,
):
    """A real create meets a deferred constraint at commit, after a dry run's rollback."""
    from app.api.main import app

    dataset_id, table_name = name_unique_deferred
    feature = _feature(POINT_A, name="taken")
    body = _collection(_feature(POINT_B), feature) if as_collection else feature

    dry = await client.post(_dry(dataset_id), json=body, headers=admin_auth_header)
    client._transport = ASGITransport(app=app, raise_app_exceptions=False)
    real = await client.post(_real(dataset_id), json=body, headers=admin_auth_header)

    assert (dry.status_code, dry.json()["detail"]) == (
        400,
        "Feature could not be written: a value is incompatible with a column's "
        "type or constraints.",
    )
    # The real create fails at commit, past the handler's error mapping.
    assert real.status_code == 500
    assert (await _stored_state(test_db_session, dataset_id, table_name))["rows"] == 1


_TRIGGER_REFUSAL = (
    "A dry run is not available for this dataset: its table has an INSERT "
    "trigger, whose effects a dry run cannot undo."
)


@pytest.fixture
async def insert_trigger(test_db_session, point_layer):
    """Build a trigger that counts rows into a side table and a sequence.

    The sequence stands in for an effect a rollback cannot undo. Returns a
    function taking the trigger's table and the extra DDL that shapes it.
    """
    _, table_name = point_layer
    side, seq, fn = f"{table_name}_side", f"{table_name}_seq", f"{table_name}_fn"
    made: list[str] = []

    async def build(target: str, timing: str = "INSERT", after: str = "") -> None:
        await test_db_session.execute(text(f"CREATE TABLE data.{side} (n int)"))
        await test_db_session.execute(text(f"CREATE SEQUENCE data.{seq}"))
        await test_db_session.execute(
            text(
                f"CREATE FUNCTION data.{fn}() RETURNS trigger LANGUAGE plpgsql AS $$ "
                f"BEGIN INSERT INTO data.{side} VALUES (nextval('data.{seq}')); "
                "RETURN NEW; END $$"
            )
        )
        await test_db_session.execute(
            text(
                f"CREATE TRIGGER {table_name}_trg BEFORE {timing} ON data.{target} "
                f"FOR EACH ROW EXECUTE FUNCTION data.{fn}()"
            )
        )
        if after:
            await test_db_session.execute(text(after))
        await test_db_session.commit()
        made.append(target)

    yield build
    for target in made:
        if target != table_name:
            await test_db_session.execute(text(f"DROP TABLE data.{target}"))
    await test_db_session.execute(
        text(f"DROP TRIGGER IF EXISTS {table_name}_trg ON data.{table_name}")
    )
    await test_db_session.execute(text(f"DROP FUNCTION IF EXISTS data.{fn}()"))
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{side}"))
    await test_db_session.execute(text(f"DROP SEQUENCE IF EXISTS data.{seq}"))
    await test_db_session.commit()


async def _trigger_effects(session, table_name: str) -> tuple:
    side = await session.scalar(text(f"SELECT count(*) FROM data.{table_name}_side"))
    advanced = await session.scalar(
        text(f"SELECT is_called FROM data.{table_name}_seq")
    )
    return side, advanced


@pytest.mark.parametrize("as_collection", [False, True], ids=["feature", "collection"])
async def test_a_dry_run_is_refused_on_a_table_with_an_insert_trigger(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    point_layer,
    insert_trigger,
    as_collection,
):
    dataset_id, table_name = point_layer
    await insert_trigger(table_name)
    feature = _feature(POINT_A, name="a")
    body = _collection(_feature(POINT_B), feature) if as_collection else feature

    resp = await client.post(_dry(dataset_id), json=body, headers=admin_auth_header)

    assert (resp.status_code, resp.json()["detail"]) == (409, _TRIGGER_REFUSAL)
    assert await _trigger_effects(test_db_session, table_name) == (0, False)


async def test_an_insert_trigger_on_an_inheritance_child_refuses_a_dry_run(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    point_layer,
    insert_trigger,
):
    dataset_id, table_name = point_layer
    child = f"{table_name}_child"
    await test_db_session.execute(
        text(f"CREATE TABLE data.{child} () INHERITS (data.{table_name})")
    )
    await insert_trigger(child)

    resp = await client.post(
        _dry(dataset_id), json=_feature(POINT_A), headers=admin_auth_header
    )

    assert (resp.status_code, resp.json()["detail"]) == (409, _TRIGGER_REFUSAL)


@pytest.mark.parametrize("kind", ["disabled", "update-only"])
async def test_a_trigger_that_does_not_fire_on_insert_leaves_the_dry_run_alone(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    point_layer,
    insert_trigger,
    kind,
):
    dataset_id, table_name = point_layer
    if kind == "disabled":
        await insert_trigger(
            table_name,
            after=f"ALTER TABLE data.{table_name} DISABLE TRIGGER {table_name}_trg",
        )
    else:
        await insert_trigger(table_name, timing="UPDATE")

    resp = await client.post(
        _dry(dataset_id), json=_feature(POINT_A), headers=admin_auth_header
    )

    assert resp.status_code == 200, resp.text
    assert await _trigger_effects(test_db_session, table_name) == (0, False)


async def test_a_real_create_after_a_dry_run_stores_its_feature(
    client: AsyncClient, admin_auth_header: dict, test_db_session, dated_layer
):
    dataset_id, table_name = dated_layer
    body = _feature(POINT_A, name="a", seen_on="2026-10-17")

    dry = await client.post(_dry(dataset_id), json=body, headers=admin_auth_header)
    real = await client.post(_real(dataset_id), json=body, headers=admin_auth_header)

    assert dry.status_code == 200, dry.text
    assert real.status_code == 201, real.text
    gid = real.json()["id"]
    stored = await test_db_session.scalar(
        text(f"SELECT name FROM data.{table_name} WHERE gid = :gid"), {"gid": gid}
    )
    assert stored == "a"
    assert {k: real.json()[k] for k in ("geometry", "properties")} == {
        k: dry.json()[k] for k in ("geometry", "properties")
    }


def _ids(made) -> list[tuple]:
    return [(dataset.id, dataset.table_name) for dataset in made]


async def test_a_dataset_key_dry_runs_a_create_on_its_own_dataset(
    client: AsyncClient,
    owner,  # noqa: F811
    datasets,  # noqa: F811
    test_db_session,
):
    headers, _ = owner
    (dataset_id, table_name), _ = _ids(datasets)
    key = {"X-Api-Key": (await _mint(client, headers, dataset_id))["key"]}
    before = await _stored_state(test_db_session, dataset_id, table_name)

    resp = await client.post(
        _dry(dataset_id), json=_feature(POINT_A, name="webhook"), headers=key
    )

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "type": "Feature",
        "geometry": POINT_A,
        "properties": {"name": "webhook"},
    }
    assert await _stored_state(test_db_session, dataset_id, table_name) == before


async def test_a_dataset_key_dry_run_on_another_dataset_is_refused_as_an_invalid_key(
    client: AsyncClient,
    owner,  # noqa: F811
    datasets,  # noqa: F811
):
    headers, _ = owner
    (bound_id, _), (other_id, _) = _ids(datasets)
    raw_key = (await _mint(client, headers, bound_id))["key"]
    body = _feature(POINT_A)

    await _assert_refused_like_an_invalid_key(
        client, "POST", _dry(other_id), raw_key, json=body
    )
    dry, real = await _both(client, {"X-Api-Key": raw_key}, other_id, body)
    assert dry == real


async def test_a_dataset_key_dry_runs_with_editing_off_as_its_writes_do(
    client: AsyncClient,
    owner,  # noqa: F811
    datasets,  # noqa: F811
    monkeypatch,
):
    headers, _ = owner
    (dataset_id, _), _ = _ids(datasets)
    key = {"X-Api-Key": (await _mint(client, headers, dataset_id))["key"]}
    await _editing_off(monkeypatch)
    body = _feature(POINT_A, name="webhook")

    by_key = await client.post(_dry(dataset_id), json=body, headers=key)
    by_session = await client.post(_dry(dataset_id), json=body, headers=headers)

    assert by_key.status_code == 200, by_key.text
    assert by_session.status_code == 403, by_session.text
    assert "disabled by the administrator" in by_session.json()["detail"]


async def test_a_dry_run_records_the_keys_use(
    client: AsyncClient,
    owner,  # noqa: F811
    datasets,  # noqa: F811
    test_db_session,
):
    """The usage bump commits on its own, so a dry run that commits nothing keeps it."""
    headers, _ = owner
    (dataset_id, _), _ = _ids(datasets)
    data = await _mint(client, headers, dataset_id)

    resp = await client.post(
        _dry(dataset_id), json=_feature(POINT_A), headers={"X-Api-Key": data["key"]}
    )

    assert resp.status_code == 200, resp.text
    await test_db_session.commit()
    last_used = await test_db_session.scalar(
        text("SELECT last_used_at FROM catalog.api_keys WHERE id = :id"),
        {"id": data["id"]},
    )
    assert last_used is not None


async def test_a_read_only_key_dry_run_is_refused_as_a_real_create_is(
    client: AsyncClient,
    owner,  # noqa: F811
    datasets,  # noqa: F811
):
    headers, _ = owner
    (dataset_id, _), _ = _ids(datasets)
    resp = await client.post(
        "/auth/api-keys/",
        json={"name": "Reader", "scope": "read_only"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    dry, real = await _both(
        client, {"X-Api-Key": resp.json()["key"]}, dataset_id, _feature(POINT_A)
    )

    assert dry[0] == 403, dry
    assert dry == real
