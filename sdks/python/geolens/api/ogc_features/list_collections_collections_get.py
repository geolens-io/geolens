from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.ogc_collections_response import OGCCollectionsResponse
from ...models.problem_detail import ProblemDetail
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
) -> OGCCollectionsResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = OGCCollectionsResponse.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = ProblemDetail.from_dict(response.json())

        return response_400

    if response.status_code == 404:
        response_404 = ProblemDetail.from_dict(response.json())

        return response_404

    if response.status_code == 429:
        response_429 = ProblemDetail.from_dict(response.json())

        return response_429

    if response.status_code == 500:
        response_500 = ProblemDetail.from_dict(response.json())

        return response_500

    if response.status_code == 503:
        response_503 = ProblemDetail.from_dict(response.json())

        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[OGCCollectionsResponse | ProblemDetail]:
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
) -> Response[OGCCollectionsResponse | ProblemDetail]:
    """List Collections

     List available OGC collections (catalog + per-dataset feature collections).

    Args:
        offset (int | Unset): Pagination offset for per-dataset collections Default: 0.
        limit (int | Unset): Max per-dataset collections to return Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[OGCCollectionsResponse | ProblemDetail]
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
) -> OGCCollectionsResponse | ProblemDetail | None:
    """List Collections

     List available OGC collections (catalog + per-dataset feature collections).

    Args:
        offset (int | Unset): Pagination offset for per-dataset collections Default: 0.
        limit (int | Unset): Max per-dataset collections to return Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        OGCCollectionsResponse | ProblemDetail
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
) -> Response[OGCCollectionsResponse | ProblemDetail]:
    """List Collections

     List available OGC collections (catalog + per-dataset feature collections).

    Args:
        offset (int | Unset): Pagination offset for per-dataset collections Default: 0.
        limit (int | Unset): Max per-dataset collections to return Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[OGCCollectionsResponse | ProblemDetail]
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
) -> OGCCollectionsResponse | ProblemDetail | None:
    """List Collections

     List available OGC collections (catalog + per-dataset feature collections).

    Args:
        offset (int | Unset): Pagination offset for per-dataset collections Default: 0.
        limit (int | Unset): Max per-dataset collections to return Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        OGCCollectionsResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
            offset=offset,
            limit=limit,
        )
    ).parsed
