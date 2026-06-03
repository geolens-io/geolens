from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.bulk_delete_layers_request import BulkDeleteLayersRequest
from ...models.bulk_delete_layers_response import BulkDeleteLayersResponse
from ...models.problem_detail import ProblemDetail
from uuid import UUID


def _get_kwargs(
    map_id: UUID,
    *,
    body: BulkDeleteLayersRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/maps/{map_id}/layers/bulk-delete".format(
            map_id=quote(str(map_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> BulkDeleteLayersResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = BulkDeleteLayersResponse.from_dict(response.json())

        return response_200

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
) -> Response[BulkDeleteLayersResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    map_id: UUID,
    *,
    client: AuthenticatedClient,
    body: BulkDeleteLayersRequest,
) -> Response[BulkDeleteLayersResponse | ProblemDetail]:
    """Bulk Delete Layers Endpoint

     Batch-delete multiple layers from a map in a single request.

    Milestone exception (v1010 Phase 1047): one additive endpoint permitted
    per REQUIREMENTS.md Out-of-Scope to reduce N sequential DELETEs to one
    batched call for bulk-delete UX (PB-03 / PERF-03).

    Returns 200 with deleted/failed arrays in all cases (partial failures
    surface inline, not as HTTP errors).  Full rollback is the caller's
    responsibility if all ids fail.

    Args:
        map_id (UUID):
        body (BulkDeleteLayersRequest): Request body for POST /maps/{map_id}/layers/bulk-delete.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[BulkDeleteLayersResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        map_id=map_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    map_id: UUID,
    *,
    client: AuthenticatedClient,
    body: BulkDeleteLayersRequest,
) -> BulkDeleteLayersResponse | ProblemDetail | None:
    """Bulk Delete Layers Endpoint

     Batch-delete multiple layers from a map in a single request.

    Milestone exception (v1010 Phase 1047): one additive endpoint permitted
    per REQUIREMENTS.md Out-of-Scope to reduce N sequential DELETEs to one
    batched call for bulk-delete UX (PB-03 / PERF-03).

    Returns 200 with deleted/failed arrays in all cases (partial failures
    surface inline, not as HTTP errors).  Full rollback is the caller's
    responsibility if all ids fail.

    Args:
        map_id (UUID):
        body (BulkDeleteLayersRequest): Request body for POST /maps/{map_id}/layers/bulk-delete.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        BulkDeleteLayersResponse | ProblemDetail
    """

    return sync_detailed(
        map_id=map_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    map_id: UUID,
    *,
    client: AuthenticatedClient,
    body: BulkDeleteLayersRequest,
) -> Response[BulkDeleteLayersResponse | ProblemDetail]:
    """Bulk Delete Layers Endpoint

     Batch-delete multiple layers from a map in a single request.

    Milestone exception (v1010 Phase 1047): one additive endpoint permitted
    per REQUIREMENTS.md Out-of-Scope to reduce N sequential DELETEs to one
    batched call for bulk-delete UX (PB-03 / PERF-03).

    Returns 200 with deleted/failed arrays in all cases (partial failures
    surface inline, not as HTTP errors).  Full rollback is the caller's
    responsibility if all ids fail.

    Args:
        map_id (UUID):
        body (BulkDeleteLayersRequest): Request body for POST /maps/{map_id}/layers/bulk-delete.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[BulkDeleteLayersResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        map_id=map_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    map_id: UUID,
    *,
    client: AuthenticatedClient,
    body: BulkDeleteLayersRequest,
) -> BulkDeleteLayersResponse | ProblemDetail | None:
    """Bulk Delete Layers Endpoint

     Batch-delete multiple layers from a map in a single request.

    Milestone exception (v1010 Phase 1047): one additive endpoint permitted
    per REQUIREMENTS.md Out-of-Scope to reduce N sequential DELETEs to one
    batched call for bulk-delete UX (PB-03 / PERF-03).

    Returns 200 with deleted/failed arrays in all cases (partial failures
    surface inline, not as HTTP errors).  Full rollback is the caller's
    responsibility if all ids fail.

    Args:
        map_id (UUID):
        body (BulkDeleteLayersRequest): Request body for POST /maps/{map_id}/layers/bulk-delete.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        BulkDeleteLayersResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            map_id=map_id,
            client=client,
            body=body,
        )
    ).parsed
