from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.map_layer_input import MapLayerInput
from ...models.map_layer_response import MapLayerResponse
from ...models.problem_detail import ProblemDetail
from uuid import UUID


def _get_kwargs(
    map_id: UUID,
    *,
    body: MapLayerInput,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/maps/{map_id}/layers".format(
            map_id=quote(str(map_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> MapLayerResponse | ProblemDetail | None:
    if response.status_code == 201:
        response_201 = MapLayerResponse.from_dict(response.json())

        return response_201

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
) -> Response[MapLayerResponse | ProblemDetail]:
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
    body: MapLayerInput,
) -> Response[MapLayerResponse | ProblemDetail]:
    """Add Layer Endpoint

     Add a layer to a map.

    Phase 280: declared on both slash variants directly so neither emits a
    307. FastAPI's default redirect_slashes builds a relative Location
    header that resolves against the request's Host header, leaking the
    in-container ``api:8000`` hostname through Vite's dev proxy. The
    canonical (OpenAPI-published) form is the no-slash sub-collection
    convention from ``docs/api-style.md``; the trailing-slash form is a
    hidden alias for callers that send the slash.

    Args:
        map_id (UUID):
        body (MapLayerInput):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[MapLayerResponse | ProblemDetail]
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
    body: MapLayerInput,
) -> MapLayerResponse | ProblemDetail | None:
    """Add Layer Endpoint

     Add a layer to a map.

    Phase 280: declared on both slash variants directly so neither emits a
    307. FastAPI's default redirect_slashes builds a relative Location
    header that resolves against the request's Host header, leaking the
    in-container ``api:8000`` hostname through Vite's dev proxy. The
    canonical (OpenAPI-published) form is the no-slash sub-collection
    convention from ``docs/api-style.md``; the trailing-slash form is a
    hidden alias for callers that send the slash.

    Args:
        map_id (UUID):
        body (MapLayerInput):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        MapLayerResponse | ProblemDetail
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
    body: MapLayerInput,
) -> Response[MapLayerResponse | ProblemDetail]:
    """Add Layer Endpoint

     Add a layer to a map.

    Phase 280: declared on both slash variants directly so neither emits a
    307. FastAPI's default redirect_slashes builds a relative Location
    header that resolves against the request's Host header, leaking the
    in-container ``api:8000`` hostname through Vite's dev proxy. The
    canonical (OpenAPI-published) form is the no-slash sub-collection
    convention from ``docs/api-style.md``; the trailing-slash form is a
    hidden alias for callers that send the slash.

    Args:
        map_id (UUID):
        body (MapLayerInput):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[MapLayerResponse | ProblemDetail]
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
    body: MapLayerInput,
) -> MapLayerResponse | ProblemDetail | None:
    """Add Layer Endpoint

     Add a layer to a map.

    Phase 280: declared on both slash variants directly so neither emits a
    307. FastAPI's default redirect_slashes builds a relative Location
    header that resolves against the request's Host header, leaking the
    in-container ``api:8000`` hostname through Vite's dev proxy. The
    canonical (OpenAPI-published) form is the no-slash sub-collection
    convention from ``docs/api-style.md``; the trailing-slash form is a
    hidden alias for callers that send the slash.

    Args:
        map_id (UUID):
        body (MapLayerInput):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        MapLayerResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            map_id=map_id,
            client=client,
            body=body,
        )
    ).parsed
