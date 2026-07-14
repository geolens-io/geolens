from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.alter_column_type_request import AlterColumnTypeRequest
from ...models.column_list_response import ColumnListResponse
from ...models.problem_detail import ProblemDetail
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    column_name: str,
    *,
    body: AlterColumnTypeRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/layers/{dataset_id}/columns/{column_name}/type".format(
            dataset_id=quote(str(dataset_id), safe=""),
            column_name=quote(str(column_name), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ColumnListResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = ColumnListResponse.from_dict(response.json())

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

    if response.status_code == 429:
        response_429 = ProblemDetail.from_dict(response.json())

        return response_429

    if response.status_code == 500:
        response_500 = ProblemDetail.from_dict(response.json())

        return response_500

    if response.status_code == 503:
        response_503 = ProblemDetail.from_dict(response.json())

        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[ColumnListResponse | ProblemDetail]:
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
    body: AlterColumnTypeRequest,
) -> Response[ColumnListResponse | ProblemDetail]:
    """Alter Column Type Endpoint

     Change a column's type on an existing layer.

    Postgres performs an implicit ``column::TYPE`` cast; values that cannot be
    cast cause the request to fail and roll back.

    Args:
        dataset_id (UUID):
        column_name (str):
        body (AlterColumnTypeRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ColumnListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        column_name=column_name,
        body=body,
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
    body: AlterColumnTypeRequest,
) -> ColumnListResponse | ProblemDetail | None:
    """Alter Column Type Endpoint

     Change a column's type on an existing layer.

    Postgres performs an implicit ``column::TYPE`` cast; values that cannot be
    cast cause the request to fail and roll back.

    Args:
        dataset_id (UUID):
        column_name (str):
        body (AlterColumnTypeRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ColumnListResponse | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        column_name=column_name,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    column_name: str,
    *,
    client: AuthenticatedClient,
    body: AlterColumnTypeRequest,
) -> Response[ColumnListResponse | ProblemDetail]:
    """Alter Column Type Endpoint

     Change a column's type on an existing layer.

    Postgres performs an implicit ``column::TYPE`` cast; values that cannot be
    cast cause the request to fail and roll back.

    Args:
        dataset_id (UUID):
        column_name (str):
        body (AlterColumnTypeRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ColumnListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        column_name=column_name,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    column_name: str,
    *,
    client: AuthenticatedClient,
    body: AlterColumnTypeRequest,
) -> ColumnListResponse | ProblemDetail | None:
    """Alter Column Type Endpoint

     Change a column's type on an existing layer.

    Postgres performs an implicit ``column::TYPE`` cast; values that cannot be
    cast cause the request to fail and roll back.

    Args:
        dataset_id (UUID):
        column_name (str):
        body (AlterColumnTypeRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ColumnListResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            column_name=column_name,
            client=client,
            body=body,
        )
    ).parsed
