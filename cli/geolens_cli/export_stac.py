# SPDX-License-Identifier: Apache-2.0
"""STAC export — fetch a STAC 1.1 item for a raster dataset and render it.

Hand-maintained — NOT regenerated. Pure SDK pass-through (D-25, D-28). The
backend at ``backend/app/standards/stac/router.py`` already produces
conformant STAC 1.1; the CLI is a pretty-printer. Vector datasets are
rejected pre-flight (D-26) so users see a clear message rather than a
confusing 404 or 422 from ``GET /stac/items/{id}``.

OCCLI-06 invariant: zero direct ``httpx`` / ``requests`` imports here —
every HTTP call goes through the generated SDK functions.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import config as _config
from ._sdk_helpers import call_sdk, unwrap


def fetch_record_type(client: Any, dataset_id: str) -> str:
    """Pre-flight check: return the dataset's ``record_type``.

    Per D-26: STAC export is raster-only. We GET ``/datasets/{id}`` first
    to avoid a confusing error from ``/stac/items/{id}`` when the dataset
    is vector-typed.

    Returns:
        The literal string ``"not_found"`` on a 404 (so the caller can
        emit a friendly "Dataset not found" message and exit 1). For all
        other non-200 statuses, ``unwrap`` translates to the appropriate
        ``typer.Exit`` (auth/server/generic). On success, returns the
        ``record_type`` string from ``DatasetResponse``
        (e.g., ``"raster_dataset"``, ``"vector_dataset"``).
    """
    from geolens_sdk.api.datasets import (
        get_single_dataset_datasets_dataset_id_get,
    )

    resp = call_sdk(
        get_single_dataset_datasets_dataset_id_get.sync_detailed,
        dataset_id=dataset_id,
        client=client,
    )
    sc = int(resp.status_code)
    if sc == 404:
        return "not_found"
    if sc != 200:
        # Let unwrap() translate the error → exit code (401/403/5xx/etc.)
        unwrap(resp, expected=200)

    rec = getattr(resp.parsed, "record_type", None)
    if rec is None:
        # Defensive: try alternate field names if the OpenAPI shape changes.
        rec = (
            getattr(resp.parsed, "type", None)
            or getattr(resp.parsed, "dataset_type", None)
        )
    return str(rec) if rec else "unknown"


def is_raster(record_type: str) -> bool:
    """True iff ``record_type`` looks like a raster dataset.

    Defensive: backend may use ``raster_dataset``, ``RasterDataset``, or
    bare ``raster``. We accept any of these so a future rename of the
    enum doesn't silently break the CLI guard.
    """
    if not record_type:
        return False
    return record_type.lower().startswith("raster")


def fetch_stac_item(client: Any, dataset_id: str) -> dict:
    """Fetch the STAC item dict for a dataset.

    Caller pre-checks ``record_type`` via :func:`fetch_record_type` so
    this function assumes the dataset is raster-typed.

    The SDK's ``get_item_stac`` is generated with ``Any`` as the 200
    response type (the OpenAPI schema declares the response as a free-
    form dict). The parsed body is therefore the STAC item dict directly
    — no ``.to_dict()`` needed.

    Defensive shape handling (in case future SDK regen wraps the body
    in a generated model):
      * If ``parsed`` is None, json-load ``resp.content``.
      * If ``parsed`` has ``.to_dict()``, call it.
      * If ``parsed`` is already a dict, return it.
    """
    from geolens_sdk.api.stac import get_item_stac_items_item_id_get

    resp = call_sdk(
        get_item_stac_items_item_id_get.sync_detailed,
        item_id=dataset_id,
        client=client,
    )
    item = unwrap(resp, expected=200)
    if item is None:
        return json.loads(resp.content.decode("utf-8"))
    if isinstance(item, dict):
        return item
    if hasattr(item, "to_dict"):
        return item.to_dict()
    # Unknown shape — best-effort fall back to the raw response body.
    return json.loads(resp.content.decode("utf-8"))


def render_stac_json(item: dict, *, compact: bool = False) -> str:
    """Format a STAC dict as JSON.

    Default (D-27): pretty-printed, ``indent=2``, sorted keys, trailing
    newline — produces diff-stable output.

    Compact: single-line JSON with no whitespace separators — for piping
    into ``jq`` or ``curl --data``.
    """
    if compact:
        return json.dumps(item, sort_keys=True, separators=(",", ":"))
    return json.dumps(item, indent=2, sort_keys=True) + "\n"


def write_stac_to_file(item: dict, path: Path, *, compact: bool = False) -> None:
    """Atomically write the rendered STAC JSON to ``path``.

    Mode 0o644 — STAC payloads are not secrets. The atomic ``tempfile +
    os.replace`` write prevents half-written files on Ctrl+C (D-27).
    """
    _config.atomic_write_text(
        path,
        render_stac_json(item, compact=compact),
        mode=0o644,
    )


def vector_rejection_message(record_type: str) -> str:
    """User-facing rejection message for non-raster datasets (D-26)."""
    return (
        "STAC export is supported for raster datasets only — "
        f"got record_type={record_type}"
    )
