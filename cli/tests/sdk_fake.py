"""Offline GeoLens API double installed under the generated SDK's httpx client."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx


@dataclass
class SdkRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes
    timeout: dict[str, float | None]

    def json(self) -> Any:
        return json.loads(self.body) if self.body else None


class FakeGeoLens:
    """Answers SDK requests by ``"<METHOD> <path>"``, records every request.

    *path* is relative to the instance's base URL, as the SDK writes it
    (``"GET /auth/me/"``). A route is a JSON value (HTTP 200), a
    ``(status, body)`` or ``(status, body, headers)`` tuple, or a callable taking the ``SdkRequest`` and
    returning either. An unrouted request answers 404 with a problem body.
    ``token`` is a generated bearer token for the fake's caller to use.
    """

    def __init__(self, base_url: str) -> None:
        self.base_path = urlsplit(base_url).path.rstrip("/")
        self.routes: dict[str, Any] = {}
        self.seen: list[SdkRequest] = []
        self.token = secrets.token_urlsafe(24)

    def handle(self, request: httpx.Request) -> httpx.Response:
        seen = SdkRequest(
            request.method,
            str(request.url),
            {k.lower(): v for k, v in request.headers.items()},
            request.read(),
            dict(request.extensions.get("timeout") or {}),
        )
        self.seen.append(seen)
        path = urlsplit(seen.url).path.removeprefix(self.base_path)
        reply = self.routes.get(f"{seen.method} {path}")
        if reply is None:
            reply = (404, {"detail": "Not Found", "status": 404, "title": "Not Found"})
        if callable(reply):
            reply = reply(seen)
        status, payload, *headers = reply if isinstance(reply, tuple) else (200, reply)
        return httpx.Response(
            status, json=payload, headers=headers[0] if headers else None
        )
