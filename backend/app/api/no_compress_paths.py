"""Serve the export download and 3D Tiles files uncompressed, by path.

Both answer with a strong ETag over the stored bytes, and ``GZipMiddleware``
would compress a 200 under that same tag, so one validator would name two
representations. Dropping gzip from ``Accept-Encoding`` is the opt-out it reads.
"""

import re

from starlette.types import ASGIApp, Receive, Scope, Send

# With or without the ``/api`` prefix an edge may not have stripped, and anchored
# at both ends so no other route matches.
_UNCOMPRESSED_PATH_RE = re.compile(
    r"^(?:/api)?/datasets/[^/]+/(?:export/?|tiles3d/.*)\Z", re.DOTALL
)


class NoCompressionByPathMiddleware:
    """Strip gzip from Accept-Encoding for the export download and 3D Tiles files."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _UNCOMPRESSED_PATH_RE.match(
            scope.get("path", "")
        ):
            await self.app(scope, receive, send)
            return

        # Rebuilt rather than edited through MutableHeaders(scope=...), which
        # keeps its own list and never writes back to the scope.
        rewritten: list[tuple[bytes, bytes]] = []
        for name, value in scope.get("headers", []):
            if name.lower() != b"accept-encoding":
                rewritten.append((name, value))
                continue
            # GZipMiddleware engages on a substring test, "gzip" in the header,
            # so every member containing it goes, x-gzip included.
            remaining = b", ".join(
                part.strip()
                for part in value.split(b",")
                if part.strip() and b"gzip" not in part.strip().lower()
            )
            if remaining:
                rewritten.append((name, remaining))
        scope["headers"] = rewritten
        await self.app(scope, receive, send)
