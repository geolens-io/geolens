"""Integration tests for the related datasets endpoint.

Tests the GET /datasets/{id}/related/ endpoint which returns similar
datasets ranked by embedding cosine similarity.
"""

import uuid

from httpx import AsyncClient

from app.embeddings.models import RecordEmbedding

from tests.factories import create_dataset, get_user_id


def _make_embedding(base: list[float], dim: int = 1536) -> list[float]:
    """Create a 1536-dim vector from a short base, padding with zeros."""
    vec = base + [0.0] * (dim - len(base))
    return vec[:dim]


async def _add_embedding(session, record_id: uuid.UUID, vector: list[float]) -> None:
    """Insert a RecordEmbedding for a given record."""
    emb = RecordEmbedding(
        record_id=record_id,
        embedding=vector,
        model_name="test-model",
        content_hash=uuid.uuid4().hex[:64],
    )
    session.add(emb)
    await session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRelatedDatasets:
    async def test_related_returns_empty_when_no_embedding(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Dataset with no embedding returns empty related list."""
        user_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session, created_by=user_id, name="No Embedding DS"
        )

        resp = await client.get(
            f"/datasets/{ds.id}/related/", headers=admin_auth_header
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_related_returns_similar_datasets(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Datasets with similar embeddings are returned ranked by similarity."""
        user_id = await get_user_id(test_db_session, "admin")

        # Create 3 datasets with distinct embeddings
        ds_a = await create_dataset(
            test_db_session, created_by=user_id, name="DS Alpha"
        )
        ds_b = await create_dataset(
            test_db_session, created_by=user_id, name="DS Beta"
        )
        ds_c = await create_dataset(
            test_db_session, created_by=user_id, name="DS Gamma"
        )

        # A and B are similar (both point roughly in same direction)
        # C points in a very different direction
        vec_a = _make_embedding([1.0, 0.0, 0.0, 0.0])
        vec_b = _make_embedding([0.9, 0.1, 0.0, 0.0])
        vec_c = _make_embedding([0.0, 0.0, 1.0, 0.0])

        await _add_embedding(test_db_session, ds_a.record_id, vec_a)
        await _add_embedding(test_db_session, ds_b.record_id, vec_b)
        await _add_embedding(test_db_session, ds_c.record_id, vec_c)

        resp = await client.get(
            f"/datasets/{ds_a.id}/related/", headers=admin_auth_header
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) >= 1

        # DS Beta should be most similar to DS Alpha
        names = [item["name"] for item in data["items"]]
        assert "DS Beta" in names

        # First result should be the most similar
        if len(data["items"]) > 1:
            assert data["items"][0]["similarity"] >= data["items"][1]["similarity"]

    async def test_related_excludes_self(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """The dataset itself should not appear in its own related results."""
        user_id = await get_user_id(test_db_session, "admin")

        ds = await create_dataset(
            test_db_session, created_by=user_id, name="Self Exclude DS"
        )
        other = await create_dataset(
            test_db_session, created_by=user_id, name="Other DS"
        )

        vec = _make_embedding([1.0, 0.0, 0.0])
        await _add_embedding(test_db_session, ds.record_id, vec)
        await _add_embedding(test_db_session, other.record_id, vec)

        resp = await client.get(
            f"/datasets/{ds.id}/related/", headers=admin_auth_header
        )
        assert resp.status_code == 200
        data = resp.json()
        ids = [item["id"] for item in data["items"]]
        assert str(ds.id) not in ids

    async def test_related_respects_visibility(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """Private datasets owned by another user should not appear in related results."""
        user_id = await get_user_id(test_db_session, "admin")

        # Public dataset (the query target)
        ds_public = await create_dataset(
            test_db_session,
            created_by=user_id,
            name="Public Related DS",
            visibility="public",
        )
        # Private dataset owned by admin (viewer should not see)
        ds_private = await create_dataset(
            test_db_session,
            created_by=user_id,
            name="Private Related DS",
            visibility="private",
        )

        vec = _make_embedding([1.0, 0.0, 0.0])
        await _add_embedding(test_db_session, ds_public.record_id, vec)
        await _add_embedding(test_db_session, ds_private.record_id, vec)

        # Viewer requests related for public dataset -- should NOT see private
        resp = await client.get(
            f"/datasets/{ds_public.id}/related/", headers=viewer_auth_header
        )
        assert resp.status_code == 200
        data = resp.json()
        ids = [item["id"] for item in data["items"]]
        assert str(ds_private.id) not in ids
