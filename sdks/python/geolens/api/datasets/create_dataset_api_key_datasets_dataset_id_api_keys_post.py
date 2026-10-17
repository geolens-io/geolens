from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.api_key_create_response import ApiKeyCreateResponse
from ...models.dataset_api_key_create_request import DatasetApiKeyCreateRequest
from ...models.problem_detail import ProblemDetail
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    *,
    body: DatasetApiKeyCreateRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/datasets/{dataset_id}/api-keys".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ApiKeyCreateResponse | ProblemDetail | None:
    if response.status_code == 201:
        response_201 = ApiKeyCreateResponse.from_dict(response.json())

        return response_201

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
) -> Response[ApiKeyCreateResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    body: DatasetApiKeyCreateRequest,
) -> Response[ApiKeyCreateResponse | ProblemDetail]:
    """Create Dataset Api Key

     Create a key that reads and writes this dataset's features only.

    The key has scope ``dataset_write`` and acts as the caller, so the
    caller's own access to the dataset still applies to every request it
    makes. It authenticates the dataset's feature routes and OGC API
    Features items, and is treated as an invalid key everywhere else. It must
    expire within 365 days. Requires write access to the dataset and a
    signed-in session; the raw key is returned only in this response.

    Args:
        dataset_id (UUID):
        body (DatasetApiKeyCreateRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ApiKeyCreateResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    body: DatasetApiKeyCreateRequest,
) -> ApiKeyCreateResponse | ProblemDetail | None:
    """Create Dataset Api Key

     Create a key that reads and writes this dataset's features only.

    The key has scope ``dataset_write`` and acts as the caller, so the
    caller's own access to the dataset still applies to every request it
    makes. It authenticates the dataset's feature routes and OGC API
    Features items, and is treated as an invalid key everywhere else. It must
    expire within 365 days. Requires write access to the dataset and a
    signed-in session; the raw key is returned only in this response.

    Args:
        dataset_id (UUID):
        body (DatasetApiKeyCreateRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ApiKeyCreateResponse | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    body: DatasetApiKeyCreateRequest,
) -> Response[ApiKeyCreateResponse | ProblemDetail]:
    """Create Dataset Api Key

     Create a key that reads and writes this dataset's features only.

    The key has scope ``dataset_write`` and acts as the caller, so the
    caller's own access to the dataset still applies to every request it
    makes. It authenticates the dataset's feature routes and OGC API
    Features items, and is treated as an invalid key everywhere else. It must
    expire within 365 days. Requires write access to the dataset and a
    signed-in session; the raw key is returned only in this response.

    Args:
        dataset_id (UUID):
        body (DatasetApiKeyCreateRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ApiKeyCreateResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    body: DatasetApiKeyCreateRequest,
) -> ApiKeyCreateResponse | ProblemDetail | None:
    """Create Dataset Api Key

     Create a key that reads and writes this dataset's features only.

    The key has scope ``dataset_write`` and acts as the caller, so the
    caller's own access to the dataset still applies to every request it
    makes. It authenticates the dataset's feature routes and OGC API
    Features items, and is treated as an invalid key everywhere else. It must
    expire within 365 days. Requires write access to the dataset and a
    signed-in session; the raw key is returned only in this response.

    Args:
        dataset_id (UUID):
        body (DatasetApiKeyCreateRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ApiKeyCreateResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
            body=body,
        )
    ).parsed
