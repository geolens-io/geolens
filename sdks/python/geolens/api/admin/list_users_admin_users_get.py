from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...models.user_list_response import UserListResponse
from ...types import Unset


def _get_kwargs(
    *,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
    status: None | str | Unset = UNSET,
    search: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["skip"] = skip

    params["limit"] = limit

    json_status: None | str | Unset
    if isinstance(status, Unset):
        json_status = UNSET
    else:
        json_status = status
    params["status"] = json_status

    json_search: None | str | Unset
    if isinstance(search, Unset):
        json_search = UNSET
    else:
        json_search = search
    params["search"] = json_search

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/admin/users/",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ProblemDetail | UserListResponse | None:
    if response.status_code == 200:
        response_200 = UserListResponse.from_dict(response.json())

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
) -> Response[ProblemDetail | UserListResponse]:
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
    status: None | str | Unset = UNSET,
    search: None | str | Unset = UNSET,
) -> Response[ProblemDetail | UserListResponse]:
    """List Users

     List all users with pagination and optional status/search filter (admin only).

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        status (None | str | Unset):
        search (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | UserListResponse]
    """

    kwargs = _get_kwargs(
        skip=skip,
        limit=limit,
        status=status,
        search=search,
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
    status: None | str | Unset = UNSET,
    search: None | str | Unset = UNSET,
) -> ProblemDetail | UserListResponse | None:
    """List Users

     List all users with pagination and optional status/search filter (admin only).

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        status (None | str | Unset):
        search (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | UserListResponse
    """

    return sync_detailed(
        client=client,
        skip=skip,
        limit=limit,
        status=status,
        search=search,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
    status: None | str | Unset = UNSET,
    search: None | str | Unset = UNSET,
) -> Response[ProblemDetail | UserListResponse]:
    """List Users

     List all users with pagination and optional status/search filter (admin only).

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        status (None | str | Unset):
        search (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | UserListResponse]
    """

    kwargs = _get_kwargs(
        skip=skip,
        limit=limit,
        status=status,
        search=search,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
    status: None | str | Unset = UNSET,
    search: None | str | Unset = UNSET,
) -> ProblemDetail | UserListResponse | None:
    """List Users

     List all users with pagination and optional status/search filter (admin only).

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        status (None | str | Unset):
        search (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | UserListResponse
    """

    return (
        await asyncio_detailed(
            client=client,
            skip=skip,
            limit=limit,
            status=status,
            search=search,
        )
    ).parsed
