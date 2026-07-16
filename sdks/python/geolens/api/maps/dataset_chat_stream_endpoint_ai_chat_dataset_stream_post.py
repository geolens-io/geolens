from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.dataset_chat_request import DatasetChatRequest
from ...models.problem_detail import ProblemDetail


def _get_kwargs(
    *,
    body: DatasetChatRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/ai/chat/dataset/stream/",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ProblemDetail | str | None:
    if response.status_code == 200:
        response_200 = response.text
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
) -> Response[ProblemDetail | str]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: DatasetChatRequest,
) -> Response[ProblemDetail | str]:
    """Dataset Chat Stream Endpoint

     Dataset-scoped AI chat: ask questions about a single dataset's data.

    Read-only by construction — ``can_edit=False`` selects the query_data-only
    tool set, and a dataset-framed system prompt replaces the map-editing one.
    Reuses the whole map-chat streaming pipeline (SQL generation, sandbox
    validation, RBAC table allowlist, token budgeting) with one synthetic
    server-built layer.

    Args:
        body (DatasetChatRequest): Dataset-scoped chat: no map, no client-supplied layer state.

            The server resolves ALL dataset context (table name, columns, samples)
            authoritatively from the DB — the client only names the dataset.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | str]
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
    body: DatasetChatRequest,
) -> ProblemDetail | str | None:
    """Dataset Chat Stream Endpoint

     Dataset-scoped AI chat: ask questions about a single dataset's data.

    Read-only by construction — ``can_edit=False`` selects the query_data-only
    tool set, and a dataset-framed system prompt replaces the map-editing one.
    Reuses the whole map-chat streaming pipeline (SQL generation, sandbox
    validation, RBAC table allowlist, token budgeting) with one synthetic
    server-built layer.

    Args:
        body (DatasetChatRequest): Dataset-scoped chat: no map, no client-supplied layer state.

            The server resolves ALL dataset context (table name, columns, samples)
            authoritatively from the DB — the client only names the dataset.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | str
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: DatasetChatRequest,
) -> Response[ProblemDetail | str]:
    """Dataset Chat Stream Endpoint

     Dataset-scoped AI chat: ask questions about a single dataset's data.

    Read-only by construction — ``can_edit=False`` selects the query_data-only
    tool set, and a dataset-framed system prompt replaces the map-editing one.
    Reuses the whole map-chat streaming pipeline (SQL generation, sandbox
    validation, RBAC table allowlist, token budgeting) with one synthetic
    server-built layer.

    Args:
        body (DatasetChatRequest): Dataset-scoped chat: no map, no client-supplied layer state.

            The server resolves ALL dataset context (table name, columns, samples)
            authoritatively from the DB — the client only names the dataset.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | str]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: DatasetChatRequest,
) -> ProblemDetail | str | None:
    """Dataset Chat Stream Endpoint

     Dataset-scoped AI chat: ask questions about a single dataset's data.

    Read-only by construction — ``can_edit=False`` selects the query_data-only
    tool set, and a dataset-framed system prompt replaces the map-editing one.
    Reuses the whole map-chat streaming pipeline (SQL generation, sandbox
    validation, RBAC table allowlist, token budgeting) with one synthetic
    server-built layer.

    Args:
        body (DatasetChatRequest): Dataset-scoped chat: no map, no client-supplied layer state.

            The server resolves ALL dataset context (table name, columns, samples)
            authoritatively from the DB — the client only names the dataset.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | str
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
