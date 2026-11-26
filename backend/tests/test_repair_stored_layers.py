"""The one-off stored-layer repair command: saves a broken layer, runs it, reads the row back.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import event, select
from sqlalchemy.dialects import postgresql

from app.modules.audit.models import AuditLog
from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.catalog.maps.repair_stored_layers import repair_stored_layers
from tests.conftest import _acquire_test_session_with_retry
from tests.factories import create_dataset
from tests.test_manifest_maps_dry_run import _admin

pytestmark = pytest.mark.anyio


async def _dataset(session, owner_id, column_info) -> uuid.UUID:
    dataset = await create_dataset(
        session,
        created_by=owner_id,
        visibility="public",
        column_info=column_info,
    )
    return dataset.id


async def _map_with_layer(session, owner_id, dataset_id, **layer_fields):
    """A map with one layer on ``dataset_id``; returns both ids."""
    map_obj = Map(name=f"Repair test {uuid.uuid4().hex[:8]}", created_by=owner_id)
    session.add(map_obj)
    await session.flush()
    layer = MapLayer(map_id=map_obj.id, dataset_id=dataset_id, **layer_fields)
    session.add(layer)
    await session.commit()
    return map_obj.id, layer.id


async def _layer_row(session, layer_id) -> MapLayer:
    return (
        await session.execute(
            select(MapLayer)
            .where(MapLayer.id == layer_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _map_row(session, map_id) -> Map:
    return (
        await session.execute(
            select(Map)
            .where(Map.id == map_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def test_command_repairs_a_saved_layer_and_reads_the_row_back(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    sourced_id = await _dataset(
        test_db_session,
        admin.id,
        [
            {"name": "full_name", "type": "text", "source_name": "Name"},
            {"name": "name", "type": "text", "source_name": "Label"},
            {"name": "some_field", "type": "text", "source_name": "Some Field"},
        ],
    )
    map_id, layer_id = await _map_with_layer(
        test_db_session,
        admin.id,
        sourced_id,
        paint={"circle-color": ["get", "Name"], "circle-radius": 6},
        label_config={"column": "Label"},
        popup_config={
            "enabled": True,
            "visible_fields": ["Some Field"],
            "expression": "{Name}",
        },
        filter=["==", ["get", "Some Field"], "x"],
    )
    updated_before = (await _map_row(test_db_session, map_id)).updated_at

    report = await repair_stored_layers(test_db_session)

    # The command repairs every map in the database, so other tests'
    # maps can share the report; look this test's layer up by its id.
    by_layer = {entry.layer_id: entry for entry in report.layers}
    entry = by_layer[layer_id]
    assert (entry.map_id, entry.layer_id, entry.status) == (
        map_id,
        layer_id,
        "repaired",
    )
    assert entry.repaired == {
        "Name": "full_name",
        "Label": "name",
        "Some Field": "some_field",
    }
    assert entry.unrepaired == {}
    row = await _layer_row(test_db_session, layer_id)
    assert row.paint == {"circle-color": ["get", "full_name"], "circle-radius": 6}
    assert row.label_config == {"column": "name"}
    assert row.popup_config == {
        "enabled": True,
        "visible_fields": ["some_field"],
        "expression": "{full_name}",
    }
    assert row.filter == ["==", ["get", "some_field"], "x"]
    # The command writes only the layer rows, so the map's updated_at stands.
    assert (await _map_row(test_db_session, map_id)).updated_at == updated_before

    # A second run finds nothing left to repair.
    again = await repair_stored_layers(test_db_session)
    again_by_layer = {entry.layer_id: entry for entry in again.layers}
    again_entry = again_by_layer[layer_id]
    assert again_entry.status == "unchanged"
    assert again_entry.repaired == {}
    assert (await _layer_row(test_db_session, layer_id)).paint == {
        "circle-color": ["get", "full_name"],
        "circle-radius": 6,
    }


async def test_command_repairs_a_dashed_name_and_leaves_an_exact_match_alone(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    plain_id = await _dataset(
        test_db_session,
        admin.id,
        [{"name": "some_field", "type": "text"}, {"name": "status", "type": "text"}],
    )
    _, dashed_id = await _map_with_layer(
        test_db_session,
        admin.id,
        plain_id,
        paint={"circle-color": ["get", "Some-Field"]},
        layout={"text-field": "{STATUS} open"},
    )
    zoned_id = await _dataset(
        test_db_session,
        admin.id,
        [{"name": "Zone", "type": "text"}, {"name": "zone", "type": "text"}],
    )
    _, zoned_layer_id = await _map_with_layer(
        test_db_session,
        admin.id,
        zoned_id,
        paint={"circle-color": ["get", "Zone"]},
    )

    report = await repair_stored_layers(test_db_session)

    by_layer = {entry.layer_id: entry for entry in report.layers}
    assert by_layer[dashed_id].status == "repaired"
    assert by_layer[zoned_layer_id].status == "unchanged"
    assert by_layer[dashed_id].repaired == {
        "Some-Field": "some_field",
        "STATUS": "status",
    }
    assert by_layer[zoned_layer_id].status == "unchanged"
    assert by_layer[zoned_layer_id].repaired == {}
    assert by_layer[zoned_layer_id].unrepaired == {}
    assert (await _layer_row(test_db_session, dashed_id)).paint == {
        "circle-color": ["get", "some_field"]
    }
    assert (await _layer_row(test_db_session, dashed_id)).layout == {
        "text-field": "{status} open"
    }
    assert (await _layer_row(test_db_session, zoned_layer_id)).paint == {
        "circle-color": ["get", "Zone"]
    }


async def test_command_skips_a_layer_with_no_recorded_columns_and_an_unreadable_one(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    unrecorded_id = await _dataset(test_db_session, admin.id, None)
    _, unrecorded_layer_id = await _map_with_layer(
        test_db_session,
        admin.id,
        unrecorded_id,
        paint={"circle-color": ["get", "Some_Field"]},
    )
    plain_id = await _dataset(
        test_db_session,
        admin.id,
        [{"name": "some_field", "type": "text"}],
    )
    _, unreadable_layer_id = await _map_with_layer(
        test_db_session,
        admin.id,
        plain_id,
        paint={"circle-color": ["get", "Some_Field"], "_weird": 1},
    )

    report = await repair_stored_layers(test_db_session)

    assert len(report.layers) == 2
    by_layer = {entry.layer_id: entry for entry in report.layers}
    assert by_layer[unrecorded_layer_id].status == "skipped"
    assert by_layer[unrecorded_layer_id].reason == "the dataset recorded no columns"
    assert by_layer[unreadable_layer_id].status == "skipped"
    assert (
        by_layer[unreadable_layer_id].reason
        == "the stored layer no longer reads as a layer"
    )
    assert (await _layer_row(test_db_session, unrecorded_layer_id)).paint == {
        "circle-color": ["get", "Some_Field"]
    }
    assert (await _layer_row(test_db_session, unreadable_layer_id)).paint == {
        "circle-color": ["get", "Some_Field"],
        "_weird": 1,
    }


async def _audit_events(session, map_id) -> list[AuditLog]:
    return list(
        (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.action == "map.repair_stored_layers")
                .where(AuditLog.resource_id == map_id)
                .order_by(AuditLog.created_at)
            )
        ).scalars()
    )


async def test_command_takes_the_map_lock_before_it_reads_the_layers(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(
        test_db_session,
        admin.id,
        [{"name": "some_field", "type": "text"}],
    )
    map_id, layer_id = await _map_with_layer(
        test_db_session,
        admin.id,
        dataset_id,
        paint={"circle-color": ["get", "Some_Field"]},
    )

    statements: list[str] = []
    engine = test_db_session.bind.sync_engine

    def _record(conn, clauseelement, multiparams, params, execution_options):
        # SQLAlchemy renders key_share=True as FOR NO KEY UPDATE on
        # PostgreSQL, so compile with that dialect to see the real clause.
        statements.append(str(clauseelement.compile(dialect=postgresql.dialect())))

    event.listen(engine, "before_execute", _record)
    try:
        report = await repair_stored_layers(test_db_session)
    finally:
        event.remove(engine, "before_execute", _record)

    by_layer = {entry.layer_id: entry for entry in report.layers}
    assert by_layer[layer_id].status == "repaired"
    assert statements
    lock_at = next(
        index for index, text in enumerate(statements) if "FOR NO KEY UPDATE" in text
    )
    layers_at = next(
        index for index, text in enumerate(statements) if "column_info" in text
    )
    assert lock_at < layers_at


async def test_command_skips_a_map_another_change_holds(test_db_session, clean_tables):
    import app.core.db as db_module

    admin = await _admin(test_db_session)
    dataset_id = await _dataset(
        test_db_session,
        admin.id,
        [{"name": "some_field", "type": "text"}],
    )
    map_id, layer_id = await _map_with_layer(
        test_db_session,
        admin.id,
        dataset_id,
        paint={"circle-color": ["get", "Some_Field"]},
    )

    async with _acquire_test_session_with_retry(db_module.async_session) as other:
        await other.execute(select(Map).where(Map.id == map_id).with_for_update())
        report = await repair_stored_layers(test_db_session)
        await other.rollback()

    by_layer = {entry.layer_id: entry for entry in report.layers}
    entry = by_layer[layer_id]
    assert (entry.map_id, entry.layer_id, entry.status) == (
        map_id,
        layer_id,
        "skipped",
    )
    assert entry.reason == "another change to the map is in progress"
    assert (await _layer_row(test_db_session, layer_id)).paint == {
        "circle-color": ["get", "Some_Field"]
    }
    # Once the other change releases the map, a rerun repairs the layer.
    again = await repair_stored_layers(test_db_session)
    again_by_layer = {entry.layer_id: entry for entry in again.layers}
    again_entry = again_by_layer[layer_id]
    assert again_entry.status == "repaired"


async def test_command_saves_the_builder_keys_validation_moved_out_of_paint(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(
        test_db_session,
        admin.id,
        [{"name": "some_field", "type": "text"}],
    )
    _, layer_id = await _map_with_layer(
        test_db_session,
        admin.id,
        dataset_id,
        paint={
            "circle-color": ["get", "Some_Field"],
            "_outline-color": "#ff0000",
            "_stroke-disabled": True,
        },
    )

    report = await repair_stored_layers(test_db_session)

    by_layer = {entry.layer_id: entry for entry in report.layers}
    entry = by_layer[layer_id]
    assert entry.status == "repaired"
    assert entry.repaired == {"Some_Field": "some_field"}
    row = await _layer_row(test_db_session, layer_id)
    assert row.paint == {"circle-color": ["get", "some_field"]}
    assert row.style_config == {
        "builder": {"outline_color": "#ff0000", "stroke_disabled": True}
    }
    # A second run keeps the saved builder keys and finds nothing to repair.
    again = await repair_stored_layers(test_db_session)
    again_by_layer = {entry.layer_id: entry for entry in again.layers}
    again_entry = again_by_layer[layer_id]
    assert again_entry.status == "unchanged"
    assert (await _layer_row(test_db_session, layer_id)).style_config == {
        "builder": {"outline_color": "#ff0000", "stroke_disabled": True}
    }


async def test_dry_run_reports_the_repair_without_writing_anything(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(
        test_db_session,
        admin.id,
        [{"name": "some_field", "type": "text"}],
    )
    map_id, layer_id = await _map_with_layer(
        test_db_session,
        admin.id,
        dataset_id,
        paint={"circle-color": ["get", "Some_Field"]},
    )

    report = await repair_stored_layers(test_db_session, dry_run=True)

    assert report.dry_run is True
    by_layer = {entry.layer_id: entry for entry in report.layers}
    entry = by_layer[layer_id]
    assert entry.status == "repaired"
    assert entry.repaired == {"Some_Field": "some_field"}
    assert report.format().startswith("Dry run: no changes were written.")
    assert "would repair" in report.format()
    row = await _layer_row(test_db_session, layer_id)
    assert row.paint == {"circle-color": ["get", "Some_Field"]}
    assert (await _audit_events(test_db_session, map_id)) == []
    # The layer is still broken, so a real run repairs it.
    again = await repair_stored_layers(test_db_session)
    again_by_layer = {entry.layer_id: entry for entry in again.layers}
    again_entry = again_by_layer[layer_id]
    assert again_entry.status == "repaired"


async def test_command_records_one_audit_event_per_repaired_map(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(
        test_db_session,
        admin.id,
        [{"name": "some_field", "type": "text"}],
    )
    first_map_id, first_layer_id = await _map_with_layer(
        test_db_session,
        admin.id,
        dataset_id,
        paint={"circle-color": ["get", "Some_Field"]},
    )
    second_map_id, second_layer_id = await _map_with_layer(
        test_db_session,
        admin.id,
        dataset_id,
        paint={"circle-color": ["get", "Some_Field"]},
    )
    unchanged_map_id, _ = await _map_with_layer(
        test_db_session,
        admin.id,
        dataset_id,
        paint={"circle-color": ["get", "some_field"]},
    )

    report = await repair_stored_layers(test_db_session)

    by_layer = {entry.layer_id: entry for entry in report.layers}
    assert by_layer[first_layer_id].status == "repaired"
    assert by_layer[second_layer_id].status == "repaired"
    [first_event] = await _audit_events(test_db_session, first_map_id)
    assert first_event.action == "map.repair_stored_layers"
    assert first_event.resource_type == "map"
    assert first_event.resource_id == first_map_id
    assert first_event.user_id is None
    assert first_event.details == {
        "layers_repaired": 1,
        "repairs": {str(first_layer_id): {"Some_Field": "some_field"}},
    }
    [second_event] = await _audit_events(test_db_session, second_map_id)
    assert second_event.details["layers_repaired"] == 1
    assert (await _audit_events(test_db_session, unchanged_map_id)) == []


def test_command_runs_in_a_fresh_process_without_the_app_imported():
    """The documented command works from a fresh interpreter.

    A fresh process imports only this module, so AuditLog's User
    relationship has no registered mapper unless the command imports
    the auth models itself; without that import the first query fails
    with InvalidRequestError. The command only reads here, so it is
    safe to run against the test database whatever other tests left.
    """
    from tests.conftest import _db_unavailable_reason

    if _db_unavailable_reason is not None:
        pytest.skip(f"Postgres unreachable: {_db_unavailable_reason}")
    backend_dir = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(backend_dir)
    # The command reads its database from settings.database_url, not
    # the test URL, so point it at this run's test database, the way
    # _point_ogr2ogr_at_test_db redirects ogr2ogr.
    env["POSTGRES_DB"] = os.environ["POSTGRES_DB_TEST"]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.modules.catalog.maps.repair_stored_layers",
            "--dry-run",
        ],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "InvalidRequestError" not in result.stderr
    assert "Dry run: no changes were written." in result.stdout
