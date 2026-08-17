"""Opt the export download out of gzip, by path (fix(#1532 review r11)).

``/datasets/{id}/export`` serves a cached artifact under a strong ETag taken
from the stored bytes, and every range is a slice of exactly those bytes.
``GZipMiddleware`` compresses a full response and skips a 206 by design, so a
compressed 200 and a raw 206 would share one validator — a client that took the
ETag from the 200 and offered it back on an ``If-Range`` would have it accepted
and splice raw bytes at compressed offsets. fix(#1540) hit the same thing on the
COG route.

Scoped to the ROUTE rather than to its media types, which is what an earlier
revision did. ``application/geo+json`` and ``text/csv`` are also produced by the
feature endpoint and by the admin and audit CSV streams, and those serve one
representation and never a range — so excluding the types stopped compressing
them for no safety gain. ``image/tiff`` stays a media-type exclusion because
there the type and the route are the same set: the COG download is its only
producer.

Dropping gzip from the request's ``Accept-Encoding`` is the opt-out
``GZipMiddleware`` itself reads (it engages only when the header offers gzip).
The alternative — a ``Content-Encoding: identity`` on the responses — would work
through the same middleware's other skip condition, but puts a token on the wire
that RFC 9110 defines for Accept-Encoding rather than for Content-Encoding.
"""

import re

from starlette.types import ASGIApp, Receive, Scope, Send

# The export download, with or without the ``/api`` prefix an edge may or may
# not have stripped. Anchored, so nothing else can match by accident.
_EXPORT_PATH_RE = re.compile(r"^(?:/api)?/datasets/[^/]+/export/?$")


class NoCompressionForExportMiddleware:
    """Strip gzip from Accept-Encoding for the export download only."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _EXPORT_PATH_RE.match(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        # ``scope["headers"]`` is rebuilt directly rather than through
        # ``MutableHeaders(scope=...)``: that class keeps its own list and does
        # NOT write back to the scope, so the edit was invisible to the
        # middleware downstream — measured, after the first version of this
        # silently did nothing and the test caught it.
        rewritten: list[tuple[bytes, bytes]] = []
        for name, value in scope.get("headers", []):
            if name.lower() != b"accept-encoding":
                rewritten.append((name, value))
                continue
            remaining = b", ".join(
                part.strip()
                for part in value.split(b",")
                if part.strip() and not part.strip().lower().startswith(b"gzip")
            )
            if remaining:
                rewritten.append((name, remaining))
        scope["headers"] = rewritten
        await self.app(scope, receive, send)
