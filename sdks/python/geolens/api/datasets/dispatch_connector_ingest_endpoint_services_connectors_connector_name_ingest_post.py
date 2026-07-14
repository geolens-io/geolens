from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.connector_ingest_request import ConnectorIngestRequest
from ...models.connector_ingest_response import ConnectorIngestResponse
from ...models.problem_detail import ProblemDetail


def _get_kwargs(
    connector_name: str,
    *,
    body: ConnectorIngestRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/services/connectors/{connector_name}/ingest/".format(
            connector_name=quote(str(connector_name), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ConnectorIngestResponse | ProblemDetail | None:
    if response.status_code == 202:
        response_202 = ConnectorIngestResponse.from_dict(response.json())

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

    if response.status_code == 504:
        response_504 = ProblemDetail.from_dict(response.json())

        return response_504

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[ConnectorIngestResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    connector_name: str,
    *,
    client: AuthenticatedClient,
    body: ConnectorIngestRequest,
) -> Response[ConnectorIngestResponse | ProblemDetail]:
    """Dispatch Connector Ingest Endpoint

     Dispatch an overlay-owned ingest and return its opaque job id.

    Args:
        connector_name (str):
        body (ConnectorIngestRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ConnectorIngestResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        connector_name=connector_name,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    connector_name: str,
    *,
    client: AuthenticatedClient,
    body: ConnectorIngestRequest,
) -> ConnectorIngestResponse | ProblemDetail | None:
    """Dispatch Connector Ingest Endpoint

     Dispatch an overlay-owned ingest and return its opaque job id.

    Args:
        connector_name (str):
        body (ConnectorIngestRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ConnectorIngestResponse | ProblemDetail
    """

    return sync_detailed(
        connector_name=connector_name,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    connector_name: str,
    *,
    client: AuthenticatedClient,
    body: ConnectorIngestRequest,
) -> Response[ConnectorIngestResponse | ProblemDetail]:
    """Dispatch Connector Ingest Endpoint

     Dispatch an overlay-owned ingest and return its opaque job id.

    Args:
        connector_name (str):
        body (ConnectorIngestRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ConnectorIngestResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        connector_name=connector_name,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    connector_name: str,
    *,
    client: AuthenticatedClient,
    body: ConnectorIngestRequest,
) -> ConnectorIngestResponse | ProblemDetail | None:
    """Dispatch Connector Ingest Endpoint

     Dispatch an overlay-owned ingest and return its opaque job id.

    Args:
        connector_name (str):
        body (ConnectorIngestRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ConnectorIngestResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            connector_name=connector_name,
            client=client,
            body=body,
        )
    ).parsed
