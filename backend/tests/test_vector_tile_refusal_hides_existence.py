"""A vector tile refused to a caller who cannot see the dataset reads as an unknown table."""

import time
import uuid

import pytest
from httpx import AsyncClient

from app.core.tile_scope import tile_signature_scope
from app.processing.tiles.signing import generate_tile_signature
from app.core.config import settings
from tests.factories import get_user_id
from tests.test_vector_tile_identity_2543 import (  # noqa: F401
    make_tiles,
    mint_key,
    people,
)

pytestmark = pytest.mark.usefixtures("_init_tile_pool_for_tests")

_ROUTES = ("data", "clusters/data")


def _url(route: str, table: str) -> str:
    return f"/tiles/{route}.{table}/0/0/0.pbf"


def _signed(table: str, *, publication_version: int = 0, exp_offset: int = 300):
    exp = int(time.time()) + exp_offset
    scope = tile_signature_scope(table, publication_version)
    return {"sig": generate_tile_signature(scope, exp), "exp": exp, "scope": scope}


def _answer(resp) -> tuple[int, object]:
    return resp.status_code, resp.json()


@pytest.fixture
async def unseen_tables(test_db_session, make_tiles):  # noqa: F811
    """A private table, a public draft and a table name no dataset has."""
    owner = await get_user_id(test_db_session, settings.geolens_admin_username)
    private = await make_tiles(owner)
    draft = await make_tiles(owner, visibility="public", record_status="draft")
    missing = f"vt_key_{uuid.uuid4().hex[:8]}"
    return private.table_name, draft.table_name, missing


@pytest.mark.parametrize("route", _ROUTES)
@pytest.mark.parametrize(
    ("shape", "expected_status"),
    [
        ("bare", 404),
        ("wrong_scope", 403),
        ("current_scope_expired", 403),
        ("forged_sig", 403),
        ("embed_token", 403),
    ],
)
async def test_anonymous_refusals_match_an_unknown_table(
    client: AsyncClient, unseen_tables, route: str, shape: str, expected_status: int
) -> None:
    private, draft, missing = unseen_tables

    def request_for(table: str) -> dict:
        if shape == "bare":
            return {}
        if shape == "wrong_scope":
            return {"params": _signed(table, publication_version=7)}
        if shape == "current_scope_expired":
            return {"params": _signed(table, exp_offset=-60)}
        if shape == "forged_sig":
            return {"params": {**_signed(table), "sig": "0" * 64}}
        return {"headers": {"X-Embed-Token": "et_not-a-real-token"}}

    answers = {
        table: _answer(await client.get(_url(route, table), **request_for(table)))
        for table in (private, draft, missing)
    }

    assert answers[private] == answers[draft] == answers[missing], answers
    assert answers[missing][0] == expected_status, answers


@pytest.mark.parametrize("route", _ROUTES)
async def test_an_expired_template_still_answers_the_remint_status(
    client: AsyncClient, unseen_tables, route: str
) -> None:
    """Map clients re-mint a vector template on a tile 401/403, never on a 404."""
    private, _, _ = unseen_tables

    expired = await client.get(
        _url(route, private), params=_signed(private, exp_offset=-60)
    )
    current = await client.get(_url(route, private), params=_signed(private))

    assert expired.status_code == 403, expired.text
    assert current.status_code in (200, 204), current.text


@pytest.mark.parametrize("route", _ROUTES)
async def test_a_stranger_with_a_key_sees_an_unknown_table(
    client: AsyncClient,
    unseen_tables,
    people,  # noqa: F811
    mint_key,  # noqa: F811
    route: str,
) -> None:
    private, draft, missing = unseen_tables
    _, stranger_id = people
    key, _ = await mint_key(stranger_id)
    headers = {"X-Api-Key": key}

    answers = {
        table: _answer(
            await client.get(
                _url(route, table),
                params=_signed(table, exp_offset=-60),
                headers=headers,
            )
        )
        for table in (private, draft, missing)
    }

    assert answers[private] == answers[draft] == answers[missing], answers
    assert answers[missing][0] == 404, answers


@pytest.mark.parametrize("route", _ROUTES)
async def test_a_dead_credential_is_refused_alike(
    client: AsyncClient, unseen_tables, route: str
) -> None:
    private, _, missing = unseen_tables
    headers = {"Authorization": "Bearer not-a-real-token"}

    answers = {
        table: _answer(await client.get(_url(route, table), headers=headers))
        for table in (private, missing)
    }

    assert answers[private] == answers[missing], answers
    assert answers[missing][0] == 401, answers
