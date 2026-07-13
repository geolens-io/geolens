from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.notification_test_response import NotificationTestResponse
from ...models.problem_detail import ProblemDetail


def _get_kwargs() -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/settings/notifications/test/",
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> NotificationTestResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = NotificationTestResponse.from_dict(response.json())

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
) -> Response[NotificationTestResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
) -> Response[NotificationTestResponse | ProblemDetail]:
    """Send Test Notification

     Send a canned test notification through each configured channel (admin only).

    Mirrors detect_embedding_dims: admin-gated probe that reports per-channel
    reachable/error in a 200 body without leaking secrets or raising 5xx on a
    bad channel (NOTIF-06 / T-1229-08 / T-1229-09 / T-1229-10).

    Per-channel approach (not EnvConfiguredNotificationSink.deliver) is used so
    each channel's success/failure is captured in its own
    NotificationTestChannelResult for display in the admin UI.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[NotificationTestResponse | ProblemDetail]
    """

    kwargs = _get_kwargs()

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
) -> NotificationTestResponse | ProblemDetail | None:
    """Send Test Notification

     Send a canned test notification through each configured channel (admin only).

    Mirrors detect_embedding_dims: admin-gated probe that reports per-channel
    reachable/error in a 200 body without leaking secrets or raising 5xx on a
    bad channel (NOTIF-06 / T-1229-08 / T-1229-09 / T-1229-10).

    Per-channel approach (not EnvConfiguredNotificationSink.deliver) is used so
    each channel's success/failure is captured in its own
    NotificationTestChannelResult for display in the admin UI.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        NotificationTestResponse | ProblemDetail
    """

    return sync_detailed(
        client=client,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
) -> Response[NotificationTestResponse | ProblemDetail]:
    """Send Test Notification

     Send a canned test notification through each configured channel (admin only).

    Mirrors detect_embedding_dims: admin-gated probe that reports per-channel
    reachable/error in a 200 body without leaking secrets or raising 5xx on a
    bad channel (NOTIF-06 / T-1229-08 / T-1229-09 / T-1229-10).

    Per-channel approach (not EnvConfiguredNotificationSink.deliver) is used so
    each channel's success/failure is captured in its own
    NotificationTestChannelResult for display in the admin UI.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[NotificationTestResponse | ProblemDetail]
    """

    kwargs = _get_kwargs()

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
) -> NotificationTestResponse | ProblemDetail | None:
    """Send Test Notification

     Send a canned test notification through each configured channel (admin only).

    Mirrors detect_embedding_dims: admin-gated probe that reports per-channel
    reachable/error in a 200 body without leaking secrets or raising 5xx on a
    bad channel (NOTIF-06 / T-1229-08 / T-1229-09 / T-1229-10).

    Per-channel approach (not EnvConfiguredNotificationSink.deliver) is used so
    each channel's success/failure is captured in its own
    NotificationTestChannelResult for display in the admin UI.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        NotificationTestResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
        )
    ).parsed
