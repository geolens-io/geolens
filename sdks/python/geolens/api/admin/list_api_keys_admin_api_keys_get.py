from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.admin_api_key_list_response import AdminApiKeyListResponse
from ...models.problem_detail import ProblemDetail
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    *,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
    user_id: None | Unset | UUID = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["skip"] = skip

    params["limit"] = limit

    json_user_id: None | str | Unset
    if isinstance(user_id, Unset):
        json_user_id = UNSET
    elif isinstance(user_id, UUID):
        json_user_id = str(user_id)
    else:
        json_user_id = user_id
    params["user_id"] = json_user_id

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/admin/api-keys/",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> AdminApiKeyListResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = AdminApiKeyListResponse.from_dict(response.json())

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
) -> Response[AdminApiKeyListResponse | ProblemDetail]:
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
    user_id: None | Unset | UUID = UNSET,
) -> Response[AdminApiKeyListResponse | ProblemDetail]:
    """List Api Keys

     List all API keys (admin only). Never returns the raw key.

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        user_id (None | Unset | UUID): Filter by user ID

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AdminApiKeyListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        skip=skip,
        limit=limit,
        user_id=user_id,
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
    user_id: None | Unset | UUID = UNSET,
) -> AdminApiKeyListResponse | ProblemDetail | None:
    """List Api Keys

     List all API keys (admin only). Never returns the raw key.

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        user_id (None | Unset | UUID): Filter by user ID

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AdminApiKeyListResponse | ProblemDetail
    """

    return sync_detailed(
        client=client,
        skip=skip,
        limit=limit,
        user_id=user_id,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
    user_id: None | Unset | UUID = UNSET,
) -> Response[AdminApiKeyListResponse | ProblemDetail]:
    """List Api Keys

     List all API keys (admin only). Never returns the raw key.

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        user_id (None | Unset | UUID): Filter by user ID

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AdminApiKeyListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        skip=skip,
        limit=limit,
        user_id=user_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
    user_id: None | Unset | UUID = UNSET,
) -> AdminApiKeyListResponse | ProblemDetail | None:
    """List Api Keys

     List all API keys (admin only). Never returns the raw key.

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.
        user_id (None | Unset | UUID): Filter by user ID

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AdminApiKeyListResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
            skip=skip,
            limit=limit,
            user_id=user_id,
        )
    ).parsed
