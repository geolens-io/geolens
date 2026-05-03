from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...models.raster_tile_token import RasterTileToken
from ...models.vector_tile_token import VectorTileToken
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/tiles/token/{dataset_id}/".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ProblemDetail | RasterTileToken | VectorTileToken | None:
    if response.status_code == 200:

        def _parse_response_200(data: object) -> RasterTileToken | VectorTileToken:
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                response_200_type_0 = VectorTileToken.from_dict(data)

                return response_200_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            if not isinstance(data, dict):
                raise TypeError()
            response_200_type_1 = RasterTileToken.from_dict(data)

            return response_200_type_1

        response_200 = _parse_response_200(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = ProblemDetail.from_dict(response.json())

        return response_400

    if response.status_code == 404:
        response_404 = ProblemDetail.from_dict(response.json())

        return response_404

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
) -> Response[ProblemDetail | RasterTileToken | VectorTileToken]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[ProblemDetail | RasterTileToken | VectorTileToken]:
    """Get Tile Token

     Generate a tile token for a dataset.

    For vector datasets: returns HMAC-signed token (sig, exp, scope, expires_in).
    For raster datasets: returns tile URL template and metadata.

    Both responses include a discriminated ``kind`` field.

    Public datasets can be accessed without authentication.
    Private/restricted datasets require authentication and RBAC checks.

    Args:
        dataset_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | RasterTileToken | VectorTileToken]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
) -> ProblemDetail | RasterTileToken | VectorTileToken | None:
    """Get Tile Token

     Generate a tile token for a dataset.

    For vector datasets: returns HMAC-signed token (sig, exp, scope, expires_in).
    For raster datasets: returns tile URL template and metadata.

    Both responses include a discriminated ``kind`` field.

    Public datasets can be accessed without authentication.
    Private/restricted datasets require authentication and RBAC checks.

    Args:
        dataset_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | RasterTileToken | VectorTileToken
    """

    return sync_detailed(
        dataset_id=dataset_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[ProblemDetail | RasterTileToken | VectorTileToken]:
    """Get Tile Token

     Generate a tile token for a dataset.

    For vector datasets: returns HMAC-signed token (sig, exp, scope, expires_in).
    For raster datasets: returns tile URL template and metadata.

    Both responses include a discriminated ``kind`` field.

    Public datasets can be accessed without authentication.
    Private/restricted datasets require authentication and RBAC checks.

    Args:
        dataset_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | RasterTileToken | VectorTileToken]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
) -> ProblemDetail | RasterTileToken | VectorTileToken | None:
    """Get Tile Token

     Generate a tile token for a dataset.

    For vector datasets: returns HMAC-signed token (sig, exp, scope, expires_in).
    For raster datasets: returns tile URL template and metadata.

    Both responses include a discriminated ``kind`` field.

    Public datasets can be accessed without authentication.
    Private/restricted datasets require authentication and RBAC checks.

    Args:
        dataset_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | RasterTileToken | VectorTileToken
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
        )
    ).parsed
