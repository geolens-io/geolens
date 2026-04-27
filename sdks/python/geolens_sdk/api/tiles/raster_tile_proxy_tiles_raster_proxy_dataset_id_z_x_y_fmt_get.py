from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.problem_detail import ProblemDetail
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    z: int,
    x: int,
    y: int,
    fmt: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/tiles/raster-proxy/{dataset_id}/{z}/{x}/{y}.{fmt}".format(
            dataset_id=quote(str(dataset_id), safe=""),
            z=quote(str(z), safe=""),
            x=quote(str(x), safe=""),
            y=quote(str(y), safe=""),
            fmt=quote(str(fmt), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = cast(Any, None)
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
) -> Response[Any | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    dataset_id: UUID,
    z: int,
    x: int,
    y: int,
    fmt: str,
    *,
    client: AuthenticatedClient,
) -> Response[Any | ProblemDetail]:
    """Raster Tile Proxy

     API-side raster tile proxy: auth check + fetch from Titiler.

    Used by Vite dev proxy and as a fallback for deployments without nginx.
    Production deployments with nginx should use the nginx raster-tiles path
    for better caching and performance.

    Args:
        dataset_id (UUID):
        z (int):
        x (int):
        y (int):
        fmt (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        z=z,
        x=x,
        y=y,
        fmt=fmt,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    z: int,
    x: int,
    y: int,
    fmt: str,
    *,
    client: AuthenticatedClient,
) -> Any | ProblemDetail | None:
    """Raster Tile Proxy

     API-side raster tile proxy: auth check + fetch from Titiler.

    Used by Vite dev proxy and as a fallback for deployments without nginx.
    Production deployments with nginx should use the nginx raster-tiles path
    for better caching and performance.

    Args:
        dataset_id (UUID):
        z (int):
        x (int):
        y (int):
        fmt (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        z=z,
        x=x,
        y=y,
        fmt=fmt,
        client=client,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    z: int,
    x: int,
    y: int,
    fmt: str,
    *,
    client: AuthenticatedClient,
) -> Response[Any | ProblemDetail]:
    """Raster Tile Proxy

     API-side raster tile proxy: auth check + fetch from Titiler.

    Used by Vite dev proxy and as a fallback for deployments without nginx.
    Production deployments with nginx should use the nginx raster-tiles path
    for better caching and performance.

    Args:
        dataset_id (UUID):
        z (int):
        x (int):
        y (int):
        fmt (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        z=z,
        x=x,
        y=y,
        fmt=fmt,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    z: int,
    x: int,
    y: int,
    fmt: str,
    *,
    client: AuthenticatedClient,
) -> Any | ProblemDetail | None:
    """Raster Tile Proxy

     API-side raster tile proxy: auth check + fetch from Titiler.

    Used by Vite dev proxy and as a fallback for deployments without nginx.
    Production deployments with nginx should use the nginx raster-tiles path
    for better caching and performance.

    Args:
        dataset_id (UUID):
        z (int):
        x (int):
        y (int):
        fmt (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            z=z,
            x=x,
            y=y,
            fmt=fmt,
            client=client,
        )
    ).parsed
