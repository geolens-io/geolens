from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...models.share_token_response import ShareTokenResponse
from uuid import UUID


def _get_kwargs(
    map_id: UUID,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/maps/{map_id}/share/".format(
            map_id=quote(str(map_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> None | ShareTokenResponse | ProblemDetail | None:
    if response.status_code == 200:

        def _parse_response_200(data: object) -> None | ShareTokenResponse:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                response_200_type_0 = ShareTokenResponse.from_dict(data)

                return response_200_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | ShareTokenResponse, data)

        response_200 = _parse_response_200(response.json())

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
) -> Response[None | ShareTokenResponse | ProblemDetail]:
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
) -> Response[None | ShareTokenResponse | ProblemDetail]:
    """Get Map Share Token Endpoint

     Return the active share token for a map, or null if none exists.

    Args:
        map_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[None | ShareTokenResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        map_id=map_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    map_id: UUID,
    *,
    client: AuthenticatedClient,
) -> None | ShareTokenResponse | ProblemDetail | None:
    """Get Map Share Token Endpoint

     Return the active share token for a map, or null if none exists.

    Args:
        map_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        None | ShareTokenResponse | ProblemDetail
    """

    return sync_detailed(
        map_id=map_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    map_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[None | ShareTokenResponse | ProblemDetail]:
    """Get Map Share Token Endpoint

     Return the active share token for a map, or null if none exists.

    Args:
        map_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[None | ShareTokenResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        map_id=map_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    map_id: UUID,
    *,
    client: AuthenticatedClient,
) -> None | ShareTokenResponse | ProblemDetail | None:
    """Get Map Share Token Endpoint

     Return the active share token for a map, or null if none exists.

    Args:
        map_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        None | ShareTokenResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            map_id=map_id,
            client=client,
        )
    ).parsed
