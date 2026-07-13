from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.http_validation_error import HTTPValidationError
from ...models.problem_detail import ProblemDetail
from uuid import UUID


def _get_kwargs(
    search_id: UUID,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "delete",
        "url": "/search/saved/{search_id}".format(
            search_id=quote(str(search_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | HTTPValidationError | ProblemDetail | None:
    if response.status_code == 204:
        response_204 = cast(Any, None)
        return response_204

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
) -> Response[Any | HTTPValidationError | ProblemDetail]:
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
) -> Response[Any | HTTPValidationError | ProblemDetail]:
    """Delete Saved Search Endpoint

     Delete a saved search.

    Args:
        search_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError | ProblemDetail]
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
) -> Any | HTTPValidationError | ProblemDetail | None:
    """Delete Saved Search Endpoint

     Delete a saved search.

    Args:
        search_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError | ProblemDetail
    """

    return sync_detailed(
        search_id=search_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    search_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[Any | HTTPValidationError | ProblemDetail]:
    """Delete Saved Search Endpoint

     Delete a saved search.

    Args:
        search_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError | ProblemDetail]
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
) -> Any | HTTPValidationError | ProblemDetail | None:
    """Delete Saved Search Endpoint

     Delete a saved search.

    Args:
        search_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError | ProblemDetail
    """

    return (
        await asyncio_detailed(
            search_id=search_id,
            client=client,
        )
    ).parsed
