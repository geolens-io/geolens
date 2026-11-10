from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.database_import_request import DatabaseImportRequest
from ...models.database_import_response import DatabaseImportResponse
from ...models.problem_detail import ProblemDetail


def _get_kwargs(
    connection: str,
    *,
    body: DatabaseImportRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/services/databases/{connection}/imports/".format(
            connection=quote(str(connection), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> DatabaseImportResponse | ProblemDetail | None:
    if response.status_code == 202:
        response_202 = DatabaseImportResponse.from_dict(response.json())

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
) -> Response[DatabaseImportResponse | ProblemDetail]:
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
    body: DatabaseImportRequest,
) -> Response[DatabaseImportResponse | ProblemDetail]:
    """Import a table from a database connection

     Copy one listed table or view into a new dataset, as an ingest job.

    The table must be one the connection's listing returns for this request.
    A second import of the same table by the same user answers 409
    `duplicate_source` naming the existing dataset; refresh that one instead.

    Args:
        connection (str): Connection name.
        body (DatabaseImportRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DatabaseImportResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        connection=connection,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    connection: str,
    *,
    client: AuthenticatedClient,
    body: DatabaseImportRequest,
) -> DatabaseImportResponse | ProblemDetail | None:
    """Import a table from a database connection

     Copy one listed table or view into a new dataset, as an ingest job.

    The table must be one the connection's listing returns for this request.
    A second import of the same table by the same user answers 409
    `duplicate_source` naming the existing dataset; refresh that one instead.

    Args:
        connection (str): Connection name.
        body (DatabaseImportRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DatabaseImportResponse | ProblemDetail
    """

    return sync_detailed(
        connection=connection,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    connection: str,
    *,
    client: AuthenticatedClient,
    body: DatabaseImportRequest,
) -> Response[DatabaseImportResponse | ProblemDetail]:
    """Import a table from a database connection

     Copy one listed table or view into a new dataset, as an ingest job.

    The table must be one the connection's listing returns for this request.
    A second import of the same table by the same user answers 409
    `duplicate_source` naming the existing dataset; refresh that one instead.

    Args:
        connection (str): Connection name.
        body (DatabaseImportRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DatabaseImportResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        connection=connection,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    connection: str,
    *,
    client: AuthenticatedClient,
    body: DatabaseImportRequest,
) -> DatabaseImportResponse | ProblemDetail | None:
    """Import a table from a database connection

     Copy one listed table or view into a new dataset, as an ingest job.

    The table must be one the connection's listing returns for this request.
    A second import of the same table by the same user answers 409
    `duplicate_source` naming the existing dataset; refresh that one instead.

    Args:
        connection (str): Connection name.
        body (DatabaseImportRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DatabaseImportResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            connection=connection,
            client=client,
            body=body,
        )
    ).parsed
