"""Opt the export download out of gzip, by path (fix(#1532)).

``/datasets/{id}/export`` serves a strong ETag over the stored bytes,
and ``GZipMiddleware`` compresses a full response but skips a 206 — so
a client offering the 200's ETag back on ``If-Range`` would have it
accepted and splice raw bytes at compressed offsets (fix(#1540) hit the
same bug on the COG route).

Scoped to the ROUTE, not media types: excluding
``application/geo+json``/``text/csv`` app-wide (an earlier revision)
also stopped compressing the feature endpoint and admin/audit CSV
streams, which never serve a range, for no safety gain. Drops gzip from
``Accept-Encoding`` (the opt-out ``GZipMiddleware`` reads) rather than
``Content-Encoding: identity``, which RFC 9110 defines for a different
header.
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

        # Rebuilt directly rather than via ``MutableHeaders(scope=...)``:
        # that class keeps its own list and does NOT write back to scope,
        # so the edit was invisible downstream (measured — the first
        # version silently did nothing until a test caught it).
        rewritten: list[tuple[bytes, bytes]] = []
        for name, value in scope.get("headers", []):
            if name.lower() != b"accept-encoding":
                rewritten.append((name, value))
                continue
            # fix(#1532): matches GZipMiddleware's own predicate — it
            # engages on `"gzip" in Accept-Encoding`, a substring test —
            # so anything that would trip it is dropped here. A member-
            # name test (`startswith(b"gzip")`) let `x-gzip` through (RFC
            # 9110 §8.4.1.3 makes it equivalent), and the export came back
            # compressed under the strong ETag this exists to keep raw.
            remaining = b", ".join(
                part.strip()
                for part in value.split(b",")
                if part.strip() and b"gzip" not in part.strip().lower()
            )
            if remaining:
                rewritten.append((name, remaining))
        scope["headers"] = rewritten
        await self.app(scope, receive, send)
