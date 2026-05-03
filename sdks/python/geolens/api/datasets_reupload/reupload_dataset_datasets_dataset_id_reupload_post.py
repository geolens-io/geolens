from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.body_reupload_dataset_datasets_dataset_id_reupload_post import (
    BodyReuploadDatasetDatasetsDatasetIdReuploadPost,
)
from ...models.problem_detail import ProblemDetail
from ...models.reupload_response import ReuploadResponse
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    *,
    body: BodyReuploadDatasetDatasetsDatasetIdReuploadPost,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/datasets/{dataset_id}/reupload".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
    }

    _kwargs["files"] = body.to_multipart()

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ProblemDetail | ReuploadResponse | None:
    if response.status_code == 201:
        response_201 = ReuploadResponse.from_dict(response.json())

        return response_201

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
) -> Response[ProblemDetail | ReuploadResponse]:
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
    body: BodyReuploadDatasetDatasetsDatasetIdReuploadPost,
) -> Response[ProblemDetail | ReuploadResponse]:
    """Reupload Dataset

     Upload a new file to replace the data in an existing dataset.

    Args:
        dataset_id (UUID):
        body (BodyReuploadDatasetDatasetsDatasetIdReuploadPost):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | ReuploadResponse]
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
    body: BodyReuploadDatasetDatasetsDatasetIdReuploadPost,
) -> ProblemDetail | ReuploadResponse | None:
    """Reupload Dataset

     Upload a new file to replace the data in an existing dataset.

    Args:
        dataset_id (UUID):
        body (BodyReuploadDatasetDatasetsDatasetIdReuploadPost):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | ReuploadResponse
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
    body: BodyReuploadDatasetDatasetsDatasetIdReuploadPost,
) -> Response[ProblemDetail | ReuploadResponse]:
    """Reupload Dataset

     Upload a new file to replace the data in an existing dataset.

    Args:
        dataset_id (UUID):
        body (BodyReuploadDatasetDatasetsDatasetIdReuploadPost):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | ReuploadResponse]
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
    body: BodyReuploadDatasetDatasetsDatasetIdReuploadPost,
) -> ProblemDetail | ReuploadResponse | None:
    """Reupload Dataset

     Upload a new file to replace the data in an existing dataset.

    Args:
        dataset_id (UUID):
        body (BodyReuploadDatasetDatasetsDatasetIdReuploadPost):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | ReuploadResponse
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
            body=body,
        )
    ).parsed
