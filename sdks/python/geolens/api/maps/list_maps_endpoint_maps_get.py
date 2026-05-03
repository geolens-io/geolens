from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.list_maps_endpoint_maps_get_sort_by import ListMapsEndpointMapsGetSortBy
from ...models.list_maps_endpoint_maps_get_sort_dir import (
    ListMapsEndpointMapsGetSortDir,
)
from ...models.map_list_response import MapListResponse
from ...models.problem_detail import ProblemDetail
from ...types import Unset


def _get_kwargs(
    *,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
    search: None | str | Unset = UNSET,
    sort_by: ListMapsEndpointMapsGetSortBy | Unset = "updated_at",
    sort_dir: ListMapsEndpointMapsGetSortDir | Unset = "desc",
    visibility: None | str | Unset = UNSET,
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

    json_sort_by: str | Unset = UNSET
    if not isinstance(sort_by, Unset):
        json_sort_by = sort_by

    params["sort_by"] = json_sort_by

    json_sort_dir: str | Unset = UNSET
    if not isinstance(sort_dir, Unset):
        json_sort_dir = sort_dir

    params["sort_dir"] = json_sort_dir

    json_visibility: None | str | Unset
    if isinstance(visibility, Unset):
        json_visibility = UNSET
    else:
        json_visibility = visibility
    params["visibility"] = json_visibility

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/maps/",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> MapListResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = MapListResponse.from_dict(response.json())

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
) -> Response[MapListResponse | ProblemDetail]:
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
    sort_by: ListMapsEndpointMapsGetSortBy | Unset = "updated_at",
    sort_dir: ListMapsEndpointMapsGetSortDir | Unset = "desc",
    visibility: None | str | Unset = UNSET,
) -> Response[MapListResponse | ProblemDetail]:
    """List Maps Endpoint

     List maps. Admins see all; authenticated users see own + internal + public; anonymous see public
    only.

    Supports search (ILIKE on name+description), sort_by (name/created_at/updated_at),
    sort_dir (asc/desc), and visibility filter (private/internal/public).

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        search (None | str | Unset):
        sort_by (ListMapsEndpointMapsGetSortBy | Unset):  Default: 'updated_at'.
        sort_dir (ListMapsEndpointMapsGetSortDir | Unset):  Default: 'desc'.
        visibility (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[MapListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        skip=skip,
        limit=limit,
        search=search,
        sort_by=sort_by,
        sort_dir=sort_dir,
        visibility=visibility,
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
    sort_by: ListMapsEndpointMapsGetSortBy | Unset = "updated_at",
    sort_dir: ListMapsEndpointMapsGetSortDir | Unset = "desc",
    visibility: None | str | Unset = UNSET,
) -> MapListResponse | ProblemDetail | None:
    """List Maps Endpoint

     List maps. Admins see all; authenticated users see own + internal + public; anonymous see public
    only.

    Supports search (ILIKE on name+description), sort_by (name/created_at/updated_at),
    sort_dir (asc/desc), and visibility filter (private/internal/public).

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        search (None | str | Unset):
        sort_by (ListMapsEndpointMapsGetSortBy | Unset):  Default: 'updated_at'.
        sort_dir (ListMapsEndpointMapsGetSortDir | Unset):  Default: 'desc'.
        visibility (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        MapListResponse | ProblemDetail
    """

    return sync_detailed(
        client=client,
        skip=skip,
        limit=limit,
        search=search,
        sort_by=sort_by,
        sort_dir=sort_dir,
        visibility=visibility,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
    search: None | str | Unset = UNSET,
    sort_by: ListMapsEndpointMapsGetSortBy | Unset = "updated_at",
    sort_dir: ListMapsEndpointMapsGetSortDir | Unset = "desc",
    visibility: None | str | Unset = UNSET,
) -> Response[MapListResponse | ProblemDetail]:
    """List Maps Endpoint

     List maps. Admins see all; authenticated users see own + internal + public; anonymous see public
    only.

    Supports search (ILIKE on name+description), sort_by (name/created_at/updated_at),
    sort_dir (asc/desc), and visibility filter (private/internal/public).

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        search (None | str | Unset):
        sort_by (ListMapsEndpointMapsGetSortBy | Unset):  Default: 'updated_at'.
        sort_dir (ListMapsEndpointMapsGetSortDir | Unset):  Default: 'desc'.
        visibility (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[MapListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        skip=skip,
        limit=limit,
        search=search,
        sort_by=sort_by,
        sort_dir=sort_dir,
        visibility=visibility,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
    search: None | str | Unset = UNSET,
    sort_by: ListMapsEndpointMapsGetSortBy | Unset = "updated_at",
    sort_dir: ListMapsEndpointMapsGetSortDir | Unset = "desc",
    visibility: None | str | Unset = UNSET,
) -> MapListResponse | ProblemDetail | None:
    """List Maps Endpoint

     List maps. Admins see all; authenticated users see own + internal + public; anonymous see public
    only.

    Supports search (ILIKE on name+description), sort_by (name/created_at/updated_at),
    sort_dir (asc/desc), and visibility filter (private/internal/public).

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        search (None | str | Unset):
        sort_by (ListMapsEndpointMapsGetSortBy | Unset):  Default: 'updated_at'.
        sort_dir (ListMapsEndpointMapsGetSortDir | Unset):  Default: 'desc'.
        visibility (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        MapListResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
            skip=skip,
            limit=limit,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            visibility=visibility,
        )
    ).parsed
