"""Integration tests for PROV-03 provenance attribution across edit paths."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.orm import joinedload

from app.modules.audit.models import AuditLog
from app.modules.catalog.datasets.domain.models import Dataset
from app.processing.ingest.tasks import _apply_reupload_swap

from tests.factories import get_user_id

pytestmark = pytest.mark.anyio


async def _create_role_user(
    client: AsyncClient,
    *,
    admin_headers: dict[str, str],
    role: str,
) -> tuple[dict[str, str], uuid.UUID]:
    username = f"prov_{role}_{uuid.uuid4().hex[:8]}"
    password = "TestPass1234!"

    create_resp = await client.post(
        "/admin/users/",
        json={"username": username, "password": password, "role": role},
        headers=admin_headers,
    )
    assert create_resp.status_code == 201, create_resp.text

    user_id = uuid.UUID(create_resp.json()["id"])

    login_resp = await client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )
    assert login_resp.status_code == 200, login_resp.text
    token = login_resp.json()["access_token"]

    return {"Authorization": f"Bearer {token}"}, user_id


@pytest.fixture
async def layer_factory(client: AsyncClient, admin_auth_header: dict):
    """Create temporary layers and clean them up automatically."""
    created: list[tuple[str, str]] = []

    async def _create(
        *,
        title: str,
        geometry_type: str = "Point",
        columns: list[dict] | None = None,
    ) -> dict:
        payload = {
            "title": title,
            "geometry_type": geometry_type,
            "columns": columns or [{"name": "name", "type": "text"}],
        }
        resp = await client.post(
            "/layers/",
            json=payload,
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        created.append((data["id"], data["title"]))
        return data

    yield _create

    for dataset_id, title in reversed(created):
        await client.request(
            "DELETE",
            f"/datasets/{dataset_id}",
            json={"confirm_title": title},
            headers=admin_auth_header,
        )


async def _dataset_history_actions(
    client: AsyncClient,
    dataset_id: str,
    headers: dict[str, str],
) -> list[dict]:
    resp = await client.get(f"/datasets/{dataset_id}/history", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["logs"]


async def test_metadata_patch_stamps_actor_and_is_visible_in_history(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    layer_factory,
):
    admin_id = await get_user_id(test_db_session, "admin")
    layer = await layer_factory(title=f"prov-meta-{uuid.uuid4().hex[:8]}")

    before = await client.get(f"/datasets/{layer['id']}", headers=admin_auth_header)
    assert before.status_code == 200
    assert before.json()["updated_by"] is None

    resp = await client.patch(
        f"/datasets/{layer['id']}",
        json={"summary": "metadata provenance update"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated_by"] == str(admin_id)

    actions = await _dataset_history_actions(client, layer["id"], admin_auth_header)
    metadata_logs = [entry for entry in actions if entry["action"] == "metadata.edit"]
    assert metadata_logs
    assert metadata_logs[0]["details"]["summary"] == "metadata provenance update"


async def test_attribute_patch_and_reset_stamp_actor_and_emit_dataset_audit(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    layer_factory,
):
    admin_id = await get_user_id(test_db_session, "admin")
    layer = await layer_factory(
        title=f"prov-attr-{uuid.uuid4().hex[:8]}",
        columns=[
            {"name": "name", "type": "text"},
            {"name": "score", "type": "integer"},
        ],
    )

    attrs_resp = await client.get(
        f"/datasets/{layer['id']}/attributes/",
        headers=admin_auth_header,
    )
    assert attrs_resp.status_code == 200, attrs_resp.text
    target_attr = next(
        attr for attr in attrs_resp.json()["attributes"] if attr["field_name"] == "name"
    )

    patch_resp = await client.patch(
        f"/datasets/{layer['id']}/attributes/{target_attr['id']}/",
        json={"title": "Display Name", "description": "Custom description"},
        headers=admin_auth_header,
    )
    assert patch_resp.status_code == 200, patch_resp.text

    reset_resp = await client.post(
        f"/datasets/{layer['id']}/attributes/{target_attr['id']}/reset/",
        headers=admin_auth_header,
    )
    assert reset_resp.status_code == 200, reset_resp.text

    dataset_resp = await client.get(
        f"/datasets/{layer['id']}", headers=admin_auth_header
    )
    assert dataset_resp.status_code == 200
    assert dataset_resp.json()["updated_by"] == str(admin_id)

    actions = await _dataset_history_actions(client, layer["id"], admin_auth_header)
    assert any(entry["action"] == "attribute.edit" for entry in actions)
    assert any(entry["action"] == "attribute.reset" for entry in actions)

    attr_edit = next(entry for entry in actions if entry["action"] == "attribute.edit")
    assert attr_edit["details"]["attribute_id"] == target_attr["id"]
    assert set(attr_edit["details"]["changed_fields"]) == {"title", "description"}


async def test_feature_write_paths_stamp_actor_and_emit_feature_audit_actions(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    layer_factory,
):
    admin_id = await get_user_id(test_db_session, "admin")
    layer = await layer_factory(title=f"prov-feature-{uuid.uuid4().hex[:8]}")

    create_resp = await client.post(
        f"/datasets/{layer['id']}/features/",
        json={
            "geometry": {"type": "Point", "coordinates": [-73.9857, 40.7484]},
            "properties": {"name": "Initial"},
        },
        headers=admin_auth_header,
    )
    assert create_resp.status_code == 201, create_resp.text
    gid = create_resp.json()["id"]

    replace_resp = await client.put(
        f"/datasets/{layer['id']}/features/{gid}",
        json={
            "geometry": {"type": "Point", "coordinates": [-118.2437, 34.0522]},
            "properties": {"name": "Replaced"},
        },
        headers=admin_auth_header,
    )
    assert replace_resp.status_code == 200, replace_resp.text

    patch_resp = await client.patch(
        f"/datasets/{layer['id']}/features/{gid}",
        json={"properties": {"name": "Patched"}},
        headers=admin_auth_header,
    )
    assert patch_resp.status_code == 200, patch_resp.text

    delete_resp = await client.delete(
        f"/datasets/{layer['id']}/features/{gid}",
        headers=admin_auth_header,
    )
    assert delete_resp.status_code == 204, delete_resp.text

    dataset_resp = await client.get(
        f"/datasets/{layer['id']}", headers=admin_auth_header
    )
    assert dataset_resp.status_code == 200
    assert dataset_resp.json()["updated_by"] == str(admin_id)

    actions = await _dataset_history_actions(client, layer["id"], admin_auth_header)
    action_names = {entry["action"] for entry in actions}
    assert {
        "feature.insert",
        "feature.replace",
        "feature.update",
        "feature.delete",
    }.issubset(action_names)


async def test_schema_add_drop_column_stamps_actor_and_emits_dataset_audit(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    layer_factory,
):
    admin_id = await get_user_id(test_db_session, "admin")
    layer = await layer_factory(title=f"prov-schema-{uuid.uuid4().hex[:8]}")

    add_resp = await client.post(
        f"/layers/{layer['id']}/columns/",
        json={"column": {"name": "score", "type": "integer"}},
        headers=admin_auth_header,
    )
    assert add_resp.status_code == 201, add_resp.text

    drop_resp = await client.delete(
        f"/layers/{layer['id']}/columns/score",
        headers=admin_auth_header,
    )
    assert drop_resp.status_code == 200, drop_resp.text

    dataset_resp = await client.get(
        f"/datasets/{layer['id']}", headers=admin_auth_header
    )
    assert dataset_resp.status_code == 200
    assert dataset_resp.json()["updated_by"] == str(admin_id)

    actions = await _dataset_history_actions(client, layer["id"], admin_auth_header)
    action_names = {entry["action"] for entry in actions}
    assert "layer.add_column" in action_names
    assert "layer.drop_column" in action_names


async def test_reupload_swap_stamps_actor_and_emits_reupload_commit_audit(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    layer_factory,
):
    admin_id = await get_user_id(test_db_session, "admin")
    layer = await layer_factory(title=f"prov-reupload-{uuid.uuid4().hex[:8]}")

    dataset_result = await test_db_session.execute(
        select(Dataset)
        .options(joinedload(Dataset.record))
        .where(Dataset.id == uuid.UUID(layer["id"]))
    )
    dataset = dataset_result.scalar_one()

    staging_table = f"{dataset.table_name}_staging"
    await test_db_session.execute(
        text(
            f"CREATE TABLE data.{staging_table} ("
            "gid SERIAL PRIMARY KEY, "
            "geom geometry(Point, 4326), "
            "geom_4326 geometry(Geometry, 4326), "
            "name TEXT)"
        )
    )

    metadata = {
        "srid": 4326,
        "geometry_type": "POINT",
        "feature_count": 5,
        "extent_wkt": "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        "column_info": [
            {"name": "name", "type": "character varying", "ordinal_position": 1},
        ],
    }

    with (
        patch(
            "app.processing.ingest.metadata.refresh_attribute_metadata",
            new_callable=AsyncMock,
        ) as mock_refresh,
        patch(
            "app.processing.ingest.metadata.compute_quality_score",
            new_callable=AsyncMock,
        ) as mock_quality,
    ):
        mock_refresh.return_value = None
        mock_quality.return_value = {"overall": 90}

        await _apply_reupload_swap(
            test_db_session,
            dataset=dataset,
            staging_table=staging_table,
            metadata=metadata,
            sample_values={"name": ["A"]},
            user_id=str(admin_id),
            source_filename="reupload.geojson",
            source_format="geojson",
            original_srid=4326,
            file_hash="abc123",
        )
        await test_db_session.commit()

    await test_db_session.refresh(dataset)
    assert dataset.record.updated_by == admin_id

    audit_result = await test_db_session.execute(
        select(AuditLog)
        .where(
            AuditLog.resource_type == "dataset",
            AuditLog.resource_id == dataset.id,
            AuditLog.action == "reupload.commit",
        )
        .order_by(AuditLog.created_at.desc())
    )
    log_entry = audit_result.scalar_one()
    assert log_entry.user_id == admin_id
    assert log_entry.details["source_type"] == "file"
    assert log_entry.details["source_format"] == "geojson"


async def test_non_mutation_operations_do_not_overwrite_last_editor(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    layer_factory,
):
    admin_id = await get_user_id(test_db_session, "admin")
    viewer_headers, viewer_id = await _create_role_user(
        client,
        admin_headers=admin_auth_header,
        role="viewer",
    )
    layer = await layer_factory(title=f"prov-nonmut-{uuid.uuid4().hex[:8]}")

    patch_resp = await client.patch(
        f"/datasets/{layer['id']}",
        json={"summary": "set editor baseline", "visibility": "public"},
        headers=admin_auth_header,
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["updated_by"] == str(admin_id)

    view_resp = await client.get(f"/datasets/{layer['id']}", headers=viewer_headers)
    assert view_resp.status_code == 200, view_resp.text

    after_resp = await client.get(f"/datasets/{layer['id']}", headers=admin_auth_header)
    assert after_resp.status_code == 200
    assert after_resp.json()["updated_by"] == str(admin_id)

    history = await _dataset_history_actions(client, layer["id"], admin_auth_header)
    view_log = next(
        entry
        for entry in history
        if entry["action"] == "dataset.view" and entry["user_id"] == str(viewer_id)
    )
    assert view_log["action"] == "dataset.view"
