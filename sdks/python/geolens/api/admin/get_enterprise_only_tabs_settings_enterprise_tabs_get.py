from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.enterprise_tabs_response import EnterpriseTabsResponse
from ...models.problem_detail import ProblemDetail


def _get_kwargs() -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/settings/enterprise-tabs/",
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EnterpriseTabsResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = EnterpriseTabsResponse.from_dict(response.json())

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

    if response.status_code == 500:
        response_500 = ProblemDetail.from_dict(response.json())

        return response_500

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[EnterpriseTabsResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
) -> Response[EnterpriseTabsResponse | ProblemDetail]:
    """Get Enterprise Only Tabs

     Return the canonical list of Settings tab keys that are enterprise-only.

    Phase 279 ADMIN-03 (M-03): single source of truth for enterprise-only
    Settings tabs. The frontend AdminSidebar uses this to conditionally render
    the tabs in community vs enterprise editions. The backend
    ``_require_enterprise_for_key`` gate uses the same set to 404 community
    attempts at writing enterprise-tab settings — keeping these aligned
    prevents silent UX drift.

    Note: not gated by ``require_enterprise``. Community callers must be able
    to read the list to render their own sidebar correctly (the response tells
    them which tabs to HIDE).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnterpriseTabsResponse | ProblemDetail]
    """

    kwargs = _get_kwargs()

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
) -> EnterpriseTabsResponse | ProblemDetail | None:
    """Get Enterprise Only Tabs

     Return the canonical list of Settings tab keys that are enterprise-only.

    Phase 279 ADMIN-03 (M-03): single source of truth for enterprise-only
    Settings tabs. The frontend AdminSidebar uses this to conditionally render
    the tabs in community vs enterprise editions. The backend
    ``_require_enterprise_for_key`` gate uses the same set to 404 community
    attempts at writing enterprise-tab settings — keeping these aligned
    prevents silent UX drift.

    Note: not gated by ``require_enterprise``. Community callers must be able
    to read the list to render their own sidebar correctly (the response tells
    them which tabs to HIDE).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnterpriseTabsResponse | ProblemDetail
    """

    return sync_detailed(
        client=client,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
) -> Response[EnterpriseTabsResponse | ProblemDetail]:
    """Get Enterprise Only Tabs

     Return the canonical list of Settings tab keys that are enterprise-only.

    Phase 279 ADMIN-03 (M-03): single source of truth for enterprise-only
    Settings tabs. The frontend AdminSidebar uses this to conditionally render
    the tabs in community vs enterprise editions. The backend
    ``_require_enterprise_for_key`` gate uses the same set to 404 community
    attempts at writing enterprise-tab settings — keeping these aligned
    prevents silent UX drift.

    Note: not gated by ``require_enterprise``. Community callers must be able
    to read the list to render their own sidebar correctly (the response tells
    them which tabs to HIDE).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnterpriseTabsResponse | ProblemDetail]
    """

    kwargs = _get_kwargs()

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
) -> EnterpriseTabsResponse | ProblemDetail | None:
    """Get Enterprise Only Tabs

     Return the canonical list of Settings tab keys that are enterprise-only.

    Phase 279 ADMIN-03 (M-03): single source of truth for enterprise-only
    Settings tabs. The frontend AdminSidebar uses this to conditionally render
    the tabs in community vs enterprise editions. The backend
    ``_require_enterprise_for_key`` gate uses the same set to 404 community
    attempts at writing enterprise-tab settings — keeping these aligned
    prevents silent UX drift.

    Note: not gated by ``require_enterprise``. Community callers must be able
    to read the list to render their own sidebar correctly (the response tells
    them which tabs to HIDE).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnterpriseTabsResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
        )
    ).parsed
