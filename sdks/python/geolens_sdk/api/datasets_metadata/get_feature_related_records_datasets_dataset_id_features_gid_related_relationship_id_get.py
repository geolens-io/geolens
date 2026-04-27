from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.dataset_rows_response import DatasetRowsResponse
from ...models.problem_detail import ProblemDetail
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    gid: int,
    relationship_id: UUID,
    *,
    limit: int | Unset = 50,
    after: int | Unset = 0,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["limit"] = limit

    params["after"] = after

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/datasets/{dataset_id}/features/{gid}/related/{relationship_id}/".format(
            dataset_id=quote(str(dataset_id), safe=""),
            gid=quote(str(gid), safe=""),
            relationship_id=quote(str(relationship_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> DatasetRowsResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = DatasetRowsResponse.from_dict(response.json())

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
) -> Response[DatasetRowsResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    dataset_id: UUID,
    gid: int,
    relationship_id: UUID,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 50,
    after: int | Unset = 0,
) -> Response[DatasetRowsResponse | ProblemDetail]:
    """Get Feature Related Records

     Get related records for a feature via FK relationship.

    Args:
        dataset_id (UUID):
        gid (int):
        relationship_id (UUID):
        limit (int | Unset):  Default: 50.
        after (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DatasetRowsResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        gid=gid,
        relationship_id=relationship_id,
        limit=limit,
        after=after,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    gid: int,
    relationship_id: UUID,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 50,
    after: int | Unset = 0,
) -> DatasetRowsResponse | ProblemDetail | None:
    """Get Feature Related Records

     Get related records for a feature via FK relationship.

    Args:
        dataset_id (UUID):
        gid (int):
        relationship_id (UUID):
        limit (int | Unset):  Default: 50.
        after (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DatasetRowsResponse | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        gid=gid,
        relationship_id=relationship_id,
        client=client,
        limit=limit,
        after=after,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    gid: int,
    relationship_id: UUID,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 50,
    after: int | Unset = 0,
) -> Response[DatasetRowsResponse | ProblemDetail]:
    """Get Feature Related Records

     Get related records for a feature via FK relationship.

    Args:
        dataset_id (UUID):
        gid (int):
        relationship_id (UUID):
        limit (int | Unset):  Default: 50.
        after (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DatasetRowsResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        gid=gid,
        relationship_id=relationship_id,
        limit=limit,
        after=after,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    gid: int,
    relationship_id: UUID,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 50,
    after: int | Unset = 0,
) -> DatasetRowsResponse | ProblemDetail | None:
    """Get Feature Related Records

     Get related records for a feature via FK relationship.

    Args:
        dataset_id (UUID):
        gid (int):
        relationship_id (UUID):
        limit (int | Unset):  Default: 50.
        after (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DatasetRowsResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            gid=gid,
            relationship_id=relationship_id,
            client=client,
            limit=limit,
            after=after,
        )
    ).parsed
