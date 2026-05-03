from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.probe_request import ProbeRequest
from ...models.probe_response import ProbeResponse
from ...models.problem_detail import ProblemDetail


def _get_kwargs(
    *,
    body: ProbeRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/services/probe/",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ProbeResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = ProbeResponse.from_dict(response.json())

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
) -> Response[ProbeResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: ProbeRequest,
) -> Response[ProbeResponse | ProblemDetail]:
    """Probe Service Url

     Probe a remote service URL to detect its type and list available layers.

    Validates the URL against SSRF, detects whether it is a WFS or ArcGIS
    service, and returns a unified layer list. All attempts are audit-logged.

    Args:
        body (ProbeRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProbeResponse | ProblemDetail]
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
    body: ProbeRequest,
) -> ProbeResponse | ProblemDetail | None:
    """Probe Service Url

     Probe a remote service URL to detect its type and list available layers.

    Validates the URL against SSRF, detects whether it is a WFS or ArcGIS
    service, and returns a unified layer list. All attempts are audit-logged.

    Args:
        body (ProbeRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProbeResponse | ProblemDetail
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: ProbeRequest,
) -> Response[ProbeResponse | ProblemDetail]:
    """Probe Service Url

     Probe a remote service URL to detect its type and list available layers.

    Validates the URL against SSRF, detects whether it is a WFS or ArcGIS
    service, and returns a unified layer list. All attempts are audit-logged.

    Args:
        body (ProbeRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProbeResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: ProbeRequest,
) -> ProbeResponse | ProblemDetail | None:
    """Probe Service Url

     Probe a remote service URL to detect its type and list available layers.

    Validates the URL against SSRF, detects whether it is a WFS or ArcGIS
    service, and returns a unified layer list. All attempts are audit-logged.

    Args:
        body (ProbeRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProbeResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
