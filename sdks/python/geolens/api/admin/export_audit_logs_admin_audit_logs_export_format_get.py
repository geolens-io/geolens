from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...types import Unset
import datetime


def _get_kwargs(
    format_: str,
    *,
    action: None | str | Unset = UNSET,
    resource_type: None | str | Unset = UNSET,
    date_from: datetime.datetime | None | Unset = UNSET,
    date_to: datetime.datetime | None | Unset = UNSET,
    search: None | str | Unset = UNSET,
    max_rows: int | Unset = 100000,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

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

    params["max_rows"] = max_rows

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/admin/audit-logs/export/{format_}".format(
            format_=quote(str(format_), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = cast(Any, None)
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
) -> Response[Any | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    format_: str,
    *,
    client: AuthenticatedClient,
    action: None | str | Unset = UNSET,
    resource_type: None | str | Unset = UNSET,
    date_from: datetime.datetime | None | Unset = UNSET,
    date_to: datetime.datetime | None | Unset = UNSET,
    search: None | str | Unset = UNSET,
    max_rows: int | Unset = 100000,
) -> Response[Any | ProblemDetail]:
    """Export Audit Logs

     Export audit logs as CSV or JSON.

    Available formats are defined by the active ``AuditExtension`` — community
    advertises none (404 via ``require_enterprise``); enterprise overlays
    advertise ``csv``/``json`` (or additional formats) by registering an
    extension whose ``get_export_formats()`` returns the format list. Unknown
    formats also 404 to prevent leaking which formats exist in other editions.

    Args:
        format_ (str):
        action (None | str | Unset):
        resource_type (None | str | Unset):
        date_from (datetime.datetime | None | Unset):
        date_to (datetime.datetime | None | Unset):
        search (None | str | Unset):
        max_rows (int | Unset):  Default: 100000.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        format_=format_,
        action=action,
        resource_type=resource_type,
        date_from=date_from,
        date_to=date_to,
        search=search,
        max_rows=max_rows,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    format_: str,
    *,
    client: AuthenticatedClient,
    action: None | str | Unset = UNSET,
    resource_type: None | str | Unset = UNSET,
    date_from: datetime.datetime | None | Unset = UNSET,
    date_to: datetime.datetime | None | Unset = UNSET,
    search: None | str | Unset = UNSET,
    max_rows: int | Unset = 100000,
) -> Any | ProblemDetail | None:
    """Export Audit Logs

     Export audit logs as CSV or JSON.

    Available formats are defined by the active ``AuditExtension`` — community
    advertises none (404 via ``require_enterprise``); enterprise overlays
    advertise ``csv``/``json`` (or additional formats) by registering an
    extension whose ``get_export_formats()`` returns the format list. Unknown
    formats also 404 to prevent leaking which formats exist in other editions.

    Args:
        format_ (str):
        action (None | str | Unset):
        resource_type (None | str | Unset):
        date_from (datetime.datetime | None | Unset):
        date_to (datetime.datetime | None | Unset):
        search (None | str | Unset):
        max_rows (int | Unset):  Default: 100000.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return sync_detailed(
        format_=format_,
        client=client,
        action=action,
        resource_type=resource_type,
        date_from=date_from,
        date_to=date_to,
        search=search,
        max_rows=max_rows,
    ).parsed


async def asyncio_detailed(
    format_: str,
    *,
    client: AuthenticatedClient,
    action: None | str | Unset = UNSET,
    resource_type: None | str | Unset = UNSET,
    date_from: datetime.datetime | None | Unset = UNSET,
    date_to: datetime.datetime | None | Unset = UNSET,
    search: None | str | Unset = UNSET,
    max_rows: int | Unset = 100000,
) -> Response[Any | ProblemDetail]:
    """Export Audit Logs

     Export audit logs as CSV or JSON.

    Available formats are defined by the active ``AuditExtension`` — community
    advertises none (404 via ``require_enterprise``); enterprise overlays
    advertise ``csv``/``json`` (or additional formats) by registering an
    extension whose ``get_export_formats()`` returns the format list. Unknown
    formats also 404 to prevent leaking which formats exist in other editions.

    Args:
        format_ (str):
        action (None | str | Unset):
        resource_type (None | str | Unset):
        date_from (datetime.datetime | None | Unset):
        date_to (datetime.datetime | None | Unset):
        search (None | str | Unset):
        max_rows (int | Unset):  Default: 100000.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        format_=format_,
        action=action,
        resource_type=resource_type,
        date_from=date_from,
        date_to=date_to,
        search=search,
        max_rows=max_rows,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    format_: str,
    *,
    client: AuthenticatedClient,
    action: None | str | Unset = UNSET,
    resource_type: None | str | Unset = UNSET,
    date_from: datetime.datetime | None | Unset = UNSET,
    date_to: datetime.datetime | None | Unset = UNSET,
    search: None | str | Unset = UNSET,
    max_rows: int | Unset = 100000,
) -> Any | ProblemDetail | None:
    """Export Audit Logs

     Export audit logs as CSV or JSON.

    Available formats are defined by the active ``AuditExtension`` — community
    advertises none (404 via ``require_enterprise``); enterprise overlays
    advertise ``csv``/``json`` (or additional formats) by registering an
    extension whose ``get_export_formats()`` returns the format list. Unknown
    formats also 404 to prevent leaking which formats exist in other editions.

    Args:
        format_ (str):
        action (None | str | Unset):
        resource_type (None | str | Unset):
        date_from (datetime.datetime | None | Unset):
        date_to (datetime.datetime | None | Unset):
        search (None | str | Unset):
        max_rows (int | Unset):  Default: 100000.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return (
        await asyncio_detailed(
            format_=format_,
            client=client,
            action=action,
            resource_type=resource_type,
            date_from=date_from,
            date_to=date_to,
            search=search,
            max_rows=max_rows,
        )
    ).parsed
