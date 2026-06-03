from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.http_validation_error import HTTPValidationError
from ...models.ogc_collections_response import OGCCollectionsResponse
from ...types import Unset


def _get_kwargs(
    *,
    offset: int | Unset = 0,
    limit: int | Unset = 50,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["offset"] = offset

    params["limit"] = limit

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/collections",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | OGCCollectionsResponse | None:
    if response.status_code == 200:
        response_200 = OGCCollectionsResponse.from_dict(response.json())

        return response_200

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[HTTPValidationError | OGCCollectionsResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    offset: int | Unset = 0,
    limit: int | Unset = 50,
) -> Response[HTTPValidationError | OGCCollectionsResponse]:
    """List Collections

     List available OGC collections (catalog + per-dataset feature collections).

    Args:
        offset (int | Unset): Pagination offset for per-dataset collections Default: 0.
        limit (int | Unset): Max per-dataset collections to return Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | OGCCollectionsResponse]
    """

    kwargs = _get_kwargs(
        offset=offset,
        limit=limit,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    offset: int | Unset = 0,
    limit: int | Unset = 50,
) -> HTTPValidationError | OGCCollectionsResponse | None:
    """List Collections

     List available OGC collections (catalog + per-dataset feature collections).

    Args:
        offset (int | Unset): Pagination offset for per-dataset collections Default: 0.
        limit (int | Unset): Max per-dataset collections to return Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | OGCCollectionsResponse
    """

    return sync_detailed(
        client=client,
        offset=offset,
        limit=limit,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    offset: int | Unset = 0,
    limit: int | Unset = 50,
) -> Response[HTTPValidationError | OGCCollectionsResponse]:
    """List Collections

     List available OGC collections (catalog + per-dataset feature collections).

    Args:
        offset (int | Unset): Pagination offset for per-dataset collections Default: 0.
        limit (int | Unset): Max per-dataset collections to return Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | OGCCollectionsResponse]
    """

    kwargs = _get_kwargs(
        offset=offset,
        limit=limit,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    offset: int | Unset = 0,
    limit: int | Unset = 50,
) -> HTTPValidationError | OGCCollectionsResponse | None:
    """List Collections

     List available OGC collections (catalog + per-dataset feature collections).

    Args:
        offset (int | Unset): Pagination offset for per-dataset collections Default: 0.
        limit (int | Unset): Max per-dataset collections to return Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | OGCCollectionsResponse
    """

    return (
        await asyncio_detailed(
            client=client,
            offset=offset,
            limit=limit,
        )
    ).parsed
