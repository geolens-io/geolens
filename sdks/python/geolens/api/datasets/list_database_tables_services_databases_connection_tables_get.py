from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.database_table_list_response import DatabaseTableListResponse
from ...models.problem_detail import ProblemDetail


def _get_kwargs(
    connection: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/services/databases/{connection}/tables/".format(
            connection=quote(str(connection), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> DatabaseTableListResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = DatabaseTableListResponse.from_dict(response.json())

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

    if response.status_code == 502:
        response_502 = ProblemDetail.from_dict(response.json())

        return response_502

    if response.status_code == 503:
        response_503 = ProblemDetail.from_dict(response.json())

        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[DatabaseTableListResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    connection: str,
    *,
    client: AuthenticatedClient,
) -> Response[DatabaseTableListResponse | ProblemDetail]:
    """List a database connection's spatial tables

     List the tables and views with a geometry or geography column that the
    connection's login can read.

    Connections come from the deployment's `DATABASE_SOURCES`. A 502 means the
    server could not be reached or signed in to, or a table could not be read;
    the detail names only the connection.

    Args:
        connection (str): Connection name.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DatabaseTableListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        connection=connection,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    connection: str,
    *,
    client: AuthenticatedClient,
) -> DatabaseTableListResponse | ProblemDetail | None:
    """List a database connection's spatial tables

     List the tables and views with a geometry or geography column that the
    connection's login can read.

    Connections come from the deployment's `DATABASE_SOURCES`. A 502 means the
    server could not be reached or signed in to, or a table could not be read;
    the detail names only the connection.

    Args:
        connection (str): Connection name.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DatabaseTableListResponse | ProblemDetail
    """

    return sync_detailed(
        connection=connection,
        client=client,
    ).parsed


async def asyncio_detailed(
    connection: str,
    *,
    client: AuthenticatedClient,
) -> Response[DatabaseTableListResponse | ProblemDetail]:
    """List a database connection's spatial tables

     List the tables and views with a geometry or geography column that the
    connection's login can read.

    Connections come from the deployment's `DATABASE_SOURCES`. A 502 means the
    server could not be reached or signed in to, or a table could not be read;
    the detail names only the connection.

    Args:
        connection (str): Connection name.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DatabaseTableListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        connection=connection,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    connection: str,
    *,
    client: AuthenticatedClient,
) -> DatabaseTableListResponse | ProblemDetail | None:
    """List a database connection's spatial tables

     List the tables and views with a geometry or geography column that the
    connection's login can read.

    Connections come from the deployment's `DATABASE_SOURCES`. A 502 means the
    server could not be reached or signed in to, or a table could not be read;
    the detail names only the connection.

    Args:
        connection (str): Connection name.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DatabaseTableListResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            connection=connection,
            client=client,
        )
    ).parsed
