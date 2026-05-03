from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.o_auth_provider_create import OAuthProviderCreate
from ...models.o_auth_provider_response import OAuthProviderResponse
from ...models.problem_detail import ProblemDetail


def _get_kwargs(
    *,
    body: OAuthProviderCreate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/settings/oauth-providers/",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> OAuthProviderResponse | ProblemDetail | None:
    if response.status_code == 201:
        response_201 = OAuthProviderResponse.from_dict(response.json())

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
) -> Response[OAuthProviderResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: OAuthProviderCreate,
) -> Response[OAuthProviderResponse | ProblemDetail]:
    """Create Oauth Provider

     Create a new OAuth or SAML provider (admin only).

    Audit-log payload includes the full ``created`` snapshot with non-secret
    fields verbatim and ``<redacted>`` markers for secrets that were submitted
    in the request body (SAML-12 / Pitfall 9 / T-217-03-AUDIT-LEAK).

    Args:
        body (OAuthProviderCreate): Schema for creating a new OAuth provider.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[OAuthProviderResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: OAuthProviderCreate,
) -> OAuthProviderResponse | ProblemDetail | None:
    """Create Oauth Provider

     Create a new OAuth or SAML provider (admin only).

    Audit-log payload includes the full ``created`` snapshot with non-secret
    fields verbatim and ``<redacted>`` markers for secrets that were submitted
    in the request body (SAML-12 / Pitfall 9 / T-217-03-AUDIT-LEAK).

    Args:
        body (OAuthProviderCreate): Schema for creating a new OAuth provider.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        OAuthProviderResponse | ProblemDetail
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: OAuthProviderCreate,
) -> Response[OAuthProviderResponse | ProblemDetail]:
    """Create Oauth Provider

     Create a new OAuth or SAML provider (admin only).

    Audit-log payload includes the full ``created`` snapshot with non-secret
    fields verbatim and ``<redacted>`` markers for secrets that were submitted
    in the request body (SAML-12 / Pitfall 9 / T-217-03-AUDIT-LEAK).

    Args:
        body (OAuthProviderCreate): Schema for creating a new OAuth provider.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[OAuthProviderResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: OAuthProviderCreate,
) -> OAuthProviderResponse | ProblemDetail | None:
    """Create Oauth Provider

     Create a new OAuth or SAML provider (admin only).

    Audit-log payload includes the full ``created`` snapshot with non-secret
    fields verbatim and ``<redacted>`` markers for secrets that were submitted
    in the request body (SAML-12 / Pitfall 9 / T-217-03-AUDIT-LEAK).

    Args:
        body (OAuthProviderCreate): Schema for creating a new OAuth provider.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        OAuthProviderResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
