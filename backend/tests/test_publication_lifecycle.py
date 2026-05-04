"""Tests for publication status lifecycle transitions.

Verifies:
  - Valid transitions: draft->ready, ready->internal, internal->published,
    published->internal, internal->ready, ready->draft
  - Invalid transitions return 422
  - Invalid status values return 422 (pydantic validation)

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

import pytest

from app.modules.catalog.datasets.api.router_data import ALLOWED_TRANSITIONS

from tests.factories import create_dataset, get_user_id


# ---------------------------------------------------------------------------
# Valid transition tests
# ---------------------------------------------------------------------------


class TestValidTransitions:
    """All allowed transitions should succeed with 200."""

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            ("draft", "ready"),
            ("ready", "internal"),
            ("internal", "published"),
            ("published", "internal"),
            ("internal", "ready"),
            ("ready", "draft"),
        ],
    )
    async def test_valid_transition(
        self, client, test_db_session, admin_auth_header, from_status, to_status
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="private",
            record_status=from_status,
        )
        await test_db_session.commit()

        resp = await client.patch(
            f"/datasets/{dataset.id}/status/",
            json={"status": to_status},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["record_status"] == to_status
        assert data["id"] == str(dataset.id)


# ---------------------------------------------------------------------------
# Invalid transition tests
# ---------------------------------------------------------------------------


class TestInvalidTransitions:
    """Skipping steps or going backward beyond one step should return 422."""

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            ("draft", "published"),
            ("draft", "internal"),
            ("published", "draft"),
            ("published", "ready"),
        ],
    )
    async def test_invalid_transition(
        self, client, test_db_session, admin_auth_header, from_status, to_status
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="private",
            record_status=from_status,
        )
        await test_db_session.commit()

        resp = await client.patch(
            f"/datasets/{dataset.id}/status/",
            json={"status": to_status},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422, resp.text
        assert "Cannot transition" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Invalid status value test
# ---------------------------------------------------------------------------


class TestInvalidStatusValue:
    async def test_invalid_status_value_rejected(
        self, client, test_db_session, admin_auth_header
    ):
        """Unknown statuses are rejected at the workflow boundary."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="private",
            record_status="draft",
        )
        await test_db_session.commit()

        resp = await client.patch(
            f"/datasets/{dataset.id}/status/",
            json={"status": "archived"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "Cannot transition" in resp.json()["detail"]

    async def test_blank_status_value_rejected(
        self, client, test_db_session, admin_auth_header
    ):
        """Blank status values fail syntactic request validation."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="private",
            record_status="draft",
        )
        await test_db_session.commit()

        resp = await client.patch(
            f"/datasets/{dataset.id}/status/",
            json={"status": "   "},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Target status walking tests
# ---------------------------------------------------------------------------


class TestTargetStatus:
    async def test_target_status_walks_forward_chain(
        self, client, test_db_session, admin_auth_header
    ):
        """draft -> published through target-status completes server-side."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="private",
            record_status="draft",
        )
        await test_db_session.commit()

        resp = await client.patch(
            f"/datasets/{dataset.id}/target-status/",
            json={"status": "published"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["record_status"] == "published"

    async def test_target_status_no_change_returns_current(
        self, client, test_db_session, admin_auth_header
    ):
        """No-change target-status preserves existing response behavior."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="private",
            record_status="ready",
        )
        await test_db_session.commit()

        resp = await client.patch(
            f"/datasets/{dataset.id}/target-status/",
            json={"status": "ready"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"id": str(dataset.id), "record_status": "ready"}


# ---------------------------------------------------------------------------
# Dataset not found test
# ---------------------------------------------------------------------------


class TestDatasetNotFound:
    async def test_nonexistent_dataset_returns_404(self, client, admin_auth_header):
        fake_id = uuid.uuid4()
        resp = await client.patch(
            f"/datasets/{fake_id}/status/",
            json={"status": "ready"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# ALLOWED_TRANSITIONS structure test
# ---------------------------------------------------------------------------


class TestAllowedTransitionsMap:
    def test_transitions_are_complete(self):
        """Verify the transition map covers all four publication states."""
        assert set(ALLOWED_TRANSITIONS.keys()) == {
            "draft",
            "ready",
            "internal",
            "published",
        }

    def test_no_self_transitions(self):
        """No state should allow transitioning to itself."""
        for state, targets in ALLOWED_TRANSITIONS.items():
            assert state not in targets
