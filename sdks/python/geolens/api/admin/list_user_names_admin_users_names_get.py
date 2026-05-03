from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...models.user_name_item import UserNameItem
from ...types import Unset


def _get_kwargs(
    *,
    skip: int | Unset = 0,
    limit: int | Unset = 500,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["skip"] = skip

    params["limit"] = limit

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/admin/users/names/",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ProblemDetail | list[UserNameItem] | None:
    if response.status_code == 200:
        response_200 = []
        _response_200 = response.json()
        for response_200_item_data in _response_200:
            response_200_item = UserNameItem.from_dict(response_200_item_data)

            response_200.append(response_200_item)

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
) -> Response[ProblemDetail | list[UserNameItem]]:
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
    limit: int | Unset = 500,
) -> Response[ProblemDetail | list[UserNameItem]]:
    """List User Names

     Return lightweight id+username list for filter dropdowns.

    Paginated to bound response size on deployments with many users. Default
    page size of 500 is enough for typical admin dropdowns; the limit cap of
    1000 matches the previous hard cap. Clients needing the full list should
    page by incrementing ``skip``.

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 500.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | list[UserNameItem]]
    """

    kwargs = _get_kwargs(
        skip=skip,
        limit=limit,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 500,
) -> ProblemDetail | list[UserNameItem] | None:
    """List User Names

     Return lightweight id+username list for filter dropdowns.

    Paginated to bound response size on deployments with many users. Default
    page size of 500 is enough for typical admin dropdowns; the limit cap of
    1000 matches the previous hard cap. Clients needing the full list should
    page by incrementing ``skip``.

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 500.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | list[UserNameItem]
    """

    return sync_detailed(
        client=client,
        skip=skip,
        limit=limit,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 500,
) -> Response[ProblemDetail | list[UserNameItem]]:
    """List User Names

     Return lightweight id+username list for filter dropdowns.

    Paginated to bound response size on deployments with many users. Default
    page size of 500 is enough for typical admin dropdowns; the limit cap of
    1000 matches the previous hard cap. Clients needing the full list should
    page by incrementing ``skip``.

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 500.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | list[UserNameItem]]
    """

    kwargs = _get_kwargs(
        skip=skip,
        limit=limit,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 500,
) -> ProblemDetail | list[UserNameItem] | None:
    """List User Names

     Return lightweight id+username list for filter dropdowns.

    Paginated to bound response size on deployments with many users. Default
    page size of 500 is enough for typical admin dropdowns; the limit cap of
    1000 matches the previous hard cap. Clients needing the full list should
    page by incrementing ``skip``.

    Args:
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 500.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | list[UserNameItem]
    """

    return (
        await asyncio_detailed(
            client=client,
            skip=skip,
            limit=limit,
        )
    ).parsed
