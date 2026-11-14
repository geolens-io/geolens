"""A streamed OGC API Features items response."""

import json
import math
from collections.abc import AsyncGenerator
from contextlib import aclosing

import anyio
import structlog
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

logger = structlog.stdlib.get_logger(__name__)

# Body text gathered before each send, so a page goes out in a few hundred
# writes rather than one per feature.
_CHUNK_CHARS = 64 * 1024


async def feature_collection_body(
    members: dict, features: AsyncGenerator[str], *, dataset_id: str
) -> AsyncGenerator[bytes]:
    """Write *members*, then ``features``, then ``numberReturned``.

    ``numberReturned`` follows the features so that it counts the features
    actually written. A failure after the status line has gone out is logged
    once and leaves the document unclosed, so no client can read a partial
    page as a complete one.
    """
    head = json.dumps(members, ensure_ascii=False, separators=(",", ":"))
    parts = [head[:-1], ',"features":[']
    size = returned = 0
    async with aclosing(features):
        try:
            async for feature in features:
                if returned:
                    parts.append(",")
                parts.append(feature)
                size += len(feature)
                returned += 1
                if size >= _CHUNK_CHARS:
                    yield "".join(parts).encode()
                    parts.clear()
                    size = 0
        except Exception:  # broad: the 200 is sent; leave the body unparseable
            logger.exception(
                "ogc_items_stream_failed", dataset_id=dataset_id, returned=returned
            )
            return
    parts.append(f'],"numberReturned":{returned}}}')
    yield "".join(parts).encode()


class FeatureCollectionStream(StreamingResponse):
    """Streams a FeatureCollection body and always closes its iterator.

    Starlette leaves an abandoned body iterator to the garbage collector, which
    would close the database cursor after the request's session is gone. The
    stream holds a pooled connection while the client reads, so it ends after
    *deadline_seconds* (0 means none), the deadline one statement would get.
    """

    media_type = "application/geo+json"

    def __init__(
        self,
        body: AsyncGenerator[bytes],
        *,
        headers: dict[str, str],
        deadline_seconds: float,
    ) -> None:
        super().__init__(body, headers=headers)
        self._body = body
        self._deadline_seconds = deadline_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            with anyio.move_on_after(self._deadline_seconds or math.inf) as window:
                await super().__call__(scope, receive, send)
            if window.cancelled_caught:
                logger.warning(
                    "ogc_items_stream_deadline",
                    deadline_seconds=self._deadline_seconds,
                )
        finally:
            await self._body.aclose()
