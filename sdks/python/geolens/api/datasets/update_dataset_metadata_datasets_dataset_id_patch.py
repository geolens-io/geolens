from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.dataset_meta import DatasetMeta
from ...models.dataset_response import DatasetResponse
from ...models.problem_detail import ProblemDetail
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    *,
    body: DatasetMeta,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/datasets/{dataset_id}".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> DatasetResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = DatasetResponse.from_dict(response.json())

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
) -> Response[DatasetResponse | ProblemDetail]:
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
    body: DatasetMeta,
) -> Response[DatasetResponse | ProblemDetail]:
    """Update Dataset Metadata

     Update user-editable dataset metadata.

    Args:
        dataset_id (UUID):
        body (DatasetMeta):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DatasetResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    body: DatasetMeta,
) -> DatasetResponse | ProblemDetail | None:
    """Update Dataset Metadata

     Update user-editable dataset metadata.

    Args:
        dataset_id (UUID):
        body (DatasetMeta):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DatasetResponse | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    body: DatasetMeta,
) -> Response[DatasetResponse | ProblemDetail]:
    """Update Dataset Metadata

     Update user-editable dataset metadata.

    Args:
        dataset_id (UUID):
        body (DatasetMeta):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DatasetResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    body: DatasetMeta,
) -> DatasetResponse | ProblemDetail | None:
    """Update Dataset Metadata

     Update user-editable dataset metadata.

    Args:
        dataset_id (UUID):
        body (DatasetMeta):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DatasetResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
            body=body,
        )
    ).parsed
