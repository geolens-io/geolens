"""Integration tests for dataset CRUD and visibility endpoints.

These tests run against a real database via httpx ASGITransport. Dataset
records are inserted directly into the DB to test endpoint behavior
without going through the full ingest flow.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid
from contextlib import asynccontextmanager

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.catalog.maps.models import Map, MapLayer
from tests.factories import (
    create_dataset as _create_dataset,
    get_user_id as _get_user_id,
)


# ---------------------------------------------------------------------------
# List datasets tests
# ---------------------------------------------------------------------------


class TestListDatasets:
    async def test_list_datasets_requires_auth(self, client: AsyncClient):
        """GET /datasets/ without token returns 401."""
        resp = await client.get("/datasets/")
        assert resp.status_code == 401

    async def test_list_datasets_empty(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /datasets/ returns a list (may be empty) with total field."""
        resp = await client.get("/datasets/", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "datasets" in data
        assert "total" in data
        assert isinstance(data["datasets"], list)

    async def test_list_datasets_visibility_public(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """Public dataset is visible to both admin and viewer."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Public DS",
        )

        # Admin can see it
        resp = await client.get("/datasets/", headers=admin_auth_header)
        assert resp.status_code == 200
        admin_ids = [d["id"] for d in resp.json()["datasets"]]
        assert str(ds.id) in admin_ids

        # Viewer can see it
        resp = await client.get("/datasets/", headers=viewer_auth_header)
        assert resp.status_code == 200
        viewer_ids = [d["id"] for d in resp.json()["datasets"]]
        assert str(ds.id) in viewer_ids

    async def test_list_datasets_visibility_private(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """Private dataset owned by admin is hidden from viewer."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="private",
            name="Private DS",
        )

        # Admin can see it
        resp = await client.get("/datasets/", headers=admin_auth_header)
        assert resp.status_code == 200
        admin_ids = [d["id"] for d in resp.json()["datasets"]]
        assert str(ds.id) in admin_ids

        # Viewer cannot see it
        resp = await client.get("/datasets/", headers=viewer_auth_header)
        assert resp.status_code == 200
        viewer_ids = [d["id"] for d in resp.json()["datasets"]]
        assert str(ds.id) not in viewer_ids


# ---------------------------------------------------------------------------
# Internal visibility tests (#930)
# ---------------------------------------------------------------------------


class TestInternalVisibility:
    """fix(#930): `internal` = any signed-in user, on a published record.

    The two write paths produce different states — ``PATCH /datasets/{id}``
    leaves ``record_status`` at ``published``, while the CLI manifest intent
    writes ``record_status='internal'`` — so both are pinned here, along with
    the two draft cases that separate "hidden from the team" from "hidden from
    its own owner".
    """

    @staticmethod
    async def _own_user_id(client: AsyncClient, headers: dict) -> uuid.UUID:
        """Resolve the caller's own user id.

        ``viewer_auth_header`` mints a fresh ``viewer_<hex>`` account per test,
        so the username is not knowable up front and ``get_user_id`` cannot be
        used to find a non-admin owner.
        """
        resp = await client.get("/auth/me/", headers=headers)
        assert resp.status_code == 200
        return uuid.UUID(resp.json()["id"])

    async def test_internal_published_visible_to_signed_in_non_owner(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """(internal, published) appears in a signed-in non-owner's list."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="internal",
            record_status="published",
            name="Internal Published DS",
        )

        resp = await client.get("/datasets/", headers=viewer_auth_header)
        assert resp.status_code == 200
        assert str(ds.id) in [d["id"] for d in resp.json()["datasets"]]

        resp = await client.get(f"/datasets/{ds.id}", headers=viewer_auth_header)
        assert resp.status_code == 200
        assert resp.json()["visibility"] == "internal"

    async def test_internal_published_visible_to_owner(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """A non-admin owner keeps their own internal dataset in their list.

        Before #930 the ``filter_visible`` conditions matched no internal
        branch at all, so an internal dataset vanished from every non-admin
        list including its owner's.
        """
        viewer_id = await self._own_user_id(client, viewer_auth_header)
        ds = await _create_dataset(
            test_db_session,
            created_by=viewer_id,
            visibility="internal",
            record_status="published",
            name="Internal Owned By Viewer DS",
        )

        resp = await client.get("/datasets/", headers=viewer_auth_header)
        assert resp.status_code == 200
        assert str(ds.id) in [d["id"] for d in resp.json()["datasets"]]

        resp = await client.get(f"/datasets/{ds.id}", headers=viewer_auth_header)
        assert resp.status_code == 200

    async def test_internal_record_status_hidden_from_non_owner(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """(internal, internal) — the `geolens apply` state — stays owner-only.

        ``record_status='internal'`` is not published, so the status gate keeps
        the record away from a signed-in non-owner on both surfaces.
        """
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="internal",
            record_status="internal",
            name="Internal Unpublished DS",
        )

        resp = await client.get("/datasets/", headers=viewer_auth_header)
        assert resp.status_code == 200
        assert str(ds.id) not in [d["id"] for d in resp.json()["datasets"]]

        resp = await client.get(f"/datasets/{ds.id}", headers=viewer_auth_header)
        assert resp.status_code == 404

    async def test_internal_draft_hidden_from_non_owner(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """An owner's (internal, draft) dataset does not leak to the team."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="internal",
            record_status="draft",
            name="Internal Draft DS",
        )

        resp = await client.get("/datasets/", headers=viewer_auth_header)
        assert resp.status_code == 200
        assert str(ds.id) not in [d["id"] for d in resp.json()["datasets"]]

        resp = await client.get(f"/datasets/{ds.id}", headers=viewer_auth_header)
        assert resp.status_code == 404

    async def test_internal_draft_still_visible_to_its_own_owner(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """A non-admin owner keeps their own *unpublished* internal dataset.

        ``status_filter`` is ``published OR created_by == <caller>``, so it
        already hides another user's draft from the team. Gating the internal
        branch on ``published`` as well would additionally hide the owner's own
        draft from the owner — the list/detail split #930 exists to close, and
        a repeat of the #929 creator-exemption bug. Private and public drafts
        stay visible to their owner, and internal must match.
        """
        viewer_id = await self._own_user_id(client, viewer_auth_header)
        ds = await _create_dataset(
            test_db_session,
            created_by=viewer_id,
            visibility="internal",
            record_status="draft",
            name="Internal Draft Owned By Viewer DS",
        )

        resp = await client.get("/datasets/", headers=viewer_auth_header)
        assert resp.status_code == 200
        assert str(ds.id) in [d["id"] for d in resp.json()["datasets"]]

        resp = await client.get(f"/datasets/{ds.id}", headers=viewer_auth_header)
        assert resp.status_code == 200

    async def test_internal_published_hidden_from_anonymous(
        self,
        client: AsyncClient,
        test_db_session,
    ):
        """Internal never reaches a signed-out visitor."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="internal",
            record_status="published",
            name="Internal Anon DS",
        )

        resp = await client.get(f"/datasets/{ds.id}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Get single dataset tests
# ---------------------------------------------------------------------------


class TestGetDataset:
    async def test_get_dataset_not_found(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /datasets/{id} for nonexistent ID returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/datasets/{fake_id}", headers=admin_auth_header)
        assert resp.status_code == 404

    async def test_get_dataset_success(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """GET /datasets/{id} returns correct fields for an existing dataset."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Get Test DS",
            srid=4326,
            geometry_type="Point",
            feature_count=10,
        )

        resp = await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(ds.id)
        assert data["title"] == "Get Test DS"
        assert data["srid"] == 4326
        assert data["geometry_type"] == "Point"
        assert data["feature_count"] == 10
        assert data["visibility"] == "public"

    async def test_get_dataset_maps_3d_metadata(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """fix(#647): is_3d/n_dims/z_min/z_max surface from the Dataset row."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="3D Meta DS"
        )
        ds.is_3d = True
        ds.n_dims = 3
        ds.z_min = 0.0
        ds.z_max = 12.5
        await test_db_session.commit()

        resp = await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_3d"] is True
        assert data["n_dims"] == 3
        assert data["z_min"] == 0.0
        assert data["z_max"] == 12.5


# ---------------------------------------------------------------------------
# Update metadata tests
# ---------------------------------------------------------------------------


class TestUpdateMetadata:
    async def test_update_metadata_requires_editor(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        admin_auth_header: dict,
        test_db_session,
    ):
        """PATCH /datasets/{id} with viewer token returns 403."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Viewer Patch Test",
        )

        resp = await client.patch(
            f"/datasets/{ds.id}",
            json={"title": "Should Not Change"},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403

    async def test_update_metadata_success(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """PATCH /datasets/{id} updates user-editable fields, preserves auto-extracted."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Original Name",
            description="Original description",
            srid=4326,
            geometry_type="MultiPolygon",
            feature_count=42,
        )

        # Patch title and summary
        resp = await client.patch(
            f"/datasets/{ds.id}",
            json={
                "title": "Updated Name",
                "summary": "Updated description",
                "theme_category": ["updated", "test"],
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()

        # User-editable fields updated
        assert data["title"] == "Updated Name"
        assert data["summary"] == "Updated description"
        assert data["theme_category"] == ["updated", "test"]

        # Auto-extracted fields preserved
        assert data["srid"] == 4326
        assert data["geometry_type"] == "MultiPolygon"
        assert data["feature_count"] == 42

    async def test_restrict_dataset_blocked_when_used_in_public_map(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """PATCH /datasets/{id} with visibility=restricted returns 422 when used in a public map."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Public In Map DS",
        )

        # Create a public map with this dataset as a layer
        map_obj = Map(
            name="Public Map With DS",
            visibility="public",
            created_by=admin_id,
        )
        test_db_session.add(map_obj)
        await test_db_session.flush()

        layer = MapLayer(
            map_id=map_obj.id,
            dataset_id=ds.id,
            sort_order=0,
        )
        test_db_session.add(layer)
        await test_db_session.commit()

        # Attempt to restrict dataset visibility
        resp = await client.patch(
            f"/datasets/{ds.id}",
            json={"visibility": "restricted"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "Public Map With DS" in resp.json()["detail"]

    async def test_restrict_dataset_allowed_when_no_public_maps(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """PATCH /datasets/{id} with visibility=restricted succeeds when not in any public map."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Unreferenced DS",
        )

        resp = await client.patch(
            f"/datasets/{ds.id}",
            json={"visibility": "restricted"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["visibility"] == "restricted"

    async def _dataset_on_map(
        self,
        test_db_session,
        admin_id,
        *,
        dataset_visibility: str,
        map_visibility: str,
        map_name: str,
    ):
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility=dataset_visibility,
            name=f"{map_name} DS",
        )
        map_obj = Map(name=map_name, visibility=map_visibility, created_by=admin_id)
        test_db_session.add(map_obj)
        await test_db_session.flush()
        test_db_session.add(MapLayer(map_id=map_obj.id, dataset_id=ds.id, sort_order=0))
        await test_db_session.commit()
        return ds

    async def _grant_role(self, test_db_session, dataset_id, role_name: str):
        from app.modules.auth.models import Role
        from app.modules.catalog.datasets.domain.models import DatasetGrant

        role = (
            await test_db_session.execute(select(Role).where(Role.name == role_name))
        ).scalar_one()
        test_db_session.add(DatasetGrant(dataset_id=dataset_id, role_id=role.id))
        await test_db_session.commit()

    async def _grant_empty_role(self, test_db_session, dataset_id):
        """Grant a role created here, so "it has no members" is a fact.

        The seeded roles are shared: 22 test files mint `editor_<hex>` accounts
        and 37 mint `viewer_<hex>`, all on the same per-worker database. A test
        asserting a grant reaches NOBODY cannot borrow one of those — its
        emptiness would depend on which files happened to run first, which is
        true in file order and false under `-n 4`.
        """
        from app.modules.auth.models import Role
        from app.modules.catalog.datasets.domain.models import DatasetGrant

        role = Role(name=f"empty-grant-{uuid.uuid4().hex[:8]}")
        test_db_session.add(role)
        await test_db_session.flush()
        test_db_session.add(DatasetGrant(dataset_id=dataset_id, role_id=role.id))
        await test_db_session.commit()

    async def test_a_grant_reaching_a_real_viewer_blocks_the_drop_to_private(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """fix(#931 codex r1/r3): `restricted` is a partial audience when, and
        only when, a grant reaches someone who would LOSE access.

        The `viewer_auth_header` fixture mints a real viewer and assigns the
        role, so the grant below reaches a user who is neither the owner nor an
        admin. That user renders the layer today and stops after the move, which
        is the stranding this guard exists for.
        """
        admin_id = await _get_user_id(test_db_session, "admin")
        map_name = "Granted Restricted Map"
        ds = await self._dataset_on_map(
            test_db_session,
            admin_id,
            dataset_visibility="restricted",
            map_visibility="internal",
            map_name=map_name,
        )
        # fix(#931): borrows the seeded `viewer` role deliberately. This asserts
        # BLOCKED, so it needs the role to have a member — `viewer_auth_header`
        # guarantees one, and the accounts other files leave on the shared
        # worker DB only reinforce it. The direction is what makes the ambient
        # dependency safe here; the empty-role case below cannot borrow and
        # builds its own.
        await self._grant_role(test_db_session, ds.id, "viewer")

        resp = await client.patch(
            f"/datasets/{ds.id}",
            json={"visibility": "private"},
            headers=admin_auth_header,
        )

        assert resp.status_code == 422
        assert map_name in resp.json()["detail"]

    async def test_a_grant_to_an_empty_role_does_not_block(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """fix(#931 codex r3): a grant row is not an audience.

        The granted role is created here and never populated, so the grant
        reaches nobody. Blocking would be a refusal that lies — the same defect
        as the ungranted case, one level further in.

        It must NOT borrow a seeded role. The first version granted `editor`
        and reasoned "no `editor_auth_header` in this test, so it is empty",
        which is a claim about the whole worker rather than about this test:
        22 files mint editor accounts on the same database. It passed in file
        order, where `test_datasets.py` runs first, and failed under `-n 4`.
        """
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await self._dataset_on_map(
            test_db_session,
            admin_id,
            dataset_visibility="restricted",
            map_visibility="internal",
            map_name="Empty Grant Map",
        )
        await self._grant_empty_role(test_db_session, ds.id)

        resp = await client.patch(
            f"/datasets/{ds.id}",
            json={"visibility": "private"},
            headers=admin_auth_header,
        )

        assert resp.status_code == 200, resp.text

    async def test_a_grant_reaching_only_an_inactive_user_does_not_block(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """fix(#931 codex r4): a grant holder who cannot authenticate is not an
        audience.

        `get_optional_user` rejects a non-active account before it can render a
        layer, so deactivating the only grant holder leaves nobody to strand —
        and the same move that must block while they are active must stop
        blocking once they are not. Both directions are asserted, because the
        failure this guards against is a refusal that lies.

        The grant goes to a role created for this test rather than to `viewer`:
        the per-worker database is shared across tests, and earlier ones leave
        active `viewer_<hex>` accounts behind, so granting `viewer` would reach
        members this test cannot deactivate.
        """
        from app.modules.auth.models import Role, User, UserRole
        from app.modules.catalog.datasets.domain.models import DatasetGrant

        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await self._dataset_on_map(
            test_db_session,
            admin_id,
            dataset_visibility="restricted",
            map_visibility="internal",
            map_name="Inactive Grant Map",
        )

        viewer_id = uuid.UUID(
            (await client.get("/auth/me/", headers=viewer_auth_header)).json()["id"]
        )
        role = Role(name=f"grant-only-{uuid.uuid4().hex[:8]}")
        test_db_session.add(role)
        await test_db_session.flush()
        test_db_session.add(UserRole(user_id=viewer_id, role_id=role.id))
        test_db_session.add(DatasetGrant(dataset_id=ds.id, role_id=role.id))
        await test_db_session.commit()

        # Sole grant holder is active: the move strands them, so it is refused.
        blocked = await client.patch(
            f"/datasets/{ds.id}",
            json={"visibility": "private"},
            headers=admin_auth_header,
        )
        assert blocked.status_code == 422
        assert "Inactive Grant Map" in blocked.json()["detail"]

        viewer = await test_db_session.get(User, viewer_id)
        viewer.is_active = False
        viewer.status = "suspended"
        await test_db_session.commit()

        # Same move, same grant row — nobody left who could have rendered it.
        allowed = await client.patch(
            f"/datasets/{ds.id}",
            json={"visibility": "private"},
            headers=admin_auth_header,
        )
        assert allowed.status_code == 200, allowed.text

    @staticmethod
    @asynccontextmanager
    async def _only_admins_active(test_db_session):
        """Temporarily leave the admin accounts as the only active users.

        The per-worker DB persists across tests, so earlier ones leave live
        `viewer_<hex>` accounts behind. A test asserting "nobody else is in the
        audience" has to remove them — and RESTORE them, or it silently rewrites
        the world for every test that runs after it in the same worker. Ask me
        how I know.
        """
        from app.modules.auth.models import Role, User, UserRole

        admin_ids = (
            select(UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.name == "admin")
        )
        strays = (
            (
                await test_db_session.execute(
                    select(User).where(
                        User.is_active.is_(True), User.id.notin_(admin_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        saved = [(u, u.is_active, u.status) for u in strays]
        for user, _, _ in saved:
            user.is_active = False
            user.status = "suspended"
        await test_db_session.commit()
        try:
            yield
        finally:
            for user, was_active, was_status in saved:
                user.is_active = was_active
                user.status = was_status
            await test_db_session.commit()

    async def test_internal_to_private_does_not_block_when_no_one_else_is_active(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """fix(#931 codex r5): a rank drop is not the same as someone losing access.

        No `viewer_auth_header` here, so the only accounts are the admin owner
        and other admins — all of whom keep access either way. The internal
        audience the move removes is empty, so refusing would be a refusal that
        lies. Deactivate any stray non-admin left by an earlier test in this
        worker, since the per-worker DB persists.
        """
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await self._dataset_on_map(
            test_db_session,
            admin_id,
            dataset_visibility="internal",
            map_visibility="internal",
            map_name="No Other Viewers Map",
        )

        async with self._only_admins_active(test_db_session):
            resp = await client.patch(
                f"/datasets/{ds.id}",
                json={"visibility": "private"},
                headers=admin_auth_header,
            )

        assert resp.status_code == 200, resp.text

    async def test_internal_to_restricted_blocks_when_someone_is_ungranted(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """The mirror: an active user no grant reaches DOES lose the layer.

        `viewer_auth_header` mints an active non-admin with no grant on this
        dataset, so narrowing `internal -> restricted` strands them and the
        refusal is honest.
        """
        assert viewer_auth_header  # the fixture's account is the stranded viewer
        admin_id = await _get_user_id(test_db_session, "admin")
        map_name = "Ungranted Viewer Map"
        ds = await self._dataset_on_map(
            test_db_session,
            admin_id,
            dataset_visibility="internal",
            map_visibility="internal",
            map_name=map_name,
        )

        resp = await client.patch(
            f"/datasets/{ds.id}",
            json={"visibility": "restricted"},
            headers=admin_auth_header,
        )

        assert resp.status_code == 422
        assert map_name in resp.json()["detail"]

    async def test_only_the_stranded_map_is_named_when_audiences_differ(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """fix(#931 codex r6): each audience is judged on its own.

        A public dataset on BOTH a public and an internal map, moving to
        private. The public map strands its anonymous visitors and must be
        named. The internal map strands nobody — the only active accounts here
        are the admin owner and other admins, all of whom keep access — so
        naming it would send the operator to remove a layer from a map that
        renders fine.
        """
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await self._dataset_on_map(
            test_db_session,
            admin_id,
            dataset_visibility="public",
            map_visibility="public",
            map_name="Anonymous Strands Here",
        )
        internal_map = Map(
            name="Internal Strands Nobody",
            visibility="internal",
            created_by=admin_id,
        )
        test_db_session.add(internal_map)
        await test_db_session.flush()
        test_db_session.add(
            MapLayer(map_id=internal_map.id, dataset_id=ds.id, sort_order=0)
        )
        await test_db_session.commit()

        async with self._only_admins_active(test_db_session):
            resp = await client.patch(
                f"/datasets/{ds.id}",
                json={"visibility": "private"},
                headers=admin_auth_header,
            )

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "Anonymous Strands Here" in detail
        assert "Internal Strands Nobody" not in detail

    async def test_an_unpublished_dataset_never_blocks(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """fix(#931 codex r3): an unpublished record is already invisible to
        every shared-map audience.

        `filter_visible`'s status gate is `published OR created_by == <caller>`,
        so a draft reaches only its creator, and admins bypass the filter — both
        keep access after any visibility change. A rank comparison alone would
        invent a 422 for a move that costs nothing.
        """
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await self._dataset_on_map(
            test_db_session,
            admin_id,
            dataset_visibility="public",
            map_visibility="public",
            map_name="Draft On Public Map",
        )
        ds.record.record_status = "draft"
        await test_db_session.commit()

        resp = await client.patch(
            f"/datasets/{ds.id}",
            json={"visibility": "private"},
            headers=admin_auth_header,
        )

        assert resp.status_code == 200, resp.text

    @pytest.mark.parametrize(
        ("dataset_visibility", "map_visibility", "new_visibility", "blocked"),
        [
            # fix(#931): the case the old query missed entirely. An internal map
            # reaches every signed-in user, so a dataset dropping to private
            # strands it — silently, before this.
            ("public", "internal", "private", True),
            ("internal", "internal", "private", True),
            ("internal", "internal", "restricted", True),
            # ...and the move that only looks like it strands one. #930 made
            # internal a real dataset rung, so an internal map keeps working.
            # A rule written against the target value alone would block this.
            ("public", "internal", "internal", False),
            # A private map has no audience beyond its owner and grantees.
            ("public", "private", "private", False),
            # fix(#931 codex r2): a restricted dataset with NO grants reaches
            # nobody beyond its owner and admins, who keep access either way —
            # blocking that move would be a refusal that lies. The granted case
            # is covered separately below, since it needs a grant row.
            ("restricted", "internal", "private", False),
            ("restricted", "public", "private", False),
            # Widening never strands anyone.
            ("restricted", "internal", "public", False),
            ("private", "internal", "internal", False),
            # The public-map rule is unchanged — any move off public strands it.
            ("public", "public", "internal", True),
            ("public", "public", "private", True),
        ],
    )
    async def test_visibility_change_blocks_exactly_the_maps_it_strands(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        dataset_visibility: str,
        map_visibility: str,
        new_visibility: str,
        blocked: bool,
    ):
        """fix(#931): the block is a before/after comparison, not a list of
        forbidden target values.

        ``find_public_maps_using_dataset`` matched ``Map.visibility == "public"``
        only, and its caller gated on ``old == public``, so an internal map was
        invisible to both halves. Once #930 made ``internal`` a real dataset
        rung the rule became a matrix, and each row here is one cell of it.
        """
        admin_id = await _get_user_id(test_db_session, "admin")
        map_name = f"Strand {map_visibility} {dataset_visibility} {new_visibility}"
        ds = await self._dataset_on_map(
            test_db_session,
            admin_id,
            dataset_visibility=dataset_visibility,
            map_visibility=map_visibility,
            map_name=map_name,
        )

        resp = await client.patch(
            f"/datasets/{ds.id}",
            json={"visibility": new_visibility},
            headers=admin_auth_header,
        )

        if blocked:
            assert resp.status_code == 422
            assert map_name in resp.json()["detail"]
        else:
            assert resp.status_code == 200, resp.text
            assert resp.json()["visibility"] == new_visibility


# ---------------------------------------------------------------------------
# Anonymous access tests
# ---------------------------------------------------------------------------


class TestAnonymousAccess:
    """Verify anonymous (no auth) users can access public resources."""

    async def test_anon_get_public_dataset(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Anonymous GET /datasets/{id} returns 200 for public+published dataset."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Anon Public DS",
        )
        resp = await client.get(f"/datasets/{ds.id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Anon Public DS"

    async def test_anon_get_private_dataset_returns_404(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Anonymous GET /datasets/{id} returns 404 for private dataset."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="private",
            name="Anon Private DS",
        )
        resp = await client.get(f"/datasets/{ds.id}")
        assert resp.status_code == 404

    async def test_anon_search_returns_public_only(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Anonymous GET /search/datasets returns only public+published datasets."""
        admin_id = await _get_user_id(test_db_session, "admin")
        pub = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Search Public",
        )
        priv = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="private",
            name="Search Private",
        )
        resp = await client.get("/search/datasets/")
        assert resp.status_code == 200
        ids = [f["id"] for f in resp.json()["features"]]
        assert str(pub.id) in ids
        assert str(priv.id) not in ids

    async def test_anon_search_facets(self, client: AsyncClient):
        """Anonymous GET /search/facets returns 200."""
        resp = await client.get("/search/facets/")
        assert resp.status_code == 200

    async def test_anon_get_dataset_rows_public(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Anonymous GET /datasets/{id}/rows returns 200 for public dataset."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Anon Rows DS",
        )
        resp = await client.get(f"/datasets/{ds.id}/rows/")
        # 200 or 404 (no data table), but NOT 401
        assert resp.status_code != 401

    async def test_anon_get_restricted_dataset_returns_404(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Anonymous GET /datasets/{id} returns 404 for restricted dataset."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="restricted",
            name="Anon Restricted DS",
        )
        resp = await client.get(f"/datasets/{ds.id}")
        assert resp.status_code == 404

    async def test_logged_in_non_grantee_get_restricted_returns_404(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """Restricted requires a role GRANT, not merely a session — but admins bypass it.

        Every other restricted-denial test signs the caller out, so nothing
        pinned the authenticated case and the UI told users "Restricted =
        logged-in users only" for months. The public control rules out a 404
        from some unrelated cause: the same viewer sees a public dataset
        built the same way. The admin leg pins the other half of the help
        text (fix(#690) review) — `can_access_dataset` returns True on the
        admin role before it ever looks for a grant.
        """
        admin_id = await _get_user_id(test_db_session, "admin")
        restricted = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="restricted",
            name="Non-Grantee Restricted DS",
        )
        public = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Non-Grantee Public DS",
        )
        control = await client.get(f"/datasets/{public.id}", headers=viewer_auth_header)
        assert control.status_code == 200
        resp = await client.get(
            f"/datasets/{restricted.id}", headers=viewer_auth_header
        )
        assert resp.status_code == 404

        # ...while an admin reads the same dataset with no grant at all.
        as_admin = await client.get(
            f"/datasets/{restricted.id}", headers=admin_auth_header
        )
        assert as_admin.status_code == 200

    async def test_owner_of_restricted_dataset_keeps_access(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """The creator of a restricted dataset is exempt from the grant check.

        fix(#929): restricted means "owner, admins, and grant holders". Before
        the creator exemption, a non-admin owner who set their own dataset to
        restricted lost read access to it — grants have no write path, so the
        lockout was unrecoverable without manual SQL. Pins both the detail
        path (can_access_dataset) and the list path (filter_visible), because
        the two deny independently.
        """
        from tests.conftest import _create_test_user

        _owner_headers, owner_id = await _create_test_user(
            client, admin_auth_header, "editor"
        )
        owner_headers = _owner_headers
        restricted = await _create_dataset(
            test_db_session,
            created_by=uuid.UUID(owner_id),
            visibility="restricted",
            name="Owner Restricted DS",
        )

        # Detail path: the owner reads their own restricted dataset...
        detail = await client.get(f"/datasets/{restricted.id}", headers=owner_headers)
        assert detail.status_code == 200

        # ...while another authenticated non-grantee still cannot.
        as_other = await client.get(
            f"/datasets/{restricted.id}", headers=viewer_auth_header
        )
        assert as_other.status_code == 404

        # List path (GET /datasets/): visible to the owner, not to others.
        owner_list = await client.get("/datasets/", headers=owner_headers)
        assert owner_list.status_code == 200
        owner_ids = [d["id"] for d in owner_list.json()["datasets"]]
        assert str(restricted.id) in owner_ids

        other_list = await client.get("/datasets/", headers=viewer_auth_header)
        assert other_list.status_code == 200
        other_ids = [d["id"] for d in other_list.json()["datasets"]]
        assert str(restricted.id) not in other_ids

        # List path (search): same rule on the search surface.
        owner_search = await client.get("/search/datasets/", headers=owner_headers)
        assert owner_search.status_code == 200
        search_ids = [f["id"] for f in owner_search.json()["features"]]
        assert str(restricted.id) in search_ids

        other_search = await client.get("/search/datasets/", headers=viewer_auth_header)
        assert other_search.status_code == 200
        other_search_ids = [f["id"] for f in other_search.json()["features"]]
        assert str(restricted.id) not in other_search_ids

        # Mirrored gate (codex review on the #929 PR): the maps bulk access
        # check replicates can_access_dataset's policy and must apply the
        # same creator exemption, or the owner cannot add their restricted
        # dataset to a map.
        from sqlalchemy import select

        from app.modules.auth.models import User
        from app.modules.catalog.maps.service import bulk_check_dataset_access

        owner_user = (
            await test_db_session.execute(
                select(User).where(User.id == uuid.UUID(owner_id))
            )
        ).scalar_one()
        accessible = await bulk_check_dataset_access(
            test_db_session, [restricted.id], owner_user, {"editor"}
        )
        assert restricted.id in accessible

    async def test_overlay_denying_creator_wins_on_bulk_check(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#929 review): bulk_check_dataset_access routes through the
        permission extension instead of an inline policy mirror, so an
        overlay that deliberately denies the creator is enforced on the
        map-attach paths — the case a hard-coded owner short-circuit got
        wrong."""
        from sqlalchemy import false, select

        import app.platform.extensions as extensions
        from app.modules.auth.models import User
        from app.modules.catalog.maps.service import bulk_check_dataset_access
        from tests.conftest import _create_test_user

        _owner_headers, owner_id = await _create_test_user(
            client, admin_auth_header, "editor"
        )
        restricted = await _create_dataset(
            test_db_session,
            created_by=uuid.UUID(owner_id),
            visibility="restricted",
            name="Overlay Denied Restricted DS",
        )
        owner_user = (
            await test_db_session.execute(
                select(User).where(User.id == uuid.UUID(owner_id))
            )
        ).scalar_one()

        class _DenyEveryone:
            def filter_visible(
                self, stmt, user, user_roles, record_cls, grant_cls=None
            ):
                return stmt.where(false())

        monkeypatch.setitem(extensions._extensions, "permission", _DenyEveryone())
        accessible = await bulk_check_dataset_access(
            test_db_session, [restricted.id], owner_user, {"editor"}
        )
        assert accessible == set()

    async def test_anon_get_attributes_public(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Anonymous GET /datasets/{id}/attributes/ returns non-401 for public dataset."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Anon Attrs DS",
        )
        resp = await client.get(f"/datasets/{ds.id}/attributes/")
        assert resp.status_code != 401

    async def test_anon_get_validate_public(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Anonymous GET /datasets/{id}/validate/ returns non-401 for public dataset."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Anon Validate DS",
        )
        resp = await client.get(f"/datasets/{ds.id}/validate/")
        assert resp.status_code != 401

    async def test_anon_get_versions_public(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Anonymous GET /datasets/{id}/versions returns non-401 for public dataset."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Anon Versions DS",
        )
        resp = await client.get(f"/datasets/{ds.id}/versions/")
        assert resp.status_code != 401

    async def test_anon_get_history_public(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Anonymous GET /datasets/{id}/history returns non-401 for public dataset."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Anon History DS",
        )
        resp = await client.get(f"/datasets/{ds.id}/history")
        assert resp.status_code != 401

    async def test_anon_collections_list(self, client: AsyncClient):
        """Anonymous GET /catalog/collections/ returns 200."""
        resp = await client.get("/catalog/collections/")
        assert resp.status_code == 200

    async def test_anon_protected_routes_return_401(self, client: AsyncClient):
        """Anonymous access to protected endpoints returns 401."""
        # Settings (admin-only)
        resp = await client.get("/settings/all/")
        assert resp.status_code == 401

        # Import (editor-only)
        resp = await client.post("/ingest/upload")
        assert resp.status_code in (
            401,
            422,
        )  # 422 if missing body, but auth checked first

        # Admin users
        resp = await client.get("/admin/users/")
        assert resp.status_code == 401


class TestDatasetSubRouterRouting:
    """Verify all dataset sub-router paths resolve (not 404 from route registration)."""

    async def test_dcat_catalog_not_captured_by_dataset_id(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /datasets/dcat/ resolves to DCAT catalog, not /{dataset_id} with 'dcat'."""
        resp = await client.get("/datasets/dcat/", headers=admin_auth_header)
        # Should be 200 (DCAT catalog), not 422 (invalid UUID) or 404
        assert resp.status_code == 200

    async def test_subrouter_paths_resolve(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Sub-router paths return valid responses (not 404 from missing registration)."""
        fake_id = str(uuid.uuid4())
        routes = [
            ("GET", f"/datasets/{fake_id}/versions/"),
            ("GET", f"/datasets/{fake_id}/rows/"),
            ("GET", f"/datasets/{fake_id}/validate/"),
            ("GET", f"/datasets/{fake_id}/related/"),
            ("GET", f"/datasets/{fake_id}/maps/"),
            ("GET", f"/datasets/{fake_id}/vrt-sources/"),
            ("GET", f"/datasets/{fake_id}/attributes/"),
        ]
        for method, path in routes:
            resp = await client.request(method, path, headers=admin_auth_header)
            # 404 with "not found" detail = dataset doesn't exist (route resolved correctly)
            # 404 without detail = route not registered (would be a regression)
            assert resp.status_code in (200, 404), (
                f"{method} {path} returned {resp.status_code}"
            )
            if resp.status_code == 404:
                assert "not found" in resp.json().get("detail", "").lower(), (
                    f"{method} {path}: 404 but no 'not found' detail — route may not be registered"
                )


class TestBulkDeleteDatasets:
    """Tests for POST /datasets/bulk-delete."""

    async def test_bulk_delete_requires_auth(self, client: AsyncClient):
        resp = await client.post("/datasets/bulk-delete/", json={"datasets": []})
        assert resp.status_code == 401

    async def test_bulk_delete_empty_list_rejected(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Empty datasets list fails validation (min_length=1)."""
        resp = await client.post(
            "/datasets/bulk-delete/",
            json={"datasets": []},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_bulk_delete_success(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Successfully delete multiple datasets in one request."""
        user_id = await _get_user_id(test_db_session, "admin")
        ds1 = await _create_dataset(
            test_db_session, created_by=user_id, name="Bulk Del 1"
        )
        ds2 = await _create_dataset(
            test_db_session, created_by=user_id, name="Bulk Del 2"
        )

        resp = await client.post(
            "/datasets/bulk-delete/",
            json={
                "datasets": [
                    {"dataset_id": str(ds1.id), "confirm_title": "Bulk Del 1"},
                    {"dataset_id": str(ds2.id), "confirm_title": "Bulk Del 2"},
                ]
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] == 2
        assert data["errors"] == 0
        assert len(data["results"]) == 2
        assert all(r["status"] == "deleted" for r in data["results"])

        # Verify datasets are gone
        resp = await client.get(f"/datasets/{ds1.id}", headers=admin_auth_header)
        assert resp.status_code == 404

    async def test_bulk_delete_mixed_success_and_errors(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Some items succeed, some fail — returns partial results."""
        user_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=user_id, name="Bulk Mix")

        resp = await client.post(
            "/datasets/bulk-delete/",
            json={
                "datasets": [
                    {"dataset_id": str(ds.id), "confirm_title": "Bulk Mix"},
                    {"dataset_id": str(uuid.uuid4()), "confirm_title": "Nonexistent"},
                ]
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] == 1
        assert data["errors"] == 1

        statuses = {r["dataset_id"]: r["status"] for r in data["results"]}
        assert statuses[str(ds.id)] == "deleted"

    async def test_bulk_delete_wrong_title(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Wrong confirm_title returns error for that item."""
        user_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=user_id, name="Title Check"
        )

        resp = await client.post(
            "/datasets/bulk-delete/",
            json={
                "datasets": [
                    {"dataset_id": str(ds.id), "confirm_title": "Wrong Title"},
                ]
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] == 0
        assert data["errors"] == 1
        assert "does not match" in data["results"][0]["detail"]
