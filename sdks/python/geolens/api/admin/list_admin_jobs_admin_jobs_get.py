from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.admin_job_list_response import AdminJobListResponse
from ...models.problem_detail import ProblemDetail
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    *,
    status: None | str | Unset = UNSET,
    user_id: None | Unset | UUID = UNSET,
    search: None | str | Unset = UNSET,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_status: None | str | Unset
    if isinstance(status, Unset):
        json_status = UNSET
    else:
        json_status = status
    params["status"] = json_status

    json_user_id: None | str | Unset
    if isinstance(user_id, Unset):
        json_user_id = UNSET
    elif isinstance(user_id, UUID):
        json_user_id = str(user_id)
    else:
        json_user_id = user_id
    params["user_id"] = json_user_id

    json_search: None | str | Unset
    if isinstance(search, Unset):
        json_search = UNSET
    else:
        json_search = search
    params["search"] = json_search

    params["skip"] = skip

    params["limit"] = limit

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/admin/jobs/",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> AdminJobListResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = AdminJobListResponse.from_dict(response.json())

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
) -> Response[AdminJobListResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    status: None | str | Unset = UNSET,
    user_id: None | Unset | UUID = UNSET,
    search: None | str | Unset = UNSET,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
) -> Response[AdminJobListResponse | ProblemDetail]:
    """List Admin Jobs

     List all ingestion jobs with optional status/user/search filters (admin only).

    Args:
        status (None | str | Unset):
        user_id (None | Unset | UUID):
        search (None | str | Unset):
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AdminJobListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        status=status,
        user_id=user_id,
        search=search,
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
    status: None | str | Unset = UNSET,
    user_id: None | Unset | UUID = UNSET,
    search: None | str | Unset = UNSET,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
) -> AdminJobListResponse | ProblemDetail | None:
    """List Admin Jobs

     List all ingestion jobs with optional status/user/search filters (admin only).

    Args:
        status (None | str | Unset):
        user_id (None | Unset | UUID):
        search (None | str | Unset):
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AdminJobListResponse | ProblemDetail
    """

    return sync_detailed(
        client=client,
        status=status,
        user_id=user_id,
        search=search,
        skip=skip,
        limit=limit,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    status: None | str | Unset = UNSET,
    user_id: None | Unset | UUID = UNSET,
    search: None | str | Unset = UNSET,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
) -> Response[AdminJobListResponse | ProblemDetail]:
    """List Admin Jobs

     List all ingestion jobs with optional status/user/search filters (admin only).

    Args:
        status (None | str | Unset):
        user_id (None | Unset | UUID):
        search (None | str | Unset):
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AdminJobListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        status=status,
        user_id=user_id,
        search=search,
        skip=skip,
        limit=limit,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    status: None | str | Unset = UNSET,
    user_id: None | Unset | UUID = UNSET,
    search: None | str | Unset = UNSET,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
) -> AdminJobListResponse | ProblemDetail | None:
    """List Admin Jobs

     List all ingestion jobs with optional status/user/search filters (admin only).

    Args:
        status (None | str | Unset):
        user_id (None | Unset | UUID):
        search (None | str | Unset):
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AdminJobListResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
            status=status,
            user_id=user_id,
            search=search,
            skip=skip,
            limit=limit,
        )
    ).parsed
