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
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

from ._sdk_helpers import EXTENDED_REQUEST_TIMEOUT_SECONDS, long_request_timeout
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
FILE_TYPES = frozenset(EXTENSIONS)
# The most layers one fan-out commit accepts.
MAX_FAN_OUT_LAYERS = 50
# The backend's default upload_max_size_mb, used when the setting is unreadable.
DEFAULT_LIMIT_MB = 500
# The single-layer upload job, until it yields its dataset.
JOB_KEY = "file"
# State keys of a fan-out's layers carry this prefix, so a layer can't collide
# with JOB_KEY whatever its name.
# Upload-job states in which a fan-out is known to have queued no child.
_CHILDLESS = frozenset({"cancelled", "failed"})
# How long after sending a fan-out a failed or cancelled upload job may still
# be read as having queued nothing: the request's own timeout (the same
# constant the request is sent with), then the server's grace before its sweep
# fails a stale dispatch, then a margin.
_SERVER_SWEEP_GRACE = 300.0
_SETTLE_MARGIN = 60.0
FAN_OUT_SETTLE = EXTENDED_REQUEST_TIMEOUT_SECONDS + _SERVER_SWEEP_GRACE + _SETTLE_MARGIN
LAYER_PREFIX = "layer:"
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


class _Skipped(Exception):
    """The item is left for the operator; the message is the reason."""


def _download(ctx: MigrationContext, item_id: str, dest: Path, limit: int) -> None:
    """Fetch the item's data into *dest*. ``_Skipped`` when it is over *limit*;
    ``ItemFailed`` / ``StopRun`` when the portal refuses."""
    client = ctx.portal.client if ctx.portal is not None else None
    if client is None:
        raise ItemFailed("the run has no connection to the ArcGIS portal")
    try:
        client.download(f"content/items/{item_id}/data", dest, limit)
    except PortalError as exc:
        if exc.kind == "too_large":
            raise _Skipped(
                f"the file is over the instance's upload limit of {_megabytes(limit)}"
            ) from None
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
    # Recorded before the request goes out: if its answer is lost, a rerun
    # knows this job was fanned out and does not upload the file again.
    entry.fan_out = {
        "job": str(job_id),
        "layers": layers,
        "titles": [titles[name] for name in layers],
        "sent_at": _wall_clock(),
    }
    ctx.save()
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
    # Every layer that is not imported is recorded in the item's notes as soon
    # as it is known, so no later failure or resume loses it.
    entry.notes = []
    for layer in result.results:
        if layer.new_job_id and layer.status == "queued":
            entry.layer_jobs[_layer_key(layer.layer_name)] = str(layer.new_job_id)
        else:
            entry.notes.append(
                f"layer not imported, {layer.layer_name}: {layer.error or layer.status}"
            )
    ctx.save()
    unknown = _wait_for_layers(ctx, entry, base)
    if not entry.layer_datasets:
        if not unknown:
            # Every outcome is known and none imported, so a rerun uploads
            # afresh. A job GeoLens no longer has leaves the outcome unknown,
            # so the record stays and the rerun does not upload again.
            entry.fan_out = None
            ctx.save()
        raise ItemFailed(f"{base}: {'; '.join(entry.notes)}")
    for name, dataset in entry.layer_datasets.items():
        _apply_target(ctx, dataset, _commit_body(titles[_layer_name(name)], visibility))
    return list(entry.notes)


def _resume_fan_out(
    ctx: MigrationContext, entry: ItemState, base: str, visibility: str
) -> ItemResult | None:
    """Carry on a fan-out an earlier run sent but never saw the answer to.

    GeoLens refuses a second fan-out of a job it already fanned out, and the
    child jobs can only be learned from the answer. A job still pending was
    never accepted and is sent again; any other state means the layers were
    queued, so the item fails, without uploading the file again, naming the
    datasets to look for. A job that ended cancelled or failed queued none, so
    the item is imported afresh (None).
    """
    from geolens.api.admin import get_job_status_jobs_job_id_get as get_job

    job_id = UUID(entry.fan_out["job"])
    layers = list(entry.fan_out["layers"])
    try:
        status = str(ctx.geolens.call(get_job.sync_detailed, job_id=job_id).status)
    except GeoLensError as exc:
        if exc.status != 404:
            raise ItemFailed(f"{base}: {exc}") from None
        status = "gone"
    if status == "pending":
        failed = _fan_out(ctx, job_id, layers, base, visibility, entry)
        return ItemResult(
            notes=[f"the file holds {len(layers)} layers, one dataset each", *failed]
        )
    wait = FAN_OUT_SETTLE - (_wall_clock() - entry.fan_out.get("sent_at", 0.0))
    if status in _CHILDLESS and wait > 0:
        # A request that was lost may still be running on the server, and the
        # stale-job sweep can fail the parent while it goes on queuing children.
        raise ItemFailed(
            f"{base}: the layers were sent {int((FAN_OUT_SETTLE - wait) // 60)} "
            f"minutes ago and GeoLens may still be queuing them (the upload job "
            f"is {status}); rerun in {int(wait // 60) + 1} minutes"
        )
    if status in _CHILDLESS:
        # The job ended without queuing a child (cancelled, expired, or the
        # dispatch was interrupted), so no dataset exists: import afresh.
        entry.fan_out = None
        ctx.save()
        return None
    # The titles as sent, not rebuilt from a plan that may have been edited.
    sent = entry.fan_out.get("titles") or [_title(base, name) for name in layers]
    titles = ", ".join(repr(title) for title in sent)
    raise ItemFailed(
        f"{base}: the layers were sent to GeoLens but the answer was lost, so "
        f"their datasets can't be linked (the upload job is {status}). Look for "
        f'datasets titled {titles}; delete them and remove "fan_out" from this '
        "item in the state file to import again, or set the item to skip."
    )


def _wall_clock() -> float:
    return time.time()


def _layer_key(name: str) -> str:
    return LAYER_PREFIX + name


def _layer_name(key: str) -> str:
    return key.removeprefix(LAYER_PREFIX)


def _wait_for_layers(ctx: MigrationContext, entry: ItemState, base: str) -> int:
    """Wait for the fan-out jobs an earlier call queued and pin their datasets.
    A job that ended without a dataset becomes a note on the item.

    Returns how many jobs GeoLens no longer had, whose outcome is unknown, and
    remembers that in the fan-out record. When the last job ends and every
    outcome is known to be a failure with no dataset, the record is cleared in
    the same save that drops that job's pin, so a rerun imports afresh.
    """
    unknown = 0
    names = [n for n in entry.layer_jobs if n.startswith(LAYER_PREFIX)]
    for position, name in enumerate(names):
        try:
            entry.layer_datasets[name] = _wait_for_dataset(
                ctx, UUID(entry.layer_jobs[name]), _title(base, _layer_name(name))
            )
        except _JobEnded as exc:
            entry.notes.append(f"layer not imported, {exc}")
        except GeoLensError as exc:
            if exc.status != 404:
                raise ItemFailed(f"{_layer_name(name)}: {exc}") from None
            # GeoLens no longer has the job: note the layer and go on, so the
            # siblings are not held up by it on every rerun.
            unknown += 1
            if entry.fan_out is not None:
                entry.fan_out["unknown"] = True
            entry.notes.append(
                f"layer not imported, {_layer_name(name)}: its import job is gone"
            )
        del entry.layer_jobs[name]
        entry.dataset_ids = list(dict.fromkeys(entry.layer_datasets.values()))
        if (
            position == len(names) - 1
            and not entry.layer_datasets
            and not (entry.fan_out or {}).get("unknown")
        ):
            entry.fan_out = None
        ctx.save()
    return unknown


def _upload_fresh(
    ctx: MigrationContext, item: Mapping[str, Any], extension: str, limit: int
) -> UUID:
    """Download and upload the item's file, returning the upload job."""
    with tempfile.TemporaryDirectory(prefix="geolens-arcgis-") as tmp:
        path = Path(tmp) / _filename(item, extension)
        _download(ctx, item["id"], path, limit)
        return _upload(ctx, path, item["title"])


def _finish_recorded(
    ctx: MigrationContext,
    job_id: UUID,
    title: str,
    visibility: str,
    columns: Mapping[str, str],
) -> str | None:
    """The dataset of a job an earlier run uploaded, or None when the file must
    be uploaded again."""
    try:
        _commit(ctx, job_id, title, visibility, columns)
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
    # Layers of a fan-out an earlier run queued but did not wait for.
    _wait_for_layers(ctx, entry, base)
    if entry.layer_datasets:
        many = JOB_KEY not in entry.layer_datasets
        for name, dataset in entry.layer_datasets.items():
            title = _title(base, _layer_name(name) if many else None)
            _apply_target(ctx, dataset, _commit_body(title, visibility))
        # Notes from the run that imported the layers, such as a layer that
        # failed to queue, must survive this resume.
        return ItemResult(notes=list(entry.notes))

    if entry.fan_out:
        resumed = _resume_fan_out(ctx, entry, base, visibility)
        if resumed is not None:
            return resumed

    recorded = entry.layer_jobs.get(JOB_KEY)
    if recorded:
        dataset = _finish_recorded(
            ctx, UUID(recorded), base, visibility, entry.file_columns
        )
        del entry.layer_jobs[JOB_KEY]
        if dataset is not None:
            # Pinned and saved before the target is applied: a failure there
            # must leave the dataset recorded, or a rerun would upload again.
            result = _pinned(entry, dataset)
            ctx.save()
            _apply_target(ctx, dataset, _commit_body(base, visibility))
            return result
        ctx.save()

    limit = _limit(ctx)
    size = row.get("size_bytes")
    try:
        if isinstance(size, int) and size > limit:
            raise _Skipped(
                f"the file is {_megabytes(size)}, over the instance's upload "
                f"limit of {_megabytes(limit)}"
            )
        job_id = _upload_fresh(ctx, item, extension, limit)
    except _Skipped as skipped:
        return ItemResult(status=SKIPPED, notes=[f"skipped: {skipped}"])
    entry.job_ids.append(str(job_id))
    preview = _preview(ctx, job_id, base)
    layers = _layer_names(preview)
    if len(layers) > MAX_FAN_OUT_LAYERS:
        return ItemResult(
            status=SKIPPED,
            notes=[
                f"skipped: the file holds {len(layers)} layers and GeoLens imports "
                f"at most {MAX_FAN_OUT_LAYERS} from one file; split the file and "
                "import the parts"
            ],
        )
    if len(layers) > 1:
        failed = _fan_out(ctx, job_id, layers, base, visibility, entry)
        return ItemResult(
            notes=[f"the file holds {len(layers)} layers, one dataset each", *failed]
        )
    # Recorded before the commit is sent: if its answer is lost, a rerun
    # finds this job rather than uploading the file a second time.
    columns = _geometry_columns(preview)
    entry.layer_jobs[JOB_KEY] = str(job_id)
    entry.file_columns = columns
    ctx.save()
    notes = []
    if item["type"] == "CSV" and not columns and preview.geometry_type is None:
        notes.append("no geometry column found; imported as a table")
    _commit(ctx, job_id, base, visibility, columns)
    dataset = _wait_for_dataset(ctx, job_id, base)
    del entry.layer_jobs[JOB_KEY]
    return _pinned(entry, dataset, notes)


def _pinned(
    entry: ItemState, dataset: str, notes: list[str] | None = None
) -> ItemResult:
    """Record the item's one dataset, so a rerun never imports the file again."""
    entry.layer_datasets[JOB_KEY] = dataset
    entry.dataset_ids = [dataset]
    return ItemResult(notes=notes or [])
