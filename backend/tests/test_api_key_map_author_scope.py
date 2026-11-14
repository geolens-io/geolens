"""map_author API keys: read like read_only, create maps, and style only the maps the key created."""

from __future__ import annotations

import re
import uuid
from unittest.mock import patch

import pytest
import sqlalchemy
from fastapi import Depends
from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.config import settings
from app.core.identity import Identity
from app.modules.audit.models import AuditLog
from app.modules.auth.dependencies import (
    _READ_ONLY_KEY_EXEMPT_ROUTES,
    _READ_ONLY_SAFE_METHODS,
    _map_author_key_may_call,
    _read_only_key_may_call,
    get_current_active_user,
)
from app.modules.catalog.maps.author_key import (
    MAP_AUTHOR_DEFAULTS_ACCEPTED,
    MAP_AUTHOR_SETTABLE_FIELDS,
)
from app.modules.catalog.maps.models import Map
from app.modules.catalog.maps.schemas import (
    MapCreate,
    MapLayerDiffRequest,
    MapLayerInput,
    MapLayerPatch,
    MapUpdate,
)
from app.platform.request_credential import MAP_AUTHOR_KEY_ROUTES
from tests import test_api_key_dataset_scope as _dataset_scope
from tests.factories import create_map_via_api, create_user
from tests.test_api_key_scope_875 import _mounted_route_pairs
from tests.test_maps import _valid_png_data_uri

owner = _dataset_scope.owner
datasets = _dataset_scope.datasets
_remove_keys_minted_by_the_test = _dataset_scope._remove_keys_minted_by_the_test

SCOPE_REFUSAL = {
    "code": "api_key_scope",
    "message": (
        "This API key has the map_author scope, which can only read, create "
        "maps and style the maps it created"
    ),
}
NOT_ITS_MAP = {
    "code": "api_key_scope",
    "message": "A map_author key can change only the maps it created",
}

# Every field of each request body the scope reaches that it may NOT set,
# except at its default in MAP_AUTHOR_DEFAULTS_ACCEPTED bodies. With
# MAP_AUTHOR_SETTABLE_FIELDS this covers each model exactly.
_REFUSED_FIELDS: dict[type, set[str]] = {
    MapCreate: {"notes", "terrain_config"},
    MapUpdate: {
        "name",
        "description",
        "notes",
        "show_basemap_labels",
        "show_attribute_table",
        "terrain_config",
        "dashboard_config",
        "visibility",
        "layers",
        "plugins",
        "legend_title",
    },
    MapLayerInput: {
        "id",
        "sort_order",
        "visible",
        "opacity",
        "layout",
        "display_name",
        "filter",
        "label_config",
        "layer_type",
        "show_in_legend",
    },
    MapLayerPatch: {
        "sort_order",
        "visible",
        "opacity",
        "layout",
        "display_name",
        "filter",
        "label_config",
        "layer_type",
        "show_in_legend",
    },
    MapLayerDiffRequest: {"removed", "order", "fallback_full_replace"},
}

PAINT = {"circle-color": "#2a7fbb"}
POPUP = {"enabled": True, "visible_fields": ["name"]}


def _scope_refused(resp) -> bool:
    if resp.status_code != 403:
        return False
    detail = resp.json().get("detail")
    if detail == "This API key is read-only":
        return True
    return isinstance(detail, dict) and detail.get("code") == "api_key_scope"


async def _mint(client: AsyncClient, headers: dict, scope: str) -> dict[str, str]:
    resp = await client.post(
        "/auth/api-keys/",
        json={"name": f"{scope} key", "scope": scope},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["scope"] == scope
    return {"X-Api-Key": resp.json()["key"], "id": resp.json()["id"]}


def _key_header(key: dict[str, str]) -> dict[str, str]:
    return {"X-Api-Key": key["X-Api-Key"]}


async def _creator_key(test_db_session, map_id) -> uuid.UUID | None:
    return (
        await test_db_session.execute(
            select(Map.created_by_api_key_id).where(Map.id == uuid.UUID(str(map_id)))
        )
    ).scalar_one()


async def _authored_map(client, key, dataset) -> tuple[str, str]:
    created = await client.post(
        "/maps/", json={"name": "Trees by species"}, headers=_key_header(key)
    )
    assert created.status_code == 201, created.text
    map_id = created.json()["id"]
    layer = await client.post(
        f"/maps/{map_id}/layers",
        json={"dataset_id": str(dataset.id), "paint": PAINT},
        headers=_key_header(key),
    )
    assert layer.status_code == 201, layer.text
    return map_id, layer.json()["id"]


def _writes(map_id: str, layer_id: str, dataset_id) -> list[tuple[str, str, dict]]:
    """A valid request on each allowlisted route that names a map."""
    return [
        ("PUT", f"/maps/{map_id}", {"zoom": 12}),
        (
            "POST",
            f"/maps/{map_id}/layers",
            {"dataset_id": str(dataset_id), "paint": PAINT},
        ),
        (
            "PATCH",
            f"/maps/{map_id}/layers",
            {"updated": [{"id": layer_id, "popup_config": POPUP}]},
        ),
    ]


# ---------------------------------------------------------------------------
# The allowlist, walked against the live route table
# ---------------------------------------------------------------------------


def test_only_the_listed_writes_pass_and_reads_follow_read_only():
    mounted = _mounted_route_pairs()
    assert MAP_AUTHOR_KEY_ROUTES <= mounted
    for method, template in mounted:
        allowed = _map_author_key_may_call(method, template)
        if method in _READ_ONLY_SAFE_METHODS:
            assert allowed == _read_only_key_may_call(method, template), template
        else:
            expected = (method, template) in (
                MAP_AUTHOR_KEY_ROUTES | _READ_ONLY_KEY_EXEMPT_ROUTES
            )
            assert allowed == expected, (method, template)
    assert not _map_author_key_may_call("POST", "<unmatched-route>")


def test_the_allowlist_holds_only_map_and_layer_authoring():
    templates = {"/maps", "/maps/", "/maps/{map_id}"} | {
        f"/maps/{{map_id}}/layers{slash}" for slash in ("", "/")
    }
    assert {template for _, template in MAP_AUTHOR_KEY_ROUTES} <= templates
    assert {method for method, _ in MAP_AUTHOR_KEY_ROUTES} <= {"POST", "PUT", "PATCH"}
    assert ("PUT", "/maps/{map_id}") in MAP_AUTHOR_KEY_ROUTES
    assert ("DELETE", "/maps/{map_id}") not in MAP_AUTHOR_KEY_ROUTES


def test_every_field_of_each_request_body_is_classified():
    assert set(MAP_AUTHOR_SETTABLE_FIELDS) == set(_REFUSED_FIELDS)
    # Only bodies that add something may carry a refused field at its default.
    assert set(MAP_AUTHOR_DEFAULTS_ACCEPTED) == {MapLayerInput, MapLayerDiffRequest}
    for model, settable in MAP_AUTHOR_SETTABLE_FIELDS.items():
        refused = _REFUSED_FIELDS[model]
        assert not settable & refused, model
        assert set(model.model_fields) == settable | refused, model


# ---------------------------------------------------------------------------
# Live requests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_both_mint_surfaces_accept_the_scope(
    client: AsyncClient, admin_auth_header
):
    await _mint(client, admin_auth_header, "map_author")
    admin_id = (await client.get("/auth/me/", headers=admin_auth_header)).json()["id"]
    resp = await client.post(
        "/admin/api-keys/",
        json={"user_id": admin_id, "name": "Agent", "scope": "map_author"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, resp.text
    listing = await client.get("/admin/api-keys/", headers=admin_auth_header)
    listed = {item["id"]: item["scope"] for item in listing.json()["items"]}
    assert listed[resp.json()["id"]] == "map_author"


@pytest.mark.anyio
async def test_every_listed_route_passes_the_scope_gate(client: AsyncClient, owner):
    """Each pair reaches its handler with a map_author key, not with a read_only one."""
    headers, _ = owner
    author = _key_header(await _mint(client, headers, "map_author"))
    read_only = _key_header(await _mint(client, headers, "read_only"))
    for method, template in sorted(MAP_AUTHOR_KEY_ROUTES):
        url = re.sub(r"\{[^}]+\}", lambda _: str(uuid.uuid4()), template)
        authored = await client.request(method, url, json={}, headers=author)
        refused = await client.request(method, url, json={}, headers=read_only)
        assert not _scope_refused(authored), (method, template, authored.text)
        assert _scope_refused(refused), (method, template, refused.text)


@pytest.mark.anyio
async def test_a_route_added_later_is_refused_until_it_is_listed(
    client: AsyncClient, owner
):
    from app.api.main import app

    async def probe(user: Identity = Depends(get_current_active_user)) -> dict:
        return {"reached": True}

    headers, _ = owner
    author = _key_header(await _mint(client, headers, "map_author"))
    full = _key_header(await _mint(client, headers, "full"))
    app.router.add_api_route("/maps/{map_id}/probe-write", probe, methods=["POST"])
    try:
        url = f"/maps/{uuid.uuid4()}/probe-write"
        refused = await client.post(url, headers=author)
        reached = await client.post(url, headers=full)
    finally:
        app.router.routes.pop()
    assert (refused.status_code, refused.json()["detail"]) == (403, SCOPE_REFUSAL)
    assert reached.status_code == 200, reached.text


@pytest.mark.anyio
async def test_the_key_creates_a_private_map_it_then_authors(
    client: AsyncClient, owner, datasets, test_db_session
):
    headers, owner_id = owner
    key = await _mint(client, headers, "map_author")
    author = _key_header(key)

    created = await client.post(
        "/maps/",
        json={
            "name": "Street trees",
            "description": "Coloured by species",
            "basemap_config": {"label_mode": "full"},
        },
        headers=author,
    )
    assert created.status_code == 201, created.text
    map_id = created.json()["id"]
    assert created.json()["visibility"] == "private"
    assert await _creator_key(test_db_session, map_id) == uuid.UUID(key["id"])
    audit = (
        await test_db_session.execute(
            select(AuditLog.details).where(
                AuditLog.action == "map.create",
                AuditLog.resource_id == uuid.UUID(map_id),
            )
        )
    ).scalar_one()
    assert audit["api_key_id"] == key["id"]

    camera = await client.put(
        f"/maps/{map_id}",
        json={
            "center_lng": -71.08,
            "center_lat": 42.37,
            "zoom": 14,
            "pitch": 30,
            "bearing": 10,
            "basemap_style": "openfreemap-liberty",
        },
        headers=author,
    )
    assert camera.status_code == 200, camera.text
    assert (camera.json()["zoom"], camera.json()["pitch"]) == (14, 30)

    layer = await client.post(
        f"/maps/{map_id}/layers",
        json={"dataset_id": str(datasets[0].id), "paint": PAINT, "popup_config": POPUP},
        headers=author,
    )
    assert layer.status_code == 201, layer.text

    patched = await client.patch(
        f"/maps/{map_id}/layers",
        json={
            "added": [{"dataset_id": str(datasets[1].id), "paint": PAINT}],
            "updated": [
                {
                    "id": layer.json()["id"],
                    "paint": {"circle-color": "#aa3300"},
                    "popup_config": {"enabled": False},
                }
            ],
        },
        headers=author,
    )
    assert patched.status_code == 200, patched.text
    layers = {item["id"]: item for item in patched.json()["layers"]}
    assert len(layers) == 2
    assert layers[layer.json()["id"]]["paint"]["circle-color"] == "#aa3300"

    owner_view = await client.get(f"/maps/{map_id}", headers=headers)
    assert owner_view.json()["created_by"] == str(owner_id)


@pytest.mark.anyio
async def test_other_scopes_record_no_creating_key(
    client: AsyncClient, owner, test_db_session
):
    headers, _ = owner
    for scope in ("publish", "full"):
        key = _key_header(await _mint(client, headers, scope))
        made = await create_map_via_api(client, key)
        assert await _creator_key(test_db_session, made["id"]) is None, scope
    made = await create_map_via_api(client, headers)
    assert await _creator_key(test_db_session, made["id"]) is None


@pytest.mark.anyio
async def test_the_key_is_refused_on_maps_it_did_not_create(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    key = await _mint(client, headers, "map_author")
    author = _key_header(key)

    app_map = await create_map_via_api(client, headers)
    app_layer = await client.post(
        f"/maps/{app_map['id']}/layers",
        json={"dataset_id": str(datasets[0].id)},
        headers=headers,
    )
    assert app_layer.status_code == 201, app_layer.text

    other_key = await _mint(client, headers, "map_author")
    other_map, other_layer = await _authored_map(client, other_key, datasets[0])

    own_map, own_layer = await _authored_map(client, key, datasets[0])

    for map_id, layer_id in (
        (app_map["id"], app_layer.json()["id"]),
        (other_map, other_layer),
    ):
        for method, url, body in _writes(map_id, layer_id, datasets[1].id):
            resp = await client.request(method, url, json=body, headers=author)
            assert (resp.status_code, resp.json()["detail"]) == (403, NOT_ITS_MAP), (
                method,
                url,
            )
    # The same requests succeed on the key's own map.
    for method, url, body in _writes(own_map, own_layer, datasets[1].id):
        resp = await client.request(method, url, json=body, headers=author)
        assert resp.status_code in (200, 201), (method, url, resp.text)


@pytest.mark.anyio
async def test_a_revoked_key_and_its_reissue_lose_the_map(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    key = await _mint(client, headers, "map_author")
    map_id, layer_id = await _authored_map(client, key, datasets[0])

    revoked = await client.delete(f"/auth/api-keys/{key['id']}", headers=headers)
    assert revoked.status_code in (200, 204), revoked.text
    reissued = _key_header(await _mint(client, headers, "map_author"))

    for method, url, body in _writes(map_id, layer_id, datasets[1].id):
        old = await client.request(method, url, json=body, headers=_key_header(key))
        assert old.status_code == 401, (method, url, old.text)
        new = await client.request(method, url, json=body, headers=reissued)
        assert (new.status_code, new.json()["detail"]) == (403, NOT_ITS_MAP), (
            method,
            url,
        )


@pytest.mark.anyio
async def test_a_map_transferred_away_is_no_longer_the_keys(
    client: AsyncClient, admin_auth_header, owner, datasets
):
    """A map moved to another owner is refused to the key that created it, an admin's key included."""
    _, new_owner = owner
    key = await _mint(client, admin_auth_header, "map_author")
    map_id, layer_id = await _authored_map(client, key, datasets[0])
    moved = await client.patch(
        f"/maps/{map_id}", json={"owner_id": str(new_owner)}, headers=admin_auth_header
    )
    assert moved.status_code == 200, moved.text

    for method, url, body in _writes(map_id, layer_id, datasets[1].id):
        resp = await client.request(method, url, json=body, headers=_key_header(key))
        assert (resp.status_code, resp.json()["detail"]) == (403, NOT_ITS_MAP), (
            method,
            url,
        )


def _refused_actions(map_id, layer_id, dataset_id) -> list[tuple[str, str, object]]:
    png = _valid_png_data_uri()
    return [
        ("DELETE", f"/maps/{map_id}", None),
        ("DELETE", f"/maps/{map_id}/layers/{layer_id}", None),
        ("POST", f"/maps/{map_id}/layers/bulk-delete", {"layer_ids": [layer_id]}),
        ("PATCH", f"/maps/{map_id}", {"owner_id": str(uuid.uuid4())}),
        ("POST", f"/maps/{map_id}/share/", {}),
        ("PATCH", f"/maps/{map_id}/share/", {"expires_in_days": 1}),
        ("DELETE", f"/maps/{map_id}/share/", None),
        ("PUT", f"/maps/{map_id}/groups", {"group_ids": []}),
        ("POST", f"/maps/{map_id}/embed-tokens", {"name": "embed"}),
        ("PUT", f"/maps/{map_id}/thumbnail/", {"data_uri": png}),
        ("PUT", f"/maps/{map_id}/og-image/", {"data_uri": png}),
        ("POST", f"/maps/{map_id}/duplicate/", None),
        ("POST", "/maps/import", {"version": 8, "sources": {}, "layers": []}),
        ("POST", "/stories/", {"title": "Story"}),
        ("PATCH", f"/datasets/{dataset_id}", {"title": "Renamed"}),
        ("DELETE", f"/datasets/{dataset_id}", None),
        ("POST", f"/datasets/{dataset_id}/features/", {"geometry": None}),
        ("POST", "/auth/api-keys/", {"name": "Child"}),
        ("POST", "/ingest/upload", None),
    ]


@pytest.mark.anyio
async def test_every_disallowed_action_answers_403(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    key = await _mint(client, headers, "map_author")
    map_id, layer_id = await _authored_map(client, key, datasets[0])
    for method, url, body in _refused_actions(map_id, layer_id, datasets[0].id):
        resp = await client.request(method, url, json=body, headers=_key_header(key))
        assert (resp.status_code, resp.json()["detail"]) == (403, SCOPE_REFUSAL), (
            method,
            url,
            resp.text,
        )
    kept = await client.get(f"/maps/{map_id}", headers=headers)
    assert kept.status_code == 200
    assert [layer["id"] for layer in kept.json()["layers"]] == [layer_id]
    assert kept.json()["visibility"] == "private"


def _beyond_v1(map_id, layer_id, dataset_id) -> list[tuple[str, str, dict, str]]:
    """Requests on allowed routes that carry one field the scope may not set."""
    layer = {"dataset_id": str(dataset_id)}
    return [
        ("POST", "/maps/", {"name": "M", "notes": "private"}, "notes"),
        ("POST", "/maps/", {"name": "M", "terrain_config": None}, "terrain_config"),
        ("PUT", f"/maps/{map_id}", {"visibility": "public"}, "visibility"),
        ("PUT", f"/maps/{map_id}", {"visibility": "private"}, "visibility"),
        ("PUT", f"/maps/{map_id}", {"dashboard_config": None}, "dashboard_config"),
        ("PUT", f"/maps/{map_id}", {"layers": []}, "layers"),
        ("PUT", f"/maps/{map_id}", {"name": "Renamed"}, "name"),
        ("PUT", f"/maps/{map_id}", {"plugins": []}, "plugins"),
        (
            "PUT",
            f"/maps/{map_id}",
            {"show_attribute_table": False},
            "show_attribute_table",
        ),
        (
            "POST",
            f"/maps/{map_id}/layers",
            {**layer, "filter": ["==", ["get", "name"], "oak"]},
            "filter",
        ),
        ("POST", f"/maps/{map_id}/layers", {**layer, "visible": False}, "visible"),
        ("POST", f"/maps/{map_id}/layers", {**layer, "id": layer_id}, "id"),
        ("PATCH", f"/maps/{map_id}/layers", {"removed": [layer_id]}, "removed"),
        (
            "PATCH",
            f"/maps/{map_id}/layers",
            {"fallback_full_replace": True},
            "fallback_full_replace",
        ),
        ("PATCH", f"/maps/{map_id}/layers", {"order": [layer_id]}, "order"),
        (
            "PATCH",
            f"/maps/{map_id}/layers",
            {"updated": [{"id": layer_id, "visible": False}]},
            "visible",
        ),
        (
            "PATCH",
            f"/maps/{map_id}/layers",
            {"added": [{**layer, "display_name": "Oaks"}]},
            "display_name",
        ),
    ]


@pytest.mark.anyio
async def test_fields_beyond_v1_are_refused_on_allowed_routes(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    key = await _mint(client, headers, "map_author")
    map_id, layer_id = await _authored_map(client, key, datasets[0])
    before = (await client.get(f"/maps/{map_id}", headers=headers)).json()
    for method, url, body, field in _beyond_v1(map_id, layer_id, datasets[1].id):
        resp = await client.request(method, url, json=body, headers=_key_header(key))
        assert resp.status_code == 403, (method, url, body, resp.text)
        assert resp.json()["detail"] == {
            "code": "api_key_scope",
            "message": f"A map_author key can't set {field}",
        }, (method, url, body)
    after = (await client.get(f"/maps/{map_id}", headers=headers)).json()
    assert after["layers"] == before["layers"]
    assert (after["name"], after["visibility"]) == (before["name"], "private")


@pytest.mark.anyio
async def test_a_dataset_the_owner_cannot_read_cannot_be_added(
    client: AsyncClient, owner, datasets, admin_auth_header, test_db_session
):
    headers, _ = owner
    key = _key_header(await _mint(client, headers, "map_author"))
    created = await client.post("/maps/", json={"name": "Mine"}, headers=key)
    map_id = created.json()["id"]
    stranger_headers, stranger_id = await create_user(
        client, admin_auth_header, "editor"
    )
    hidden = await _dataset_scope._feature_dataset(
        test_db_session, owner_id=uuid.UUID(stranger_id)
    )
    try:
        added = await client.post(
            f"/maps/{map_id}/layers", json={"dataset_id": str(hidden.id)}, headers=key
        )
        assert added.status_code == 403, added.text
        patched = await client.patch(
            f"/maps/{map_id}/layers",
            json={"added": [{"dataset_id": str(hidden.id)}]},
            headers=key,
        )
        assert patched.status_code == 403, patched.text
        kept = await client.get(f"/maps/{map_id}", headers=headers)
        assert kept.json()["layers"] == []
    finally:
        await test_db_session.execute(
            text(f"DROP TABLE IF EXISTS data.{hidden.table_name}")
        )
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE id = :id"),
            {"id": hidden.record_id},
        )
        await test_db_session.commit()


@pytest.mark.anyio
async def test_the_query_string_key_cannot_write(client: AsyncClient, owner, datasets):
    headers, _ = owner
    key = await _mint(client, headers, "map_author")
    map_id, layer_id = await _authored_map(client, key, datasets[0])
    query = {"api_key": key["X-Api-Key"]}
    created = await client.post("/maps/", json={"name": "Via URL"}, params=query)
    assert created.status_code == 401, created.text
    for method, url, body in _writes(map_id, layer_id, datasets[1].id):
        resp = await client.request(method, url, json=body, params=query)
        assert resp.status_code == 401, (method, url, resp.text)
    read = await client.get(f"/maps/{map_id}", params=query)
    assert read.status_code == 200, read.text


@pytest.fixture
def transfer_after_precheck(owner):
    """Moves the map to ``owner`` once the key pre-check passes, before the write locks it."""
    from app.modules.catalog.maps import router as maps_router

    _, new_owner = owner
    original = maps_router.refuse_map_author_key

    def precheck_then_transfer(db, user_id, body, map_obj=None):
        original(db, user_id, body, map_obj)
        if map_obj is None:
            return
        engine = sqlalchemy.create_engine(settings.test_database_url_sync)
        try:
            with engine.begin() as conn:
                conn.execute(text("SET LOCAL lock_timeout = '3s'"))
                conn.execute(
                    text("UPDATE catalog.maps SET created_by = :owner WHERE id = :id"),
                    {"owner": new_owner, "id": map_obj.id},
                )
        finally:
            engine.dispose()

    with patch.object(maps_router, "refuse_map_author_key", precheck_then_transfer):
        yield


@pytest.mark.anyio
@pytest.mark.parametrize("write", range(3), ids=["put", "post_layer", "patch_layers"])
async def test_a_transfer_after_the_precheck_is_caught_under_the_lock(
    client: AsyncClient, admin_auth_header, owner, datasets, write, request
):
    """An admin's key loses a map transferred between its pre-check and the write."""
    key = await _mint(client, admin_auth_header, "map_author")
    map_id, layer_id = await _authored_map(client, key, datasets[0])
    before = (await client.get(f"/maps/{map_id}", headers=admin_auth_header)).json()

    request.getfixturevalue("transfer_after_precheck")
    method, url, body = _writes(map_id, layer_id, datasets[1].id)[write]
    resp = await client.request(method, url, json=body, headers=_key_header(key))

    assert (resp.status_code, resp.json()["detail"]) == (403, NOT_ITS_MAP)
    after = (await client.get(f"/maps/{map_id}", headers=admin_auth_header)).json()
    assert after["zoom"] == before["zoom"]
    assert after["layers"] == before["layers"]


async def _stored_orders(test_db_session, map_id) -> dict[str, int]:
    rows = await test_db_session.execute(
        text("SELECT id, sort_order FROM catalog.map_layers WHERE map_id = :id"),
        {"id": uuid.UUID(map_id)},
    )
    return {str(layer_id): order for layer_id, order in rows.all()}


@pytest.mark.anyio
async def test_layers_a_map_author_key_adds_go_on_top_in_request_order(
    client: AsyncClient, owner, datasets, test_db_session
):
    headers, _ = owner
    key = _key_header(await _mint(client, headers, "map_author"))
    created = await client.post("/maps/", json={"name": "Stack"}, headers=key)
    map_id = created.json()["id"]
    first, second = (str(d.id) for d in datasets)
    seeded = await client.patch(
        f"/maps/{map_id}/layers",
        json={
            "added": [{"dataset_id": first, "sort_order": order} for order in (0, 1, 2)]
        },
        headers=headers,
    )
    assert seeded.status_code == 200, seeded.text
    expected = {layer["id"]: layer["sort_order"] for layer in seeded.json()["layers"]}
    assert sorted(expected.values()) == [0, 1, 2]

    for body in (
        {"dataset_id": second},
        {"dataset_id": second, "sort_order": 0},
        {
            "dataset_id": second,
            "sort_order": 0,
            "visible": True,
            "opacity": 1.0,
            "show_in_legend": True,
        },
    ):
        added = await client.post(f"/maps/{map_id}/layers", json=body, headers=key)
        assert added.status_code == 201, added.text
        expected[added.json()["id"]] = len(expected)

    for url, datasets_added in (
        (f"/maps/{map_id}/layers", [second]),
        (f"/maps/{map_id}/layers/", [first, second]),
    ):
        before = set(expected)
        patched = await client.patch(
            url,
            json={
                "added": [{"dataset_id": d, "sort_order": 0} for d in datasets_added]
            },
            headers=key,
        )
        assert patched.status_code == 200, patched.text
        new = [layer for layer in patched.json()["layers"] if layer["id"] not in before]
        assert [layer["dataset_id"] for layer in new] == datasets_added
        for layer in new:
            expected[layer["id"]] = len(expected)

    assert await _stored_orders(test_db_session, map_id) == expected
    shown = (await client.get(f"/maps/{map_id}", headers=headers)).json()["layers"]
    assert [layer["id"] for layer in shown] == sorted(expected, key=expected.get)


@pytest.mark.anyio
async def test_other_callers_keep_the_order_they_send(
    client: AsyncClient, owner, datasets, test_db_session
):
    headers, _ = owner
    made = await create_map_via_api(client, headers)
    layer = {"dataset_id": str(datasets[0].id)}
    for _ in range(2):
        resp = await client.post(
            f"/maps/{made['id']}/layers", json=layer, headers=headers
        )
        assert resp.status_code == 201, resp.text
    pinned = await client.post(
        f"/maps/{made['id']}/layers", json={**layer, "sort_order": 0}, headers=headers
    )
    patched = await client.patch(
        f"/maps/{made['id']}/layers", json={"added": [layer]}, headers=headers
    )
    assert patched.status_code == 200, patched.text
    orders = await _stored_orders(test_db_session, made["id"])
    assert orders[pinned.json()["id"]] == 0
    assert sorted(orders.values()) == [0, 0, 0, 1]
