from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...types import Unset


def _get_kwargs(
    *,
    limit: int | Unset = 10000,
    offset: int | Unset = 0,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["limit"] = limit

    params["offset"] = offset

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/datasets/dcat/",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = response.json()
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
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 10000,
    offset: int | Unset = 0,
) -> Response[Any | ProblemDetail]:
    """Get Dcat Catalog

     DCAT 3 JSON-LD catalog feed. Respects dataset visibility.

    Args:
        limit (int | Unset): Max datasets in this page (default = max). Default: 10000.
        offset (int | Unset): Datasets to skip — page a catalog larger than one page. Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        limit=limit,
        offset=offset,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 10000,
    offset: int | Unset = 0,
) -> Any | ProblemDetail | None:
    """Get Dcat Catalog

     DCAT 3 JSON-LD catalog feed. Respects dataset visibility.

    Args:
        limit (int | Unset): Max datasets in this page (default = max). Default: 10000.
        offset (int | Unset): Datasets to skip — page a catalog larger than one page. Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return sync_detailed(
        client=client,
        limit=limit,
        offset=offset,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 10000,
    offset: int | Unset = 0,
) -> Response[Any | ProblemDetail]:
    """Get Dcat Catalog

     DCAT 3 JSON-LD catalog feed. Respects dataset visibility.

    Args:
        limit (int | Unset): Max datasets in this page (default = max). Default: 10000.
        offset (int | Unset): Datasets to skip — page a catalog larger than one page. Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        limit=limit,
        offset=offset,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 10000,
    offset: int | Unset = 0,
) -> Any | ProblemDetail | None:
    """Get Dcat Catalog

     DCAT 3 JSON-LD catalog feed. Respects dataset visibility.

    Args:
        limit (int | Unset): Max datasets in this page (default = max). Default: 10000.
        offset (int | Unset): Datasets to skip — page a catalog larger than one page. Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
            limit=limit,
            offset=offset,
        )
    ).parsed
