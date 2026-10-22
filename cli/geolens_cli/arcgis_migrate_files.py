# SPDX-License-Identifier: Apache-2.0
"""The ``import_file`` action of `geolens arcgis migrate`.

Hand-maintained. Downloads a data file item (CSV, GeoJSON, Shapefile or File
Geodatabase) from the plan's portal into a fresh temporary directory, uploads
it to GeoLens, previews and commits it, and waits for the ingest job. The
download is bounded by the instance's ``upload_max_size_mb``. The portal is the
only host the file is read from; GeoLens receives it from the CLI.
"""

from __future__ import annotations

import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

from ._sdk_helpers import long_request_timeout
from . import publish as _publish
from .arcgis_migrate_layers import (
    _ALREADY_COMMITTED,
    _JobEnded,
    _JobGone,
    _apply_target,
    _commit_body,
    _title,
    _wait_for_dataset,
)
from .arcgis_migrate_session import (
    GeoLensError,
    ItemFailed,
    ItemResult,
    MigrationContext,
    StopRun,
)
from .arcgis_migrate_state import SKIPPED, ItemState
from .arcgis_portal import PortalError

# ArcGIS item type -> the extension GeoLens recognises the file by.
EXTENSIONS = {
    "CSV": ".csv",
    "GeoJson": ".geojson",
    "Shapefile": ".zip",
    "File Geodatabase": ".zip",
}
# The backend's default upload_max_size_mb, used when the setting is unreadable.
DEFAULT_LIMIT_MB = 500
# The single-layer upload job, until it yields its dataset.
JOB_KEY = "file"
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_TOKEN_STATUSES = (498, 499)


def _limit(ctx: MigrationContext) -> int:
    """The instance's upload size limit in bytes, read once as the operator."""
    if ctx.upload_limit is None:
        from geolens.api.admin import get_all_settings_settings_all_get as get_settings

        megabytes = DEFAULT_LIMIT_MB
        try:
            settings = ctx.geolens.call(get_settings.sync_detailed)
        except GeoLensError:
            settings = None
        if settings is not None:
            for items in settings.tabs.additional_properties.values():
                for setting in items:
                    value = setting.value
                    if (
                        setting.key == "upload_max_size_mb"
                        and isinstance(value, int)
                        and not isinstance(value, bool)
                        and value > 0
                    ):
                        megabytes = value
        ctx.upload_limit = megabytes * 1024 * 1024
    return ctx.upload_limit


def _megabytes(size: int) -> str:
    return f"{size / (1024 * 1024):.1f} MB"


def _filename(item: Mapping[str, Any], extension: str) -> str:
    stem = _UNSAFE.sub("_", item["title"]).strip("._-")[:80] or item["id"]
    return stem + extension


def _download(ctx: MigrationContext, item_id: str, dest: Path, limit: int) -> int | str:
    """Fetch the item's data into *dest*: its size, or the reason it was
    skipped. ``ItemFailed`` / ``StopRun`` when the portal refuses."""
    client = ctx.portal.client if ctx.portal is not None else None
    if client is None:
        raise ItemFailed("the run has no connection to the ArcGIS portal")
    try:
        return client.download(f"content/items/{item_id}/data", dest, limit)
    except PortalError as exc:
        if exc.kind == "too_large":
            return f"larger than the instance's upload limit of {_megabytes(limit)}"
        if exc.http_status in _TOKEN_STATUSES:
            raise StopRun(
                f"the portal refused the ArcGIS token ({exc}); it may have "
                "expired. Rerun with a fresh token to resume."
            ) from None
        raise ItemFailed(f"downloading the data file failed, {exc}") from None


def _upload(ctx: MigrationContext, path: Path, title: str) -> UUID:
    try:
        upload = ctx.geolens.call(
            _publish.upload_file,
            expected=_publish.UPLOAD_OK_STATUS,
            path=path,
        )
    except GeoLensError as exc:
        if exc.status in (413, 422):
            raise ItemFailed(f"{title}: GeoLens refused the upload, {exc}") from None
        raise ItemFailed(f"{title}: upload failed, {exc}") from None
    return upload.job_id


def _preview(ctx: MigrationContext, job_id: UUID, title: str) -> Any:
    from geolens.api.datasets import preview_file_ingest_preview_job_id_post as preview

    try:
        with long_request_timeout(ctx.geolens.client):
            return ctx.geolens.call(preview.sync_detailed, job_id=job_id)
    except GeoLensError as exc:
        raise ItemFailed(f"{title}: preview failed, {exc}") from None


def _layer_names(preview: Any) -> list[str]:
    layers = preview.layers
    if not isinstance(layers, list):
        return []
    return [layer.name for layer in layers]


def _geometry_columns(preview: Any) -> dict[str, Any]:
    """The x, y or WKT columns the preview detected in a CSV, or nothing."""
    detected = preview.detected_geometry_columns
    if not hasattr(detected, "to_dict"):
        return {}
    columns = detected.to_dict()
    found = {
        "x_column": columns.get("x_column"),
        "y_column": columns.get("y_column"),
        "geom_column": columns.get("wkt_column"),
    }
    return {name: value for name, value in found.items() if value}


def _commit(
    ctx: MigrationContext, job_id: UUID, title: str, visibility: str, extra: Mapping
) -> None:
    from geolens.api.datasets import commit_import_ingest_commit_job_id_post as commit

    body = _commit_body(title, visibility)
    for name, value in extra.items():
        setattr(body, name, value)
    try:
        ctx.geolens.call(commit.sync_detailed, job_id=job_id, body=body, expected=202)
    except GeoLensError as exc:
        if exc.status in (400, 409) and _ALREADY_COMMITTED in str(exc):
            return
        if exc.status == 404:
            raise _JobGone(f"{title}: the import job {job_id} is gone") from None
        raise ItemFailed(f"{title}: commit failed, {exc}") from None


def _fan_out(
    ctx: MigrationContext,
    job_id: UUID,
    layers: list[str],
    base: str,
    visibility: str,
    entry: ItemState,
) -> list[str]:
    """Import each layer of a multi-layer file as its own dataset."""
    from geolens.api.datasets import (
        commit_fan_out_ingest_commit_fan_out_job_id_post as fan_out,
    )
    from geolens.models.fan_out_commit_request import FanOutCommitRequest
    from geolens.models.fan_out_layer_request import FanOutLayerRequest

    titles = {name: _title(base, name) for name in layers}
    request = FanOutCommitRequest(
        layers=[FanOutLayerRequest(layer_name=n, title=titles[n]) for n in layers]
    )
    try:
        with long_request_timeout(ctx.geolens.client):
            result = ctx.geolens.call(
                fan_out.sync_detailed, job_id=job_id, body=request, expected=202
            )
    except GeoLensError as exc:
        raise ItemFailed(f"{base}: commit failed, {exc}") from None
    failures = []
    for layer in result.results:
        if layer.dataset_id and layer.status == "queued":
            entry.layer_datasets[layer.layer_name] = str(layer.dataset_id)
        else:
            failures.append(f"{layer.layer_name}: {layer.error or layer.status}")
    entry.dataset_ids = list(dict.fromkeys(entry.layer_datasets.values()))
    ctx.save()
    if not entry.layer_datasets:
        raise ItemFailed(f"{base}: {'; '.join(failures)}")
    for name, dataset in entry.layer_datasets.items():
        _apply_target(ctx, dataset, _commit_body(titles[name], visibility))
    return [f"layer not imported, {failure}" for failure in failures]


def _upload_fresh(
    ctx: MigrationContext,
    item: Mapping[str, Any],
    extension: str,
    limit: int,
) -> tuple[UUID | None, str | None]:
    """Download and upload the item's file: the job id, or why it was skipped."""
    with tempfile.TemporaryDirectory(prefix="geolens-arcgis-") as tmp:
        path = Path(tmp) / _filename(item, extension)
        outcome = _download(ctx, item["id"], path, limit)
        if isinstance(outcome, str):
            return None, outcome
        return _upload(ctx, path, item["title"]), None


def _finish_recorded(
    ctx: MigrationContext, job_id: UUID, title: str, visibility: str
) -> str | None:
    """The dataset of a job an earlier run uploaded, or None when the file must
    be uploaded again."""
    try:
        _commit(ctx, job_id, title, visibility, {})
        return _wait_for_dataset(ctx, job_id, title)
    except (_JobEnded, _JobGone):
        return None
    except GeoLensError as exc:
        if exc.status == 404:
            return None
        raise ItemFailed(f"{title}: {exc}") from None


def import_file(
    ctx: MigrationContext, item: Mapping[str, Any], entry: ItemState
) -> ItemResult:
    """Import a data file item as one dataset, or one per layer for a file
    holding several.

    The upload job is recorded before the commit, so a rerun after a crash
    resumes that job instead of uploading the file again. An item over the
    instance's size limit is skipped with its size; a quota refusal fails it.
    """
    extension = EXTENSIONS.get(item["type"])
    if extension is None:
        return ItemResult(
            status=SKIPPED,
            notes=[
                f"{item['type']} items hold ArcGIS JSON, not a file GeoLens can "
                "read; export the layer to a file and upload it"
            ],
        )
    row = ctx.inventory.get(item["id"])
    if row is None:
        raise ItemFailed("the item is not in the inventory the plan was built from")
    base = item["target"]["title"] or item["title"]
    visibility = item["target"]["visibility"]
    limit = _limit(ctx)
    if entry.layer_datasets:
        many = len(entry.layer_datasets) > 1
        for name, dataset in entry.layer_datasets.items():
            title = _title(base, name if many else None)
            _apply_target(ctx, dataset, _commit_body(title, visibility))
        return ItemResult()

    size = row.get("size_bytes")
    if isinstance(size, int) and size > limit:
        return ItemResult(
            status=SKIPPED,
            notes=[
                f"skipped: the file is {_megabytes(size)}, over the instance's "
                f"upload limit of {_megabytes(limit)}"
            ],
        )
    notes: list[str] = []
    recorded = entry.layer_jobs.get(JOB_KEY)
    if recorded:
        dataset = _finish_recorded(ctx, UUID(recorded), base, visibility)
        del entry.layer_jobs[JOB_KEY]
        ctx.save()
        if dataset is not None:
            _apply_target(ctx, dataset, _commit_body(base, visibility))
            entry.layer_datasets[JOB_KEY] = dataset
            entry.dataset_ids = [dataset]
            return ItemResult()

    job_id, skipped = _upload_fresh(ctx, item, extension, limit)
    if job_id is None:
        return ItemResult(status=SKIPPED, notes=[f"skipped: {skipped}"])
    entry.job_ids.append(str(job_id))
    entry.layer_jobs[JOB_KEY] = str(job_id)
    ctx.save()
    preview = _preview(ctx, job_id, base)
    layers = _layer_names(preview)
    if len(layers) > 1:
        _fan_out(ctx, job_id, layers, base, visibility, entry)
        del entry.layer_jobs[JOB_KEY]
        return ItemResult(
            notes=[f"the file holds {len(layers)} layers; one dataset each"]
        )
    columns = _geometry_columns(preview)
    if item["type"] == "CSV" and not columns and preview.geometry_type is None:
        notes.append("no geometry column found; imported as a table")
    _commit(ctx, job_id, base, visibility, columns)
    dataset = _wait_for_dataset(ctx, job_id, base)
    del entry.layer_jobs[JOB_KEY]
    entry.layer_datasets[JOB_KEY] = dataset
    entry.dataset_ids = [dataset]
    return ItemResult(notes=notes)
