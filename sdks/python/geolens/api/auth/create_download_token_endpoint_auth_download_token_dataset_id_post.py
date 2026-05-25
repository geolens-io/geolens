from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.download_token_response import DownloadTokenResponse
from ...models.problem_detail import ProblemDetail
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/auth/download-token/{dataset_id}".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> DownloadTokenResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = DownloadTokenResponse.from_dict(response.json())

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
) -> Response[DownloadTokenResponse | ProblemDetail]:
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
) -> Response[DownloadTokenResponse | ProblemDetail]:
    """Create Download Token Endpoint

     Mint a short-lived download-scoped JWT for a single dataset.

    IA-P0-01 / SEC-04: the existing COG download URL path requires a
    ``typ='download'`` JWT on the ``?token=`` query parameter — session JWTs
    are rejected. This endpoint issues that token after verifying the caller
    has read access to the dataset.

    Anonymous callers are allowed for public datasets. The returned token has
    ``typ='download'``, ``scope='dataset:{dataset_id}'``, and a TTL of 120s.

    Args:
        dataset_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DownloadTokenResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
) -> DownloadTokenResponse | ProblemDetail | None:
    """Create Download Token Endpoint

     Mint a short-lived download-scoped JWT for a single dataset.

    IA-P0-01 / SEC-04: the existing COG download URL path requires a
    ``typ='download'`` JWT on the ``?token=`` query parameter — session JWTs
    are rejected. This endpoint issues that token after verifying the caller
    has read access to the dataset.

    Anonymous callers are allowed for public datasets. The returned token has
    ``typ='download'``, ``scope='dataset:{dataset_id}'``, and a TTL of 120s.

    Args:
        dataset_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DownloadTokenResponse | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[DownloadTokenResponse | ProblemDetail]:
    """Create Download Token Endpoint

     Mint a short-lived download-scoped JWT for a single dataset.

    IA-P0-01 / SEC-04: the existing COG download URL path requires a
    ``typ='download'`` JWT on the ``?token=`` query parameter — session JWTs
    are rejected. This endpoint issues that token after verifying the caller
    has read access to the dataset.

    Anonymous callers are allowed for public datasets. The returned token has
    ``typ='download'``, ``scope='dataset:{dataset_id}'``, and a TTL of 120s.

    Args:
        dataset_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DownloadTokenResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
) -> DownloadTokenResponse | ProblemDetail | None:
    """Create Download Token Endpoint

     Mint a short-lived download-scoped JWT for a single dataset.

    IA-P0-01 / SEC-04: the existing COG download URL path requires a
    ``typ='download'`` JWT on the ``?token=`` query parameter — session JWTs
    are rejected. This endpoint issues that token after verifying the caller
    has read access to the dataset.

    Anonymous callers are allowed for public datasets. The returned token has
    ``typ='download'``, ``scope='dataset:{dataset_id}'``, and a TTL of 120s.

    Args:
        dataset_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DownloadTokenResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
        )
    ).parsed
