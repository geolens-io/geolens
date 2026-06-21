"""Integration tests for the allowed_email_domains setting round-trip.

Tests PUT /settings/ and GET /settings/all/ for the allowed_email_domains key,
verifying persistence, case-folding, 422 on invalid patterns (no partial-apply),
and empty-list-means-unrestricted semantics.

Mirrors test_settings_admin.py conventions: client + admin_auth_header fixtures,
PUT to /settings/, read back from GET /settings/all/.
"""

from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _get_allowed_domains(client: AsyncClient, header: dict) -> object:
    """GET /settings/all/ and return the value of allowed_email_domains from tabs['auth']."""
    resp = await client.get("/settings/all/", headers=header)
    assert resp.status_code == 200
    auth_items = resp.json()["tabs"]["auth"]
    item = next((s for s in auth_items if s["key"] == "allowed_email_domains"), None)
    assert item is not None, "allowed_email_domains not found in auth tab"
    return item["value"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAllowedEmailDomainsSetting:
    async def test_put_valid_list_persists_and_get_returns_normalized(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """PUT a valid non-empty list; GET returns the case-folded result (DOMAIN-01 criterion 1)."""
        resp = await client.put(
            "/settings/",
            json={
                "settings": {
                    "allowed_email_domains": ["example.com", "*.sub.example.com"]
                }
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200

        value = await _get_allowed_domains(client, admin_auth_header)
        assert value == ["example.com", "*.sub.example.com"]

    async def test_put_mixed_case_stored_as_lowercase(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """PUT mixed-case domains; GET returns case-folded value (DOMAIN-01 criterion 2)."""
        resp = await client.put(
            "/settings/",
            json={"settings": {"allowed_email_domains": ["EXAMPLE.COM"]}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200

        value = await _get_allowed_domains(client, admin_auth_header)
        assert value == ["example.com"]

    async def test_put_invalid_patterns_returns_422_and_nothing_persisted(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """PUT invalid patterns -> 422, and prior value is unchanged (no partial-apply, DOMAIN-01 criterion 1)."""
        # First set a known good value
        await client.put(
            "/settings/",
            json={"settings": {"allowed_email_domains": ["safe.org"]}},
            headers=admin_auth_header,
        )
        prior_value = await _get_allowed_domains(client, admin_auth_header)
        assert prior_value == ["safe.org"]

        # Now attempt an invalid update — bare all-match and a domain with a space
        resp_bad_star = await client.put(
            "/settings/",
            json={"settings": {"allowed_email_domains": ["*"]}},
            headers=admin_auth_header,
        )
        assert resp_bad_star.status_code == 422
        detail = resp_bad_star.json()["detail"]
        assert "allowed_email_domains" in detail

        resp_bad_space = await client.put(
            "/settings/",
            json={"settings": {"allowed_email_domains": ["bad domain.com"]}},
            headers=admin_auth_header,
        )
        assert resp_bad_space.status_code == 422
        detail_space = resp_bad_space.json()["detail"]
        assert "allowed_email_domains" in detail_space

        # Setting must not have changed
        unchanged_value = await _get_allowed_domains(client, admin_auth_header)
        assert unchanged_value == ["safe.org"]

    async def test_put_non_string_entry_returns_422_not_500(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Codex P3: a non-string entry (e.g. 123) must be a 422, not a 500.

        normalize_domains calls .strip() on each entry; a non-string would raise
        AttributeError (uncaught -> 500) without the explicit type check.
        """
        resp = await client.put(
            "/settings/",
            json={"settings": {"allowed_email_domains": [123]}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422, (
            f"Expected 422 for non-string entry, got {resp.status_code}: {resp.text}"
        )
        assert "allowed_email_domains" in resp.json()["detail"]

    async def test_put_empty_list_succeeds_and_get_returns_empty(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """PUT [] succeeds; GET returns [] (unrestricted, DOMAIN-01 criterion 3)."""
        resp = await client.put(
            "/settings/",
            json={"settings": {"allowed_email_domains": []}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200

        value = await _get_allowed_domains(client, admin_auth_header)
        assert value == []
