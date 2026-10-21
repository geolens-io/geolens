from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.capabilities_response import CapabilitiesResponse
from ...models.problem_detail import ProblemDetail


def _get_kwargs() -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/capabilities/",
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> CapabilitiesResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = CapabilitiesResponse.from_dict(response.json())

        return response_200

    if response.status_code == 401:
        response_401 = ProblemDetail.from_dict(response.json())

        return response_401

    if response.status_code == 429:
        response_429 = ProblemDetail.from_dict(response.json())

        return response_429

    if response.status_code == 500:
        response_500 = ProblemDetail.from_dict(response.json())

        return response_500

    if response.status_code == 503:
        response_503 = ProblemDetail.from_dict(response.json())

        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[CapabilitiesResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
) -> Response[CapabilitiesResponse | ProblemDetail]:
    """Get Capabilities

     Describe what this server offers, for a client's first call.

    Anonymous callers get the server, sign-in, basemap, workflow and rate-limit
    facts. A caller with credentials also gets `upload` and `me`.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CapabilitiesResponse | ProblemDetail]
    """

    kwargs = _get_kwargs()

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
) -> CapabilitiesResponse | ProblemDetail | None:
    """Get Capabilities

     Describe what this server offers, for a client's first call.

    Anonymous callers get the server, sign-in, basemap, workflow and rate-limit
    facts. A caller with credentials also gets `upload` and `me`.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CapabilitiesResponse | ProblemDetail
    """

    return sync_detailed(
        client=client,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
) -> Response[CapabilitiesResponse | ProblemDetail]:
    """Get Capabilities

     Describe what this server offers, for a client's first call.

    Anonymous callers get the server, sign-in, basemap, workflow and rate-limit
    facts. A caller with credentials also gets `upload` and `me`.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CapabilitiesResponse | ProblemDetail]
    """

    kwargs = _get_kwargs()

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
) -> CapabilitiesResponse | ProblemDetail | None:
    """Get Capabilities

     Describe what this server offers, for a client's first call.

    Anonymous callers get the server, sign-in, basemap, workflow and rate-limit
    facts. A caller with credentials also gets `upload` and `me`.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CapabilitiesResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
        )
    ).parsed
