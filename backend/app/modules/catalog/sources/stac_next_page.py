"""The opaque cursor a STAC search response hands out for its next page.

The cursor carries the catalog's next link, and a client could otherwise edit
it into any request on the catalog's origin. It is therefore signed over the
exact encoded text, and a follow-up is replayed only from the decoded
descriptor of a cursor whose signature matches and which was issued for the
same catalog URL and collections.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import settings as app_settings

_DOMAIN = b"stac-next-page\0"
MAX_CURSOR_CHARS = 32768


class StacNextPage(BaseModel):
    """Opaque handle for the next page of a search."""

    cursor: str | None = Field(
        default=None,
        max_length=MAX_CURSOR_CHARS,
        description=(
            "Server-issued token for the next page. Echo the next_page of the "
            "previous response unchanged, with the same url and collections; "
            "a missing or altered cursor is refused."
        ),
    )


def _mac(encoded: str) -> str:
    key = app_settings.jwt_secret_key.get_secret_value().encode("utf-8")
    return hmac.new(key, _DOMAIN + encoded.encode("ascii"), hashlib.sha256).hexdigest()


def issue_cursor(
    catalog_url: str, collections: list[str] | None, descriptor: dict[str, Any]
) -> str | None:
    """A signed cursor for *descriptor*, or None if it would exceed the length cap."""
    payload = json.dumps(
        {
            "catalog_url": catalog_url,
            "collections": collections,
            "href": descriptor["href"],
            "method": descriptor["method"],
            "body": descriptor.get("body"),
            "merge": bool(descriptor.get("merge")),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
    cursor = f"{encoded}.{_mac(encoded)}"
    return cursor if len(cursor) <= MAX_CURSOR_CHARS else None


def open_cursor(
    catalog_url: str, collections: list[str] | None, cursor: str | None
) -> dict[str, Any] | None:
    """The ``{method, href, body, merge}`` a valid cursor carries, else None.

    Valid means the signature matches the received text and the cursor was
    issued for this catalog URL and these collections.
    """
    if not cursor or "." not in cursor:
        return None
    encoded, _, signature = cursor.partition(".")
    if not encoded.isascii() or not hmac.compare_digest(_mac(encoded), signature):
        return None
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (binascii.Error, ValueError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("catalog_url") != catalog_url
        or payload.get("collections") != collections
    ):
        return None
    return {k: payload.get(k) for k in ("method", "href", "body", "merge")}
