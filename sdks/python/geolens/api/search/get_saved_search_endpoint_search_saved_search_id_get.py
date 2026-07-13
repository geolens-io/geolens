from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.http_validation_error import HTTPValidationError
from ...models.problem_detail import ProblemDetail
from ...models.saved_search_response import SavedSearchResponse
from uuid import UUID


def _get_kwargs(
    search_id: UUID,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/search/saved/{search_id}".format(
            search_id=quote(str(search_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | ProblemDetail | SavedSearchResponse | None:
    if response.status_code == 200:
        response_200 = SavedSearchResponse.from_dict(response.json())

        return response_200

    if response.status_code == 404:
        response_404 = ProblemDetail.from_dict(response.json())

        return response_404

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

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
) -> Response[HTTPValidationError | ProblemDetail | SavedSearchResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    search_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[HTTPValidationError | ProblemDetail | SavedSearchResponse]:
    """Get Saved Search Endpoint

     Get a single saved search by ID.

    Args:
        search_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | ProblemDetail | SavedSearchResponse]
    """

    kwargs = _get_kwargs(
        search_id=search_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    search_id: UUID,
    *,
    client: AuthenticatedClient,
) -> HTTPValidationError | ProblemDetail | SavedSearchResponse | None:
    """Get Saved Search Endpoint

     Get a single saved search by ID.

    Args:
        search_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | ProblemDetail | SavedSearchResponse
    """

    return sync_detailed(
        search_id=search_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    search_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[HTTPValidationError | ProblemDetail | SavedSearchResponse]:
    """Get Saved Search Endpoint

     Get a single saved search by ID.

    Args:
        search_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | ProblemDetail | SavedSearchResponse]
    """

    kwargs = _get_kwargs(
        search_id=search_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    search_id: UUID,
    *,
    client: AuthenticatedClient,
) -> HTTPValidationError | ProblemDetail | SavedSearchResponse | None:
    """Get Saved Search Endpoint

     Get a single saved search by ID.

    Args:
        search_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | ProblemDetail | SavedSearchResponse
    """

    return (
        await asyncio_detailed(
            search_id=search_id,
            client=client,
        )
    ).parsed
