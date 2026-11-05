"""The hosts a story's embed and video blocks may frame, and the CSP that admits them.

An admin lists exact host names. A block's address must be ``https://`` on one
of them, with no userinfo, no IP literal and no port but 443. The server never
fetches the address; the reader's browser does, inside a sandboxed iframe.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.stdlib.get_logger(__name__)

MAX_STORY_FRAME_HOSTS = 50
MAX_FRAME_URL_LENGTH = 2048
FRAME_SRC_BASE = "frame-src 'self' blob:"

_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_UNSAFE_URL_CHARS = re.compile(r"[\s\\\x00-\x1f\x7f]")


def normalize_frame_host(value: str) -> str:
    """A lower-cased DNS host name with at least two labels; ValueError otherwise.

    No scheme, port, path or wildcard, and no IP literal: a numeric last label
    is refused, so ``10.0.0.1`` never passes as a name.
    """
    host = value.strip().lower()
    labels = host.split(".")
    if (
        len(host) > 253
        or len(labels) < 2
        or not all(_LABEL.match(label) for label in labels)
        or labels[-1].isdigit()
    ):
        raise ValueError(f"{value!r} is not a host name like media.example.org")
    return host


def frame_url_host(url: str) -> str:
    """The host of an address a story block may frame; ValueError when its shape is wrong."""
    if len(url) > MAX_FRAME_URL_LENGTH or _UNSAFE_URL_CHARS.search(url):
        raise ValueError("the address has characters a frame address can't hold")
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValueError("the address must start with https://")
    try:
        port = parts.port
    except ValueError:
        port = -1
    if (
        parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
    ):
        raise ValueError("the address must not carry a user name or a port")
    host = normalize_frame_host(parts.hostname or "")
    if parts.netloc.lower() not in (host, f"{host}:443"):
        raise ValueError("the address's host must be a plain host name")
    return host


def validate_frame_url(url: str) -> str:
    """``url`` unchanged when :func:`frame_url_host` accepts it."""
    frame_url_host(url)
    return url


class StoryFrameHost(BaseModel):
    """One approved host."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(description="An exact host name, such as media.example.org.")
    allow_same_origin: bool = Field(
        default=False,
        description="Let this host's frames keep their own origin, which some "
        "video players need for playback.",
    )

    @field_validator("host", mode="before")
    @classmethod
    def _host(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("host must be a string")
        return normalize_frame_host(value)


def parse_frame_hosts(raw: Any) -> list[dict[str, Any]]:
    """The setting's value, lower-cased, with later repeats of a host dropped.

    Raises ValueError for anything but a list of at most 50 host entries.
    """
    if not isinstance(raw, list):
        raise ValueError("story_frame_hosts must be a list")
    entries: dict[str, StoryFrameHost] = {}
    for item in raw:
        entry = StoryFrameHost.model_validate(item)
        entries.setdefault(entry.host, entry)
    if len(entries) > MAX_STORY_FRAME_HOSTS:
        raise ValueError(
            f"story_frame_hosts holds at most {MAX_STORY_FRAME_HOSTS} hosts"
        )
    return [entry.model_dump() for entry in entries.values()]


async def approved_frame_hosts(db: AsyncSession) -> list[StoryFrameHost]:
    """The hosts stories may frame now; none when the stored value doesn't parse."""
    from app.core.persistent_config import STORY_FRAME_HOSTS

    try:
        entries = parse_frame_hosts(await STORY_FRAME_HOSTS.get(db))
    except ValueError:
        logger.warning("story_frame_hosts.invalid_stored_value_ignored")
        return []
    return [StoryFrameHost.model_validate(entry) for entry in entries]


def frame_src_directive(hosts: list[StoryFrameHost]) -> str:
    """``frame-src`` admitting this origin, blob: and exactly ``hosts`` over https."""
    return " ".join([FRAME_SRC_BASE, *(f"https://{entry.host}" for entry in hosts)])
