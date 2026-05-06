from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.get_geolens_sprite_index_endpoint_maps_sprites_geolens_json_get_response_get_geolens_sprite_index_endpoint_maps_sprites_geolens_json_get import (
    GetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGetResponseGetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGet,
)
from ...models.problem_detail import ProblemDetail


def _get_kwargs() -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/maps/sprites/geolens.json",
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    GetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGetResponseGetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGet
    | ProblemDetail
    | None
):
    if response.status_code == 200:
        response_200 = GetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGetResponseGetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGet.from_dict(
            response.json()
        )

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
) -> Response[
    GetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGetResponseGetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGet
    | ProblemDetail
]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
) -> Response[
    GetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGetResponseGetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGet
    | ProblemDetail
]:
    """Get Geolens Sprite Index Endpoint

     Serve the stable GeoLens sprite JSON index.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[GetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGetResponseGetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGet | ProblemDetail]
    """

    kwargs = _get_kwargs()

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
) -> (
    GetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGetResponseGetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGet
    | ProblemDetail
    | None
):
    """Get Geolens Sprite Index Endpoint

     Serve the stable GeoLens sprite JSON index.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        GetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGetResponseGetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGet | ProblemDetail
    """

    return sync_detailed(
        client=client,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
) -> Response[
    GetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGetResponseGetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGet
    | ProblemDetail
]:
    """Get Geolens Sprite Index Endpoint

     Serve the stable GeoLens sprite JSON index.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[GetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGetResponseGetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGet | ProblemDetail]
    """

    kwargs = _get_kwargs()

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
) -> (
    GetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGetResponseGetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGet
    | ProblemDetail
    | None
):
    """Get Geolens Sprite Index Endpoint

     Serve the stable GeoLens sprite JSON index.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        GetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGetResponseGetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGet | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
        )
    ).parsed
