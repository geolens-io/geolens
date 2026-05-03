"""Tests for WorkflowExtension Protocol, default behavior, and overlay dispatch."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
    assert await extension.allowed_transitions(_context("draft", "ready")) == {
        "ready"
    }
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
    assert await extension.allowed_transitions(
        _context("review", "published", mode="metadata_patch")
    ) == set()
    assert await extension.allowed_transitions(
        _context("draft", "review", mode="metadata_patch")
    ) == set()


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
