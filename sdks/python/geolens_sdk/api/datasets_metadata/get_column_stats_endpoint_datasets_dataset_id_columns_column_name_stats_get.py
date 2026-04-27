from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.column_stats_response import ColumnStatsResponse
from ...models.problem_detail import ProblemDetail
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    column_name: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/datasets/{dataset_id}/columns/{column_name}/stats/".format(
            dataset_id=quote(str(dataset_id), safe=""),
            column_name=quote(str(column_name), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ColumnStatsResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = ColumnStatsResponse.from_dict(response.json())

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
) -> Response[ColumnStatsResponse | ProblemDetail]:
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
) -> Response[ColumnStatsResponse | ProblemDetail]:
    """Get Column Stats Endpoint

     Get statistics for a numeric dataset column (for graduated styling).

    Args:
        dataset_id (UUID):
        column_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ColumnStatsResponse | ProblemDetail]
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
) -> ColumnStatsResponse | ProblemDetail | None:
    """Get Column Stats Endpoint

     Get statistics for a numeric dataset column (for graduated styling).

    Args:
        dataset_id (UUID):
        column_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ColumnStatsResponse | ProblemDetail
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
) -> Response[ColumnStatsResponse | ProblemDetail]:
    """Get Column Stats Endpoint

     Get statistics for a numeric dataset column (for graduated styling).

    Args:
        dataset_id (UUID):
        column_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ColumnStatsResponse | ProblemDetail]
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
) -> ColumnStatsResponse | ProblemDetail | None:
    """Get Column Stats Endpoint

     Get statistics for a numeric dataset column (for graduated styling).

    Args:
        dataset_id (UUID):
        column_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ColumnStatsResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            column_name=column_name,
            client=client,
        )
    ).parsed
