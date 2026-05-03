from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.add_column_request import AddColumnRequest
from ...models.column_list_response import ColumnListResponse
from ...models.http_validation_error import HTTPValidationError
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    *,
    body: AddColumnRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/layers/{dataset_id}/columns/".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ColumnListResponse | HTTPValidationError | None:
    if response.status_code == 201:
        response_201 = ColumnListResponse.from_dict(response.json())

        return response_201

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[ColumnListResponse | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    body: AddColumnRequest,
) -> Response[ColumnListResponse | HTTPValidationError]:
    """Add Column Endpoint

     Add a column to an existing layer.

    Args:
        dataset_id (UUID):
        body (AddColumnRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ColumnListResponse | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    body: AddColumnRequest,
) -> ColumnListResponse | HTTPValidationError | None:
    """Add Column Endpoint

     Add a column to an existing layer.

    Args:
        dataset_id (UUID):
        body (AddColumnRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ColumnListResponse | HTTPValidationError
    """

    return sync_detailed(
        dataset_id=dataset_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    body: AddColumnRequest,
) -> Response[ColumnListResponse | HTTPValidationError]:
    """Add Column Endpoint

     Add a column to an existing layer.

    Args:
        dataset_id (UUID):
        body (AddColumnRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ColumnListResponse | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    body: AddColumnRequest,
) -> ColumnListResponse | HTTPValidationError | None:
    """Add Column Endpoint

     Add a column to an existing layer.

    Args:
        dataset_id (UUID):
        body (AddColumnRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ColumnListResponse | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
            body=body,
        )
    ).parsed
