from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.branding_response import BrandingResponse
from ...models.problem_detail import ProblemDetail


def _get_kwargs() -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/settings/branding/",
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> BrandingResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = BrandingResponse.from_dict(response.json())

        return response_200

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
) -> Response[BrandingResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
) -> Response[BrandingResponse | ProblemDetail]:
    """Get Branding

     Return branding configuration (public, no auth required).

    The active ``BrandingExtension`` provides initial defaults for branding
    keys. PersistentConfig overrides take precedence when set. Community
    advertises read-only ``show_badge`` only; badge-removal writes and
    additional branding keys are restricted controls.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[BrandingResponse | ProblemDetail]
    """

    kwargs = _get_kwargs()

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
) -> BrandingResponse | ProblemDetail | None:
    """Get Branding

     Return branding configuration (public, no auth required).

    The active ``BrandingExtension`` provides initial defaults for branding
    keys. PersistentConfig overrides take precedence when set. Community
    advertises read-only ``show_badge`` only; badge-removal writes and
    additional branding keys are restricted controls.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        BrandingResponse | ProblemDetail
    """

    return sync_detailed(
        client=client,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
) -> Response[BrandingResponse | ProblemDetail]:
    """Get Branding

     Return branding configuration (public, no auth required).

    The active ``BrandingExtension`` provides initial defaults for branding
    keys. PersistentConfig overrides take precedence when set. Community
    advertises read-only ``show_badge`` only; badge-removal writes and
    additional branding keys are restricted controls.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[BrandingResponse | ProblemDetail]
    """

    kwargs = _get_kwargs()

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
) -> BrandingResponse | ProblemDetail | None:
    """Get Branding

     Return branding configuration (public, no auth required).

    The active ``BrandingExtension`` provides initial defaults for branding
    keys. PersistentConfig overrides take precedence when set. Community
    advertises read-only ``show_badge`` only; badge-removal writes and
    additional branding keys are restricted controls.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        BrandingResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
        )
    ).parsed
