from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.admin_share_token_list_response import AdminShareTokenListResponse
from ...models.problem_detail import ProblemDetail
from ...types import Unset


def _get_kwargs(
    *,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
    search: None | str | Unset = UNSET,
    status: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["skip"] = skip

    params["limit"] = limit

    json_search: None | str | Unset
    if isinstance(search, Unset):
        json_search = UNSET
    else:
        json_search = search
    params["search"] = json_search

    json_status: None | str | Unset
    if isinstance(status, Unset):
        json_status = UNSET
    else:
        json_status = status
    params["status"] = json_status

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/admin/share-tokens/",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> AdminShareTokenListResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = AdminShareTokenListResponse.from_dict(response.json())

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
) -> Response[AdminShareTokenListResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
    search: None | str | Unset = UNSET,
    status: None | str | Unset = UNSET,
) -> Response[AdminShareTokenListResponse | ProblemDetail]:
    """List Share Tokens Endpoint

     List all share tokens with map info (admin only).

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        search (None | str | Unset):
        status (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AdminShareTokenListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        skip=skip,
        limit=limit,
        search=search,
        status=status,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
    search: None | str | Unset = UNSET,
    status: None | str | Unset = UNSET,
) -> AdminShareTokenListResponse | ProblemDetail | None:
    """List Share Tokens Endpoint

     List all share tokens with map info (admin only).

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        search (None | str | Unset):
        status (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AdminShareTokenListResponse | ProblemDetail
    """

    return sync_detailed(
        client=client,
        skip=skip,
        limit=limit,
        search=search,
        status=status,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
    search: None | str | Unset = UNSET,
    status: None | str | Unset = UNSET,
) -> Response[AdminShareTokenListResponse | ProblemDetail]:
    """List Share Tokens Endpoint

     List all share tokens with map info (admin only).

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        search (None | str | Unset):
        status (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AdminShareTokenListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        skip=skip,
        limit=limit,
        search=search,
        status=status,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
    search: None | str | Unset = UNSET,
    status: None | str | Unset = UNSET,
) -> AdminShareTokenListResponse | ProblemDetail | None:
    """List Share Tokens Endpoint

     List all share tokens with map info (admin only).

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        search (None | str | Unset):
        status (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AdminShareTokenListResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
            skip=skip,
            limit=limit,
            search=search,
            status=status,
        )
    ).parsed
