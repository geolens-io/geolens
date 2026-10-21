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
)
from .arcgis_migrate_state import DONE, EXISTS, ItemState

# ArcGIS sub-layer types that hold features GeoLens can import.
IMPORTABLE_LAYER_TYPES = frozenset({"Feature Layer", "Table"})
JOB_POLL_INTERVAL = 5.0
JOB_TIMEOUT = 3600.0
_JOB_FAILED = frozenset({"failed", "cancelled", "fanned_out"})
# GeoLens answers a service's token refusal with a 403 carrying this text, and
# a missing credential store with this code.
_TOKEN_REFUSED = "Provide a valid ArcGIS token"
_STORE_UNAVAILABLE = "credential_store_unavailable"


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
    secure = parts.scheme == "https" or (
        parts.scheme == "http" and ctx.allow_insecure_http
    )
    if not secure or ".." in unquote(parts.path).split("/"):
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


def _layer_key(layer: Any) -> str:
    layer_id = getattr(layer, "layer_id", None)
    return str(layer_id) if isinstance(layer_id, int | str) else str(layer.name)


def _layer_label(layer: Any) -> str:
    title = getattr(layer, "title", None)
    return title if isinstance(title, str) and title else str(layer.name)


def _importable(layer: Any) -> str | None:
    """Why *layer* is not imported, or None."""
    kind = getattr(layer, "source_layer_type", None)
    if not isinstance(kind, str):
        kind = None
    if getattr(layer, "importable", True) is False or (
        kind is not None and kind not in IMPORTABLE_LAYER_TYPES
    ):
        return f"{_layer_label(layer)}: {kind or 'this kind of'} layer, not imported"
    return None


class _JobEnded(ItemFailed):
    """The ingest job finished without a dataset."""


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
    from geolens.api.datasets import commit_import_ingest_commit_job_id_post as commit
    from geolens.api.datasets import (
        preview_service_layer_services_preview_post as preview,
    )
    from geolens.models.commit_request import CommitRequest
    from geolens.models.service_preview_request import ServicePreviewRequest

    key = _layer_key(layer)
    committed = entry.layer_jobs.get(key)
    if committed:
        try:
            entry.layer_datasets[key] = _wait_for_dataset(ctx, UUID(committed), title)
        except _JobEnded:
            del entry.layer_jobs[key]
            ctx.save()
        else:
            del entry.layer_jobs[key]
            return False

    request = ServicePreviewRequest(
        url=probe.url,
        service_type=probe.service_type,
        layer_name=str(layer.name),
        layer_title=_layer_label(layer),
        layer_id=layer.layer_id if isinstance(layer.layer_id, int | str) else None,
        object_id_field=layer.object_id_field
        if isinstance(layer.object_id_field, str)
        else None,
    )
    try:
        with long_request_timeout(ctx.geolens.client):
            previewed = _send(ctx, row, probe.url, preview.sync_detailed, body=request)
    except GeoLensError as exc:
        existing = _existing_dataset(exc)
        if existing is None:
            raise ItemFailed(f"{title}: preview failed, {exc}") from None
        entry.layer_datasets[key] = existing
        return True
    entry.job_ids.append(str(previewed.job_id))
    ctx.save()
    try:
        _send(
            ctx,
            row,
            probe.url,
            commit.sync_detailed,
            job_id=previewed.job_id,
            body=CommitRequest(title=title, visibility=visibility),
            expected=202,
        )
    except GeoLensError as exc:
        raise ItemFailed(f"{title}: commit failed, {exc}") from None
    entry.layer_jobs[key] = str(previewed.job_id)
    ctx.save()
    entry.layer_datasets[key] = _wait_for_dataset(ctx, previewed.job_id, title)
    del entry.layer_jobs[key]
    return False


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
    layers = list(probe.layers)
    selected = probe.selected_layer_id
    if isinstance(selected, int | str):
        layers = [layer for layer in layers if str(layer.layer_id) == str(selected)]
    reasons = [(layer, _importable(layer)) for layer in layers]
    notes = [reason for _layer, reason in reasons if reason]
    wanted = [layer for layer, reason in reasons if reason is None]
    if not wanted:
        # Done rather than skipped, so a rerun doesn't probe it again.
        return ItemResult(notes=[*notes, "the service has no layer to import"])

    base = item["target"]["title"] or item["title"]
    found = 0
    for layer in wanted:
        if _layer_key(layer) in entry.layer_datasets:
            continue
        title = base if len(wanted) == 1 else f"{base} - {_layer_label(layer)}"
        found += _import_layer(
            ctx, row, probe, layer, title, item["target"]["visibility"], entry
        )
        entry.dataset_ids = list(dict.fromkeys(entry.layer_datasets.values()))
        ctx.save()
    return ItemResult(status=EXISTS if found == len(wanted) else DONE, notes=notes)
