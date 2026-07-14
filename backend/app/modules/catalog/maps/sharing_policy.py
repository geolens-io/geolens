"""Saved-map sharing policy."""

from datetime import datetime, timedelta, timezone
from typing import Literal, TypeAlias

from app.core.edition import is_enterprise
from app.modules.embed_tokens.schemas import ADVANCED_SHARING_ERROR

ShareExpirationPresetDays: TypeAlias = Literal[1, 7, 30, 90]

SHARE_EXPIRATION_PRESET_DAYS = frozenset({1, 7, 30, 90})
SHARE_EXPIRATION_SELECTION_ERROR = (
    "Choose either a fixed expiration preset or a custom expiration date, not both"
)


def _reject_custom_expiration_in_community(expires_at: datetime | None) -> None:
    """Keep custom expiration dates behind the advanced-sharing boundary."""
    if expires_at is not None and not is_enterprise():
        raise ValueError(ADVANCED_SHARING_ERROR)


def resolve_share_expiration(
    expires_at: datetime | None,
    expires_in_days: ShareExpirationPresetDays | int | None,
    *,
    now: datetime | None = None,
) -> datetime | None:
    """Resolve a fixed preset or an Enterprise custom timestamp."""
    if expires_at is not None and expires_in_days is not None:
        raise ValueError(SHARE_EXPIRATION_SELECTION_ERROR)
    if expires_in_days is not None:
        if expires_in_days not in SHARE_EXPIRATION_PRESET_DAYS:
            raise ValueError("Share-link expiration must be 1, 7, 30, or 90 days")
        base = now or datetime.now(timezone.utc)
        return base + timedelta(days=expires_in_days)
    _reject_custom_expiration_in_community(expires_at)
    return expires_at
