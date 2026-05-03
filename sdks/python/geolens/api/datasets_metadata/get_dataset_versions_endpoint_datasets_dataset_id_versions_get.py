from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.dataset_version_list_response import DatasetVersionListResponse
from ...models.problem_detail import ProblemDetail
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    *,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["skip"] = skip

    params["limit"] = limit

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/datasets/{dataset_id}/versions/".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> DatasetVersionListResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = DatasetVersionListResponse.from_dict(response.json())

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
) -> Response[DatasetVersionListResponse | ProblemDetail]:
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
    skip: int | Unset = 0,
    limit: int | Unset = 50,
) -> Response[DatasetVersionListResponse | ProblemDetail]:
    """Get Dataset Versions Endpoint

     Get paginated version history for a dataset.

    Args:
        dataset_id (UUID):
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DatasetVersionListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        skip=skip,
        limit=limit,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
) -> DatasetVersionListResponse | ProblemDetail | None:
    """Get Dataset Versions Endpoint

     Get paginated version history for a dataset.

    Args:
        dataset_id (UUID):
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DatasetVersionListResponse | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        client=client,
        skip=skip,
        limit=limit,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
) -> Response[DatasetVersionListResponse | ProblemDetail]:
    """Get Dataset Versions Endpoint

     Get paginated version history for a dataset.

    Args:
        dataset_id (UUID):
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DatasetVersionListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        skip=skip,
        limit=limit,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
) -> DatasetVersionListResponse | ProblemDetail | None:
    """Get Dataset Versions Endpoint

     Get paginated version history for a dataset.

    Args:
        dataset_id (UUID):
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DatasetVersionListResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
            skip=skip,
            limit=limit,
        )
    ).parsed
