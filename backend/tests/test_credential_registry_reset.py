"""Every test starts with an empty credential-secret registry."""

import pytest

from app.core.service_tokens import (
    register_credential_secret,
    registered_credential_secrets,
)

pytestmark = pytest.mark.xdist_group("credential_registry_reset")


def test_a_sync_test_registers_a_secret_and_leaves_it():
    """A sync test registers a secret and does not clear it."""
    register_credential_secret("X-Api-Key: registry-reset-probe-value")
    assert registered_credential_secrets()


def test_a_later_sync_test_starts_with_an_empty_registry():
    """A sync test starts with no secret registered."""
    assert registered_credential_secrets() == frozenset()


@pytest.mark.anyio
async def test_a_later_async_test_starts_with_an_empty_registry():
    """An async test starts with no secret registered."""
    assert registered_credential_secrets() == frozenset()
