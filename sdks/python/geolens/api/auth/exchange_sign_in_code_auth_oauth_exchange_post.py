from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...models.sso_exchange_request import SsoExchangeRequest
from ...models.token_response import TokenResponse
from ...types import Unset


def _get_kwargs(
    *,
    body: SsoExchangeRequest,
    x_geo_lens_auth_mode: None | str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(x_geo_lens_auth_mode, Unset):
        headers["X-GeoLens-Auth-Mode"] = x_geo_lens_auth_mode

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/auth/oauth/exchange/",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ProblemDetail | TokenResponse | None:
    if response.status_code == 200:
        response_200 = TokenResponse.from_dict(response.json())

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
) -> Response[ProblemDetail | TokenResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: SsoExchangeRequest,
    x_geo_lens_auth_mode: None | str | Unset = UNSET,
) -> Response[ProblemDetail | TokenResponse]:
    """Exchange Sign In Code

     Exchange a single sign-on code for a browser session.

    When the SPA shares the API's origin, an OAuth or SAML callback redirects
    with a one-time code in the URL fragment instead of setting the refresh
    cookie. The sign-in page posts that code here, and the response sets the
    httpOnly refresh cookie and its CSRF cookie the way ``/auth/login`` does
    in cookie mode, with a null ``refresh_token`` in the body.

    A code is valid once, for about a minute, and only from the browser the
    callback redirected. Every refusal is the same 401.

    Args:
        x_geo_lens_auth_mode (None | str | Unset): Must be `cookie`: this call only establishes a
            browser cookie session.
        body (SsoExchangeRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | TokenResponse]
    """

    kwargs = _get_kwargs(
        body=body,
        x_geo_lens_auth_mode=x_geo_lens_auth_mode,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    body: SsoExchangeRequest,
    x_geo_lens_auth_mode: None | str | Unset = UNSET,
) -> ProblemDetail | TokenResponse | None:
    """Exchange Sign In Code

     Exchange a single sign-on code for a browser session.

    When the SPA shares the API's origin, an OAuth or SAML callback redirects
    with a one-time code in the URL fragment instead of setting the refresh
    cookie. The sign-in page posts that code here, and the response sets the
    httpOnly refresh cookie and its CSRF cookie the way ``/auth/login`` does
    in cookie mode, with a null ``refresh_token`` in the body.

    A code is valid once, for about a minute, and only from the browser the
    callback redirected. Every refusal is the same 401.

    Args:
        x_geo_lens_auth_mode (None | str | Unset): Must be `cookie`: this call only establishes a
            browser cookie session.
        body (SsoExchangeRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | TokenResponse
    """

    return sync_detailed(
        client=client,
        body=body,
        x_geo_lens_auth_mode=x_geo_lens_auth_mode,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: SsoExchangeRequest,
    x_geo_lens_auth_mode: None | str | Unset = UNSET,
) -> Response[ProblemDetail | TokenResponse]:
    """Exchange Sign In Code

     Exchange a single sign-on code for a browser session.

    When the SPA shares the API's origin, an OAuth or SAML callback redirects
    with a one-time code in the URL fragment instead of setting the refresh
    cookie. The sign-in page posts that code here, and the response sets the
    httpOnly refresh cookie and its CSRF cookie the way ``/auth/login`` does
    in cookie mode, with a null ``refresh_token`` in the body.

    A code is valid once, for about a minute, and only from the browser the
    callback redirected. Every refusal is the same 401.

    Args:
        x_geo_lens_auth_mode (None | str | Unset): Must be `cookie`: this call only establishes a
            browser cookie session.
        body (SsoExchangeRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | TokenResponse]
    """

    kwargs = _get_kwargs(
        body=body,
        x_geo_lens_auth_mode=x_geo_lens_auth_mode,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: SsoExchangeRequest,
    x_geo_lens_auth_mode: None | str | Unset = UNSET,
) -> ProblemDetail | TokenResponse | None:
    """Exchange Sign In Code

     Exchange a single sign-on code for a browser session.

    When the SPA shares the API's origin, an OAuth or SAML callback redirects
    with a one-time code in the URL fragment instead of setting the refresh
    cookie. The sign-in page posts that code here, and the response sets the
    httpOnly refresh cookie and its CSRF cookie the way ``/auth/login`` does
    in cookie mode, with a null ``refresh_token`` in the body.

    A code is valid once, for about a minute, and only from the browser the
    callback redirected. Every refusal is the same 401.

    Args:
        x_geo_lens_auth_mode (None | str | Unset): Must be `cookie`: this call only establishes a
            browser cookie session.
        body (SsoExchangeRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | TokenResponse
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
            x_geo_lens_auth_mode=x_geo_lens_auth_mode,
        )
    ).parsed
