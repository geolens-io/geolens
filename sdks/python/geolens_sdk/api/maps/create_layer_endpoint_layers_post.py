from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.create_layer_request import CreateLayerRequest
from ...models.create_layer_response import CreateLayerResponse
from ...models.http_validation_error import HTTPValidationError


def _get_kwargs(
    *,
    body: CreateLayerRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/layers/",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> CreateLayerResponse | HTTPValidationError | None:
    if response.status_code == 201:
        response_201 = CreateLayerResponse.from_dict(response.json())

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
) -> Response[CreateLayerResponse | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: CreateLayerRequest,
) -> Response[CreateLayerResponse | HTTPValidationError]:
    """Create Layer Endpoint

     Create a new empty spatial layer.

    Creates a PostGIS table with a typed geometry column, runs the full
    post-processing pipeline (geom_4326, spatial index, reader grants),
    and registers the layer as a catalog dataset.

    Requires editor or admin role.

    Args:
        body (CreateLayerRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CreateLayerResponse | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: CreateLayerRequest,
) -> CreateLayerResponse | HTTPValidationError | None:
    """Create Layer Endpoint

     Create a new empty spatial layer.

    Creates a PostGIS table with a typed geometry column, runs the full
    post-processing pipeline (geom_4326, spatial index, reader grants),
    and registers the layer as a catalog dataset.

    Requires editor or admin role.

    Args:
        body (CreateLayerRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CreateLayerResponse | HTTPValidationError
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: CreateLayerRequest,
) -> Response[CreateLayerResponse | HTTPValidationError]:
    """Create Layer Endpoint

     Create a new empty spatial layer.

    Creates a PostGIS table with a typed geometry column, runs the full
    post-processing pipeline (geom_4326, spatial index, reader grants),
    and registers the layer as a catalog dataset.

    Requires editor or admin role.

    Args:
        body (CreateLayerRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CreateLayerResponse | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: CreateLayerRequest,
) -> CreateLayerResponse | HTTPValidationError | None:
    """Create Layer Endpoint

     Create a new empty spatial layer.

    Creates a PostGIS table with a typed geometry column, runs the full
    post-processing pipeline (geom_4326, spatial index, reader grants),
    and registers the layer as a catalog dataset.

    Requires editor or admin role.

    Args:
        body (CreateLayerRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CreateLayerResponse | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
