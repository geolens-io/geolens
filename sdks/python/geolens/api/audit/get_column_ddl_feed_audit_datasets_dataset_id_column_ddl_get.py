from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.column_ddl_feed_response import ColumnDdlFeedResponse
from ...models.problem_detail import ProblemDetail
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    *,
    limit: int | Unset = 50,
    offset: int | Unset = 0,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["limit"] = limit

    params["offset"] = offset

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/audit/datasets/{dataset_id}/column-ddl".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ColumnDdlFeedResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = ColumnDdlFeedResponse.from_dict(response.json())

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
) -> Response[ColumnDdlFeedResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 50,
    offset: int | Unset = 0,
) -> Response[ColumnDdlFeedResponse | ProblemDetail]:
    """Get Column Ddl Feed

     Return the column-DDL audit history for a dataset.

    SEC-FU-08: Surfaces the column-DDL events written by SEC-S03 (Phase 1061)
    to dataset owners so they can detect editor-initiated schema changes.

    Access control (AGENTS.md Pre-Commit Checklist Rule 1):
    - Owner + granted roles: 200 with their own dataset's DDL history
    - Non-owner editor (no grant): 404 (check_dataset_access raises 404 for
      private datasets)
    - Admin: 200 (admin access is always allowed)
    - Anonymous: 401 (get_current_active_user dependency)

    The dataset 404-before-auth-query ordering ensures non-existent datasets
    return 404 without leaking audit log details.

    Args:
        dataset_id (UUID):
        limit (int | Unset):  Default: 50.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ColumnDdlFeedResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        limit=limit,
        offset=offset,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 50,
    offset: int | Unset = 0,
) -> ColumnDdlFeedResponse | ProblemDetail | None:
    """Get Column Ddl Feed

     Return the column-DDL audit history for a dataset.

    SEC-FU-08: Surfaces the column-DDL events written by SEC-S03 (Phase 1061)
    to dataset owners so they can detect editor-initiated schema changes.

    Access control (AGENTS.md Pre-Commit Checklist Rule 1):
    - Owner + granted roles: 200 with their own dataset's DDL history
    - Non-owner editor (no grant): 404 (check_dataset_access raises 404 for
      private datasets)
    - Admin: 200 (admin access is always allowed)
    - Anonymous: 401 (get_current_active_user dependency)

    The dataset 404-before-auth-query ordering ensures non-existent datasets
    return 404 without leaking audit log details.

    Args:
        dataset_id (UUID):
        limit (int | Unset):  Default: 50.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ColumnDdlFeedResponse | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        client=client,
        limit=limit,
        offset=offset,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 50,
    offset: int | Unset = 0,
) -> Response[ColumnDdlFeedResponse | ProblemDetail]:
    """Get Column Ddl Feed

     Return the column-DDL audit history for a dataset.

    SEC-FU-08: Surfaces the column-DDL events written by SEC-S03 (Phase 1061)
    to dataset owners so they can detect editor-initiated schema changes.

    Access control (AGENTS.md Pre-Commit Checklist Rule 1):
    - Owner + granted roles: 200 with their own dataset's DDL history
    - Non-owner editor (no grant): 404 (check_dataset_access raises 404 for
      private datasets)
    - Admin: 200 (admin access is always allowed)
    - Anonymous: 401 (get_current_active_user dependency)

    The dataset 404-before-auth-query ordering ensures non-existent datasets
    return 404 without leaking audit log details.

    Args:
        dataset_id (UUID):
        limit (int | Unset):  Default: 50.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ColumnDdlFeedResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        limit=limit,
        offset=offset,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 50,
    offset: int | Unset = 0,
) -> ColumnDdlFeedResponse | ProblemDetail | None:
    """Get Column Ddl Feed

     Return the column-DDL audit history for a dataset.

    SEC-FU-08: Surfaces the column-DDL events written by SEC-S03 (Phase 1061)
    to dataset owners so they can detect editor-initiated schema changes.

    Access control (AGENTS.md Pre-Commit Checklist Rule 1):
    - Owner + granted roles: 200 with their own dataset's DDL history
    - Non-owner editor (no grant): 404 (check_dataset_access raises 404 for
      private datasets)
    - Admin: 200 (admin access is always allowed)
    - Anonymous: 401 (get_current_active_user dependency)

    The dataset 404-before-auth-query ordering ensures non-existent datasets
    return 404 without leaking audit log details.

    Args:
        dataset_id (UUID):
        limit (int | Unset):  Default: 50.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ColumnDdlFeedResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
            limit=limit,
            offset=offset,
        )
    ).parsed
