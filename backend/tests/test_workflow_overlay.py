"""Composed integration tests for the enterprise publication WorkflowExtension.

These exercise the private overlay's ``EnterpriseWorkflowExtension`` SoD /
clearance / reviewer-role gating through the REAL core consumption path — the
real ``WorkflowTransitionContext`` protocol class over real seeded
``Dataset`` / ``Record`` / ``User`` rows, and the real
``update_publication_status`` route handler that raises 422 when a transition is
denied. The overlay's own suite can only assert this logic against
``SimpleNamespace`` stubs, so context-shape drift (``dataset.record.created_by``,
``actor.roles``) would go undetected there; this composed file catches it. It
lives in CORE because only core ships the ORM models, the route, and the DB
fixtures. See enterprise-overlay-audit-20260715 §6.

Skip-not-fail: the overlay is imported via ``pytest.importorskip`` inside the
``enterprise_workflow`` fixture, exactly like conftest's
``saml_overlay_registered``. An OSS checkout without ``geolens_enterprise``
SKIPS these tests; the overlay's cross-repo CI job forces them to run.

The workflow is inert unless ``GEOLENS_WORKFLOW_MODE=on``. Each test sets the
mode + policy via ``monkeypatch`` BEFORE constructing the extension, because
``load_policy()`` reads the environment at construction time.
"""

from __future__ import annotations

import json
import uuid

from fastapi import HTTPException
import pytest
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from types import SimpleNamespace

from app.modules.auth.models import Role, User, UserRole
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.extensions.defaults import DefaultWorkflowExtension
from app.platform.extensions.protocols import WorkflowTransitionContext


@pytest.fixture
def enterprise_workflow():
    """Import the overlay's workflow package or SKIP (never fail)."""
    return pytest.importorskip(
        "geolens_enterprise.workflow",
        reason="geolens_enterprise package is not installed",
    )


@pytest.fixture
def workflow_slot():
    """Save/restore ``_extensions['workflow']`` so a test can install the overlay
    into the live registry (the shape the /status/ route reads) without leaking
    it to other tests. Mirrors conftest's ``saml_overlay_registered`` teardown."""
    import app.platform.extensions as ext_mod

    had = "workflow" in ext_mod._extensions
    saved = ext_mod._extensions.get("workflow")
    yield ext_mod
    if had:
        ext_mod._extensions["workflow"] = saved
    else:
        ext_mod._extensions.pop("workflow", None)


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _policy_json(reviewer_role: str) -> str:
    """A minimal three-axis approval policy: only ``reviewer_role`` may approve,
    the edge is separation-of-duties AND clearance gated."""
    return json.dumps(
        {
            "states": ["draft", "pending_review", "approved", "published"],
            "transitions": {
                "draft": ["pending_review"],
                "pending_review": ["approved", "draft"],
                "approved": ["published", "pending_review"],
                "published": ["approved"],
            },
            "edge_roles": {"pending_review->approved": [reviewer_role]},
            "sod_edges": ["pending_review->approved"],
            "clearance_edges": ["pending_review->approved"],
            "role_clearance": {reviewer_role: "confidential"},
        }
    )


async def _make_role(session, name: str) -> Role:
    role = Role(name=name, description="wf test role")
    session.add(role)
    await session.flush()
    return role


async def _get_or_create_admin_role(session) -> Role:
    result = await session.execute(select(Role).where(Role.name == "admin"))
    role = result.scalar_one_or_none()
    if role is None:
        role = await _make_role(session, "admin")
    return role


async def _make_user(session, role_ids: list[uuid.UUID]) -> User:
    user = User(username=_unique("wf_user"), status="active", is_active=True)
    session.add(user)
    await session.flush()
    for role_id in role_ids:
        session.add(UserRole(user_id=user.id, role_id=role_id))
    await session.flush()
    # Re-fetch so the selectin `roles` relationship is populated for async access.
    result = await session.execute(select(User).where(User.id == user.id))
    return result.scalar_one()


async def _make_dataset(
    session, *, created_by: uuid.UUID, sensitivity: str, record_status: str
) -> Dataset:
    record = Record(
        title=_unique("record"),
        visibility="private",
        record_status=record_status,
        record_type="vector_dataset",
        sensitivity_classification=sensitivity,
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(record_id=record.id, table_name=_unique("tbl"))
    session.add(dataset)
    await session.flush()
    # joinedload so the overlay's `dataset.record.*` reads work in async context.
    result = await session.execute(
        select(Dataset)
        .options(joinedload(Dataset.record))
        .where(Dataset.id == dataset.id)
    )
    return result.unique().scalar_one()


def _context(dataset, actor, from_status, to_status, *, mode="status"):
    return WorkflowTransitionContext(
        session=None,
        dataset=dataset,
        actor=actor,
        from_status=from_status,
        to_status=to_status,
        mode=mode,
    )


# ---------------------------------------------------------------------------
# Gating matrix — real WorkflowTransitionContext over real models
# ---------------------------------------------------------------------------


async def test_allowed_transitions_allows_cleared_non_author_reviewer(
    enterprise_workflow, test_db_session, clean_tables, monkeypatch
):
    """A reviewer who is NOT the author and holds sufficient clearance may
    approve — 'approved' is a permitted transition from 'pending_review'."""
    session = test_db_session
    reviewer_role = _unique("reviewer")
    role = await _make_role(session, reviewer_role)
    author = await _make_user(session, [])
    reviewer = await _make_user(session, [role.id])
    dataset = await _make_dataset(
        session,
        created_by=author.id,
        sensitivity="confidential",
        record_status="pending_review",
    )
    await session.commit()

    monkeypatch.setenv("GEOLENS_WORKFLOW_MODE", "on")
    monkeypatch.setenv("GEOLENS_WORKFLOW_POLICY", _policy_json(reviewer_role))
    ext = enterprise_workflow.EnterpriseWorkflowExtension()

    allowed = await ext.allowed_transitions(
        _context(dataset, reviewer, "pending_review", "approved")
    )
    assert "approved" in allowed


async def test_allowed_transitions_denies_self_approval_sod(
    enterprise_workflow, test_db_session, clean_tables, monkeypatch
):
    """Separation of duties: the dataset author cannot approve their own
    dataset, even holding the reviewer role and sufficient clearance."""
    session = test_db_session
    reviewer_role = _unique("reviewer")
    role = await _make_role(session, reviewer_role)
    # Author also holds the reviewer role, so the ONLY failing axis is SoD.
    author = await _make_user(session, [role.id])
    dataset = await _make_dataset(
        session,
        created_by=author.id,
        sensitivity="confidential",
        record_status="pending_review",
    )
    await session.commit()

    monkeypatch.setenv("GEOLENS_WORKFLOW_MODE", "on")
    monkeypatch.setenv("GEOLENS_WORKFLOW_POLICY", _policy_json(reviewer_role))
    ext = enterprise_workflow.EnterpriseWorkflowExtension()

    allowed = await ext.allowed_transitions(
        _context(dataset, author, "pending_review", "approved")
    )
    assert "approved" not in allowed


async def test_allowed_transitions_denies_insufficient_clearance(
    enterprise_workflow, test_db_session, clean_tables, monkeypatch
):
    """A reviewer whose clearance is below the dataset's sensitivity cannot
    approve it (they could not even see it under the ABAC gate)."""
    session = test_db_session
    reviewer_role = _unique("reviewer")
    role = await _make_role(session, reviewer_role)
    author = await _make_user(session, [])
    reviewer = await _make_user(session, [role.id])  # clearance = confidential (2)
    dataset = await _make_dataset(
        session,
        created_by=author.id,
        sensitivity="restricted",  # ordinal 3 > reviewer's 2
        record_status="pending_review",
    )
    await session.commit()

    monkeypatch.setenv("GEOLENS_WORKFLOW_MODE", "on")
    monkeypatch.setenv("GEOLENS_WORKFLOW_POLICY", _policy_json(reviewer_role))
    ext = enterprise_workflow.EnterpriseWorkflowExtension()

    allowed = await ext.allowed_transitions(
        _context(dataset, reviewer, "pending_review", "approved")
    )
    assert "approved" not in allowed


async def test_allowed_transitions_denies_missing_reviewer_role(
    enterprise_workflow, test_db_session, clean_tables, monkeypatch
):
    """An actor lacking the edge's required role cannot traverse it, even when
    SoD and clearance would otherwise pass."""
    session = test_db_session
    reviewer_role = _unique("reviewer")
    other_role = await _make_role(session, _unique("editor"))
    author = await _make_user(session, [])
    actor = await _make_user(session, [other_role.id])  # not the reviewer role
    dataset = await _make_dataset(
        session,
        created_by=author.id,
        sensitivity="public",
        record_status="pending_review",
    )
    await session.commit()

    monkeypatch.setenv("GEOLENS_WORKFLOW_MODE", "on")
    monkeypatch.setenv("GEOLENS_WORKFLOW_POLICY", _policy_json(reviewer_role))
    ext = enterprise_workflow.EnterpriseWorkflowExtension()

    allowed = await ext.allowed_transitions(
        _context(dataset, actor, "pending_review", "approved")
    )
    assert "approved" not in allowed


async def test_allowed_transitions_inert_when_mode_off(
    enterprise_workflow, test_db_session, clean_tables, monkeypatch
):
    """With mode unset the overlay delegates entirely to the community default —
    same status_order and the same allowed set for the same context."""
    session = test_db_session
    monkeypatch.delenv("GEOLENS_WORKFLOW_MODE", raising=False)
    author = await _make_user(session, [])
    dataset = await _make_dataset(
        session, created_by=author.id, sensitivity="internal", record_status="draft"
    )
    await session.commit()

    default = DefaultWorkflowExtension()
    ext = enterprise_workflow.EnterpriseWorkflowExtension()

    assert ext.status_order() == default.status_order()
    ctx = _context(dataset, author, "draft", "ready")
    assert await ext.allowed_transitions(ctx) == await default.allowed_transitions(ctx)
    assert "ready" in await ext.allowed_transitions(ctx)


# ---------------------------------------------------------------------------
# Real route handler — 422 on deny / 200 on allow / inert delegate
# ---------------------------------------------------------------------------


async def test_status_route_denies_sod_self_approval_422(
    enterprise_workflow, workflow_slot, test_db_session, clean_tables, monkeypatch
):
    """The real /status/ handler returns 422 when the overlay denies a
    self-approval (SoD), and the record status is left unchanged."""
    from app.modules.catalog.datasets.api.router_data import update_publication_status
    from app.modules.catalog.datasets.domain.schemas import StatusUpdate

    session = test_db_session
    reviewer_role = _unique("reviewer")
    role = await _make_role(session, reviewer_role)
    author = await _make_user(session, [role.id])
    dataset = await _make_dataset(
        session,
        created_by=author.id,
        sensitivity="confidential",
        record_status="pending_review",
    )
    await session.commit()

    monkeypatch.setenv("GEOLENS_WORKFLOW_MODE", "on")
    monkeypatch.setenv("GEOLENS_WORKFLOW_POLICY", _policy_json(reviewer_role))
    workflow_slot._extensions["workflow"] = (
        enterprise_workflow.EnterpriseWorkflowExtension()
    )

    with pytest.raises(HTTPException) as exc:
        await update_publication_status(
            dataset.id,
            StatusUpdate(status="approved"),
            SimpleNamespace(),
            author,
            session,
        )
    assert exc.value.status_code == 422
    assert "Cannot transition" in exc.value.detail

    refreshed = await session.execute(
        select(Record.record_status).where(Record.id == dataset.record_id)
    )
    assert refreshed.scalar_one() == "pending_review"


async def test_status_route_allows_admin_transition_200(
    enterprise_workflow, workflow_slot, test_db_session, clean_tables, monkeypatch
):
    """The real /status/ handler commits an admin-bypassed transition (200) and
    persists the new status."""
    from app.modules.catalog.datasets.api.router_data import update_publication_status
    from app.modules.catalog.datasets.domain.schemas import StatusUpdate

    session = test_db_session
    admin_role = await _get_or_create_admin_role(session)
    admin = await _make_user(session, [admin_role.id])
    reviewer_role = _unique("reviewer")
    dataset = await _make_dataset(
        session,
        created_by=admin.id,
        sensitivity="confidential",
        record_status="pending_review",
    )
    await session.commit()

    monkeypatch.setenv("GEOLENS_WORKFLOW_MODE", "on")
    monkeypatch.setenv("GEOLENS_WORKFLOW_POLICY", _policy_json(reviewer_role))
    workflow_slot._extensions["workflow"] = (
        enterprise_workflow.EnterpriseWorkflowExtension()
    )

    response = await update_publication_status(
        dataset.id,
        StatusUpdate(status="approved"),
        SimpleNamespace(),
        admin,
        session,
    )
    assert response.record_status == "approved"

    refreshed = await session.execute(
        select(Record.record_status).where(Record.id == dataset.record_id)
    )
    assert refreshed.scalar_one() == "approved"


async def test_status_route_inert_delegates_when_mode_off(
    enterprise_workflow, workflow_slot, test_db_session, clean_tables, monkeypatch
):
    """With the overlay installed but mode unset, the /status/ handler follows
    the community lifecycle: draft->ready allowed (200), draft->published 422."""
    from app.modules.catalog.datasets.api.router_data import update_publication_status
    from app.modules.catalog.datasets.domain.schemas import StatusUpdate

    session = test_db_session
    monkeypatch.delenv("GEOLENS_WORKFLOW_MODE", raising=False)
    admin_role = await _get_or_create_admin_role(session)
    admin = await _make_user(session, [admin_role.id])
    dataset = await _make_dataset(
        session, created_by=admin.id, sensitivity="internal", record_status="draft"
    )
    await session.commit()

    workflow_slot._extensions["workflow"] = (
        enterprise_workflow.EnterpriseWorkflowExtension()
    )

    ok = await update_publication_status(
        dataset.id, StatusUpdate(status="ready"), SimpleNamespace(), admin, session
    )
    assert ok.record_status == "ready"

    # Reset to draft to exercise the disallowed one-shot jump from the same base.
    reset = await session.execute(select(Record).where(Record.id == dataset.record_id))
    reset.scalar_one().record_status = "draft"
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await update_publication_status(
            dataset.id,
            StatusUpdate(status="published"),
            SimpleNamespace(),
            admin,
            session,
        )
    assert exc.value.status_code == 422
