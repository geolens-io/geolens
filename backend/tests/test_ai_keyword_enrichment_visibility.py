"""AI keyword suggestions enrich the prompt only from records the caller may read.

The suggestion prompt adds the catalog's keyword vocabulary and the keywords of
the nearest records by embedding. Both reads cover other records than the one
the caller asked about, so each must apply the caller's catalog visibility, not
only the tenant boundary.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.processing.ai.metadata_schemas import (
    KeywordSuggestion,
    KeywordSuggestionsResponse,
)
from app.processing.embeddings.models import RecordEmbedding

from tests.factories import create_dataset, create_user

_DIMS = 1536
_VOCABULARY = "Existing catalog vocabulary"
_NEIGHBORS = "Keywords from similar datasets"


def _vec(*head: float) -> list[float]:
    return (list(head) + [0.0] * _DIMS)[:_DIMS]


class _CapturingProvider:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def resolve_runtime_config(self, _db):
        return {}

    async def structured_complete(self, *, user_message, **_kw):
        self.prompts.append(user_message)
        response = KeywordSuggestionsResponse(
            keywords=[KeywordSuggestion(keyword="parks", keyword_type="theme")]
        )
        return response, 0, 0


async def _embed(session, record_id: uuid.UUID, vector: list[float], model: str):
    session.add(
        RecordEmbedding(
            record_id=record_id,
            embedding=vector,
            model_name=model,
            content_hash=uuid.uuid4().hex,
        )
    )
    await session.commit()


async def _keyword_prompt(client: AsyncClient, headers: dict, dataset_id) -> str:
    provider = _CapturingProvider()
    with (
        patch("app.processing.ai.router._check_ai_available", new=AsyncMock()),
        patch(
            "app.processing.ai.metadata_service.get_ai_provider",
            return_value=provider,
        ),
    ):
        resp = await client.post(
            "/ai/metadata/keywords/",
            json={"dataset_id": str(dataset_id)},
            headers=headers,
        )
    assert resp.status_code == 200, resp.text
    (prompt,) = provider.prompts
    return prompt


def _section(prompt: str, label: str) -> str:
    return next(
        (block for block in prompt.split("\n\n") if block.startswith(label)), ""
    )


@pytest.mark.anyio
async def test_keyword_prompt_omits_keywords_of_records_the_caller_cannot_read(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    reader_headers, _ = await create_user(client, admin_auth_header, "editor")
    owner = uuid.UUID(owner_id)
    tag = uuid.uuid4().hex
    private_keyword = f"private-{tag}"
    public_keyword = f"public-{tag}"
    # A model name no other test writes keeps every other row out of the
    # neighbor search, so the neighbors are exactly the records seeded here.
    model = f"keyword-visibility-{tag[:8]}"

    target = await create_dataset(
        test_db_session, created_by=owner, name="Shared parks", visibility="public"
    )
    private = await create_dataset(
        test_db_session,
        created_by=owner,
        name="Owner notes",
        visibility="private",
        keywords=[private_keyword],
    )
    public = await create_dataset(
        test_db_session,
        created_by=owner,
        name="Shared trails",
        visibility="public",
        keywords=[public_keyword],
    )
    await _embed(test_db_session, target.record_id, _vec(1.0, 0.0), model)
    await _embed(test_db_session, private.record_id, _vec(0.9, 0.1), model)
    await _embed(test_db_session, public.record_id, _vec(0.8, 0.2), model)

    reader_prompt = await _keyword_prompt(client, reader_headers, target.id)
    owner_prompt = await _keyword_prompt(client, owner_headers, target.id)

    assert public_keyword in _section(reader_prompt, _VOCABULARY)
    assert public_keyword in _section(reader_prompt, _NEIGHBORS)
    assert private_keyword not in reader_prompt

    assert private_keyword in _section(owner_prompt, _VOCABULARY)
    assert private_keyword in _section(owner_prompt, _NEIGHBORS)


@pytest.mark.anyio
async def test_hidden_nearer_records_do_not_crowd_out_a_readable_neighbor(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    reader_headers, _ = await create_user(client, admin_auth_header, "editor")
    owner = uuid.UUID(owner_id)
    tag = uuid.uuid4().hex
    public_keyword = f"public-{tag}"
    model = f"keyword-crowding-{tag[:8]}"

    target = await create_dataset(
        test_db_session, created_by=owner, name="Shared parks", visibility="public"
    )
    await _embed(test_db_session, target.record_id, _vec(1.0, 0.0), model)
    for index in range(6):
        hidden = await create_dataset(
            test_db_session,
            created_by=owner,
            name=f"Owner notes {index}",
            visibility="private",
            keywords=[f"private-{index}-{tag}"],
        )
        await _embed(test_db_session, hidden.record_id, _vec(0.95, 0.05), model)
    public = await create_dataset(
        test_db_session,
        created_by=owner,
        name="Shared trails",
        visibility="public",
        keywords=[public_keyword],
    )
    await _embed(test_db_session, public.record_id, _vec(0.8, 0.2), model)

    reader_prompt = await _keyword_prompt(client, reader_headers, target.id)

    assert public_keyword in _section(reader_prompt, _NEIGHBORS)
    assert f"private-0-{tag}" not in reader_prompt
