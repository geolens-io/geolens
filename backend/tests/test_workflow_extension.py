"""Tests for WorkflowExtension Protocol, default behavior, and overlay dispatch."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import uuid

from fastapi import HTTPException
import pytest


def _reset_registry():
    """Reset extension registry state between tests."""
    import app.platform.extensions as ext_mod

    ext_mod._extensions.clear()
    ext_mod._loaded = False


@pytest.fixture(autouse=True)
def _clean_registry():
    """Isolate tests from environment-discovered extension entry points."""
    _reset_registry()
    with patch("app.platform.extensions.entry_points", return_value=[]):
        yield
    _reset_registry()


def _context(from_status: str, to_status: str, *, mode: str = "status"):
    from app.platform.extensions.protocols import WorkflowTransitionContext

    return WorkflowTransitionContext(
        session=MagicMock(),
        dataset=SimpleNamespace(id="dataset-1"),
        actor=SimpleNamespace(id="user-1"),
        from_status=from_status,
        to_status=to_status,
        mode=mode,
    )


def _dataset(record_status: str):
    return SimpleNamespace(
        id=uuid.uuid4(),
        record=SimpleNamespace(record_status=record_status),
    )


class _FakeScalarResult:
    def __init__(self, dataset):
        self._dataset = dataset

    def unique(self):
        return self

    def scalar_one_or_none(self):
        return self._dataset


class _FakeDB:
    def __init__(self, dataset):
        self.dataset = dataset
        self.committed = False
        self.flushed = False
        self.refreshed = None

    async def execute(self, stmt):
        self.statement = stmt
        return _FakeScalarResult(self.dataset)

    async def commit(self):
        self.committed = True

    async def flush(self):
        self.flushed = True

    async def refresh(self, dataset):
        self.refreshed = dataset


def test_default_workflow_extension_registered():
    """Community mode returns the default and it satisfies the Protocol."""
    from app.platform.extensions import get_workflow_extension
    from app.platform.extensions.defaults import DefaultWorkflowExtension
    from app.platform.extensions.protocols import WorkflowExtension

    extension = get_workflow_extension()

    assert isinstance(extension, DefaultWorkflowExtension)
    assert isinstance(extension, WorkflowExtension)


@pytest.mark.asyncio
async def test_default_workflow_extension_status_order_and_transitions():
    """Default policy preserves the Community one-step lifecycle."""
    from app.platform.extensions.defaults import DefaultWorkflowExtension

    extension = DefaultWorkflowExtension()

    assert extension.status_order() == ("draft", "ready", "internal", "published")
    assert await extension.allowed_transitions(_context("draft", "ready")) == {"ready"}
    assert await extension.allowed_transitions(_context("ready", "draft")) == {
        "draft",
        "internal",
    }
    assert await extension.allowed_transitions(_context("internal", "published")) == {
        "ready",
        "published",
    }
    assert await extension.allowed_transitions(_context("published", "internal")) == {
        "internal"
    }


@pytest.mark.asyncio
async def test_default_workflow_extension_metadata_patch_allows_direct_status_changes():
    """Metadata PATCH mode keeps direct Community status-set behavior."""
    from app.platform.extensions.defaults import DefaultWorkflowExtension

    extension = DefaultWorkflowExtension()

    assert await extension.allowed_transitions(
        _context("draft", "published", mode="metadata_patch")
    ) == {"ready", "internal", "published"}
    assert (
        await extension.allowed_transitions(
            _context("review", "published", mode="metadata_patch")
        )
        == set()
    )
    assert (
        await extension.allowed_transitions(
            _context("draft", "review", mode="metadata_patch")
        )
        == set()
    )


@pytest.mark.asyncio
async def test_default_workflow_extension_on_transition_is_noop():
    """The default transition hook is awaitable and side-effect free."""
    from app.platform.extensions.defaults import DefaultWorkflowExtension

    extension = DefaultWorkflowExtension()

    assert await extension.on_transition(_context("draft", "ready")) is None


@pytest.mark.asyncio
async def test_overlay_workflow_extension_is_dispatched():
    """An entry-point overlay can replace the singleton workflow policy."""
    from app.platform.extensions import get_workflow_extension, load_extensions

    class TestWorkflowExtension:
        def status_order(self):
            return ("draft", "review", "published")

        async def allowed_transitions(self, context):
            assert context.mode == "status"
            return {"review"}

        async def on_transition(self, context):
            context.dataset.transition_seen = True

    def register(registry: dict) -> None:
        registry["workflow"] = TestWorkflowExtension()

    mock_ep = MagicMock()
    mock_ep.name = "geolens.workflow.test"
    mock_ep.load.return_value = register

    with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
        load_extensions()
        extension = get_workflow_extension()

    context = _context("draft", "review")

    assert extension.status_order() == ("draft", "review", "published")
    assert await extension.allowed_transitions(context) == {"review"}
    await extension.on_transition(context)
    assert context.dataset.transition_seen is True


@pytest.mark.asyncio
async def test_status_endpoint_uses_overlay_added_transition():
    """The /status/ endpoint can accept overlay-added transitions."""
    import app.platform.extensions as ext_mod
    from app.modules.catalog.datasets.api.router_data import update_publication_status
    from app.modules.catalog.datasets.domain.schemas import StatusUpdate
    from app.platform.extensions.defaults import DefaultWorkflowExtension

    class DirectPublishWorkflow(DefaultWorkflowExtension):
        async def allowed_transitions(self, context):
            allowed = await super().allowed_transitions(context)
            if context.from_status == "ready":
                allowed.add("published")
            return allowed

    dataset = _dataset("ready")
    db = _FakeDB(dataset)
    ext_mod._extensions["workflow"] = DirectPublishWorkflow()

    response = await update_publication_status(
        dataset.id,
        StatusUpdate(status="published"),
        SimpleNamespace(),
        SimpleNamespace(id="admin"),
        db,
    )

    assert response.record_status == "published"
    assert dataset.record.record_status == "published"
    assert db.committed is True
    assert db.refreshed is dataset


@pytest.mark.asyncio
async def test_target_status_endpoint_observes_each_intermediate_transition():
    """The /target-status/ endpoint calls on_transition for every step."""
    import app.platform.extensions as ext_mod
    from app.modules.catalog.datasets.api.router_data import set_target_status
    from app.modules.catalog.datasets.domain.schemas import StatusUpdate
    from app.platform.extensions.defaults import DefaultWorkflowExtension

    observed: list[tuple[str, str, str]] = []

    class ObservingWorkflow(DefaultWorkflowExtension):
        async def on_transition(self, context) -> None:
            observed.append((context.from_status, context.to_status, context.mode))

    dataset = _dataset("draft")
    db = _FakeDB(dataset)
    ext_mod._extensions["workflow"] = ObservingWorkflow()

    response = await set_target_status(
        dataset.id,
        StatusUpdate(status="published"),
        SimpleNamespace(),
        SimpleNamespace(id="admin"),
        db,
    )

    assert response.record_status == "published"
    assert observed == [
        ("draft", "ready", "target_status"),
        ("ready", "internal", "target_status"),
        ("internal", "published", "target_status"),
    ]
    assert db.committed is True


@pytest.mark.asyncio
async def test_target_status_endpoint_uses_overlay_block():
    """The /target-status/ endpoint returns 422 when an overlay blocks a step."""
    import app.platform.extensions as ext_mod
    from app.modules.catalog.datasets.api.router_data import set_target_status
    from app.modules.catalog.datasets.domain.schemas import StatusUpdate
    from app.platform.extensions.defaults import DefaultWorkflowExtension

    class BlockingWorkflow(DefaultWorkflowExtension):
        async def allowed_transitions(self, context):
            if context.from_status == "internal" and context.to_status == "published":
                return set()
            return await super().allowed_transitions(context)

    dataset = _dataset("draft")
    db = _FakeDB(dataset)
    ext_mod._extensions["workflow"] = BlockingWorkflow()

    with pytest.raises(HTTPException) as exc:
        await set_target_status(
            dataset.id,
            StatusUpdate(status="published"),
            SimpleNamespace(),
            SimpleNamespace(id="admin"),
            db,
        )

    assert exc.value.status_code == 422
    assert "Cannot transition from 'internal' to 'published'" in exc.value.detail
    assert db.committed is False


@pytest.mark.asyncio
async def test_metadata_patch_endpoint_uses_overlay_block():
    """PATCH /datasets/{id} cannot bypass WorkflowExtension for record_status."""
    import app.platform.extensions as ext_mod
    from app.modules.catalog.datasets.api.router import update_dataset_metadata
    from app.modules.catalog.datasets.domain.schemas import DatasetMeta
    from app.platform.extensions.defaults import DefaultWorkflowExtension

    class BlockingWorkflow(DefaultWorkflowExtension):
        async def allowed_transitions(self, context):
            assert context.mode == "metadata_patch"
            assert context.actor.id == "admin"
            return set()

    dataset = _dataset("draft")
    db = _FakeDB(dataset)
    ext_mod._extensions["workflow"] = BlockingWorkflow()

    with patch(
        "app.modules.catalog.datasets.domain.service_metadata.get_dataset",
        return_value=dataset,
    ):
        with pytest.raises(HTTPException) as exc:
            await update_dataset_metadata(
                dataset.id,
                DatasetMeta(record_status="published"),
                SimpleNamespace(client=None),
                SimpleNamespace(id="admin"),
                db,
            )

    assert exc.value.status_code == 422
    assert "Cannot transition from 'draft' to 'published'" in exc.value.detail
    assert dataset.record.record_status == "draft"
    assert db.committed is False


@pytest.mark.asyncio
async def test_status_endpoint_persists_extension_defined_custom_status():
    """Relaxed workflow validation allows an overlay-defined status through /status/."""
    import app.platform.extensions as ext_mod
    from app.modules.catalog.datasets.api.router_data import update_publication_status
    from app.modules.catalog.datasets.domain.schemas import StatusUpdate
    from app.platform.extensions.defaults import DefaultWorkflowExtension

    class ReviewWorkflow(DefaultWorkflowExtension):
        def status_order(self):
            return ("draft", "review", "published")

        async def allowed_transitions(self, context):
            if context.from_status == "draft":
                return {"review"}
            return set()

    dataset = _dataset("draft")
    db = _FakeDB(dataset)
    ext_mod._extensions["workflow"] = ReviewWorkflow()

    response = await update_publication_status(
        dataset.id,
        StatusUpdate(status="review"),
        SimpleNamespace(),
        SimpleNamespace(id="admin"),
        db,
    )

    assert response.record_status == "review"
    assert dataset.record.record_status == "review"
    assert db.committed is True
