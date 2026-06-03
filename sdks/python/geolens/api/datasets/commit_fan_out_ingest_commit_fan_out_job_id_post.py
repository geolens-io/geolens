from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.fan_out_commit_request import FanOutCommitRequest
from ...models.fan_out_commit_response import FanOutCommitResponse
from ...models.problem_detail import ProblemDetail
from uuid import UUID


def _get_kwargs(
    job_id: UUID,
    *,
    body: FanOutCommitRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/ingest/commit-fan-out/{job_id}".format(
            job_id=quote(str(job_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> FanOutCommitResponse | ProblemDetail | None:
    if response.status_code == 202:
        response_202 = FanOutCommitResponse.from_dict(response.json())

        return response_202

    if response.status_code == 400:
        response_400 = ProblemDetail.from_dict(response.json())

        return response_400

    if response.status_code == 401:
        response_401 = ProblemDetail.from_dict(response.json())

        return response_401

    if response.status_code == 403:
        response_403 = ProblemDetail.from_dict(response.json())

        return response_403

    if response.status_code == 404:
        response_404 = ProblemDetail.from_dict(response.json())

        return response_404

    if response.status_code == 409:
        response_409 = ProblemDetail.from_dict(response.json())

        return response_409

    if response.status_code == 422:
        response_422 = ProblemDetail.from_dict(response.json())

        return response_422

    if response.status_code == 500:
        response_500 = ProblemDetail.from_dict(response.json())

        return response_500

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[FanOutCommitResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    job_id: UUID,
    *,
    client: AuthenticatedClient,
    body: FanOutCommitRequest,
) -> Response[FanOutCommitResponse | ProblemDetail]:
    """Commit Fan Out

     Convert a single pending IngestJob into N independent per-layer ingest tasks.

    For multi-layer sources (e.g. GeoPackage with 2+ layers), this endpoint
    fans out the original upload into one Procrastinate task per requested
    layer, each becoming a separate dataset. The original job is marked
    'fanned_out' (a terminal state).

    Required: original job must be in status='pending'. Each layer_name in
    the request body must appear in job.user_metadata['all_layers']. Unknown
    layer names return HTTP 422 with the list of unrecognized names.

    Returns HTTP 202 with per-layer outcomes. Partial success is possible:
    each layer result carries status='queued' or status='failed' with a
    user-safe error message.

    Permission: same as POST /ingest/commit/{job_id} — 'upload' capability.

    Args:
        job_id (UUID):
        body (FanOutCommitRequest): Request body for POST /ingest/commit-fan-out/{job_id}.

            Converts one pending IngestJob (multi-layer file) into N independent
            ingest tasks — one per requested layer. Maximum 50 layers per request.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[FanOutCommitResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        job_id=job_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    job_id: UUID,
    *,
    client: AuthenticatedClient,
    body: FanOutCommitRequest,
) -> FanOutCommitResponse | ProblemDetail | None:
    """Commit Fan Out

     Convert a single pending IngestJob into N independent per-layer ingest tasks.

    For multi-layer sources (e.g. GeoPackage with 2+ layers), this endpoint
    fans out the original upload into one Procrastinate task per requested
    layer, each becoming a separate dataset. The original job is marked
    'fanned_out' (a terminal state).

    Required: original job must be in status='pending'. Each layer_name in
    the request body must appear in job.user_metadata['all_layers']. Unknown
    layer names return HTTP 422 with the list of unrecognized names.

    Returns HTTP 202 with per-layer outcomes. Partial success is possible:
    each layer result carries status='queued' or status='failed' with a
    user-safe error message.

    Permission: same as POST /ingest/commit/{job_id} — 'upload' capability.

    Args:
        job_id (UUID):
        body (FanOutCommitRequest): Request body for POST /ingest/commit-fan-out/{job_id}.

            Converts one pending IngestJob (multi-layer file) into N independent
            ingest tasks — one per requested layer. Maximum 50 layers per request.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        FanOutCommitResponse | ProblemDetail
    """

    return sync_detailed(
        job_id=job_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    job_id: UUID,
    *,
    client: AuthenticatedClient,
    body: FanOutCommitRequest,
) -> Response[FanOutCommitResponse | ProblemDetail]:
    """Commit Fan Out

     Convert a single pending IngestJob into N independent per-layer ingest tasks.

    For multi-layer sources (e.g. GeoPackage with 2+ layers), this endpoint
    fans out the original upload into one Procrastinate task per requested
    layer, each becoming a separate dataset. The original job is marked
    'fanned_out' (a terminal state).

    Required: original job must be in status='pending'. Each layer_name in
    the request body must appear in job.user_metadata['all_layers']. Unknown
    layer names return HTTP 422 with the list of unrecognized names.

    Returns HTTP 202 with per-layer outcomes. Partial success is possible:
    each layer result carries status='queued' or status='failed' with a
    user-safe error message.

    Permission: same as POST /ingest/commit/{job_id} — 'upload' capability.

    Args:
        job_id (UUID):
        body (FanOutCommitRequest): Request body for POST /ingest/commit-fan-out/{job_id}.

            Converts one pending IngestJob (multi-layer file) into N independent
            ingest tasks — one per requested layer. Maximum 50 layers per request.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[FanOutCommitResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        job_id=job_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    job_id: UUID,
    *,
    client: AuthenticatedClient,
    body: FanOutCommitRequest,
) -> FanOutCommitResponse | ProblemDetail | None:
    """Commit Fan Out

     Convert a single pending IngestJob into N independent per-layer ingest tasks.

    For multi-layer sources (e.g. GeoPackage with 2+ layers), this endpoint
    fans out the original upload into one Procrastinate task per requested
    layer, each becoming a separate dataset. The original job is marked
    'fanned_out' (a terminal state).

    Required: original job must be in status='pending'. Each layer_name in
    the request body must appear in job.user_metadata['all_layers']. Unknown
    layer names return HTTP 422 with the list of unrecognized names.

    Returns HTTP 202 with per-layer outcomes. Partial success is possible:
    each layer result carries status='queued' or status='failed' with a
    user-safe error message.

    Permission: same as POST /ingest/commit/{job_id} — 'upload' capability.

    Args:
        job_id (UUID):
        body (FanOutCommitRequest): Request body for POST /ingest/commit-fan-out/{job_id}.

            Converts one pending IngestJob (multi-layer file) into N independent
            ingest tasks — one per requested layer. Maximum 50 layers per request.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        FanOutCommitResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            job_id=job_id,
            client=client,
            body=body,
        )
    ).parsed
