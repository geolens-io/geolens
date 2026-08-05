from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.list_users_admin_users_get_order import ListUsersAdminUsersGetOrder
from ...models.list_users_admin_users_get_sort import ListUsersAdminUsersGetSort
from ...models.problem_detail import ProblemDetail
from ...models.user_list_response import UserListResponse
from ...types import Unset


def _get_kwargs(
    *,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
    status: None | str | Unset = UNSET,
    search: None | str | Unset = UNSET,
    sort: ListUsersAdminUsersGetSort | Unset = "created_at",
    order: ListUsersAdminUsersGetOrder | Unset = "asc",
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

    json_sort: str | Unset = UNSET
    if not isinstance(sort, Unset):
        json_sort = sort

    params["sort"] = json_sort

    json_order: str | Unset = UNSET
    if not isinstance(order, Unset):
        json_order = order

    params["order"] = json_order

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
    sort: ListUsersAdminUsersGetSort | Unset = "created_at",
    order: ListUsersAdminUsersGetOrder | Unset = "asc",
) -> Response[ProblemDetail | UserListResponse]:
    """List Users

     List all users with pagination and optional status/search/sort filter (admin only).

    `sort` and `order` are closed enums, so an unrecognised value is refused
    with a 422 and never reaches the query.

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        status (None | str | Unset):
        search (None | str | Unset):
        sort (ListUsersAdminUsersGetSort | Unset): Column to order by. Roles and storage are not
            sortable: roles is a many-to-many and storage is aggregated per page after the query.
            Default: 'created_at'.
        order (ListUsersAdminUsersGetOrder | Unset): Sort direction. Default: 'asc'.

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
        sort=sort,
        order=order,
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
    sort: ListUsersAdminUsersGetSort | Unset = "created_at",
    order: ListUsersAdminUsersGetOrder | Unset = "asc",
) -> ProblemDetail | UserListResponse | None:
    """List Users

     List all users with pagination and optional status/search/sort filter (admin only).

    `sort` and `order` are closed enums, so an unrecognised value is refused
    with a 422 and never reaches the query.

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        status (None | str | Unset):
        search (None | str | Unset):
        sort (ListUsersAdminUsersGetSort | Unset): Column to order by. Roles and storage are not
            sortable: roles is a many-to-many and storage is aggregated per page after the query.
            Default: 'created_at'.
        order (ListUsersAdminUsersGetOrder | Unset): Sort direction. Default: 'asc'.

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
        sort=sort,
        order=order,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
    status: None | str | Unset = UNSET,
    search: None | str | Unset = UNSET,
    sort: ListUsersAdminUsersGetSort | Unset = "created_at",
    order: ListUsersAdminUsersGetOrder | Unset = "asc",
) -> Response[ProblemDetail | UserListResponse]:
    """List Users

     List all users with pagination and optional status/search/sort filter (admin only).

    `sort` and `order` are closed enums, so an unrecognised value is refused
    with a 422 and never reaches the query.

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        status (None | str | Unset):
        search (None | str | Unset):
        sort (ListUsersAdminUsersGetSort | Unset): Column to order by. Roles and storage are not
            sortable: roles is a many-to-many and storage is aggregated per page after the query.
            Default: 'created_at'.
        order (ListUsersAdminUsersGetOrder | Unset): Sort direction. Default: 'asc'.

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
        sort=sort,
        order=order,
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
    sort: ListUsersAdminUsersGetSort | Unset = "created_at",
    order: ListUsersAdminUsersGetOrder | Unset = "asc",
) -> ProblemDetail | UserListResponse | None:
    """List Users

     List all users with pagination and optional status/search/sort filter (admin only).

    `sort` and `order` are closed enums, so an unrecognised value is refused
    with a 422 and never reaches the query.

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        status (None | str | Unset):
        search (None | str | Unset):
        sort (ListUsersAdminUsersGetSort | Unset): Column to order by. Roles and storage are not
            sortable: roles is a many-to-many and storage is aggregated per page after the query.
            Default: 'created_at'.
        order (ListUsersAdminUsersGetOrder | Unset): Sort direction. Default: 'asc'.

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
            sort=sort,
            order=order,
        )
    ).parsed
