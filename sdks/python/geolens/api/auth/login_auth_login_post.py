from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.body_login_auth_login_post import BodyLoginAuthLoginPost
from ...models.problem_detail import ProblemDetail
from ...models.token_response import TokenResponse
from ...types import Unset


def _get_kwargs(
    *,
    body: BodyLoginAuthLoginPost,
    x_geo_lens_auth_mode: None | str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(x_geo_lens_auth_mode, Unset):
        headers["X-GeoLens-Auth-Mode"] = x_geo_lens_auth_mode

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/auth/login",
    }

    _kwargs["data"] = body.to_dict()

    headers["Content-Type"] = "application/x-www-form-urlencoded"

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
    body: BodyLoginAuthLoginPost,
    x_geo_lens_auth_mode: None | str | Unset = UNSET,
) -> Response[ProblemDetail | TokenResponse]:
    """Login

     Authenticate with username and password, receive a JWT token.

    GH-1302: a caller sending ``X-GeoLens-Auth-Mode: cookie`` receives the
    refresh token as an httpOnly cookie and a null ``refresh_token`` in the
    body. Without that header the response is unchanged, which is what keeps
    the CLI, the generated SDKs, Postman, and CI logins working.

    Args:
        x_geo_lens_auth_mode (None | str | Unset): Browser session-transport negotiation. Send
            `cookie` to carry the refresh token in an httpOnly `geolens_refresh` cookie, paired with a
            script-readable `geolens_csrf` cookie, and receive a null `refresh_token` in the response
            body. When the header is absent (the default) the refresh token is returned in the
            response body, which is the contract every non-browser caller uses.
        body (BodyLoginAuthLoginPost):

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
    body: BodyLoginAuthLoginPost,
    x_geo_lens_auth_mode: None | str | Unset = UNSET,
) -> ProblemDetail | TokenResponse | None:
    """Login

     Authenticate with username and password, receive a JWT token.

    GH-1302: a caller sending ``X-GeoLens-Auth-Mode: cookie`` receives the
    refresh token as an httpOnly cookie and a null ``refresh_token`` in the
    body. Without that header the response is unchanged, which is what keeps
    the CLI, the generated SDKs, Postman, and CI logins working.

    Args:
        x_geo_lens_auth_mode (None | str | Unset): Browser session-transport negotiation. Send
            `cookie` to carry the refresh token in an httpOnly `geolens_refresh` cookie, paired with a
            script-readable `geolens_csrf` cookie, and receive a null `refresh_token` in the response
            body. When the header is absent (the default) the refresh token is returned in the
            response body, which is the contract every non-browser caller uses.
        body (BodyLoginAuthLoginPost):

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
    body: BodyLoginAuthLoginPost,
    x_geo_lens_auth_mode: None | str | Unset = UNSET,
) -> Response[ProblemDetail | TokenResponse]:
    """Login

     Authenticate with username and password, receive a JWT token.

    GH-1302: a caller sending ``X-GeoLens-Auth-Mode: cookie`` receives the
    refresh token as an httpOnly cookie and a null ``refresh_token`` in the
    body. Without that header the response is unchanged, which is what keeps
    the CLI, the generated SDKs, Postman, and CI logins working.

    Args:
        x_geo_lens_auth_mode (None | str | Unset): Browser session-transport negotiation. Send
            `cookie` to carry the refresh token in an httpOnly `geolens_refresh` cookie, paired with a
            script-readable `geolens_csrf` cookie, and receive a null `refresh_token` in the response
            body. When the header is absent (the default) the refresh token is returned in the
            response body, which is the contract every non-browser caller uses.
        body (BodyLoginAuthLoginPost):

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
    body: BodyLoginAuthLoginPost,
    x_geo_lens_auth_mode: None | str | Unset = UNSET,
) -> ProblemDetail | TokenResponse | None:
    """Login

     Authenticate with username and password, receive a JWT token.

    GH-1302: a caller sending ``X-GeoLens-Auth-Mode: cookie`` receives the
    refresh token as an httpOnly cookie and a null ``refresh_token`` in the
    body. Without that header the response is unchanged, which is what keeps
    the CLI, the generated SDKs, Postman, and CI logins working.

    Args:
        x_geo_lens_auth_mode (None | str | Unset): Browser session-transport negotiation. Send
            `cookie` to carry the refresh token in an httpOnly `geolens_refresh` cookie, paired with a
            script-readable `geolens_csrf` cookie, and receive a null `refresh_token` in the response
            body. When the header is absent (the default) the refresh token is returned in the
            response body, which is the contract every non-browser caller uses.
        body (BodyLoginAuthLoginPost):

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
