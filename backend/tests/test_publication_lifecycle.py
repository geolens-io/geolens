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
from sqlalchemy import select

from app.auth.models import User
from app.datasets.models import Dataset, Record
from app.datasets.router import ALLOWED_TRANSITIONS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_admin_id(session) -> uuid.UUID:
    result = await session.execute(select(User).where(User.username == "admin"))
    return result.scalar_one().id


async def _create_dataset_with_status(
    session, *, admin_id: uuid.UUID, record_status: str = "draft"
) -> Dataset:
    """Create a minimal Record + Dataset with a given record_status."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=f"Lifecycle Test {uuid.uuid4().hex[:6]}",
        visibility="private",
        record_status=record_status,
        created_by=admin_id,
        theme_category=[],
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        source_format="geojson",
    )
    session.add(dataset)
    await session.flush()
    return dataset


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
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_dataset_with_status(
            test_db_session, admin_id=admin_id, record_status=from_status
        )
        await test_db_session.commit()

        resp = await client.patch(
            f"/datasets/{dataset.id}/status",
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
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_dataset_with_status(
            test_db_session, admin_id=admin_id, record_status=from_status
        )
        await test_db_session.commit()

        resp = await client.patch(
            f"/datasets/{dataset.id}/status",
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
        """A status value not in the allowed set should return 422."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_dataset_with_status(
            test_db_session, admin_id=admin_id, record_status="draft"
        )
        await test_db_session.commit()

        resp = await client.patch(
            f"/datasets/{dataset.id}/status",
            json={"status": "archived"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Dataset not found test
# ---------------------------------------------------------------------------


class TestDatasetNotFound:
    async def test_nonexistent_dataset_returns_404(
        self, client, admin_auth_header
    ):
        fake_id = uuid.uuid4()
        resp = await client.patch(
            f"/datasets/{fake_id}/status",
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
