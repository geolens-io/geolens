# SPDX-License-Identifier: Apache-2.0
"""Analysis commands — preview a PostGIS operation, or save it as a dataset.

Hand-maintained — NOT regenerated. Pure SDK pass-through (D-25, D-28): the
backend at ``backend/app/modules/catalog/datasets/api/router_analysis.py``
owns every rule, and the CLI carries no copy of them.

That includes the operation list. ``--operation`` is handed to the SDK
unchanged rather than validated against a literal here, so the generated
enum stays the single authority and a new backend operation reaches the CLI
with the next ``make sdks`` instead of a second list to keep in step (#685).

OCCLI-06 invariant: zero direct ``httpx`` / ``requests`` imports — every HTTP
call goes through the generated SDK functions.
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from ._sdk_helpers import call_sdk, unwrap

#: Distances are metres on the wire, matching the API and the map builder's
#: unit picker (AnalysisPanel converts feet/miles before it POSTs).
DISTANCE_UNIT = "metres"

#: fix(#685 review): publish's 120s poll default is far too short here. The
#: server gives a materialize 300s of processing on its own
#: (MATERIALIZE_TIMEOUT, backend/app/processing/analysis/tasks.py), and #703
#: deliberately queues analysis BELOW uploads, so a legitimate run can sit
#: waiting for minutes before it starts. Ten minutes covers both with room.
#: A constant rather than a --timeout option on purpose: the flag is worth
#: adding when someone has a job that legitimately outlives this, and not
#: before.
POLL_TIMEOUT_SECONDS: float = 600.0


def _mask_dataset_arg(mask_dataset_id: Optional[str]) -> Any:
    """Coerce a mask dataset id to the UUID the SDK models declare."""
    from geolens.types import UNSET

    if not mask_dataset_id:
        return UNSET
    try:
        return UUID(mask_dataset_id)
    except ValueError as exc:
        raise ValueError(f"--mask-dataset is not a valid id: {mask_dataset_id}") from exc


def build_preview_request(
    operation: str,
    *,
    distance_meters: Optional[float] = None,
    mask_dataset_id: Optional[str] = None,
) -> Any:
    """Build an AnalysisPreviewRequest, omitting the params that were not given.

    Unset beats null: the request model is deliberately flat and the server
    strips params belonging to other operations, so sending an explicit null
    for every unused field would only make the wire payload noisier.
    """
    from geolens.models.analysis_preview_request import AnalysisPreviewRequest
    from geolens.types import UNSET

    return AnalysisPreviewRequest(
        operation=operation,  # type: ignore[arg-type]  # the SDK enum is the authority
        distance_meters=UNSET if distance_meters is None else distance_meters,
        mask_dataset_id=_mask_dataset_arg(mask_dataset_id),
    )


def build_materialize_request(
    operation: str,
    title: str,
    *,
    distance_meters: Optional[float] = None,
    mask_dataset_id: Optional[str] = None,
    by_field: Optional[str] = None,
) -> Any:
    """Build an AnalysisMaterializeRequest. See build_preview_request on UNSET."""
    from geolens.models.analysis_materialize_request import AnalysisMaterializeRequest
    from geolens.types import UNSET

    return AnalysisMaterializeRequest(
        operation=operation,  # type: ignore[arg-type]  # the SDK enum is the authority
        title=title,
        distance_meters=UNSET if distance_meters is None else distance_meters,
        mask_dataset_id=_mask_dataset_arg(mask_dataset_id),
        by_field=UNSET if by_field is None else by_field,
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
    """POST the materialize request and return the parsed job response."""
    from geolens.api.datasets_analysis import (
        analysis_materialize_endpoint_datasets_dataset_id_analysis_materialize_post as _materialize,
    )

    resp = call_sdk(
        _materialize.sync_detailed,
        dataset_id=dataset_id,
        client=client,
        body=request,
    )
    return unwrap(resp, expected=200)


def job_status(client: Any, job_id: str) -> Optional[str]:
    """The job's current status, or None when it cannot be read.

    Used only to word the failure: ``resolve_dataset_id`` collapses "the job
    failed" and "the poll ran out" into the same ``None``, and those two
    deserve different sentences even though both mean "no dataset".
    """
    from geolens.api.admin import get_job_status_jobs_job_id_get

    try:
        job_uuid = UUID(str(job_id))
    except ValueError:
        return None
    resp = call_sdk(
        get_job_status_jobs_job_id_get.sync_detailed,
        job_id=job_uuid,
        client=client,
    )
    if int(resp.status_code) != 200:
        return None
    return getattr(resp.parsed, "status", None)


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
