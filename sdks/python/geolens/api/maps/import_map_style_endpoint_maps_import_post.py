from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.import_map_style_endpoint_maps_import_post_style import (
    ImportMapStyleEndpointMapsImportPostStyle,
)
from ...models.map_style_import_response import MapStyleImportResponse
from ...models.problem_detail import ProblemDetail


def _get_kwargs(
    *,
    body: ImportMapStyleEndpointMapsImportPostStyle,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/maps/import",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> MapStyleImportResponse | ProblemDetail | None:
    if response.status_code == 201:
        response_201 = MapStyleImportResponse.from_dict(response.json())

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
) -> Response[MapStyleImportResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: ImportMapStyleEndpointMapsImportPostStyle,
) -> Response[MapStyleImportResponse | ProblemDetail]:
    """Import Map Style Endpoint

     Import a MapLibre style JSON document into a new GeoLens map.

    Args:
        body (ImportMapStyleEndpointMapsImportPostStyle):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[MapStyleImportResponse | ProblemDetail]
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
    body: ImportMapStyleEndpointMapsImportPostStyle,
) -> MapStyleImportResponse | ProblemDetail | None:
    """Import Map Style Endpoint

     Import a MapLibre style JSON document into a new GeoLens map.

    Args:
        body (ImportMapStyleEndpointMapsImportPostStyle):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        MapStyleImportResponse | ProblemDetail
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: ImportMapStyleEndpointMapsImportPostStyle,
) -> Response[MapStyleImportResponse | ProblemDetail]:
    """Import Map Style Endpoint

     Import a MapLibre style JSON document into a new GeoLens map.

    Args:
        body (ImportMapStyleEndpointMapsImportPostStyle):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[MapStyleImportResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: ImportMapStyleEndpointMapsImportPostStyle,
) -> MapStyleImportResponse | ProblemDetail | None:
    """Import Map Style Endpoint

     Import a MapLibre style JSON document into a new GeoLens map.

    Args:
        body (ImportMapStyleEndpointMapsImportPostStyle):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        MapStyleImportResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
