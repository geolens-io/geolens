from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.ogc_record_response import OGCRecordResponse
from ...models.problem_detail import ProblemDetail
from uuid import UUID


def _get_kwargs(
    record_id: UUID,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/collections/datasets/items/{record_id}".format(
            record_id=quote(str(record_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> OGCRecordResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = OGCRecordResponse.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = ProblemDetail.from_dict(response.json())

        return response_400

    if response.status_code == 404:
        response_404 = ProblemDetail.from_dict(response.json())

        return response_404

    if response.status_code == 500:
        response_500 = ProblemDetail.from_dict(response.json())

        return response_500

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[OGCRecordResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    record_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[OGCRecordResponse | ProblemDetail]:
    """Get Collection Item

     Get a single dataset as an OGC Record Feature.

    Args:
        record_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[OGCRecordResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        record_id=record_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    record_id: UUID,
    *,
    client: AuthenticatedClient,
) -> OGCRecordResponse | ProblemDetail | None:
    """Get Collection Item

     Get a single dataset as an OGC Record Feature.

    Args:
        record_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        OGCRecordResponse | ProblemDetail
    """

    return sync_detailed(
        record_id=record_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    record_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[OGCRecordResponse | ProblemDetail]:
    """Get Collection Item

     Get a single dataset as an OGC Record Feature.

    Args:
        record_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[OGCRecordResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        record_id=record_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    record_id: UUID,
    *,
    client: AuthenticatedClient,
) -> OGCRecordResponse | ProblemDetail | None:
    """Get Collection Item

     Get a single dataset as an OGC Record Feature.

    Args:
        record_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        OGCRecordResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            record_id=record_id,
            client=client,
        )
    ).parsed
