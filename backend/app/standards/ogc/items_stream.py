"""A streamed OGC API Features items response."""

import json
import math
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence

import anyio
import structlog
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

logger = structlog.stdlib.get_logger(__name__)

# Body text gathered before each send, so a page goes out in a few hundred
# writes rather than one per feature.
_CHUNK_CHARS = 64 * 1024


class _StreamFailed(Exception):
    """A body failure already logged, which must not complete the response."""


async def feature_collection_body(
    members: dict,
    first_batch: list[str],
    batches: Sequence[Sequence[int]],
    read_batch: Callable[[Sequence[int]], Awaitable[list[str]]],
    *,
    dataset_id: str,
) -> AsyncGenerator[bytes]:
    """Write *members*, the features, then ``numberReturned``.

    *first_batch* was read before the status line, so the first chunk always
    carries features; each of *batches* is read once the one before it has
    been written. ``numberReturned`` follows the features so that it counts
    the features actually written.
    """
    head = json.dumps(members, ensure_ascii=False, separators=(",", ":"))
    parts = [head[:-1], ',"features":[']
    size = returned = 0
    features = first_batch
    remaining = iter(batches)
    while True:
        for feature in features:
            if returned:
                parts.append(",")
            parts.append(feature)
            size += len(feature)
            returned += 1
            if size >= _CHUNK_CHARS:
                yield "".join(parts).encode()
                parts.clear()
                size = 0
        gids = next(remaining, None)
        if gids is None:
            break
        # Written before the next read, so a failed read never follows an
        # empty body and no batch waits in memory behind another.
        yield "".join(parts).encode()
        parts.clear()
        size = 0
        features = []
        try:
            features = await read_batch(gids)
        except Exception as exc:  # broad: the 200 is sent; log once, cut the body
            logger.exception(
                "ogc_items_stream_failed", dataset_id=dataset_id, returned=returned
            )
            raise _StreamFailed from exc
    parts.append(f'],"numberReturned":{returned}}}')
    yield "".join(parts).encode()


class FeatureCollectionStream(StreamingResponse):
    """Streams a FeatureCollection body and always closes its iterator.

    The body holds a pooled connection while the client reads, so it ends
    after *deadline_seconds* (0 means none), the deadline one statement would
    get. A failed or cut-off body never sends its final message, so a gzip
    response stays unterminated; the iterator is closed here rather than left
    to the garbage collector after the request's session is gone.
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
        except _StreamFailed:
            pass
        finally:
            await self._body.aclose()
