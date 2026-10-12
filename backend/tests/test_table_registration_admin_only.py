"""Only administrators may discover or register existing data-schema tables."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import _create_test_user

pytestmark = pytest.mark.anyio

_MISSING_TABLE = "no_such_table_admin_only"
_REQUESTS = {
    "discover": ("GET", "/ingest/discover/", None),
    "register": (
        "POST",
        "/ingest/register/",
        {"table_name": _MISSING_TABLE, "title": "Claimed"},
    ),
    "bulk": (
        "POST",
        "/ingest/register/bulk/",
        {"tables": [{"table_name": _MISSING_TABLE, "title": "Claimed"}]},
    ),
}


@pytest.mark.parametrize("route", list(_REQUESTS))
async def test_an_editor_is_refused(
    client: AsyncClient, admin_auth_header: dict, route: str
) -> None:
    editor_headers, _ = await _create_test_user(client, admin_auth_header, "editor")
    method, url, body = _REQUESTS[route]

    resp = await client.request(method, url, json=body, headers=editor_headers)

    assert resp.status_code == 403, resp.text


@pytest.mark.parametrize(
    ("route", "expected"), [("discover", 200), ("register", 400), ("bulk", 201)]
)
async def test_an_admin_passes_the_gate(
    client: AsyncClient, admin_auth_header: dict, route: str, expected: int
) -> None:
    """The admin reaches the handler: discovery lists, and a missing table is the handler's own refusal."""
    method, url, body = _REQUESTS[route]

    resp = await client.request(method, url, json=body, headers=admin_auth_header)

    assert resp.status_code == expected, resp.text
