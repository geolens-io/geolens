"""API keys carry the glk_ prefix, keys minted before it still work, and logs redact them."""

import hashlib
import secrets

import pytest
from httpx import AsyncClient

from app.core.logging_config import _API_KEY_VALUE_RE, _redact_sensitive_fields
from app.modules.auth.models import ApiKey, User
from app.modules.auth.service import API_KEY_PREFIX
from tests import test_api_key_scope_875 as _scope_tests
from tests.factories import get_user_id

_remove_keys_minted_by_the_test = _scope_tests._remove_keys_minted_by_the_test


@pytest.mark.anyio
async def test_a_new_key_is_prefixed_and_authenticates_both_ways(
    client: AsyncClient, admin_auth_header
):
    data = await _scope_tests._mint(client, admin_auth_header)
    key = data["key"]

    assert key.startswith(API_KEY_PREFIX)
    assert _API_KEY_VALUE_RE.fullmatch(key)
    assert data["fingerprint"] == f"{key[:12]}…{key[-4:]}"
    assert (
        await client.get("/auth/me/", headers={"X-Api-Key": key})
    ).status_code == 200
    assert (await client.get("/auth/me/", params={"api_key": key})).status_code == 200


@pytest.mark.anyio
async def test_a_key_minted_before_the_prefix_still_authenticates(
    client: AsyncClient, test_db_session
):
    admin_id = await get_user_id(test_db_session, "admin")
    raw_key = secrets.token_urlsafe(32)
    admin = await test_db_session.get(User, admin_id)
    test_db_session.add(
        ApiKey(
            user_id=admin_id,
            key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
            fingerprint=f"{raw_key[:8]}…{raw_key[-4:]}",
            name="Unprefixed key",
            key_epoch=admin.key_epoch,
        )
    )
    await test_db_session.commit()

    resp = await client.get("/auth/me/", headers={"X-Api-Key": raw_key})
    assert resp.status_code == 200, resp.text


def test_a_key_is_redacted_in_every_logged_string():
    key = API_KEY_PREFIX + secrets.token_urlsafe(32)
    record = _redact_sensitive_fields(
        None,
        "info",
        {
            "event": f"calling the API with {key}",
            "note": f"pasted {key} into the plugin",
            "extra": {"headers": [f"X-Api-Key: {key}"]},
            "exception": f"ValueError: bad key {key}",
            key: "failed",
            "by_key": {key: "failed"},
            "error": ValueError(f"bad key {key}"),
            "errors": [ValueError(f"bad key {key}")],
        },
    )

    rendered = repr(record)
    assert key not in rendered
    assert "glk_[REDACTED]" in record["event"]
    assert record["note"] == "pasted glk_[REDACTED] into the plugin"


def test_short_glk_words_are_left_alone():
    record = _redact_sensitive_fields(None, "info", {"event": "the glk_ prefix"})
    assert record["event"] == "the glk_ prefix"
