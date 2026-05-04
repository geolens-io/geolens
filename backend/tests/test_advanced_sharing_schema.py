from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.modules.catalog.maps.schemas import ShareTokenRequest
from app.modules.embed_tokens.schemas import (
    ADVANCED_SHARING_ERROR,
    EmbedTokenCreate,
    EmbedTokenUpdate,
)


def _future_timestamp() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=7)


def _assert_advanced_sharing_error(exc_info: pytest.ExceptionInfo[ValidationError]):
    assert ADVANCED_SHARING_ERROR in str(exc_info.value)


def test_community_rejects_custom_embed_lifetime(community_edition):
    with pytest.raises(ValidationError) as exc_info:
        EmbedTokenCreate(expires_in_days=90)

    _assert_advanced_sharing_error(exc_info)


def test_community_rejects_embed_allowed_origins(community_edition):
    with pytest.raises(ValidationError) as exc_info:
        EmbedTokenCreate(allowed_origins=["https://example.com"])

    _assert_advanced_sharing_error(exc_info)


def test_community_rejects_embed_update_allowed_origins(community_edition):
    with pytest.raises(ValidationError) as exc_info:
        EmbedTokenUpdate(allowed_origins=["https://example.com"])

    _assert_advanced_sharing_error(exc_info)


def test_community_rejects_share_expiration(community_edition):
    with pytest.raises(ValidationError) as exc_info:
        ShareTokenRequest(expires_at=_future_timestamp())

    _assert_advanced_sharing_error(exc_info)


def test_community_accepts_basic_sharing_defaults(community_edition):
    embed_request = EmbedTokenCreate()
    share_request = ShareTokenRequest(expires_at=None)

    assert embed_request.expires_in_days == 30
    assert embed_request.allowed_origins is None
    assert share_request.expires_at is None


def test_enterprise_accepts_custom_embed_lifetime_and_origins(enterprise_edition):
    create_request = EmbedTokenCreate(
        expires_in_days=90,
        allowed_origins=["https://Example.com/"],
    )
    update_request = EmbedTokenUpdate(allowed_origins=["example.org"])

    assert create_request.expires_in_days == 90
    assert create_request.allowed_origins == ["https://example.com"]
    assert update_request.allowed_origins == ["https://example.org"]


def test_enterprise_accepts_share_expiration(enterprise_edition):
    expires_at = _future_timestamp()

    request = ShareTokenRequest(expires_at=expires_at)

    assert request.expires_at == expires_at
