"""Per-layer ``hasAttachments``, ``relationships`` and the layer properties an
import doesn't carry (time settings, subtypes, M values, time-only and
timestamp-offset fields) from an ArcGIS service's "All Layers and Tables".

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
        rel_id, name = rel.get("id"), rel.get("name")
        out.append(
            {
                "id": rel_id
                if isinstance(rel_id, int) and not isinstance(rel_id, bool)
                else None,
                "name": name if isinstance(name, str) and name else None,
                "related_layer_id": related,
                "cardinality": _short(rel.get("cardinality"), "esriRelCardinality"),
                "role": _short(rel.get("role"), "esriRelRole"),
            }
        )
    return out


def _field_names(entry: dict, esri_type: str) -> list[str]:
    fields = entry.get("fields")
    return [
        f["name"]
        for f in (fields if isinstance(fields, list) else [])
        if isinstance(f, dict)
        and f.get("type") == esri_type
        and isinstance(f.get("name"), str)
        and f["name"]
    ]


def _uncarried(entry: dict) -> dict:
    """The layer properties an import doesn't carry that *entry* states."""
    found: dict = {}
    time_info = entry.get("timeInfo")
    if isinstance(time_info, dict):
        found["time_fields"] = [
            name
            for key in ("startTimeField", "endTimeField")
            if isinstance(name := time_info.get(key), str) and name
        ]
    # Subtypes appear as subtypeField + subtypes, or as typeIdField + types
    # (feature types); a field with an empty list declares none.
    for field_key, list_key in (("subtypeField", "subtypes"), ("typeIdField", "types")):
        subtype_field, subtypes = entry.get(field_key), entry.get(list_key)
        if (
            isinstance(subtype_field, str)
            and subtype_field
            and (isinstance(subtypes, list) and subtypes)
        ):
            found["subtype_field"] = subtype_field
            break
    if isinstance(entry.get("hasM"), bool):
        found["has_m"] = entry["hasM"]
    for key, esri_type in (
        ("time_only_fields", "esriFieldTypeTimeOnly"),
        ("timestamp_offset_fields", "esriFieldTypeTimestampOffset"),
    ):
        if names := _field_names(entry, esri_type):
            found[key] = names
    return found


async def fetch_arcgis_layer_details(
    base_url: str,
    client: httpx.AsyncClient,
    token: str | None = None,
    *,
    current_version: object = None,
) -> dict[str, dict]:
    """``{layer id: {"has_attachments": bool, "relationships": [...], ...}}``
    with the properties ``_uncarried`` reads, each key present only where the
    entry states it."""
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
    details: dict[str, dict] = {}
    for key in ("layers", "tables"):
        entries = data.get(key)
        for entry in entries if isinstance(entries, list) else []:
            layer_id = entry.get("id") if isinstance(entry, dict) else None
            if isinstance(layer_id, bool) or not isinstance(layer_id, int | str):
                continue
            found: dict = {}
            if isinstance(entry.get("hasAttachments"), bool):
                found["has_attachments"] = entry["hasAttachments"]
            if relationships := _relationships(entry):
                found["relationships"] = relationships
            found.update(_uncarried(entry))
            if found:
                details[str(layer_id)] = found
    return details


def apply_layer_details(layers: list[dict], details: dict[str, dict]) -> list[dict]:
    """Layers with the attachment flag, relationships and properties *details*
    states."""
    return [
        {**layer, **details[str(layer.get("id"))]}
        if str(layer.get("id")) in details
        else layer
        for layer in layers
    ]
