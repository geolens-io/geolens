"""Owner filtering precedes map pagination and preserves the other filters."""

from uuid import UUID, uuid4

import pytest

from app.modules.catalog.maps.models import Map

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("role", ["editor", "admin"])
async def test_owned_maps_are_filtered_before_pagination_and_count(
    client, test_db_session, editor_auth_header, admin_auth_header, role
):
    headers = editor_auth_header if role == "editor" else admin_auth_header
    other_headers = admin_auth_header if role == "editor" else editor_auth_header
    owner = await client.get("/auth/me/", headers=headers)
    other = await client.get("/auth/me/", headers=other_headers)
    owner_id = UUID(owner.json()["id"])
    other_id = UUID(other.json()["id"])
    prefix = f"owner-filter-{uuid4().hex}"
    other_maps = [
        Map(name=f"{prefix}-a-{index:02}", created_by=other_id, visibility="public")
        for index in range(21)
    ]
    own_maps = [
        Map(name=f"{prefix}-z-{index}", created_by=owner_id, visibility=visibility)
        for index, visibility in enumerate(("private", "internal", "public"))
    ]
    test_db_session.add_all(other_maps + own_maps)
    await test_db_session.commit()
    own_ids = [str(map_obj.id) for map_obj in own_maps]
    params = {"search": prefix, "sort_by": "name", "sort_dir": "asc", "limit": 20}

    unfiltered = await client.get("/maps/", params=params, headers=headers)
    assert unfiltered.status_code == 200
    assert unfiltered.json()["total"] == 24
    assert len(unfiltered.json()["maps"]) == 20
    assert not set(own_ids) & {item["id"] for item in unfiltered.json()["maps"]}

    filtered = await client.get(
        "/maps/", params={**params, "owned_only": True}, headers=headers
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 3
    assert [item["id"] for item in filtered.json()["maps"]] == own_ids

    page = await client.get(
        "/maps/",
        params={**params, "owned_only": True, "skip": 1, "limit": 1},
        headers=headers,
    )
    assert page.status_code == 200
    assert page.json()["total"] == 3
    assert [item["id"] for item in page.json()["maps"]] == own_ids[1:2]

    private = await client.get(
        "/maps/",
        params={**params, "owned_only": True, "visibility": "private"},
        headers=headers,
    )
    assert private.status_code == 200
    assert private.json()["total"] == 1
    assert [item["id"] for item in private.json()["maps"]] == own_ids[:1]


async def test_anonymous_owned_only_does_not_include_orphaned_maps(
    client, test_db_session
):
    name = f"orphan-owner-filter-{uuid4().hex}"
    test_db_session.add(Map(name=name, created_by=None, visibility="public"))
    await test_db_session.commit()

    public = await client.get("/maps/", params={"search": name})
    assert public.status_code == 200
    assert public.json()["total"] == 1

    owned = await client.get("/maps/", params={"search": name, "owned_only": True})
    assert owned.status_code == 200
    assert owned.json() == {"maps": [], "total": 0}
