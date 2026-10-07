"""Where Titiler reads a raster dataset from, and which mosaics it must not read.

A remote raster is read through the API relay. A mosaic that names a remote
member in its own file can't be, since Titiler would fetch that member itself,
so it is refused.
"""

import posixpath
import uuid
from typing import Protocol

from cachetools import LRUCache
from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring
from fastapi import HTTPException, Request, status

from app.platform.storage.provider import get_storage
from app.platform.storage.raster_relay import is_relay_url
from app.platform.storage.titiler_url import (
    is_managed_open_path,
    resolve_open_path,
    resolve_storage_key,
    resolve_titiler_source,
)

# A select-list column over `catalog.records r`, `catalog.datasets d` and
# `catalog.raster_assets ra`. A mosaic built before its build record existed
# is "unrecorded": only its stored file says what it names.
MEMBER_SOURCES_COLUMN = """jsonb_build_object(
                    'remote', ra.built_from::text ~* '"https?://' OR EXISTS (
                        SELECT 1 FROM catalog.vrt_source_links vsl
                        JOIN catalog.raster_assets m
                            ON m.dataset_id = vsl.source_dataset_id
                        WHERE vsl.vrt_dataset_id = d.id
                          AND m.storage_backend = 'remote'
                    ),
                    'unrecorded',
                    r.record_type = 'vrt_dataset'
                    AND coalesce(jsonb_typeof(ra.built_from), 'null') = 'null',
                    'sha256', ra.sha256
                ) AS member_sources"""

_MAX_VRT_BYTES = 16 * 1024 * 1024
_SOURCE_ELEMENTS = frozenset({"sourcefilename", "sourcedataset"})
_REMOTE_MEMBER_DETAIL = "This mosaic includes a remote raster; rebuild it without one."
# Keyed by the stored file's content hash, so a rebuild is read afresh.
_unrecorded_verdicts: LRUCache[tuple, bool] = LRUCache(maxsize=1024)


class _Source(Protocol):
    asset_uri: str
    member_sources: dict


def _local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1].lower()


def _relative_to_vrt(element) -> bool:
    """How GDAL reads ``relativeToVRT``: absent is false, and any value but
    a spelling of false is true."""
    for name, value in element.attrib.items():
        if _local_name(name) == "relativetovrt":
            return value.strip().lower() not in ("0", "no", "false", "off")
    return False


def _names_only_managed_sources(vrt_xml: bytes, vrt_open_path: str) -> bool:
    """Whether a stored VRT names at least one source and every one of them
    resolves under the managed storage prefix.

    Element and attribute names are compared case-insensitively and without
    a namespace, so no spelling of a source element is skipped.
    """
    try:
        root = fromstring(vrt_xml, forbid_dtd=True)
    except (DefusedXmlException, SyntaxError, ValueError):
        return False
    vrt_dir = posixpath.dirname(vrt_open_path)
    found = False
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        if _local_name(element.tag) not in _SOURCE_ELEMENTS:
            continue
        found = True
        path = (element.text or "").strip()
        if not path or "\\" in path:
            return False
        if _relative_to_vrt(element):
            if ":" in path or path.startswith("/"):
                return False
            path = posixpath.normpath(posixpath.join(vrt_dir, path))
        if not is_managed_open_path(path):
            return False
    return found


async def _unrecorded_mosaic_is_managed(meta: _Source, tenant_id: str | None) -> bool:
    sha256 = meta.member_sources.get("sha256")
    key = (tenant_id, meta.asset_uri, sha256)
    if sha256 is not None and key in _unrecorded_verdicts:
        return _unrecorded_verdicts[key]
    storage = get_storage()
    storage_key = resolve_storage_key(meta.asset_uri, tenant_id=tenant_id)
    try:
        if await storage.size(storage_key) > _MAX_VRT_BYTES:
            verdict = False
        else:
            verdict = _names_only_managed_sources(
                await storage.get(storage_key),
                resolve_open_path(meta.asset_uri, tenant_id=tenant_id),
            )
    except Exception:  # broad: any provider failure leaves the verdict unknown
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tile service unavailable",
        ) from None
    if sha256 is not None:
        _unrecorded_verdicts[key] = verdict
    return verdict


async def titiler_open_path(
    meta: _Source, dataset_id: uuid.UUID, tenant_id: str | None
) -> str:
    """The ``url`` Titiler opens for a dataset: its storage path, prefixed with
    ``tenant_id`` when one is given, or a relay address. A mosaic naming a
    remote member is refused with 409."""
    sources = meta.member_sources
    if sources.get("remote") or (
        sources.get("unrecorded")
        and not await _unrecorded_mosaic_is_managed(meta, tenant_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_REMOTE_MEMBER_DETAIL
        )
    return resolve_titiler_source(
        meta.asset_uri, dataset_id=dataset_id, tenant_id=tenant_id
    )


def open_path_header(request: Request, open_path: str, consumer: object) -> dict:
    """The open-path header for this caller: a relay address is a capability,
    so only the in-process ``consumer`` endpoint sees one."""
    if is_relay_url(open_path) and request.scope.get("endpoint") is not consumer:
        return {}
    return {"X-GeoLens-Asset-OpenPath": open_path}
