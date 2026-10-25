# SPDX-License-Identifier: Apache-2.0
"""The ``import_layers`` action of `geolens arcgis migrate`.

Hand-maintained. Imports every feature layer and table of one ArcGIS service
item through GeoLens's own service import: probe the item's URL, then preview
and commit each layer, then wait for its ingest job. GeoLens fetches the
service server-side under its SSRF checks; this module never contacts it.
A non-public item's requests carry the run's ArcGIS token as ``auth`` on the
probe, the preview and the commit, since each reads the credential from its
own body.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import UUID

from ._sdk_helpers import PollDeadlineExceeded, long_request_timeout, poll_until
from .arcgis_inventory import external_by_url
from .arcgis_migrate_session import (
    GeoLensError,
    ItemFailed,
    ItemResult,
    MigrationContext,
    StopRun,
    changed_before_handover,
    operator_or_nobody_wrote_last,
)
from .arcgis_migrate_state import DONE, EXISTS, ItemState

GROUP_LAYER = "Group Layer"
MAX_TITLE = 500
JOB_POLL_INTERVAL = 5.0
JOB_TIMEOUT = 3600.0
_JOB_FAILED = frozenset({"failed", "cancelled", "fanned_out"})
# GeoLens answers a service's token refusal with a 403 carrying this text, and
# a missing credential store with this code.
_TOKEN_REFUSED = "Provide a valid ArcGIS token"
_STORE_UNAVAILABLE = "credential_store_unavailable"
# GeoLens's answer to a commit of a job that was committed before.
_ALREADY_COMMITTED = "already processed"


def _row(ctx: MigrationContext, item: Mapping[str, Any]) -> Mapping[str, Any]:
    row = ctx.inventory.get(item["id"])
    if row is None:
        raise ItemFailed("the item is not in the inventory the plan was built from")
    if not row.get("url"):
        raise ItemFailed("the inventory has no service URL for the item")
    return row


def _trusted(ctx: MigrationContext, url: str) -> bool:
    """Whether *url* is one of the organization's own services.

    GeoLens forwards the token to the service URL, and an item's URL is
    whatever its owner typed, so the token goes only to the portal's host,
    the organization's ArcGIS Online hosted services, or a host the operator
    named with --trust-service-host.
    """
    parts = urlsplit(url)
    # Always https: --allow-insecure-http covers a test portal, not a token
    # GeoLens would forward in clear text.
    if parts.scheme != "https" or ".." in unquote(parts.path).split("/"):
        return False
    if (parts.hostname or "").lower() in ctx.trusted_hosts:
        return True
    return (
        ctx.portal_info is not None and external_by_url(url, ctx.portal_info) is False
    )


def _auth(ctx: MigrationContext, row: Mapping[str, Any], url: str) -> Any:
    """The credential for a request about a non-public item, or None for a
    public one. ``ItemFailed`` when *url* isn't trusted with the token."""
    if (row.get("sharing") or {}).get("access") == "public":
        return None
    if ctx.portal is None:
        raise ItemFailed("the item is not public and the run has no ArcGIS token")
    if not _trusted(ctx, url):
        host = urlsplit(url).hostname or url
        raise ItemFailed(
            f"the service host {host} is not one of the organization's servers, "
            "so the ArcGIS token was not sent; if it is a federated server, "
            f"rerun with --trust-service-host {host}"
        )
    return ctx.portal.service_auth()


def _send(
    ctx: MigrationContext, row: Mapping[str, Any], url: str, fn: Any, **kwargs: Any
) -> Any:
    """One GeoLens call about the service at *url*, carrying the item's
    credential.

    When the service refuses the token, a token minted from a password is
    renewed and the call retried once; otherwise the run stops so it can
    resume with a fresh token. An instance without a credential store can't
    take any token-bearing import, so that stops the run too.
    """
    body = kwargs.pop("body")
    for attempt in (1, 2):
        auth = _auth(ctx, row, url)
        if auth is not None:
            body.auth = auth
        try:
            return ctx.geolens.call(fn, body=body, **kwargs)
        except GeoLensError as exc:
            if auth is None:
                raise
            detail = exc.detail if isinstance(exc.detail, Mapping) else {}
            if exc.status == 503 and detail.get("code") == _STORE_UNAVAILABLE:
                raise StopRun(f"GeoLens can't take the ArcGIS token: {exc}") from None
            if exc.status != 403 or _TOKEN_REFUSED not in str(exc):
                raise
            if attempt == 1 and ctx.portal is not None and ctx.portal.renew():
                continue
            raise StopRun(
                f"the service refused the ArcGIS token ({exc}); it may have "
                "expired. Rerun with a fresh token to resume."
            ) from None
    raise AssertionError("unreachable")


def _title(base: str, layer: str | None, layer_id: str | None = None) -> str:
    """The dataset title: the item's, then `` - <layer>`` for a service with
    several layers, within GeoLens's title limit. A layer whose title another
    layer of the same service also takes carries `` (<layer id>)`` as well,
    so the catalog can tell the two datasets apart."""
    if layer is None:
        return base[:MAX_TITLE]
    tag = f" ({layer_id})" if layer_id is not None else ""
    suffix = f" - {layer}"[: MAX_TITLE // 2 - len(tag)] + tag
    return base[: MAX_TITLE - len(suffix)] + suffix


def _layer_id(layer: Any) -> str | None:
    layer_id = getattr(layer, "layer_id", None)
    return str(layer_id) if isinstance(layer_id, int | str) else None


def _layer_key(layer: Any) -> str:
    return _layer_id(layer) or str(layer.name)


def _layer_label(layer: Any) -> str:
    title = getattr(layer, "title", None)
    return title if isinstance(title, str) and title else str(layer.name)


def attachment_flags(layers: Any) -> dict[str, bool | None]:
    """Probed layer -> whether it has attachments, None where the service
    doesn't say."""
    flags: dict[str, bool | None] = {}
    for layer in layers:
        value = getattr(layer, "has_attachments", None)
        flags[_layer_key(layer)] = value if isinstance(value, bool) else None
    return flags


def importable_layers(probe: Any) -> tuple[list[Any], list[str], list[str]]:
    """The probed layers to import, a note for each one left out, and those of
    the notes that are data left behind: every left-out layer but a group
    layer, which holds no data of its own."""
    layers = list(probe.layers)
    selected = probe.selected_layer_id
    if isinstance(selected, int | str):
        layers = [layer for layer in layers if str(layer.layer_id) == str(selected)]
    reasons = [(layer, _importable(layer)) for layer in layers]
    notes = [reason for _layer, reason in reasons if reason]
    lost = [
        reason
        for layer, reason in reasons
        if reason and getattr(layer, "source_layer_type", None) != GROUP_LAYER
    ]
    return [layer for layer, reason in reasons if reason is None], notes, lost


def _titles(base: str, layers: list[Any]) -> list[str]:
    """The dataset title for each of a service's layers, in order.

    Layers that would share a title get their layer id added, checked
    against the final titles: a layer already named like another layer's
    tagged title is tagged too, so every layer ends up told apart (layer
    ids are unique within a service).
    """
    labels = [_layer_label(layer) if len(layers) > 1 else None for layer in layers]
    titles = [_title(base, label) for label in labels]
    tagged = [False] * len(layers)
    while True:
        shared = {title for title in titles if titles.count(title) > 1}
        if not shared:
            return titles
        moved = False
        for i, (layer, label) in enumerate(zip(layers, labels)):
            if titles[i] in shared and not tagged[i]:
                titles[i] = _title(base, label, _layer_id(layer))
                tagged[i] = True
                moved = True
        if not moved:
            return titles


def _importable(layer: Any) -> str | None:
    """Why *layer* is not imported, or None."""
    if getattr(layer, "importable", True) is not False:
        return None
    kind = getattr(layer, "source_layer_type", None)
    kind = kind if isinstance(kind, str) else "this kind of"
    return f"{_layer_label(layer)}: {kind} layer, not imported"


class _JobEnded(ItemFailed):
    """The ingest job finished without a dataset."""


class _JobGone(ItemFailed):
    """GeoLens no longer has the ingest job (expired or purged)."""


def _wait_for_dataset(ctx: MigrationContext, job_id: UUID, title: str) -> str:
    from geolens.api.admin import get_job_status_jobs_job_id_get as get_job

    deadline = ctx.clock() + JOB_TIMEOUT
    status = "pending"
    while True:
        try:
            # A slow status read is retried until the deadline rather than
            # ending the run.
            job = poll_until(
                lambda: ctx.geolens.call(
                    get_job.sync_detailed, job_id=job_id, reraise_timeout=True
                ),
                deadline=deadline,
                interval=JOB_POLL_INTERVAL,
                sleep=ctx.sleep,
                monotonic=ctx.clock,
            )
        except PollDeadlineExceeded:
            job = None
        if job is not None:
            if job.dataset_id:
                return str(job.dataset_id)
            status = job.status
            if status in _JOB_FAILED or status == "complete":
                reason = job.error_message or f"the import job ended {status}"
                raise _JobEnded(f"{title}: {reason}")
        if job is None or ctx.clock() >= deadline:
            raise ItemFailed(
                f"{title}: the import job {job_id} was still {status} after "
                f"{JOB_TIMEOUT:g} s; rerun once it finishes"
            )
        ctx.sleep(JOB_POLL_INTERVAL)


def _existing_dataset(exc: GeoLensError) -> str | None:
    detail = exc.detail if isinstance(exc.detail, Mapping) else {}
    if exc.status == 409 and detail.get("code") == "duplicate_source":
        existing = detail.get("existing_dataset_id")
        return str(existing) if existing else None
    return None


def _import_layer(
    ctx: MigrationContext,
    row: Mapping[str, Any],
    probe: Any,
    layer: Any,
    title: str,
    visibility: str,
    entry: ItemState,
) -> bool:
    """Import one layer; True when GeoLens already had it.

    A job a previous run committed for the layer is waited for instead of
    importing the layer again; only a job that ended without a dataset is
    replaced.
    """
    from geolens.api.datasets import (
        preview_service_layer_services_preview_post as preview,
    )
    from geolens.models.service_preview_request import ServicePreviewRequest

    key = _layer_key(layer)
    title_visibility = _commit_body(title, visibility)
    recorded = entry.layer_jobs.get(key)
    if recorded:
        dataset = _finish_job(ctx, row, probe, UUID(recorded), title_visibility)
        del entry.layer_jobs[key]
        if dataset is not None:
            # The commit that made it may predate an edit of the plan.
            _apply_target(ctx, entry, dataset, title_visibility)
            entry.layer_datasets[key] = dataset
            return False
        ctx.save()

    request = ServicePreviewRequest(
        url=probe.url,
        service_type=probe.service_type,
        layer_name=str(layer.name),
        layer_title=_layer_label(layer),
        layer_id=layer.layer_id if isinstance(layer.layer_id, int | str) else None,
        object_id_field=layer.object_id_field
        if isinstance(layer.object_id_field, str)
        else None,
        **_item_link(ctx, row["id"]),
    )
    try:
        with long_request_timeout(ctx.geolens.client):
            previewed = _send(ctx, row, probe.url, preview.sync_detailed, body=request)
    except GeoLensError as exc:
        existing = _existing_dataset(exc)
        if existing is None:
            raise ItemFailed(f"{title}: preview failed, {exc}") from None
        if existing not in entry.reused:
            entry.reused.append(existing)
        _apply_target(ctx, entry, existing, title_visibility)
        entry.layer_datasets[key] = existing
        return True
    # Recorded before the commit is sent: if its answer is lost, a rerun
    # finds this job rather than importing the layer a second time.
    entry.job_ids.append(str(previewed.job_id))
    entry.layer_jobs[key] = str(previewed.job_id)
    ctx.save()
    _commit(ctx, row, probe, previewed.job_id, title_visibility)
    entry.layer_datasets[key] = _wait_for_dataset(ctx, previewed.job_id, title)
    del entry.layer_jobs[key]
    return False


def _commit_body(title: str, visibility: str) -> Any:
    from geolens.models.commit_request import CommitRequest

    return CommitRequest(title=title, visibility=visibility)


def _item_link(ctx: MigrationContext, item_id: str) -> dict[str, str]:
    """The fields a dataset links back to its portal item with."""
    return {"item_id": item_id, "portal_url": ctx.portal_root}


def _apply_target(
    ctx: MigrationContext, entry: ItemState, dataset: str, target: Any
) -> None:
    """Give a dataset GeoLens already held the plan's title and visibility,
    which a fresh import would have received at commit. A dataset an earlier
    attempt handed to its owner, which has a recorded last update, is left.

    One this command imported is refused when somebody else wrote it last, so
    this write doesn't make their edit the operator's. A reused dataset
    predates the migration, and its owner's edits are taken as they are.
    """
    if dataset in entry.last_update:
        return
    from geolens.api.datasets import get_single_dataset_datasets_dataset_id_get as get
    from geolens.api.datasets import (
        update_dataset_metadata_datasets_dataset_id_patch as patch_dataset,
    )
    from geolens.models.dataset_meta import DatasetMeta

    try:
        read = ctx.geolens.call(get.sync_detailed, dataset_id=UUID(dataset))
        if dataset not in entry.reused and not operator_or_nobody_wrote_last(ctx, read):
            raise changed_before_handover(dataset)
        ctx.geolens.write(
            patch_dataset.sync_detailed,
            during=f"the plan's title and visibility were written to dataset {dataset}",
            dataset_id=UUID(dataset),
            body=DatasetMeta(
                title=target.title,
                visibility=target.visibility,
                expected_updated_at=read.updated_at,
            ),
        )
    except GeoLensError as exc:
        raise ItemFailed(
            f"{target.title}: updating the existing dataset failed, {exc}"
        ) from None


def _commit(
    ctx: MigrationContext,
    row: Mapping[str, Any],
    probe: Any,
    job_id: UUID,
    body: Any,
) -> None:
    """Commit a previewed job; a job that was committed already is fine."""
    from geolens.api.datasets import commit_import_ingest_commit_job_id_post as commit

    try:
        _send(
            ctx,
            row,
            probe.url,
            commit.sync_detailed,
            job_id=job_id,
            body=body,
            expected=202,
        )
    except GeoLensError as exc:
        if exc.status in (400, 409) and _ALREADY_COMMITTED in str(exc):
            return
        if exc.status == 404:
            raise _JobGone(f"{body.title}: the import job {job_id} is gone") from None
        raise ItemFailed(f"{body.title}: commit failed, {exc}") from None


def _finish_job(
    ctx: MigrationContext,
    row: Mapping[str, Any],
    probe: Any,
    job_id: UUID,
    body: Any,
) -> str | None:
    """The dataset of a job a previous run recorded, or None when the layer
    must be imported afresh.

    The earlier run may have stopped before or after its commit landed, so the
    commit is sent again (GeoLens answers "already processed" for a committed
    job), then the job is waited for. A job that ended without a dataset, or
    that GeoLens no longer has, is replaced.
    """
    try:
        _commit(ctx, row, probe, job_id, body)
        return _wait_for_dataset(ctx, job_id, body.title)
    except (_JobEnded, _JobGone):
        return None
    except GeoLensError as exc:
        if exc.status == 404:
            return None
        raise ItemFailed(f"{body.title}: {exc}") from None


def import_layers(
    ctx: MigrationContext, item: Mapping[str, Any], entry: ItemState
) -> ItemResult:
    """Import the item's feature layers and tables, one dataset each.

    Layers a previous run imported are not imported again. A layer GeoLens
    already holds for the operator (409 ``duplicate_source``) is reused. The
    item is ``exists`` when GeoLens already held every layer.
    """
    from geolens.api.datasets import probe_service_url_services_probe_post as probe_api
    from geolens.models.probe_request import ProbeRequest

    row = _row(ctx, item)
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
        raise ItemFailed(f"probe failed, {exc}") from None
    if entry.service_url not in (None, row["url"]):
        # Only once the new service answered: a typo'd URL must not drop the
        # pins of the service the item still belongs to. A layer id from the
        # old service could match one of the new service's.
        entry.layer_datasets.clear()
        entry.layer_jobs.clear()
        entry.dataset_ids.clear()
    entry.service_url = row["url"]
    wanted, notes, entry.left_behind = importable_layers(probe)
    entry.attachments = attachment_flags(wanted)
    if not wanted:
        # Done rather than skipped: a rerun's probe reports a layer added later.
        return ItemResult(notes=[*notes, "the service has no layer to import"])

    base = item["target"]["title"] or item["title"]
    titles = _titles(base, wanted)
    found = 0
    for layer, title in zip(wanted, titles):
        pinned = entry.layer_datasets.get(_layer_key(layer))
        if pinned:
            # The plan may have been edited since that layer was imported.
            target = _commit_body(title, item["target"]["visibility"])
            _apply_target(ctx, entry, pinned, target)
            continue
        found += _import_layer(
            ctx, row, probe, layer, title, item["target"]["visibility"], entry
        )
        entry.dataset_ids = list(dict.fromkeys(entry.layer_datasets.values()))
        ctx.save()
    return ItemResult(status=EXISTS if found == len(wanted) else DONE, notes=notes)
