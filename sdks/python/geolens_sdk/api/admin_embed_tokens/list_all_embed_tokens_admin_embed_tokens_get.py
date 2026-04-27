from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.admin_embed_token_list_response import AdminEmbedTokenListResponse
from ...models.problem_detail import ProblemDetail
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    *,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
    map_id: None | Unset | UUID = UNSET,
    map_search: None | str | Unset = UNSET,
    creator: None | str | Unset = UNSET,
    status: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["skip"] = skip

    params["limit"] = limit

    json_map_id: None | str | Unset
    if isinstance(map_id, Unset):
        json_map_id = UNSET
    elif isinstance(map_id, UUID):
        json_map_id = str(map_id)
    else:
        json_map_id = map_id
    params["map_id"] = json_map_id

    json_map_search: None | str | Unset
    if isinstance(map_search, Unset):
        json_map_search = UNSET
    else:
        json_map_search = map_search
    params["map_search"] = json_map_search

    json_creator: None | str | Unset
    if isinstance(creator, Unset):
        json_creator = UNSET
    else:
        json_creator = creator
    params["creator"] = json_creator

    json_status: None | str | Unset
    if isinstance(status, Unset):
        json_status = UNSET
    else:
        json_status = status
    params["status"] = json_status

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/admin/embed-tokens/",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> AdminEmbedTokenListResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = AdminEmbedTokenListResponse.from_dict(response.json())

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
) -> Response[AdminEmbedTokenListResponse | ProblemDetail]:
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
    map_id: None | Unset | UUID = UNSET,
    map_search: None | str | Unset = UNSET,
    creator: None | str | Unset = UNSET,
    status: None | str | Unset = UNSET,
) -> Response[AdminEmbedTokenListResponse | ProblemDetail]:
    """List All Embed Tokens

     List all embed tokens across all maps with optional filters (admin only).

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        map_id (None | Unset | UUID):
        map_search (None | str | Unset):
        creator (None | str | Unset):
        status (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AdminEmbedTokenListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        skip=skip,
        limit=limit,
        map_id=map_id,
        map_search=map_search,
        creator=creator,
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
    map_id: None | Unset | UUID = UNSET,
    map_search: None | str | Unset = UNSET,
    creator: None | str | Unset = UNSET,
    status: None | str | Unset = UNSET,
) -> AdminEmbedTokenListResponse | ProblemDetail | None:
    """List All Embed Tokens

     List all embed tokens across all maps with optional filters (admin only).

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        map_id (None | Unset | UUID):
        map_search (None | str | Unset):
        creator (None | str | Unset):
        status (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AdminEmbedTokenListResponse | ProblemDetail
    """

    return sync_detailed(
        client=client,
        skip=skip,
        limit=limit,
        map_id=map_id,
        map_search=map_search,
        creator=creator,
        status=status,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
    map_id: None | Unset | UUID = UNSET,
    map_search: None | str | Unset = UNSET,
    creator: None | str | Unset = UNSET,
    status: None | str | Unset = UNSET,
) -> Response[AdminEmbedTokenListResponse | ProblemDetail]:
    """List All Embed Tokens

     List all embed tokens across all maps with optional filters (admin only).

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        map_id (None | Unset | UUID):
        map_search (None | str | Unset):
        creator (None | str | Unset):
        status (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AdminEmbedTokenListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        skip=skip,
        limit=limit,
        map_id=map_id,
        map_search=map_search,
        creator=creator,
        status=status,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
    map_id: None | Unset | UUID = UNSET,
    map_search: None | str | Unset = UNSET,
    creator: None | str | Unset = UNSET,
    status: None | str | Unset = UNSET,
) -> AdminEmbedTokenListResponse | ProblemDetail | None:
    """List All Embed Tokens

     List all embed tokens across all maps with optional filters (admin only).

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        map_id (None | Unset | UUID):
        map_search (None | str | Unset):
        creator (None | str | Unset):
        status (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AdminEmbedTokenListResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
            skip=skip,
            limit=limit,
            map_id=map_id,
            map_search=map_search,
            creator=creator,
            status=status,
        )
    ).parsed
