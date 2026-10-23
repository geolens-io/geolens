# SPDX-License-Identifier: Apache-2.0
"""Bring finished items up to date on a rerun of `geolens arcgis migrate`.

Hand-maintained. A service item's datasets are refreshed through
``POST /datasets/{id}/refresh`` with the run's ArcGIS credential, a data file
item's are replaced by a fresh download and a re-upload, and the item metadata
is written again. A run that stops for review is reported, never accepted.

A dataset changed in GeoLens since this command last left it is reported and
left alone. The state file records each dataset's ``updated_at``, feature
count and data revision after every write this command makes; a rerun
compares them right before each dataset's request, and sends the revision so
GeoLens stops the publication for review if the data changes after that.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path
from typing import Any
from uuid import UUID

from . import replace as _replace
from ._sdk_helpers import PollDeadlineExceeded, long_request_timeout, poll_until
from .arcgis_item_metadata import apply_item_metadata
from .arcgis_migrate_files import (
    EXTENSIONS,
    JOB_KEY,
    _download,
    _filename,
    _layer_name,
    _limit,
    _megabytes,
    _Skipped,
)
from .arcgis_migrate_layers import (
    JOB_POLL_INTERVAL,
    JOB_TIMEOUT,
    _layer_key,
    _layer_label,
    _send,
    attachment_flags,
    importable_layers,
)
from .arcgis_migrate_session import GeoLensError, ItemFailed, MigrationContext
from .arcgis_migrate_state import ItemState, aware_time, whole_number
from .refresh import (
    RefreshPollResult,
    _value,
    blocked_guidance,
    describe_failure_reason,
)

_ENDED = frozenset({"succeeded", "failed", "cancelled", "blocked"})
RUN_PAGE = 50

# Starts one dataset's refresh or replacement and records its marker: the
# dataset id, its GeoLens record and the data revision to send. Returns why it
# couldn't start, or None.
Starter = Callable[[str, Any, int], "str | None"]
Refresher = Callable[[MigrationContext, Mapping[str, Any], ItemState], list[str]]


def get_dataset(ctx: MigrationContext, dataset_id: str) -> Any:
    from geolens.api.datasets import get_single_dataset_datasets_dataset_id_get as get

    return ctx.geolens.call(get.sync_detailed, dataset_id=UUID(dataset_id))


def snapshot(dataset: Any) -> dict[str, Any]:
    """What a later run compares to tell whether GeoLens changed *dataset*."""
    return {
        "updated_at": dataset.updated_at.isoformat(),
        "feature_count": _value(dataset.feature_count),
        "data_revision": _revision(dataset),
    }


def _revision(dataset: Any) -> int | None:
    return _value(getattr(dataset, "data_revision", None))


def record(entry: ItemState, dataset_id: str, dataset: Any) -> None:
    """Record *dataset* as this command left it."""
    entry.last_update[dataset_id] = snapshot(dataset)
    entry.refreshing.pop(dataset_id, None)


def operator_wrote_last(
    ctx: MigrationContext, dataset: Any, operator: str | None = None
) -> bool:
    """Whether *operator*, by default this run's, made the dataset's last write."""
    by = _value(getattr(dataset, "updated_by", None))
    return by is not None and str(by) == (operator or ctx.operator_id)


def _find_run(
    ctx: MigrationContext, dataset_id: str, marker: Mapping[str, Any], **kwargs: Any
) -> Any | None:
    """The refresh run *marker* names, by its id or its ingest job, looked for
    through the dataset's whole history, newest first."""
    skip = 0
    while True:
        page = _run_page(ctx, dataset_id, skip, RUN_PAGE, **kwargs)
        for run in page.runs:
            if (
                str(run.id) == marker.get("run")
                or (
                    marker.get("job")
                    and str(_value(run.ingest_job_id)) == marker["job"]
                )
                or (marker.get("blocked") and _accepted_run(run) == marker["blocked"])
            ):
                return run
        skip += len(page.runs)
        if not page.runs or skip >= page.total:
            return None


def _accepted_run(run: Any) -> str | None:
    """The blocked run whose acceptance *run* carries out."""
    found = _value(getattr(run, "verification", None))
    if hasattr(found, "to_dict"):
        found = found.to_dict()
    accepted = found.get("accepted_blocked_run_id") if isinstance(found, dict) else None
    return None if accepted is None else str(accepted)


def _run_page(
    ctx: MigrationContext, dataset_id: str, skip: int, limit: int, **kwargs: Any
) -> Any:
    from geolens.api.datasets import (
        list_dataset_refresh_runs_datasets_dataset_id_refresh_runs_get as list_runs,
    )

    return ctx.geolens.call(
        list_runs.sync_detailed,
        dataset_id=UUID(dataset_id),
        skip=skip,
        limit=limit,
        **kwargs,
    )


def _adopt_pending(
    ctx: MigrationContext, entry: ItemState, dataset_id: str, marker: Mapping[str, Any]
) -> str | None:
    """Settle a refresh request whose answer the last run never saw: the one
    run the operator started since is adopted as the marker's run, and none
    means the request never landed. Why it can't be settled, or None."""
    before = whole_number(marker.get("pending")) or 0
    page = _run_page(ctx, dataset_id, 0, RUN_PAGE)
    added = max(page.total - before, 0)
    if added > len(page.runs):
        return (
            "more refreshes were started since a request whose answer was lost "
            "than one page of history shows, so the one it sent can't be found"
        )
    # Newest first, so the runs added since the request are the first.
    started = page.runs[:added]
    ours = [run for run in started if str(_value(run.triggered_by)) == marker.get("by")]
    if len(ours) > 1:
        return (
            "more than one refresh was started since a request whose answer was "
            "lost, so none can be told from the one it sent"
        )
    settled = {k: v for k, v in marker.items() if k != "pending"}
    if ours:
        entry.refreshing[dataset_id] = {**settled, "run": str(ours[0].id)}
    else:
        del entry.refreshing[dataset_id]
    ctx.save()
    return None


def _published_unchanged(
    ctx: MigrationContext, dataset: Any, marker: Mapping[str, Any]
) -> bool:
    """Whether *dataset* is as the succeeded run *marker* names published it:
    the admin who started it (by default this run's) wrote it last, and its
    data revision and owner are the ones the run was sent with. A marker from
    before the owner was recorded skips the owner."""
    expected = whole_number(marker.get("revision"))
    return (
        expected is not None
        and _revision(dataset) == expected
        and operator_wrote_last(ctx, dataset, marker.get("by"))
        and ("owner" not in marker or _owner(dataset) == marker["owner"])
    )


def _owner(dataset: Any) -> str | None:
    owner = _value(getattr(dataset, "created_by", None))
    return None if owner is None else str(owner)


def changed_in_geolens(
    ctx: MigrationContext, entry: ItemState, dataset_id: str, dataset: Any
) -> str | None:
    """Why *dataset* must be left alone, or None when this command may write it.

    A refresh an earlier run started and never settled explains a change only
    when it succeeded and the dataset is still as it published it; that result
    is then recorded as this command's own write before anything else. A dataset
    with no recorded last update (a state file from before they were recorded)
    counts as unchanged only when the operator wrote it last, before the item
    finished.
    """
    marker = entry.refreshing.get(dataset_id)
    if marker and "pending" in marker:
        unsettled = _adopt_pending(ctx, entry, dataset_id, marker)
        if unsettled:
            return unsettled
        marker = entry.refreshing.get(dataset_id)
    run = _find_run(ctx, dataset_id, marker) if marker else None
    if run is not None:
        if str(run.status) not in _ENDED:
            return "a refresh an earlier run started is still running"
        if "blocked" in marker:
            # The accepted successor is started by whoever accepted the run.
            marker = {**marker, "by": str(_value(run.triggered_by))}
        # The admin who started the run, who may not be this run's operator.
        if str(run.status) == "succeeded" and _published_unchanged(
            ctx, dataset, marker
        ):
            record(entry, dataset_id, dataset)
            ctx.save()
            return None
    seen = entry.last_update.get(dataset_id)
    if seen is None:
        finished = aware_time(entry.finished_at)
        if (
            finished is not None
            and operator_wrote_last(ctx, dataset)
            and dataset.updated_at <= finished
        ):
            return None
        return "changed in GeoLens since it was migrated"
    if snapshot(dataset) != seen:
        return "changed in GeoLens since the last run"
    return None


def _wait_for_run(
    ctx: MigrationContext, entry: ItemState, dataset_id: str
) -> tuple[bool, str | None]:
    """Whether the run ``entry.refreshing`` names for *dataset_id* ended before
    the deadline, and why it didn't publish."""
    marker = entry.refreshing[dataset_id]
    deadline = ctx.clock() + JOB_TIMEOUT
    while True:
        try:
            run = poll_until(
                lambda: _find_run(ctx, dataset_id, marker, reraise_timeout=True),
                deadline=deadline,
                interval=JOB_POLL_INTERVAL,
                sleep=ctx.sleep,
                monotonic=ctx.clock,
            )
        except PollDeadlineExceeded:
            run = None
        if run is not None and str(run.status) in _ENDED:
            break
        if ctx.clock() >= deadline:
            return False, (
                f"its refresh was still running after {JOB_TIMEOUT:g} s; a rerun "
                "picks up its result"
            )
        ctx.sleep(JOB_POLL_INTERVAL)
    status = str(run.status)
    if status == "succeeded":
        return True, None
    if status == "blocked":
        # Kept so a rerun finds the run the operator accepts it with.
        entry.refreshing[dataset_id] = {
            **{k: v for k, v in marker.items() if k not in ("run", "job")},
            "blocked": str(run.id),
        }
        ctx.save()
        found = _value(run.verification)
        poll = RefreshPollResult(
            status,
            verification=found.to_dict() if hasattr(found, "to_dict") else found,
            run_id=str(run.id),
        )
        return True, " ".join(
            [
                "its refresh stopped for review and published nothing.",
                *blocked_guidance(UUID(dataset_id), poll),
            ]
        )
    error = _value(run.error_message)
    return True, f"its refresh ended {status}" + (
        f": {describe_failure_reason(str(error))}" if error else ""
    )


def _origin_url(dataset: Any) -> str | None:
    ref = _value(getattr(dataset, "origin_ref", None))
    url = ref.to_dict().get("url") if hasattr(ref, "to_dict") else None
    return url if isinstance(url, str) and url else None


def _start_refresh(
    ctx: MigrationContext,
    row: Mapping[str, Any],
    entry: ItemState,
    dataset_id: str,
    dataset: Any,
    revision: int,
) -> str | None:
    from geolens.api.datasets_refresh import (
        refresh_dataset_datasets_dataset_id_refresh_post as refresh,
    )
    from geolens.models.dataset_refresh_request import DatasetRefreshRequest

    # The token goes where the dataset's stored source points, which the
    # trust check must judge rather than the inventory's URL.
    url = _origin_url(dataset)
    if url is None and (row.get("sharing") or {}).get("access") != "public":
        return "its stored source can't be read, so the ArcGIS token was not sent"
    # Recorded before the request: if its answer is lost, a rerun adopts the
    # run it started.
    try:
        runs_before = _run_page(ctx, dataset_id, 0, 1).total
    except GeoLensError as exc:
        return f"reading the dataset's refresh history failed, {exc}"
    entry.refreshing[dataset_id] = {
        "pending": runs_before,
        "revision": revision,
        "by": ctx.operator_id,
        "owner": _owner(dataset),
    }
    ctx.save()
    try:
        accepted = _send(
            ctx,
            row,
            url or row["url"],
            refresh.sync_detailed,
            body=DatasetRefreshRequest(expected_data_revision=revision),
            dataset_id=UUID(dataset_id),
            expected=202,
        )
    except GeoLensError as exc:
        return _settle_unrecorded(
            ctx, entry, dataset_id, f"GeoLens refused the refresh, {exc}"
        )
    except ItemFailed as exc:
        return _settle_unrecorded(ctx, entry, dataset_id, str(exc))
    entry.refreshing[dataset_id] = {
        "run": str(accepted.run_id),
        "revision": revision,
        "by": ctx.operator_id,
        "owner": _owner(dataset),
    }
    ctx.save()
    return None


def refresh_layers(
    ctx: MigrationContext, item: Mapping[str, Any], entry: ItemState
) -> list[str]:
    """Probe a service item, record which layers have attachments and report
    layers added since it was migrated, then refresh each dataset from its
    stored source."""
    from geolens.api.datasets import probe_service_url_services_probe_post as probe_api
    from geolens.models.probe_request import ProbeRequest

    row = ctx.inventory.get(item["id"])
    if row is None or not row.get("url"):
        return ["the inventory has no service URL for the item"]
    if entry.service_url not in (None, row["url"]):
        return [
            "its service URL changed in the portal since it was migrated, so its "
            "datasets were not refreshed from the old one"
        ]
    try:
        with long_request_timeout(ctx.geolens.client):
            probe = _send(
                ctx,
                row,
                row["url"],
                probe_api.sync_detailed,
                body=ProbeRequest(url=row["url"]),
            )
    except GeoLensError as exc:
        return [f"probe failed, {exc}"]
    except ItemFailed as exc:
        return [str(exc)]
    # A state file from before the URL was recorded adopts the one that
    # answered, so a later change of service is refused like any other.
    entry.service_url = row["url"]
    if not probe.layers and entry.layer_datasets:
        return ["couldn't check the service's layers: its probe listed none"]
    flags = attachment_flags(probe.layers)
    entry.attachments = {key: flags.get(key) for key in entry.layer_datasets}
    ctx.save()
    wanted, _notes, entry.left_behind = importable_layers(probe)
    added = [
        f"layer {_layer_label(layer)} was added to the service in the portal and "
        "isn't migrated"
        for layer in wanted
        if _layer_key(layer) not in entry.layer_datasets
    ]
    return added + _bring_each(
        ctx, item, entry, partial(_start_refresh, ctx, row, entry)
    )


def _start_replace(
    ctx: MigrationContext,
    entry: ItemState,
    dataset_id: str,
    dataset: Any,
    revision: int,
    path: Path,
    layers_seen: set[str],
) -> str | None:
    from geolens.api.datasets_reupload import (
        reupload_commit_datasets_dataset_id_reupload_job_id_commit_post as commit,
        reupload_preview_datasets_dataset_id_reupload_job_id_preview_post as preview,
    )

    refusal = _replace.origin_refusal_message(_value(dataset.origin))
    if refusal is not None:
        return refusal
    key = next(k for k, d in entry.layer_datasets.items() if d == dataset_id)
    layer = None if key == JOB_KEY else _layer_name(key)
    try:
        upload = ctx.geolens.call(
            _replace.upload_file,
            expected=_replace.UPLOAD_OK_STATUS,
            dataset_id=UUID(dataset_id),
            path=path,
        )
        # Recorded before the commit: if its answer is lost, a rerun still
        # finds the run it started.
        entry.refreshing[dataset_id] = {
            "job": str(upload.job_id),
            "revision": revision,
            "by": ctx.operator_id,
            "owner": _owner(dataset),
        }
        ctx.save()
        with long_request_timeout(ctx.geolens.client):
            previewed = ctx.geolens.call(
                preview.sync_detailed,
                dataset_id=UUID(dataset_id),
                job_id=upload.job_id,
                body=_replace.build_preview_request(layer),
            )
        layers_seen.update(
            found["name"] for found in _replace.layer_summaries(previewed)
        )
        if layer is None and _replace.layer_summaries(previewed):
            return _settle_unrecorded(
                ctx,
                entry,
                dataset_id,
                "the file now holds several layers; replace it by hand with "
                f"geolens replace {dataset_id} --layer <name>",
            )
        # A swap made in GeoLens during the upload, which doesn't move the
        # data revision the commit sends, would otherwise be replaced.
        if snapshot(get_dataset(ctx, dataset_id)) != snapshot(dataset):
            return _settle_unrecorded(
                ctx,
                entry,
                dataset_id,
                "changed in GeoLens during the upload; it was left as it is",
            )
        ctx.geolens.call(
            commit.sync_detailed,
            dataset_id=UUID(dataset_id),
            job_id=upload.job_id,
            body=_replace.build_commit_request(
                layer_name=layer,
                srid_override=None,
                expected_origin_kind=_replace.captured_origin_kind(dataset),
                expected_data_revision=revision,
            ),
            expected=_replace.COMMIT_OK_STATUS,
        )
    except GeoLensError as exc:
        return f"GeoLens refused the replacement, {exc}"
    return None


def refresh_file(
    ctx: MigrationContext, item: Mapping[str, Any], entry: ItemState
) -> list[str]:
    """Download a data file item again, then replace each of its datasets with
    it, one layer each for a multi-layer file."""
    if not entry.layer_datasets:
        return ["no dataset of it is recorded, so there is nothing to replace"]
    extension = EXTENSIONS.get(item["type"])
    row = ctx.inventory.get(item["id"])
    if extension is None or row is None:
        return ["the item is not in the inventory the plan was built from"]
    limit = _limit(ctx)
    size = row.get("size_bytes")
    if isinstance(size, int) and size > limit:
        return [
            f"not replaced: the file is {_megabytes(size)}, over the instance's "
            f"upload limit of {_megabytes(limit)}"
        ]
    with tempfile.TemporaryDirectory(prefix="geolens-arcgis-") as tmp:
        path = Path(tmp) / _filename(item, extension)
        try:
            _download(ctx, item["id"], path, limit)
        except _Skipped as skipped:
            return [f"not replaced: {skipped}"]
        except ItemFailed as exc:
            return [str(exc)]
        layers_seen: set[str] = set()
        problems = _bring_each(
            ctx,
            item,
            entry,
            partial(_start_replace, ctx, entry, path=path, layers_seen=layers_seen),
        )
    known = {_layer_name(key) for key in entry.layer_datasets if key != JOB_KEY}
    if known and not layers_seen and not problems:
        return ["couldn't check the file's layers: its previews listed none"]
    # Only a multi-layer file's previews list its layers.
    added = sorted(layers_seen - known) if known else []
    return [
        f"layer {name} is in the file but isn't migrated" for name in added
    ] + problems


def _bring_one(
    ctx: MigrationContext,
    item: Mapping[str, Any],
    entry: ItemState,
    dataset_id: str,
    start: Starter,
) -> str | None:
    """Refresh one dataset and write its metadata again; why it isn't up to
    date, or None.

    Checked right before its own request. A run that didn't publish leaves the
    previous record and writes no metadata; a published one is recorded only
    while the dataset is still as the run left it.
    """
    try:
        dataset = get_dataset(ctx, dataset_id)
    except GeoLensError as exc:
        if exc.status != 404:
            raise
        return "deleted in GeoLens; it was left as it is"
    revision = _revision(dataset)
    if revision is None:
        return (
            "this GeoLens doesn't report data revisions, so edits made in it "
            "can't all be told apart; upgrade GeoLens to bring migrated datasets "
            "up to date safely"
        )
    reason = changed_in_geolens(ctx, entry, dataset_id, dataset)
    if reason:
        return f"{reason}; it was left as it is"
    problem, dataset = _apply_visibility(ctx, item, entry, dataset_id, dataset)
    if problem:
        return problem
    problem = start(dataset_id, dataset, revision)
    if problem:
        return problem
    ended, problem = _wait_for_run(ctx, entry, dataset_id)
    if not ended:
        return problem
    if problem:
        if "blocked" in entry.refreshing[dataset_id]:
            return problem
        return _settle_unrecorded(ctx, entry, dataset_id, problem)
    marker = entry.refreshing[dataset_id]
    published = get_dataset(ctx, dataset_id)
    if not _published_unchanged(ctx, published, marker):
        return _settle_unrecorded(
            ctx,
            entry,
            dataset_id,
            "changed in GeoLens while its refresh ran; it was left as it is",
        )
    record(entry, dataset_id, published)
    ctx.save()
    apply_item_metadata(ctx, item, entry, [dataset_id])
    after = get_dataset(ctx, dataset_id)
    if not _published_unchanged(ctx, after, marker):
        return "changed in GeoLens while its metadata was written; it was left as it is"
    record(entry, dataset_id, after)
    ctx.save()
    return None


def _apply_visibility(
    ctx: MigrationContext,
    item: Mapping[str, Any],
    entry: ItemState,
    dataset_id: str,
    dataset: Any,
) -> tuple[str | None, Any]:
    """Give the dataset the plan's visibility when the portal's sharing moved
    it since the import; why it can't, or None, and the dataset as this left
    it.

    A visibility changed in GeoLens since this command set it is kept and
    reported, and so is a difference a state file without the record can't
    tell the origin of.
    """
    from geolens.api.datasets import (
        update_dataset_metadata_datasets_dataset_id_patch as patch,
    )
    from geolens.models.dataset_meta import DatasetMeta

    wanted = item["target"]["visibility"]
    applied = entry.visibility.get(dataset_id)
    current = _value(dataset.visibility)
    if current == wanted:
        entry.visibility[dataset_id] = wanted
        return None, dataset
    if applied is None:
        return (
            f"its visibility is {current} in GeoLens and {wanted} in the plan, and "
            "the state doesn't say which changed; set it by hand"
        ), dataset
    if current != applied:
        return (
            f"its visibility was changed to {current} in GeoLens, and the plan now "
            f"says {wanted}; it was left as it is"
        ), dataset
    written = ctx.geolens.write(
        patch.sync_detailed,
        during="its visibility was written",
        dataset_id=UUID(dataset_id),
        body=DatasetMeta(visibility=wanted, expected_updated_at=dataset.updated_at),
    )
    record(entry, dataset_id, written)
    entry.visibility[dataset_id] = wanted
    ctx.save()
    return None, written


def _settle_unrecorded(
    ctx: MigrationContext, entry: ItemState, dataset_id: str, problem: str
) -> str:
    """Drop the marker of an ended run whose result isn't recorded, so the
    next run compares with the record from before it."""
    entry.refreshing.pop(dataset_id, None)
    ctx.save()
    return problem


def _bring_each(
    ctx: MigrationContext, item: Mapping[str, Any], entry: ItemState, start: Starter
) -> list[str]:
    problems = []
    for dataset_id in dict.fromkeys(entry.layer_datasets.values()):
        try:
            problem = _bring_one(ctx, item, entry, dataset_id, start)
        except (ItemFailed, GeoLensError) as exc:
            problem = str(exc)
        if problem:
            problems.append(f"dataset {dataset_id}: {problem}")
    return problems
