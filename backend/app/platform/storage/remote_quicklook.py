"""Quicklook PNGs for a remote raster, drawn by Titiler through the raster relay.

An ingested raster's quicklooks are drawn from its local file. A remote COG is
never opened in-process, so Titiler draws them from the same relay address it
reads the COG's tiles and metadata through, and they are stored under the
dataset's ``rasters/{id}/`` prefix like an ingested raster's.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlencode

import httpx
import structlog

from app.platform.storage.raster_relay import relay_url
from app.platform.storage.titiler_url import (
    RemoteRasterPathError,
    build_titiler_cog_url,
    resolve_current_storage_key,
)

logger = structlog.get_logger(__name__)

# The timeout one Titiler read already has in fetch_cog_info. Every draw a
# request or refresh makes shares one deadline this far out, however many
# items it covers.
DRAW_BUDGET_S = 15.0
_CONCURRENCY = 10
_SIZES = (256, 512)
_MAX_PNG_BYTES = 4 * 1024 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# The tile proxy's ceilings, for a band whose statistics were never read.
_DTYPE_MAX = {
    "uint16": 65535,
    "uint32": 4294967295,
    "int8": 127,
    "int16": 32767,
    "int32": 2147483647,
    "float32": 1.0,
    "float64": 1.0,
}


class _NotDrawn(Exception):
    def __init__(self, reason: str, status: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _render_query(described: Mapping[str, Any]) -> list[tuple[str, str]]:
    """``bidx``/``rescale`` pairs choosing the bands the tile proxy renders.

    Each band is stretched over its own probed min/max, as an ingested
    quicklook is stretched over its pixels, and over its dtype's range when
    no statistics were read.
    """
    band_count = described.get("band_count") or 1
    bands = (1, 2, 3) if band_count >= 3 else (1,)
    query = [("bidx", str(band)) for band in bands] if band_count >= 2 else []
    dtype = str(described.get("dtype") or "uint8").lower()
    if dtype == "uint8":
        return query
    band_info = described.get("band_info")
    band_info = band_info if isinstance(band_info, list) else []
    for band in bands:
        stats = band_info[band - 1] if len(band_info) >= band else None
        low = stats.get("min") if isinstance(stats, dict) else None
        high = stats.get("max") if isinstance(stats, dict) else None
        if _finite(low) and _finite(high) and high > low:
            query.append(("rescale", f"{low},{high}"))
        else:
            query.append(("rescale", f"0,{_DTYPE_MAX.get(dtype, 65535)}"))
    return query


async def _draw(
    client: httpx.AsyncClient, source: str, size: int, render: str
) -> bytes:
    response = await client.get(
        build_titiler_cog_url(
            "preview.png",
            query={"url": source, "max_size": str(size)},
            raw_query_suffix=render,
        )
    )
    if response.status_code != 200:
        raise _NotDrawn("titiler_status", response.status_code)
    body = response.content
    if not body.startswith(_PNG_SIGNATURE) or len(body) > _MAX_PNG_BYTES:
        raise _NotDrawn("not_a_png")
    return body


async def _store(dataset_id: uuid.UUID, pngs: Mapping[int, bytes]) -> tuple[str, str]:
    """Write both PNGs under a fresh prefix; return their logical keys.

    A fresh prefix per draw changes ``quicklook_version``, so a card that
    showed the previous image fetches the new one.
    """
    from app.platform.storage import get_storage

    base = f"rasters/{dataset_id}/remote-quicklook-{uuid.uuid4().hex[:12]}"
    keys = tuple(f"{base}/quicklook_{size}.png" for size in _SIZES)
    storage = get_storage()
    written: list[str] = []
    try:
        for key, size in zip(keys, _SIZES, strict=True):
            physical = resolve_current_storage_key(key)
            # Recorded before the put: a cancelled put may still land.
            written.append(physical)
            await storage.put(physical, pngs[size])
    except BaseException as exc:
        await _delete_physical(written)
        if isinstance(exc, Exception):
            raise _NotDrawn("storage_failed") from exc
        raise
    return keys[0], keys[1]


async def _delete_physical(physical_keys: list[str]) -> None:
    from app.platform.storage.reap import delete_objects_best_effort

    await delete_objects_best_effort(physical_keys, "remote_quicklook_delete_failed")


async def _draw_one(
    dataset_id: uuid.UUID, url: str, described: Mapping[str, Any], deadline: float
) -> tuple[str, str] | None:
    reason, status = "draw_failed", None
    try:
        async with asyncio.timeout_at(deadline):
            source = relay_url(url, dataset_id)
            render = urlencode(_render_query(described))
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(DRAW_BUDGET_S, connect=5.0)
            ) as client:
                pngs = {
                    size: await _draw(client, source, size, render) for size in _SIZES
                }
            return await _store(dataset_id, pngs)
    except TimeoutError:
        reason = "timeout"
    except _NotDrawn as exc:
        reason, status = exc.reason, exc.status
    except RemoteRasterPathError:
        reason = "source_refused"
    except httpx.HTTPError:
        reason = "titiler_unreachable"
    except Exception:  # broad: a failed draw leaves the dataset without a quicklook, never fails its import
        pass
    # The URL stays out of the log: it can carry a presigned query.
    logger.warning(
        "remote_quicklook_not_drawn",
        reason=reason,
        status=status,
        dataset_id=str(dataset_id),
    )
    return None


async def draw_remote_quicklooks(
    targets: Mapping[uuid.UUID, tuple[str, Mapping[str, Any]]],
) -> dict[uuid.UUID, tuple[str, str]]:
    """Draw and store the 256 and 512 px quicklooks of each remote raster.

    ``targets`` maps a dataset id to its asset URL and the description
    ``fetch_cog_info`` returned for it. Returns the logical ``(256, 512)``
    keys of every pair stored within ``DRAW_BUDGET_S`` of the call; a draw
    that failed or ran out of time is logged once with a reason code, leaves
    nothing stored, and is absent from the result.

    Each URL has already passed the SSRF guard (import validates it, and
    refresh draws only an href its safe-client probe reached); the relay then
    checks and pins every connection Titiler's read makes.
    """
    deadline = asyncio.get_running_loop().time() + DRAW_BUDGET_S
    gate = asyncio.Semaphore(_CONCURRENCY)

    async def bounded(dataset_id: uuid.UUID, url: str, described: Mapping[str, Any]):
        async with gate:
            return dataset_id, await _draw_one(dataset_id, url, described, deadline)

    drawn = await asyncio.gather(
        *(bounded(dataset_id, *target) for dataset_id, target in targets.items())
    )
    return {dataset_id: keys for dataset_id, keys in drawn if keys is not None}


async def discard_remote_quicklooks(keys: Iterable[str]) -> None:
    """Delete stored quicklooks by logical key; failures are logged, never raised."""
    await _delete_physical([resolve_current_storage_key(key) for key in keys])
