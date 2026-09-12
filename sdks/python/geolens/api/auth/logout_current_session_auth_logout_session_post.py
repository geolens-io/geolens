from http import HTTPStatus
from typing import Any, cast

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...models.refresh_request import RefreshRequest
from ...types import Unset


def _get_kwargs(
    *,
    body: None | RefreshRequest | Unset = UNSET,
    authorization: None | str | Unset = UNSET,
    x_csrf_token: None | str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(authorization, Unset):
        headers["authorization"] = authorization

    if not isinstance(x_csrf_token, Unset):
        headers["X-CSRF-Token"] = x_csrf_token

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/auth/logout/session/",
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
) -> Any | ProblemDetail | None:
    if response.status_code == 204:
        response_204 = cast(Any, None)
        return response_204

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
) -> Response[Any | ProblemDetail]:
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
    authorization: None | str | Unset = UNSET,
    x_csrf_token: None | str | Unset = UNSET,
) -> Response[Any | ProblemDetail]:
    """Logout Current Session

     Revoke only the presented session's refresh-token family.

    Other devices and API keys survive. Access JWTs remain usable until their
    normal expiry; /logout/ still immediately revokes every access and refresh
    session. A valid signed access JWT with sid, a refresh body token, or a
    refresh cookie authorizes this operation. Legacy JWTs without sid must use
    the refresh credential. Cookie authorization requires double-submit CSRF.

    Bearer/body revocation does not change cookies, allowing a captured old
    session to be discarded safely after a newer login. Cookie authorization
    clears the browser's refresh and CSRF cookies.

    Args:
        authorization (None | str | Unset):
        x_csrf_token (None | str | Unset): Double-submit CSRF token, enforced only when the
            refresh cookie is what authenticates the call. Echo the value of the `geolens_csrf` cookie
            issued alongside the refresh cookie. Callers presenting a refresh token in the request
            body do not send it.
        body (None | RefreshRequest | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        body=body,
        authorization=authorization,
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
    authorization: None | str | Unset = UNSET,
    x_csrf_token: None | str | Unset = UNSET,
) -> Any | ProblemDetail | None:
    """Logout Current Session

     Revoke only the presented session's refresh-token family.

    Other devices and API keys survive. Access JWTs remain usable until their
    normal expiry; /logout/ still immediately revokes every access and refresh
    session. A valid signed access JWT with sid, a refresh body token, or a
    refresh cookie authorizes this operation. Legacy JWTs without sid must use
    the refresh credential. Cookie authorization requires double-submit CSRF.

    Bearer/body revocation does not change cookies, allowing a captured old
    session to be discarded safely after a newer login. Cookie authorization
    clears the browser's refresh and CSRF cookies.

    Args:
        authorization (None | str | Unset):
        x_csrf_token (None | str | Unset): Double-submit CSRF token, enforced only when the
            refresh cookie is what authenticates the call. Echo the value of the `geolens_csrf` cookie
            issued alongside the refresh cookie. Callers presenting a refresh token in the request
            body do not send it.
        body (None | RefreshRequest | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return sync_detailed(
        client=client,
        body=body,
        authorization=authorization,
        x_csrf_token=x_csrf_token,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: None | RefreshRequest | Unset = UNSET,
    authorization: None | str | Unset = UNSET,
    x_csrf_token: None | str | Unset = UNSET,
) -> Response[Any | ProblemDetail]:
    """Logout Current Session

     Revoke only the presented session's refresh-token family.

    Other devices and API keys survive. Access JWTs remain usable until their
    normal expiry; /logout/ still immediately revokes every access and refresh
    session. A valid signed access JWT with sid, a refresh body token, or a
    refresh cookie authorizes this operation. Legacy JWTs without sid must use
    the refresh credential. Cookie authorization requires double-submit CSRF.

    Bearer/body revocation does not change cookies, allowing a captured old
    session to be discarded safely after a newer login. Cookie authorization
    clears the browser's refresh and CSRF cookies.

    Args:
        authorization (None | str | Unset):
        x_csrf_token (None | str | Unset): Double-submit CSRF token, enforced only when the
            refresh cookie is what authenticates the call. Echo the value of the `geolens_csrf` cookie
            issued alongside the refresh cookie. Callers presenting a refresh token in the request
            body do not send it.
        body (None | RefreshRequest | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        body=body,
        authorization=authorization,
        x_csrf_token=x_csrf_token,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: None | RefreshRequest | Unset = UNSET,
    authorization: None | str | Unset = UNSET,
    x_csrf_token: None | str | Unset = UNSET,
) -> Any | ProblemDetail | None:
    """Logout Current Session

     Revoke only the presented session's refresh-token family.

    Other devices and API keys survive. Access JWTs remain usable until their
    normal expiry; /logout/ still immediately revokes every access and refresh
    session. A valid signed access JWT with sid, a refresh body token, or a
    refresh cookie authorizes this operation. Legacy JWTs without sid must use
    the refresh credential. Cookie authorization requires double-submit CSRF.

    Bearer/body revocation does not change cookies, allowing a captured old
    session to be discarded safely after a newer login. Cookie authorization
    clears the browser's refresh and CSRF cookies.

    Args:
        authorization (None | str | Unset):
        x_csrf_token (None | str | Unset): Double-submit CSRF token, enforced only when the
            refresh cookie is what authenticates the call. Echo the value of the `geolens_csrf` cookie
            issued alongside the refresh cookie. Callers presenting a refresh token in the request
            body do not send it.
        body (None | RefreshRequest | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
            authorization=authorization,
            x_csrf_token=x_csrf_token,
        )
    ).parsed
