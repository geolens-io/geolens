from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...models.refresh_request import RefreshRequest
from ...models.token_response import TokenResponse
from ...types import Unset


def _get_kwargs(
    *,
    body: None | RefreshRequest | Unset = UNSET,
    x_geo_lens_auth_mode: None | str | Unset = UNSET,
    x_csrf_token: None | str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(x_geo_lens_auth_mode, Unset):
        headers["X-GeoLens-Auth-Mode"] = x_geo_lens_auth_mode

    if not isinstance(x_csrf_token, Unset):
        headers["X-CSRF-Token"] = x_csrf_token

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/auth/refresh/",
    }

    if isinstance(body, RefreshRequest):
        _kwargs["json"] = body.to_dict()
    elif not isinstance(body, Unset):
        _kwargs["json"] = body

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
    body: None | RefreshRequest | Unset = UNSET,
    x_geo_lens_auth_mode: None | str | Unset = UNSET,
    x_csrf_token: None | str | Unset = UNSET,
) -> Response[ProblemDetail | TokenResponse]:
    """Refresh

     Exchange a valid refresh token for a new access + refresh token pair.

    Multi-tenant clients must call this endpoint on their tenant host. Refresh
    tokens are opaque and carry no bearer ``tid`` claim, so tenant middleware
    binds the database transaction from that same-origin host before the user
    row is resolved and the next tenant-bound access token is minted.

    GH-1302: with ``X-GeoLens-Auth-Mode: cookie`` the presented token is read
    from the httpOnly cookie (falling back to the body once, so a session
    established before the cookie flow shipped migrates on its next refresh
    instead of being logged out), the double-submit CSRF token is enforced, and
    the rotated token goes back out as a cookie with a null body
    ``refresh_token``. Without the header this endpoint behaves exactly as
    before.

    Args:
        x_geo_lens_auth_mode (None | str | Unset): Browser session-transport negotiation. Send
            `cookie` to carry the refresh token in an httpOnly `geolens_refresh` cookie, paired with a
            script-readable `geolens_csrf` cookie, and receive a null `refresh_token` in the response
            body. When the header is absent (the default) the refresh token is returned in the
            response body, which is the contract every non-browser caller uses.
        x_csrf_token (None | str | Unset): Double-submit CSRF token, enforced only when the
            refresh cookie is what authenticates the call. Echo the value of the `geolens_csrf` cookie
            issued alongside the refresh cookie. Callers presenting a refresh token in the request
            body do not send it.
        body (None | RefreshRequest | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | TokenResponse]
    """

    kwargs = _get_kwargs(
        body=body,
        x_geo_lens_auth_mode=x_geo_lens_auth_mode,
        x_csrf_token=x_csrf_token,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    body: None | RefreshRequest | Unset = UNSET,
    x_geo_lens_auth_mode: None | str | Unset = UNSET,
    x_csrf_token: None | str | Unset = UNSET,
) -> ProblemDetail | TokenResponse | None:
    """Refresh

     Exchange a valid refresh token for a new access + refresh token pair.

    Multi-tenant clients must call this endpoint on their tenant host. Refresh
    tokens are opaque and carry no bearer ``tid`` claim, so tenant middleware
    binds the database transaction from that same-origin host before the user
    row is resolved and the next tenant-bound access token is minted.

    GH-1302: with ``X-GeoLens-Auth-Mode: cookie`` the presented token is read
    from the httpOnly cookie (falling back to the body once, so a session
    established before the cookie flow shipped migrates on its next refresh
    instead of being logged out), the double-submit CSRF token is enforced, and
    the rotated token goes back out as a cookie with a null body
    ``refresh_token``. Without the header this endpoint behaves exactly as
    before.

    Args:
        x_geo_lens_auth_mode (None | str | Unset): Browser session-transport negotiation. Send
            `cookie` to carry the refresh token in an httpOnly `geolens_refresh` cookie, paired with a
            script-readable `geolens_csrf` cookie, and receive a null `refresh_token` in the response
            body. When the header is absent (the default) the refresh token is returned in the
            response body, which is the contract every non-browser caller uses.
        x_csrf_token (None | str | Unset): Double-submit CSRF token, enforced only when the
            refresh cookie is what authenticates the call. Echo the value of the `geolens_csrf` cookie
            issued alongside the refresh cookie. Callers presenting a refresh token in the request
            body do not send it.
        body (None | RefreshRequest | Unset):

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
        x_csrf_token=x_csrf_token,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: None | RefreshRequest | Unset = UNSET,
    x_geo_lens_auth_mode: None | str | Unset = UNSET,
    x_csrf_token: None | str | Unset = UNSET,
) -> Response[ProblemDetail | TokenResponse]:
    """Refresh

     Exchange a valid refresh token for a new access + refresh token pair.

    Multi-tenant clients must call this endpoint on their tenant host. Refresh
    tokens are opaque and carry no bearer ``tid`` claim, so tenant middleware
    binds the database transaction from that same-origin host before the user
    row is resolved and the next tenant-bound access token is minted.

    GH-1302: with ``X-GeoLens-Auth-Mode: cookie`` the presented token is read
    from the httpOnly cookie (falling back to the body once, so a session
    established before the cookie flow shipped migrates on its next refresh
    instead of being logged out), the double-submit CSRF token is enforced, and
    the rotated token goes back out as a cookie with a null body
    ``refresh_token``. Without the header this endpoint behaves exactly as
    before.

    Args:
        x_geo_lens_auth_mode (None | str | Unset): Browser session-transport negotiation. Send
            `cookie` to carry the refresh token in an httpOnly `geolens_refresh` cookie, paired with a
            script-readable `geolens_csrf` cookie, and receive a null `refresh_token` in the response
            body. When the header is absent (the default) the refresh token is returned in the
            response body, which is the contract every non-browser caller uses.
        x_csrf_token (None | str | Unset): Double-submit CSRF token, enforced only when the
            refresh cookie is what authenticates the call. Echo the value of the `geolens_csrf` cookie
            issued alongside the refresh cookie. Callers presenting a refresh token in the request
            body do not send it.
        body (None | RefreshRequest | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | TokenResponse]
    """

    kwargs = _get_kwargs(
        body=body,
        x_geo_lens_auth_mode=x_geo_lens_auth_mode,
        x_csrf_token=x_csrf_token,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: None | RefreshRequest | Unset = UNSET,
    x_geo_lens_auth_mode: None | str | Unset = UNSET,
    x_csrf_token: None | str | Unset = UNSET,
) -> ProblemDetail | TokenResponse | None:
    """Refresh

     Exchange a valid refresh token for a new access + refresh token pair.

    Multi-tenant clients must call this endpoint on their tenant host. Refresh
    tokens are opaque and carry no bearer ``tid`` claim, so tenant middleware
    binds the database transaction from that same-origin host before the user
    row is resolved and the next tenant-bound access token is minted.

    GH-1302: with ``X-GeoLens-Auth-Mode: cookie`` the presented token is read
    from the httpOnly cookie (falling back to the body once, so a session
    established before the cookie flow shipped migrates on its next refresh
    instead of being logged out), the double-submit CSRF token is enforced, and
    the rotated token goes back out as a cookie with a null body
    ``refresh_token``. Without the header this endpoint behaves exactly as
    before.

    Args:
        x_geo_lens_auth_mode (None | str | Unset): Browser session-transport negotiation. Send
            `cookie` to carry the refresh token in an httpOnly `geolens_refresh` cookie, paired with a
            script-readable `geolens_csrf` cookie, and receive a null `refresh_token` in the response
            body. When the header is absent (the default) the refresh token is returned in the
            response body, which is the contract every non-browser caller uses.
        x_csrf_token (None | str | Unset): Double-submit CSRF token, enforced only when the
            refresh cookie is what authenticates the call. Echo the value of the `geolens_csrf` cookie
            issued alongside the refresh cookie. Callers presenting a refresh token in the request
            body do not send it.
        body (None | RefreshRequest | Unset):

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
            x_csrf_token=x_csrf_token,
        )
    ).parsed
