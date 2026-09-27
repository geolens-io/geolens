"""What the chat add_layer tool reports about the dataset it names."""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from tests.factories import (
    create_dataset,
    create_map_via_api,
    create_user,
    get_user_id,
)


async def test_add_layer_names_only_datasets_the_caller_can_read(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """A dataset the caller can't read gets the same add_layer result as one
    that doesn't exist. A dataset the caller can read gets its title."""
    admin_id = await get_user_id(test_db_session, "admin")
    editor_header, editor_id = await create_user(client, admin_auth_header, "editor")
    marker = uuid.uuid4().hex[:8]
    unreadable = await create_dataset(
        test_db_session,
        created_by=admin_id,
        visibility="private",
        name=f"Unreadable {marker}",
    )
    readable = await create_dataset(
        test_db_session,
        created_by=uuid.UUID(editor_id),
        visibility="private",
        name=f"Readable {marker}",
    )
    missing_id = str(uuid.uuid4())
    map_id = (await create_map_via_api(client, editor_header))["id"]

    tool_results: dict[str, dict] = {}

    class _EchoingProvider:
        """Runs add_layer for each id and repeats every tool result verbatim."""

        async def complete(self, *, tool_executor, **_kwargs):
            for dataset_id in (str(unreadable.id), missing_id, str(readable.id)):
                tool_results[dataset_id] = await tool_executor(
                    "add_layer", {"dataset_id": dataset_id}
                )
            return SimpleNamespace(
                text=json.dumps(list(tool_results.values())),
                actions=[],
                input_tokens=0,
                output_tokens=0,
            )

    with (
        patch("app.processing.ai.router._check_ai_available", new_callable=AsyncMock),
        patch(
            "app.processing.ai.chat_service.resolve_provider",
            new_callable=AsyncMock,
            return_value=("anthropic", "test-model", {}),
        ),
        patch(
            "app.processing.ai.chat_service.get_ai_provider",
            return_value=_EchoingProvider(),
        ),
    ):
        resp = await client.post(
            "/ai/chat/",
            json={"message": "Add these layers", "map_id": map_id, "layers": []},
            headers=editor_header,
        )

    assert resp.status_code == 200, resp.text

    def without_id(result: dict) -> dict:
        return {k: v for k, v in result.items() if k != "dataset_id"}

    assert without_id(tool_results[str(unreadable.id)]) == without_id(
        tool_results[missing_id]
    )
    assert f"Unreadable {marker}" not in resp.text
    assert tool_results[str(readable.id)]["dataset_name"] == f"Readable {marker}"
    assert f"Readable {marker}" in resp.text
