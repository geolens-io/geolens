"""Shared fixtures for the live-provider evals."""

import pytest

from app.platform.extensions.defaults import (
    DefaultAnthropicProvider,
    DefaultOpenAICompatibleProvider,
)


@pytest.fixture(autouse=True)
async def _fresh_provider_clients():
    """Give each eval its own provider SDK clients, closed on its own loop.

    A cached client keeps its pooled connections on the event loop that
    opened them, and each test runs on a new loop. httpx2 raises "Event loop
    is closed" when a later test reuses or garbage-collects such a connection.
    """
    yield
    clients = list(DefaultOpenAICompatibleProvider._clients.values())
    if DefaultAnthropicProvider._client is not None:
        clients.append(DefaultAnthropicProvider._client)
    DefaultAnthropicProvider._client = None
    DefaultOpenAICompatibleProvider._clients.clear()
    for client in clients:
        await client.close()
