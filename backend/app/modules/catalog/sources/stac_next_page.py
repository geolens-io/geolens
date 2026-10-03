"""Authentication for the STAC next-page descriptor a search response hands out.

The descriptor round-trips through the client, which could otherwise edit it
into any request on the catalog's origin. Each one is signed over the request
that produced it, and a follow-up is replayed only if the signature still
matches the request it arrives with.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings as app_settings
from app.modules.catalog.sources.adapters.stac import MAX_NEXT_BODY_BYTES

_DOMAIN = b"stac-next-page\0"


class StacNextPage(BaseModel):
    """A STAC ``rel="next"`` link, echoed back to fetch the following page."""

    method: Literal["GET", "POST"] = Field(description="HTTP method of the link.")
    href: str = Field(
        max_length=4096,
        description=(
            "Absolute URL of the next page. It must share the origin of the "
            "catalog URL it came from; any other origin is refused."
        ),
    )
    body: dict[str, Any] | None = Field(
        default=None, description="JSON body of a POST link."
    )
    merge: bool = Field(
        default=False,
        description="Whether the body is merged into the original search body.",
    )
    signature: str | None = Field(
        default=None,
        max_length=128,
        description=(
            "Server-issued signature of this link for the catalog URL and "
            "collections it was issued for. Echo it back unchanged; a link "
            "without a matching signature is refused."
        ),
    )

    @field_validator("body")
    @classmethod
    def _bound_body(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and len(json.dumps(value)) > MAX_NEXT_BODY_BYTES:
            raise ValueError("next page body is too large")
        return value


def _signed_payload(
    catalog_url: str, collections: list[str] | None, descriptor: dict[str, Any]
) -> bytes:
    return json.dumps(
        {
            "catalog_url": catalog_url,
            "collections": collections,
            "href": descriptor.get("href"),
            "method": descriptor.get("method"),
            "body": descriptor.get("body"),
            "merge": descriptor.get("merge"),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def sign_next_page(
    catalog_url: str, collections: list[str] | None, descriptor: dict[str, Any]
) -> str:
    """The hex signature binding *descriptor* to the request's catalog and collections."""
    key = app_settings.jwt_secret_key.get_secret_value().encode("utf-8")
    message = _DOMAIN + _signed_payload(catalog_url, collections, descriptor)
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def verify_next_page(
    catalog_url: str,
    collections: list[str] | None,
    descriptor: dict[str, Any],
    signature: str | None,
) -> bool:
    """Whether *signature* is the one issued for *descriptor* under this request."""
    if not signature:
        return False
    expected = sign_next_page(catalog_url, collections, descriptor)
    return hmac.compare_digest(expected, signature)
