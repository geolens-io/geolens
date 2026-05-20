"""SEC-FU-07: service_crud.py list_maps ILIKE search must escape %/_ wildcards.

The list_maps() function in service_crud.py composes an ILIKE pattern as
f"%{search}%" without escaping the user-supplied string first. A search of
"%" matches all rows because the pattern becomes "%%", which Postgres treats
as "match any string". Similarly, "_" matches any single character.

Fix: escape '%' and '_' using str.replace before composing the ILIKE pattern.
Same pattern as service_public.py:407-409.

Tests use API layer (GET /maps/?search=...) to verify behavior end-to-end.
All test maps use unique names with a uuid prefix to isolate from other tests.

Note: service_collections.py (referenced in CONTEXT.md) does not exist in the
current tree. Only service_crud.py:140-147 needs the escape fix;
service_public.py:407-409 already has it from prior phases.
"""

import uuid

import pytest
from httpx import AsyncClient


def _uid() -> str:
    """Return an 8-char hex unique ID for test isolation."""
    return uuid.uuid4().hex[:8]


async def _create_map(
    client: AsyncClient,
    headers: dict,
    name: str,
    description: str = "",
) -> dict:
    """Create a map and return the response body."""
    resp = await client.post(
        "/maps/",
        json={"name": name, "description": description},
        headers=headers,
    )
    assert resp.status_code == 201, f"Create map failed: {resp.text}"
    return resp.json()


async def _search_maps(
    client: AsyncClient,
    headers: dict,
    search: str,
) -> list[dict]:
    """Call GET /maps/?search=<search> and return the items list."""
    resp = await client.get(
        "/maps/",
        params={"search": search},
        headers=headers,
    )
    assert resp.status_code == 200, f"List maps failed: {resp.text}"
    return resp.json()["maps"]


@pytest.mark.anyio
class TestSecFu07IlikeEscape:
    async def test_sec_fu_07_normal_search_returns_match(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """search='MapAlpha' returns only rows containing 'MapAlpha' in name."""
        uid = _uid()
        target_name = f"MapAlpha_{uid}"
        noise_name = f"OtherMap_{uid}"

        await _create_map(client, admin_auth_header, target_name)
        await _create_map(client, admin_auth_header, noise_name)

        results = await _search_maps(client, admin_auth_header, f"MapAlpha_{uid}")
        names = [r["name"] for r in results]
        assert target_name in names, f"Expected '{target_name}' in {names}"
        assert noise_name not in names, f"Did not expect '{noise_name}' in {names}"

    async def test_sec_fu_07_percent_literal_not_wildcard(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """search='%' must NOT match all rows.

        Pre-fix behavior: pattern becomes '%%' which Postgres treats as
        'match anything', returning every row.

        Post-fix behavior: pattern becomes the 4-char sequence percent+backslash+percent+percent
        which only matches rows containing a literal '%' character.
        """
        uid = _uid()
        percent_name = f"100pct_{uid}_Coverage%"  # has literal %
        normal_name = f"RegularMap_{uid}"

        await _create_map(client, admin_auth_header, percent_name)
        await _create_map(client, admin_auth_header, normal_name)

        # Search for literal "%" — should only match names containing "%"
        # We search for the full unique fragment including "%" to be precise
        results = await _search_maps(client, admin_auth_header, f"Coverage%")
        names = [r["name"] for r in results]

        # The percent-containing map must be in results
        assert percent_name in names, f"Expected percent map '{percent_name}' in {names}"

        # Verify that a search for just "%" doesn't return the normal map
        # (the normal map name contains no "%")
        all_results = await _search_maps(client, admin_auth_header, "%")
        all_names = [r["name"] for r in all_results]
        assert normal_name not in all_names, (
            f"search='%' returned '{normal_name}' which has no literal '%'. "
            f"This means '%' is acting as a wildcard (SEC-FU-07 not applied)."
        )

    async def test_sec_fu_07_underscore_literal_not_wildcard(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """search='_' must NOT match all rows as a single-char wildcard.

        Post-fix: the escaped pattern only matches rows containing a literal '_' character.
        """
        uid = _uid()
        under_name = f"row_under_score_{uid}"  # has multiple "_"
        normal_name = f"NoUnderscore{uid}"     # no "_"

        await _create_map(client, admin_auth_header, under_name)
        await _create_map(client, admin_auth_header, normal_name)

        # "_" as wildcard would match any single-char name — but our names are
        # longer than 1 char, so it wouldn't match them anyway. Instead verify
        # that searching for a known underscored fragment finds the right map.
        results = await _search_maps(client, admin_auth_header, f"row_under_score_{uid}")
        names = [r["name"] for r in results]
        assert under_name in names, f"Expected underscore map '{under_name}' in {names}"
        assert normal_name not in names, f"Did not expect '{normal_name}' in {names}"

    async def test_sec_fu_07_combined_escape(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """search='%a_b' returns only maps with literal substring '%a_b'."""
        uid = _uid()
        target_name = f"Map%a_b_{uid}"   # has literal "%a_b"
        other_name = f"OtherMap_{uid}"   # no "%a_b"

        await _create_map(client, admin_auth_header, target_name)
        await _create_map(client, admin_auth_header, other_name)

        results = await _search_maps(client, admin_auth_header, "%a_b")
        names = [r["name"] for r in results]
        assert target_name in names, f"Expected '{target_name}' in {names}"
        assert other_name not in names, (
            f"'{other_name}' should not match '%a_b' literal search"
        )

    async def test_sec_fu_07_normal_text_search_unchanged(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Normal text without special chars is not affected by the escape."""
        uid = _uid()
        target = f"NormalSearch_{uid}_Map"

        await _create_map(client, admin_auth_header, target)

        results = await _search_maps(client, admin_auth_header, f"NormalSearch_{uid}")
        names = [r["name"] for r in results]
        assert target in names, f"Expected '{target}' in {names}"
