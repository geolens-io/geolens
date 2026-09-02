# SPDX-License-Identifier: Apache-2.0
"""Dataset replace: reupload a file over an existing dataset's data.

Hand-maintained, NOT regenerated. Runs the same 3-step flow as ``publish``
(upload -> preview -> commit), pointed at ``/datasets/{id}/reupload*``
instead of ``/ingest/*``. Reuses ``publish.py``'s multipart-upload
workaround (the generated ``to_multipart()`` for the reupload body has the
identical bug, packing ``(None, str(self.file).encode(), 'text/plain')``
instead of a real file) and ``refresh.py``'s job poller and ProblemDetail
parsing, rather than re-implementing either.

gh#1739: the only supported way to replace an uploaded dataset's data from a
local file. A dataset whose data comes from a server-stored source binding
is refreshed with ``geolens refresh`` instead; that endpoint pulls from the
stored origin and takes no file.
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from . import publish as _publish
from ._sdk_helpers import EXIT_AUTH, EXIT_GENERIC, EXIT_SERVER
from .refresh import _problem_detail

#: Upload returns 201 Created (ReuploadResponse). Cited:
#: sdks/python/geolens/api/datasets_reupload/
#:   reupload_dataset_datasets_dataset_id_reupload_post.py
UPLOAD_OK_STATUS = 201

#: Preview returns 200 OK (ReuploadPreviewResponse).
PREVIEW_OK_STATUS = 200

#: Commit returns 202 Accepted (ReuploadCommitResponse with status="pending").
COMMIT_OK_STATUS = 202


@dataclass(frozen=True)
class ReplaceRequestError(Exception):
    """A replace-flow refusal translated into a stable CLI message + exit code."""

    message: str
    exit_code: int = EXIT_GENERIC
    code: str | None = None


# ---------------------------------------------------------------------------
# Multipart upload (same workaround as publish.upload_file)
# ---------------------------------------------------------------------------


def upload_file(client: Any, dataset_id: UUID, path: Path) -> Any:
    """Upload a replacement file via the SDK-owned httpx client.

    Same multipart workaround as ``publish.upload_file``: the generated
    ``BodyReuploadDatasetDatasetsDatasetIdReuploadPost.to_multipart()`` packs
    a text field instead of a real file, so this builds the multipart
    payload directly on the SDK's httpx client instead. OCCLI-06: the client
    comes from ``client.get_httpx_client()``, never a direct ``httpx``
    construction.
    """
    from geolens.api.datasets_reupload import (
        reupload_dataset_datasets_dataset_id_reupload_post as _reupload,
    )
    from geolens.types import Response

    httpx_client = client.get_httpx_client()
    with path.open("rb") as fh:
        files = {"file": (path.name, fh, _publish.guess_mime(path))}
        raw = httpx_client.post(f"/datasets/{dataset_id}/reupload", files=files)
    parsed = _reupload._parse_response(client=client, response=raw)
    return Response(
        status_code=HTTPStatus(raw.status_code),
        content=raw.content,
        headers=raw.headers,
        parsed=parsed,
    )


# ---------------------------------------------------------------------------
# Request builders
# ---------------------------------------------------------------------------


def build_preview_request(layer_name: Optional[str]) -> Any:
    """Build the reupload preview request body (UNSET when no layer given)."""
    from geolens.models.reupload_preview_request import ReuploadPreviewRequest
    from geolens.types import UNSET

    if layer_name is None:
        return UNSET
    return ReuploadPreviewRequest(layer_name=layer_name)


def build_commit_request(
    *, layer_name: Optional[str], srid_override: Optional[int]
) -> Any:
    """Build a ReuploadCommitRequest. No ``token``; replace is file-only."""
    from geolens.models.reupload_commit_request import ReuploadCommitRequest
    from geolens.types import UNSET

    return ReuploadCommitRequest(
        layer_name=layer_name if layer_name is not None else UNSET,
        srid_override=srid_override if srid_override is not None else UNSET,
    )


# ---------------------------------------------------------------------------
# Preview inspection
# ---------------------------------------------------------------------------


def layer_summaries(preview: Any) -> list[dict[str, Any]]:
    """Extract ``{name, feature_count}`` entries from a preview's all_layers.

    ``all_layers`` items are opaque generated models; the real content
    lives in ``.additional_properties`` (``name``, ``feature_count``,
    ``field_count``; see ``backend/app/processing/ingest/ogr.py``).
    """
    from geolens.types import Unset

    all_layers = getattr(preview, "all_layers", None)
    if all_layers is None or isinstance(all_layers, Unset):
        return []
    summaries: list[dict[str, Any]] = []
    for item in all_layers:
        props = getattr(item, "additional_properties", None) or {}
        summaries.append(
            {
                "name": props.get("name", ""),
                "feature_count": props.get("feature_count"),
            }
        )
    return summaries


def is_multi_layer(preview: Any) -> bool:
    """True when the source file has more than one layer.

    The backend only populates ``all_layers`` when the file has more than
    one layer, so a non-empty list is itself the multi-layer signal.
    """
    return len(layer_summaries(preview)) > 0


def preview_summary(preview: Any) -> dict[str, Any]:
    """Select the stable preview fields worth printing before commit."""
    return {
        "layer_name": getattr(preview, "layer_name", None),
        "feature_count": getattr(preview, "feature_count", None),
        "srid": getattr(preview, "crs", None),
        "geometry_type": getattr(preview, "geometry_type", None),
    }


def multi_layer_refusal_message(layers: list[dict[str, Any]]) -> str:
    """Build the refusal text listing every layer, so the user can pick one."""
    lines = [
        f"  {entry['name']} ({entry['feature_count']} features)"
        for entry in layers
    ]
    return "This file has more than one layer; pass --layer to choose one:\n" + "\n".join(
        lines
    )


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------

_REFUSAL_MESSAGES: dict[str, str] = {
    # The reverse of refresh.py's `refresh_not_applicable`: this dataset's
    # data comes from a server-stored source binding, not an upload, so a
    # file replace is the wrong tool.
    "refresh_not_applicable": (
        "This dataset's data comes from a remote service origin, not an "
        "upload. Run `geolens refresh <dataset-id>` to update it instead."
    ),
    "dataset_busy": (
        "A refresh or re-upload is already running for this dataset. Wait "
        "for it to finish, then try again."
    ),
    "job_conflict": (
        "The job changed while this commit was in flight, so nothing was "
        "queued. Run `geolens replace` again."
    ),
    "credential_store_unavailable": (
        "GeoLens could not stage this request. Ask an operator to check the "
        "shared credential store, then try again."
    ),
    "invalid_service_token": (
        "GeoLens rejected the request. Check the dataset's status and try "
        "again."
    ),
}


def replace_request_error(response: Any) -> ReplaceRequestError:
    """Translate a non-2xx SDK response into a stable CLI message.

    404 and 403 stay plain: the server's own detail text, not a
    reconstructed hint, per gh#1739. 409 codes get the same actionable
    treatment refresh.py gives its own refusals.
    """
    status_code = int(response.status_code)
    code, server_message = _problem_detail(response.parsed)

    if status_code == 404:
        return ReplaceRequestError(server_message or "Dataset not found.", code=code)
    if status_code in {401, 403}:
        return ReplaceRequestError(
            server_message
            or "Authentication or edit permission is required to replace "
            "this dataset's data.",
            exit_code=EXIT_AUTH,
            code=code,
        )
    if code in _REFUSAL_MESSAGES:
        return ReplaceRequestError(
            _REFUSAL_MESSAGES[code],
            exit_code=EXIT_SERVER if status_code >= 500 else EXIT_GENERIC,
            code=code,
        )
    if status_code >= 500:
        return ReplaceRequestError(
            server_message or f"GeoLens could not process the replace ({status_code}).",
            exit_code=EXIT_SERVER,
            code=code,
        )
    return ReplaceRequestError(
        server_message or f"Replace request failed ({status_code}).",
        code=code,
    )


def unwrap_or_raise(response: Any, *, expected: int) -> Any:
    """Return the parsed body on the expected status, else raise."""
    if int(response.status_code) == expected:
        return response.parsed
    raise replace_request_error(response)
