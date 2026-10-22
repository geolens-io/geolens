"""Per-layer ``hasAttachments`` from an ArcGIS service's "All Layers and Tables".

The service root lists layers without it; ``<base>/layers`` carries it for
every layer and table in one request. It is an optional fact like a feature
count: any failure leaves the probe's layers as they were.
"""

import asyncio
from urllib.parse import urlencode

import httpx

from app.modules.catalog.sources.adapters.arcgis import read_arcgis_json
from app.platform.service_endpoints import (
    DEFAULT_CHECK_TIMEOUT,
    EndpointCheckFailedError,
)


def _layers_url(base_url: str):
    def build(query_token: str | None) -> str:
        params = {"f": "json", **({"token": query_token} if query_token else {})}
        return f"{base_url.rstrip('/')}/layers?{urlencode(params)}"

    return build


async def fetch_arcgis_attachment_flags(
    base_url: str,
    client: httpx.AsyncClient,
    token: str | None = None,
    *,
    current_version: object = None,
) -> dict[str, bool]:
    """``{layer id: hasAttachments}`` for the entries that state a boolean."""
    try:
        async with asyncio.timeout(DEFAULT_CHECK_TIMEOUT):
            data = await read_arcgis_json(
                client, _layers_url(base_url), token, current_version=current_version
            )
    except (
        httpx.HTTPStatusError,
        httpx.TransportError,
        EndpointCheckFailedError,
        TimeoutError,
        ValueError,
        KeyError,
    ):
        # `SSRFError` is a `ValueError`: a refused redirect degrades like any
        # other failure of this optional read.
        return {}
    if not isinstance(data, dict) or "error" in data:
        return {}
    flags: dict[str, bool] = {}
    for key in ("layers", "tables"):
        entries = data.get(key)
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or isinstance(entry.get("id"), bool):
                continue
            has = entry.get("hasAttachments")
            if isinstance(entry.get("id"), int | str) and isinstance(has, bool):
                flags[str(entry["id"])] = has
    return flags


def apply_attachment_flags(layers: list[dict], flags: dict[str, bool]) -> list[dict]:
    """Layers with ``has_attachments`` taken from *flags* where it names them."""
    return [
        {**layer, "has_attachments": flags[str(layer["id"])]}
        if str(layer.get("id")) in flags
        else layer
        for layer in layers
    ]
