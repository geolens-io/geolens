from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.audit_log_list_response import AuditLogListResponse
from ...models.problem_detail import ProblemDetail
from ...types import Unset
from uuid import UUID
import datetime


def _get_kwargs(
    *,
    user_id: None | Unset | UUID = UNSET,
    action: None | str | Unset = UNSET,
    resource_type: None | str | Unset = UNSET,
    date_from: datetime.datetime | None | Unset = UNSET,
    date_to: datetime.datetime | None | Unset = UNSET,
    search: None | str | Unset = UNSET,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_user_id: None | str | Unset
    if isinstance(user_id, Unset):
        json_user_id = UNSET
    elif isinstance(user_id, UUID):
        json_user_id = str(user_id)
    else:
        json_user_id = user_id
    params["user_id"] = json_user_id

    json_action: None | str | Unset
    if isinstance(action, Unset):
        json_action = UNSET
    else:
        json_action = action
    params["action"] = json_action

    json_resource_type: None | str | Unset
    if isinstance(resource_type, Unset):
        json_resource_type = UNSET
    else:
        json_resource_type = resource_type
    params["resource_type"] = json_resource_type

    json_date_from: None | str | Unset
    if isinstance(date_from, Unset):
        json_date_from = UNSET
    elif isinstance(date_from, datetime.datetime):
        json_date_from = date_from.isoformat()
    else:
        json_date_from = date_from
    params["date_from"] = json_date_from

    json_date_to: None | str | Unset
    if isinstance(date_to, Unset):
        json_date_to = UNSET
    elif isinstance(date_to, datetime.datetime):
        json_date_to = date_to.isoformat()
    else:
        json_date_to = date_to
    params["date_to"] = json_date_to

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
        "url": "/admin/audit-logs/",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> AuditLogListResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = AuditLogListResponse.from_dict(response.json())

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
) -> Response[AuditLogListResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    user_id: None | Unset | UUID = UNSET,
    action: None | str | Unset = UNSET,
    resource_type: None | str | Unset = UNSET,
    date_from: datetime.datetime | None | Unset = UNSET,
    date_to: datetime.datetime | None | Unset = UNSET,
    search: None | str | Unset = UNSET,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
) -> Response[AuditLogListResponse | ProblemDetail]:
    """List Audit Logs

     Query audit logs with optional filters (admin only).

    Args:
        user_id (None | Unset | UUID):
        action (None | str | Unset):
        resource_type (None | str | Unset):
        date_from (datetime.datetime | None | Unset):
        date_to (datetime.datetime | None | Unset):
        search (None | str | Unset):
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AuditLogListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        date_from=date_from,
        date_to=date_to,
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
    user_id: None | Unset | UUID = UNSET,
    action: None | str | Unset = UNSET,
    resource_type: None | str | Unset = UNSET,
    date_from: datetime.datetime | None | Unset = UNSET,
    date_to: datetime.datetime | None | Unset = UNSET,
    search: None | str | Unset = UNSET,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
) -> AuditLogListResponse | ProblemDetail | None:
    """List Audit Logs

     Query audit logs with optional filters (admin only).

    Args:
        user_id (None | Unset | UUID):
        action (None | str | Unset):
        resource_type (None | str | Unset):
        date_from (datetime.datetime | None | Unset):
        date_to (datetime.datetime | None | Unset):
        search (None | str | Unset):
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AuditLogListResponse | ProblemDetail
    """

    return sync_detailed(
        client=client,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        date_from=date_from,
        date_to=date_to,
        search=search,
        skip=skip,
        limit=limit,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    user_id: None | Unset | UUID = UNSET,
    action: None | str | Unset = UNSET,
    resource_type: None | str | Unset = UNSET,
    date_from: datetime.datetime | None | Unset = UNSET,
    date_to: datetime.datetime | None | Unset = UNSET,
    search: None | str | Unset = UNSET,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
) -> Response[AuditLogListResponse | ProblemDetail]:
    """List Audit Logs

     Query audit logs with optional filters (admin only).

    Args:
        user_id (None | Unset | UUID):
        action (None | str | Unset):
        resource_type (None | str | Unset):
        date_from (datetime.datetime | None | Unset):
        date_to (datetime.datetime | None | Unset):
        search (None | str | Unset):
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AuditLogListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        date_from=date_from,
        date_to=date_to,
        search=search,
        skip=skip,
        limit=limit,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    user_id: None | Unset | UUID = UNSET,
    action: None | str | Unset = UNSET,
    resource_type: None | str | Unset = UNSET,
    date_from: datetime.datetime | None | Unset = UNSET,
    date_to: datetime.datetime | None | Unset = UNSET,
    search: None | str | Unset = UNSET,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
) -> AuditLogListResponse | ProblemDetail | None:
    """List Audit Logs

     Query audit logs with optional filters (admin only).

    Args:
        user_id (None | Unset | UUID):
        action (None | str | Unset):
        resource_type (None | str | Unset):
        date_from (datetime.datetime | None | Unset):
        date_to (datetime.datetime | None | Unset):
        search (None | str | Unset):
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AuditLogListResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            date_from=date_from,
            date_to=date_to,
            search=search,
            skip=skip,
            limit=limit,
        )
    ).parsed
