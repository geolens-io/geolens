"""Shared provenance projection helpers for API response serialization."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


UNKNOWN_ACTOR_LABEL = "Unknown"
RESTRICTED_ACTOR_LABEL = "Restricted user"
SYSTEM_ACTOR_LABEL = "System"
SYSTEM_ACTOR_UUID = uuid.UUID(int=0)

_SYSTEM_USERNAMES = {
    "automation",
    "bot",
    "geolens-system",
    "service",
    "system",
}


class ActorIdentity(Protocol):
    """Minimal actor shape required for display-name derivation."""

    username: str
    email: str | None


@dataclass(frozen=True)
class LastEditedProjection:
    """Derived last-edited state used by API serializers."""

    display: str | None
    timestamp: datetime | None
    never_edited: bool


def _email_local_part(email: str | None) -> str | None:
    if not email:
        return None
    local_part, _, _domain = email.strip().partition("@")
    local_part = local_part.strip()
    return local_part or None


def _is_system_identity(actor_id: uuid.UUID | None, user: ActorIdentity | None) -> bool:
    if actor_id == SYSTEM_ACTOR_UUID:
        return True
    if user is None:
        return False
    username = user.username.strip().lower()
    if username in _SYSTEM_USERNAMES or username.endswith("-bot"):
        return True
    email_local = _email_local_part(user.email)
    if email_local is None:
        return False
    normalized = email_local.lower()
    return normalized in _SYSTEM_USERNAMES or normalized.endswith("-bot")


def resolve_actor(
    actor_id: uuid.UUID | None,
    user: ActorIdentity | None,
    *,
    missing_label: str = UNKNOWN_ACTOR_LABEL,
    restricted_label: str = RESTRICTED_ACTOR_LABEL,
    system_label: str = SYSTEM_ACTOR_LABEL,
) -> str:
    """Resolve a human-readable actor label from optional identity inputs."""
    if _is_system_identity(actor_id, user):
        return system_label

    if user is not None:
        username = user.username.strip()
        if username:
            return username

        email_local = _email_local_part(user.email)
        if email_local:
            return email_local

        return restricted_label

    if actor_id is None:
        return missing_label
    return restricted_label


def derive_last_edited(
    *,
    created_at: datetime | None,
    updated_at: datetime | None,
    updated_by: uuid.UUID | None,
    updated_user: ActorIdentity | None,
    system_label: str = SYSTEM_ACTOR_LABEL,
    restricted_label: str = RESTRICTED_ACTOR_LABEL,
) -> LastEditedProjection:
    """Derive last-edited projection and explicit never-edited state."""
    if updated_at is None:
        return LastEditedProjection(display=None, timestamp=None, never_edited=True)

    if updated_by is None and created_at is not None and updated_at <= created_at:
        return LastEditedProjection(display=None, timestamp=None, never_edited=True)

    if updated_by is None:
        return LastEditedProjection(
            display=system_label,
            timestamp=updated_at,
            never_edited=False,
        )

    return LastEditedProjection(
        display=resolve_actor(
            updated_by,
            updated_user,
            missing_label=restricted_label,
            restricted_label=restricted_label,
            system_label=system_label,
        ),
        timestamp=updated_at,
        never_edited=False,
    )
