# SPDX-License-Identifier: Apache-2.0
"""Analysis commands — preview a PostGIS operation, or save it as a dataset.

Hand-maintained — NOT regenerated. Pure SDK pass-through (D-25, D-28): the
backend at ``backend/app/modules/catalog/datasets/api/router_analysis.py``
owns every rule, and the CLI carries no copy of them.

That includes the operation list. ``--operation`` is handed to the SDK
unchanged rather than validated against a literal here, so the generated
enum stays the single authority and a new backend operation reaches the CLI
with the next ``make sdks`` instead of a second list to keep in step (#685).

The single exception is ``_require_join_dataset`` below, which copies one
requiredness rule because it is really about a flag name the CLI owns — see
its docstring (#1105). The operation list is still not copied; the help
strings in main.py that name it are held to the SDK enum by
cli/tests/test_analysis.py rather than by a check at call time.

OCCLI-06 invariant: zero direct ``httpx`` / ``requests`` imports — every HTTP
call goes through the generated SDK functions.
"""
from __future__ import annotations

import math
from typing import Any, Optional
from uuid import UUID

import typer

from ._sdk_helpers import EXIT_AUTH, call_sdk, unwrap, upload_timeout

#: Distances are metres on the wire, matching the API and the map builder's
#: unit picker (AnalysisPanel converts feet/miles before it POSTs).
DISTANCE_UNIT = "metres"

#: fix(#685 review): there is no defensible fixed wait, so the default is not
#: one. publish's 120s, then 600s, then an hour were each a guess about how
#: long the work takes, and the queue makes that unanswerable. #703 ranks
#: analysis below uploads, and the server states the consequence outright in
#: no_live_procrastinate_job() (backend/app/platform/jobs/router.py): a job
#: Procrastinate still holds is "simply waiting ... with no upper bound", and
#: failing it at the one-hour mark would be "both a lie and a loss". A CLI
#: that gives up first tells automation the analysis produced nothing while
#: the server is still going to produce it.
#:
#: So --wait waits for a terminal state. Ctrl+C is the way out of a wait the
#: user no longer wants; --timeout is the way out for automation that needs a
#: bound of its own, and hitting it reports honestly that the job is unfinished
#: rather than failed.
POLL_FOREVER: float = float("inf")


def require_finite(value: Optional[float], flag: str) -> Optional[float]:
    """Reject NaN/Infinity before they reach the wire (fix(#685 review)).

    Click parses ``nan``, ``inf`` and overflowing literals like ``1e309`` into
    real float values, and JSON has no way to spell any of them: the encoder
    downstream either emits non-standard tokens or raises from inside the SDK,
    neither of which reads as "that argument was not a number".
    """
    if value is None:
        return None
    if not math.isfinite(value):
        raise ValueError(f"{flag} must be a finite number")
    return value


def _dataset_id_arg(dataset_id: Optional[str], flag: str) -> Any:
    """Coerce a dataset-id option to the UUID the SDK models declare."""
    from geolens.types import UNSET

    if not dataset_id:
        return UNSET
    try:
        return UUID(dataset_id)
    except ValueError as exc:
        raise ValueError(f"{flag} is not a valid id: {dataset_id}") from exc


def parse_join_fields(raw: Optional[str]) -> Optional[list[str]]:
    """Split ``--join-fields`` on commas, dropping the whitespace around them.

    One comma-separated flag rather than a repeatable one because the columns
    are a set the server validates as a unit — it rejects the whole list if a
    name repeats or is missing from the join layer.
    """
    if raw is None:
        return None
    fields = [part.strip() for part in raw.split(",") if part.strip()]
    if not fields:
        raise ValueError("--join-fields needs at least one column name")
    return fields


def _require_join_dataset(operation: str, join_dataset_id: Optional[str]) -> None:
    """Reject a spatial_join with no join layer before it reaches the wire.

    fix(#1105): the one server rule this module copies, and deliberately so.
    The operation list stays uncopied (see the module docstring), but this
    condition is about a flag the CLI owns the name of: without it the request
    comes back 422 and ``unwrap`` reports it as a generic failure (exit 1),
    naming the JSON field ``join_dataset_id`` the user never typed. The
    server's rule is ``_require_analysis_params`` in
    backend/app/modules/catalog/datasets/domain/schemas.py; the wording below
    mirrors it and adds the flag that supplies it.
    """
    if operation == "spatial_join" and not join_dataset_id:
        raise ValueError(
            "spatial_join requires join_dataset_id: "
            "pass --join-dataset-id <dataset-id>"
        )


def build_preview_request(
    operation: str,
    *,
    distance_meters: Optional[float] = None,
    mask_dataset_id: Optional[str] = None,
    join_dataset_id: Optional[str] = None,
    join_fields: Optional[str] = None,
) -> Any:
    """Build an AnalysisPreviewRequest, omitting the params that were not given.

    Unset beats null: the request model is deliberately flat and the server
    strips params belonging to other operations, so sending an explicit null
    for every unused field would only make the wire payload noisier.
    """
    from geolens.models.analysis_preview_request import AnalysisPreviewRequest
    from geolens.types import UNSET

    _require_join_dataset(operation, join_dataset_id)
    distance_meters = require_finite(distance_meters, "--distance")
    parsed_join_fields = parse_join_fields(join_fields)
    return AnalysisPreviewRequest(
        operation=operation,  # type: ignore[arg-type]  # the SDK enum is the authority
        distance_meters=UNSET if distance_meters is None else distance_meters,
        mask_dataset_id=_dataset_id_arg(mask_dataset_id, "--mask-dataset"),
        join_dataset_id=_dataset_id_arg(join_dataset_id, "--join-dataset-id"),
        join_fields=UNSET if parsed_join_fields is None else parsed_join_fields,
    )


def build_materialize_request(
    operation: str,
    title: str,
    *,
    distance_meters: Optional[float] = None,
    mask_dataset_id: Optional[str] = None,
    by_field: Optional[str] = None,
    join_dataset_id: Optional[str] = None,
    join_fields: Optional[str] = None,
) -> Any:
    """Build an AnalysisMaterializeRequest. See build_preview_request on UNSET."""
    from geolens.models.analysis_materialize_request import AnalysisMaterializeRequest
    from geolens.types import UNSET

    _require_join_dataset(operation, join_dataset_id)
    distance_meters = require_finite(distance_meters, "--distance")
    parsed_join_fields = parse_join_fields(join_fields)
    return AnalysisMaterializeRequest(
        operation=operation,  # type: ignore[arg-type]  # the SDK enum is the authority
        title=title,
        distance_meters=UNSET if distance_meters is None else distance_meters,
        mask_dataset_id=_dataset_id_arg(mask_dataset_id, "--mask-dataset"),
        by_field=UNSET if by_field is None else by_field,
        join_dataset_id=_dataset_id_arg(join_dataset_id, "--join-dataset-id"),
        join_fields=UNSET if parsed_join_fields is None else parsed_join_fields,
    )


def run_preview(client: Any, dataset_id: str, request: Any) -> Any:
    """POST the preview and return the parsed AnalysisPreviewResponse."""
    from geolens.api.datasets_analysis import (
        analysis_preview_endpoint_datasets_dataset_id_analysis_preview_post as _preview,
    )

    resp = call_sdk(
        _preview.sync_detailed,
        dataset_id=dataset_id,
        client=client,
        body=request,
    )
    return unwrap(resp, expected=200)


def run_materialize(client: Any, dataset_id: str, request: Any) -> Any:
    """POST the materialize request and return the parsed job response.

    fix(#1778 review round 5): this expects 200 back, not a fire-and-
    forget 202 — the backend does the submit-time validation/setup work
    synchronously before responding, which can outlast AppState.sdk()'s
    plain 30s bound for a large or complex request. Wrapped in
    ``upload_timeout()``.
    """
    from geolens.api.datasets_analysis import (
        analysis_materialize_endpoint_datasets_dataset_id_analysis_materialize_post as _materialize,
    )

    with upload_timeout(client):
        resp = call_sdk(
            _materialize.sync_detailed,
            dataset_id=dataset_id,
            client=client,
            body=request,
        )
    return unwrap(resp, expected=200)


def job_snapshot(client: Any, job_id: str) -> tuple[Optional[str], Optional[str]]:
    """``(status, dataset_id)`` for a job, or ``(None, None)`` when unreadable.

    ``resolve_dataset_id`` collapses "the job failed", "the poll ran out" and
    "the job endpoint would not answer" into one ``None``, and those deserve
    different sentences even though all three mean "no dataset" (fix(#685
    review)).

    The dataset id rides along because the job can finish between the poll's
    last look and this one: the status response carries the id, and discarding
    it would report a completed job as unfinished.

    A 401/403 is raised rather than reported, so the exit code matches what
    actually went wrong (D-32) instead of collapsing into the generic one.
    """
    from geolens.api.admin import get_job_status_jobs_job_id_get

    try:
        job_uuid = UUID(str(job_id))
    except ValueError:
        return None, None
    resp = call_sdk(
        get_job_status_jobs_job_id_get.sync_detailed,
        job_id=job_uuid,
        client=client,
    )
    code = int(resp.status_code)
    if code in (401, 403):
        typer.secho(
            "Authentication failed while reading the job status. "
            "Run `geolens login` first.",
            fg="red",
            err=True,
        )
        raise typer.Exit(EXIT_AUTH)
    if code != 200:
        return None, None
    dataset_id = getattr(resp.parsed, "dataset_id", None)
    return getattr(resp.parsed, "status", None), (
        str(dataset_id) if dataset_id else None
    )


def preview_geojson(response: Any) -> dict:
    """The FeatureCollection from a preview response, as a plain dict.

    The generated model wraps it in an attrs class whose ``to_dict`` gives the
    GeoJSON back verbatim; a caller piping stdout into a .geojson file needs
    that, not the envelope.
    """
    geojson = getattr(response, "geojson", None)
    if geojson is None:
        return {"type": "FeatureCollection", "features": []}
    to_dict = getattr(geojson, "to_dict", None)
    return to_dict() if callable(to_dict) else dict(geojson)


def render_geojson(payload: dict, *, compact: bool = False) -> str:
    """Format the FeatureCollection for stdout.

    Same contract as ``geolens export stac`` (D-27: pretty with sorted keys
    by default, single-line under ``--compact``), and the same implementation,
    so the two commands cannot drift into different JSON shapes.
    """
    from .export_stac import render_stac_json

    return render_stac_json(payload, compact=compact)


def truncation_warning(response: Any) -> Optional[str]:
    """Message for a capped preview, or None when the result is complete.

    The cap is silent in the GeoJSON itself, so a scripted caller that only
    reads stdout would treat the first 500 features as the whole answer.
    """
    if not getattr(response, "truncated", False):
        return None
    shown = getattr(response, "feature_count", None)
    total = getattr(response, "source_feature_count", None)
    if total:
        return (
            f"Preview capped at {shown} of {total} source features. "
            "Use `geolens analysis materialize` to run over every feature."
        )
    return (
        f"Preview capped at {shown} features. "
        "Use `geolens analysis materialize` to run over every feature."
    )
