from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.modules.catalog.maps.schemas import ShareTokenRequest
from app.modules.catalog.maps.sharing_policy import SHARE_EXPIRATION_SELECTION_ERROR
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
    """fix(#435): a custom expiration is an Enterprise control at the schema layer too.

    This test previously asserted the opposite — that Community accepts the input —
    which pinned the gap the router alone was papering over.
    """
    with pytest.raises(ValidationError) as exc_info:
        ShareTokenRequest(expires_at=_future_timestamp())

    _assert_advanced_sharing_error(exc_info)


def test_enterprise_accepts_share_expiration(enterprise_edition):
    expires_at = _future_timestamp()

    request = ShareTokenRequest(expires_at=expires_at)

    assert request.expires_at == expires_at


@pytest.mark.parametrize(
    "naive",
    [
        "2030-06-01T00:00:00",
        datetime(2030, 6, 1, 0, 0, 0),
    ],
    ids=["naive-string", "naive-datetime"],
)
def test_share_expiration_rejects_naive_timestamp(enterprise_edition, naive):
    """fix(#435): a naive timestamp is a 422, not a `TypeError` 500.

    `expires_at: datetime` accepted naive input, then `v < datetime.now(timezone.utc)`
    raised `TypeError: can't compare offset-naive and offset-aware datetimes`.
    """
    with pytest.raises(ValidationError) as exc_info:
        ShareTokenRequest(expires_at=naive)

    assert exc_info.value.errors()[0]["type"] == "timezone_aware"


@pytest.mark.parametrize(
    "value",
    ["2030-06-01T00:00:00Z", "2030-06-01T00:00:00+05:30", "2030-05-31T18:30:00-05:00"],
)
def test_share_expiration_accepts_any_offset(enterprise_edition, value):
    assert ShareTokenRequest(expires_at=value).expires_at.tzinfo is not None


def test_community_accepts_basic_sharing_defaults(community_edition):
    embed_request = EmbedTokenCreate()
    share_request = ShareTokenRequest(expires_at=None)

    assert embed_request.expires_in_days == 30
    assert embed_request.allowed_origins is None
    assert share_request.expires_at is None
    assert share_request.expires_in_days is None


@pytest.mark.parametrize("days", [1, 7, 30, 90])
def test_community_accepts_fixed_share_expiration_presets(community_edition, days):
    request = ShareTokenRequest(expires_in_days=days)

    assert request.expires_in_days == days


def test_share_expiration_rejects_custom_date_with_preset(enterprise_edition):
    with pytest.raises(ValidationError) as exc_info:
        ShareTokenRequest(expires_at=_future_timestamp(), expires_in_days=7)

    assert SHARE_EXPIRATION_SELECTION_ERROR in str(exc_info.value)


def test_share_expiration_rejects_unknown_preset(community_edition):
    with pytest.raises(ValidationError):
        ShareTokenRequest(expires_in_days=14)


def test_enterprise_accepts_custom_embed_lifetime_and_origins(enterprise_edition):
    create_request = EmbedTokenCreate(
        expires_in_days=90,
        allowed_origins=["https://Example.com/"],
    )
    update_request = EmbedTokenUpdate(allowed_origins=["example.org"])

    assert create_request.expires_in_days == 90
    assert create_request.allowed_origins == ["https://example.com"]
    assert update_request.allowed_origins == ["https://example.org"]


def test_share_expiration_must_be_future():
    with pytest.raises(ValidationError) as exc_info:
        ShareTokenRequest(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))

    assert "expires_at must be in the future" in str(exc_info.value)


async def test_service_rejects_community_share_expiration(community_edition):
    """fix(#435): the guard repeats at the service entry points.

    The schema only protects HTTP callers. An internal caller — bulk import, an
    overlay, a test helper — reaches `create_share_token` directly, and nothing
    below the router stopped it persisting an Enterprise-only expiration.
    """
    import uuid

    from app.modules.catalog.maps.service_public import (
        create_share_token,
        update_share_token,
    )

    map_id = uuid.uuid4()
    with pytest.raises(ValueError, match=ADVANCED_SHARING_ERROR):
        await create_share_token(None, map_id, uuid.uuid4(), _future_timestamp())

    with pytest.raises(ValueError, match=ADVANCED_SHARING_ERROR):
        await update_share_token(None, map_id, _future_timestamp())


async def test_service_allows_clearing_expiration_in_community(
    community_edition, monkeypatch
):
    """`None` must stay valid: Community keeps create/revoke and can clear an expiry."""
    import uuid

    from app.modules.catalog.maps import service_public

    # Guard runs before any DB work; assert we get past it, not that we hit the DB.
    async def _no_token(*args, **kwargs):
        class _Empty:
            def scalar_one_or_none(self):
                return None

        return _Empty()

    class _Session:
        execute = staticmethod(_no_token)

    assert (
        await service_public.update_share_token(_Session(), uuid.uuid4(), None) is None
    )


def test_service_resolves_fixed_preset_on_server(community_edition):
    from app.modules.catalog.maps.service_public import _resolve_share_expiration

    now = datetime(2026, 7, 14, tzinfo=timezone.utc)

    assert _resolve_share_expiration(None, 7, now=now) == now + timedelta(days=7)


def test_service_rejects_unknown_fixed_preset(community_edition):
    from app.modules.catalog.maps.service_public import _resolve_share_expiration

    with pytest.raises(ValueError, match="must be 1, 7, 30, or 90 days"):
        _resolve_share_expiration(None, 14)
