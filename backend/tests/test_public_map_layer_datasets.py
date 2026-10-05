"""Which datasets a public map may draw, and who gets its stored images."""

import base64
import re
import uuid
from io import BytesIO

import pytest
from httpx import AsyncClient
from PIL import Image

from app.modules.catalog.maps.models import MapLayer

from tests.factories import create_dataset, create_user, get_user_id


def _image_data_uri(fmt: str) -> str:
    buf = BytesIO()
    Image.new("RGB", (4, 4), color=(10, 20, 30)).save(buf, format=fmt)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/{fmt.lower()};base64,{encoded}"


async def _public_map_with_layer(
    client: AsyncClient, headers: dict, dataset_id: uuid.UUID
) -> str:
    created = await client.post(
        "/maps/", json={"name": f"Public {uuid.uuid4().hex[:6]}"}, headers=headers
    )
    assert created.status_code == 201, created.text
    map_id = created.json()["id"]
    added = await client.post(
        f"/maps/{map_id}/layers", json={"dataset_id": str(dataset_id)}, headers=headers
    )
    assert added.status_code == 201, added.text
    published = await client.put(
        f"/maps/{map_id}", json={"visibility": "public"}, headers=headers
    )
    assert published.status_code == 200, published.text
    return map_id


async def test_layer_changes_keep_a_public_map_to_public_datasets(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Adding a layer re-runs the check publishing runs, on every path that
    can add one; a map that isn't public can still take a private dataset."""
    admin_id = await get_user_id(test_db_session, "admin")
    public_ds = await create_dataset(test_db_session, created_by=admin_id)
    other_public_ds = await create_dataset(test_db_session, created_by=admin_id)
    private_ds = await create_dataset(
        test_db_session, created_by=admin_id, visibility="private"
    )
    map_id = await _public_map_with_layer(client, admin_auth_header, public_ds.id)

    add = await client.post(
        f"/maps/{map_id}/layers",
        json={"dataset_id": str(private_ds.id)},
        headers=admin_auth_header,
    )
    assert add.status_code == 400, add.text

    patch = await client.patch(
        f"/maps/{map_id}/layers",
        json={"added": [{"dataset_id": str(private_ds.id)}]},
        headers=admin_auth_header,
    )
    assert patch.status_code == 400, patch.text

    replace = await client.put(
        f"/maps/{map_id}",
        json={
            "layers": [
                {"dataset_id": str(public_ds.id)},
                {"dataset_id": str(private_ds.id)},
            ]
        },
        headers=admin_auth_header,
    )
    assert replace.status_code == 400, replace.text

    current = await client.get(f"/maps/{map_id}", headers=admin_auth_header)
    assert [layer["dataset_id"] for layer in current.json()["layers"]] == [
        str(public_ds.id)
    ]

    add_public = await client.post(
        f"/maps/{map_id}/layers",
        json={"dataset_id": str(other_public_ds.id)},
        headers=admin_auth_header,
    )
    assert add_public.status_code == 201, add_public.text

    private_map = await client.post(
        "/maps/", json={"name": "Private map"}, headers=admin_auth_header
    )
    add_to_private = await client.post(
        f"/maps/{private_map.json()['id']}/layers",
        json={"dataset_id": str(private_ds.id)},
        headers=admin_auth_header,
    )
    assert add_to_private.status_code == 201, add_to_private.text


async def test_stored_images_go_only_to_callers_who_can_read_every_dataset(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch: pytest.MonkeyPatch,
):
    """A public map that already draws a private dataset keeps its stored
    thumbnail and OG image from anyone who can't read that dataset."""
    from app.modules.catalog.maps import sharing

    async def _app_url(*_args, **_kwargs) -> str:
        return "https://app.example.test"

    monkeypatch.setattr(sharing, "get_public_app_url", _app_url)

    admin_id = await get_user_id(test_db_session, "admin")
    viewer_header, _ = await create_user(client, admin_auth_header, "editor")
    public_ds = await create_dataset(test_db_session, created_by=admin_id)
    private_ds = await create_dataset(
        test_db_session, created_by=admin_id, visibility="private"
    )
    map_id = await _public_map_with_layer(client, admin_auth_header, public_ds.id)
    for path, fmt in (("thumbnail", "PNG"), ("og-image", "JPEG")):
        stored = await client.put(
            f"/maps/{map_id}/{path}/",
            json={"data_uri": _image_data_uri(fmt)},
            headers=admin_auth_header,
        )
        assert stored.status_code == 204, stored.text
    shared = await client.post(f"/maps/{map_id}/share/", headers=admin_auth_header)
    assert shared.status_code == 200, shared.text
    card_path = f"/maps/shared/{shared.json()['token']}/card"

    anonymous = await client.get(f"/maps/{map_id}/thumbnail/")
    assert anonymous.status_code == 200
    assert anonymous.headers["cache-control"] == "public, max-age=3600, s-maxage=60"
    card = await client.get(card_path)
    assert card.headers["cache-control"] == "public, max-age=300, s-maxage=60"
    assert f"/maps/{map_id}/og-image/" in card.text

    # A layer added before public maps were limited to public datasets.
    test_db_session.add(
        MapLayer(map_id=uuid.UUID(map_id), dataset_id=private_ds.id, sort_order=1)
    )
    await test_db_session.commit()

    for path in ("thumbnail", "og-image"):
        assert (await client.get(f"/maps/{map_id}/{path}/")).status_code == 404
        viewer = await client.get(f"/maps/{map_id}/{path}/", headers=viewer_header)
        assert viewer.status_code == 404
        owner = await client.get(f"/maps/{map_id}/{path}/", headers=admin_auth_header)
        assert owner.status_code == 200
        assert owner.headers["cache-control"] == "private, no-cache"

    card = await client.get(card_path)
    image = re.search(r'property="og:image"\s+content="([^"]+)"', card.text)
    assert image is not None, card.text
    assert image.group(1) == "https://app.example.test/og-image.png"


async def test_publishing_while_replacing_layers_checks_the_new_layers(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """One PUT that publishes and replaces the layers is judged on the layers
    it leaves, not the ones it replaces."""
    admin_id = await get_user_id(test_db_session, "admin")
    public_ds = await create_dataset(test_db_session, created_by=admin_id)
    private_ds = await create_dataset(
        test_db_session, created_by=admin_id, visibility="private"
    )

    async def private_map_with_private_layer() -> str:
        created = await client.post(
            "/maps/",
            json={"name": f"Draft {uuid.uuid4().hex[:6]}"},
            headers=admin_auth_header,
        )
        assert created.status_code == 201, created.text
        map_id = created.json()["id"]
        added = await client.post(
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(private_ds.id)},
            headers=admin_auth_header,
        )
        assert added.status_code == 201, added.text
        return map_id

    swapped = await private_map_with_private_layer()
    ok = await client.put(
        f"/maps/{swapped}",
        json={"visibility": "public", "layers": [{"dataset_id": str(public_ds.id)}]},
        headers=admin_auth_header,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["visibility"] == "public"

    kept = await private_map_with_private_layer()
    refused = await client.put(
        f"/maps/{kept}",
        json={"visibility": "public", "layers": [{"dataset_id": str(private_ds.id)}]},
        headers=admin_auth_header,
    )
    assert refused.status_code == 400, refused.text
    after = await client.get(f"/maps/{kept}", headers=admin_auth_header)
    assert after.json()["visibility"] != "public"
