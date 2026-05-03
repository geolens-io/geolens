from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.column_list_response import ColumnListResponse
from ...models.http_validation_error import HTTPValidationError
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    column_name: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "delete",
        "url": "/layers/{dataset_id}/columns/{column_name}".format(
            dataset_id=quote(str(dataset_id), safe=""),
            column_name=quote(str(column_name), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ColumnListResponse | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = ColumnListResponse.from_dict(response.json())

        return response_200

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
    column_name: str,
    *,
    client: AuthenticatedClient,
) -> Response[ColumnListResponse | HTTPValidationError]:
    """Drop Column Endpoint

     Remove a column from an existing layer.

    Args:
        dataset_id (UUID):
        column_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ColumnListResponse | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        column_name=column_name,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    column_name: str,
    *,
    client: AuthenticatedClient,
) -> ColumnListResponse | HTTPValidationError | None:
    """Drop Column Endpoint

     Remove a column from an existing layer.

    Args:
        dataset_id (UUID):
        column_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ColumnListResponse | HTTPValidationError
    """

    return sync_detailed(
        dataset_id=dataset_id,
        column_name=column_name,
        client=client,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    column_name: str,
    *,
    client: AuthenticatedClient,
) -> Response[ColumnListResponse | HTTPValidationError]:
    """Drop Column Endpoint

     Remove a column from an existing layer.

    Args:
        dataset_id (UUID):
        column_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ColumnListResponse | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        column_name=column_name,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    column_name: str,
    *,
    client: AuthenticatedClient,
) -> ColumnListResponse | HTTPValidationError | None:
    """Drop Column Endpoint

     Remove a column from an existing layer.

    Args:
        dataset_id (UUID):
        column_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ColumnListResponse | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            column_name=column_name,
            client=client,
        )
    ).parsed
