from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...models.share_token_request import ShareTokenRequest
from ...models.share_token_response import ShareTokenResponse
from uuid import UUID


def _get_kwargs(
    map_id: UUID,
    *,
    body: ShareTokenRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/maps/{map_id}/share/".format(
            map_id=quote(str(map_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ProblemDetail | ShareTokenResponse | None:
    if response.status_code == 200:
        response_200 = ShareTokenResponse.from_dict(response.json())

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
) -> Response[ProblemDetail | ShareTokenResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    map_id: UUID,
    *,
    client: AuthenticatedClient,
    body: ShareTokenRequest,
) -> Response[ProblemDetail | ShareTokenResponse]:
    """Update Map Share Token Endpoint

     Update expiration on an existing share token (enterprise only). Owner or admin only.

    Args:
        map_id (UUID):
        body (ShareTokenRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | ShareTokenResponse]
    """

    kwargs = _get_kwargs(
        map_id=map_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    map_id: UUID,
    *,
    client: AuthenticatedClient,
    body: ShareTokenRequest,
) -> ProblemDetail | ShareTokenResponse | None:
    """Update Map Share Token Endpoint

     Update expiration on an existing share token (enterprise only). Owner or admin only.

    Args:
        map_id (UUID):
        body (ShareTokenRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | ShareTokenResponse
    """

    return sync_detailed(
        map_id=map_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    map_id: UUID,
    *,
    client: AuthenticatedClient,
    body: ShareTokenRequest,
) -> Response[ProblemDetail | ShareTokenResponse]:
    """Update Map Share Token Endpoint

     Update expiration on an existing share token (enterprise only). Owner or admin only.

    Args:
        map_id (UUID):
        body (ShareTokenRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | ShareTokenResponse]
    """

    kwargs = _get_kwargs(
        map_id=map_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    map_id: UUID,
    *,
    client: AuthenticatedClient,
    body: ShareTokenRequest,
) -> ProblemDetail | ShareTokenResponse | None:
    """Update Map Share Token Endpoint

     Update expiration on an existing share token (enterprise only). Owner or admin only.

    Args:
        map_id (UUID):
        body (ShareTokenRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | ShareTokenResponse
    """

    return (
        await asyncio_detailed(
            map_id=map_id,
            client=client,
            body=body,
        )
    ).parsed
