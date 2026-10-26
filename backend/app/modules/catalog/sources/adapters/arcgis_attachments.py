"""Per-layer ``hasAttachments`` and ``relationships`` from an ArcGIS service's
"All Layers and Tables".

The service root lists layers without them; ``<base>/layers`` carries them for
every layer and table in one request. They are optional facts like a feature
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


def _short(value: object, prefix: str) -> str | None:
    """``esriRelCardinalityOneToMany`` -> ``OneToMany``."""
    if not isinstance(value, str) or not value:
        return None
    return value.removeprefix(prefix)


def _relationships(entry: dict) -> list[dict]:
    declared = entry.get("relationships")
    out = []
    for rel in declared if isinstance(declared, list) else []:
        related = rel.get("relatedTableId") if isinstance(rel, dict) else None
        if isinstance(related, bool) or not isinstance(related, int | str):
            continue
        name = rel.get("name")
        out.append(
            {
                "id": rel.get("id") if isinstance(rel.get("id"), int) else None,
                "name": name if isinstance(name, str) and name else None,
                "related_layer_id": related,
                "cardinality": _short(rel.get("cardinality"), "esriRelCardinality"),
                "role": _short(rel.get("role"), "esriRelRole"),
            }
        )
    return out


async def fetch_arcgis_layer_details(
    base_url: str,
    client: httpx.AsyncClient,
    token: str | None = None,
    *,
    current_version: object = None,
) -> tuple[dict[str, bool], dict[str, list[dict]]]:
    """``({layer id: hasAttachments}, {layer id: relationships})`` for the
    entries that state them."""
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
        return {}, {}
    if not isinstance(data, dict) or "error" in data:
        return {}, {}
    flags: dict[str, bool] = {}
    relationships: dict[str, list[dict]] = {}
    for key in ("layers", "tables"):
        entries = data.get(key)
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or isinstance(entry.get("id"), bool):
                continue
            if not isinstance(entry.get("id"), int | str):
                continue
            has = entry.get("hasAttachments")
            if isinstance(has, bool):
                flags[str(entry["id"])] = has
            if found := _relationships(entry):
                relationships[str(entry["id"])] = found
    return flags, relationships


async def fetch_arcgis_attachment_flags(
    base_url: str,
    client: httpx.AsyncClient,
    token: str | None = None,
    *,
    current_version: object = None,
) -> dict[str, bool]:
    """``{layer id: hasAttachments}`` for the entries that state a boolean."""
    flags, _relationships_by_layer = await fetch_arcgis_layer_details(
        base_url, client, token, current_version=current_version
    )
    return flags


def apply_attachment_flags(layers: list[dict], flags: dict[str, bool]) -> list[dict]:
    """Layers with ``has_attachments`` taken from *flags* where it names them."""
    return [
        {**layer, "has_attachments": flags[str(layer["id"])]}
        if str(layer.get("id")) in flags
        else layer
        for layer in layers
    ]


def apply_relationships(
    layers: list[dict], relationships: dict[str, list[dict]]
) -> list[dict]:
    """Layers with ``relationships`` taken from *relationships* where it names them."""
    return [
        {**layer, "relationships": relationships[str(layer["id"])]}
        if str(layer.get("id")) in relationships
        else layer
        for layer in layers
    ]
