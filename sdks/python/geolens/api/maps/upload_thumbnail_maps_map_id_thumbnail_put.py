from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...models.thumbnail_upload_request import ThumbnailUploadRequest
from uuid import UUID


def _get_kwargs(
    map_id: UUID,
    *,
    body: ThumbnailUploadRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/maps/{map_id}/thumbnail/".format(
            map_id=quote(str(map_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

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
) -> Response[Any | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    map_id: UUID,
    *,
    client: AuthenticatedClient,
    body: ThumbnailUploadRequest,
) -> Response[Any | ProblemDetail]:
    """Upload Thumbnail

     Upload a base64 thumbnail for a map.

    Accepts a data:image/ URI, decodes the base64 payload, writes the image
    bytes to the configured storage provider, and stores the storage key.

    Args:
        map_id (UUID):
        body (ThumbnailUploadRequest): JSON body for PUT /maps/{map_id}/thumbnail/.

            Replaces a previous text/plain body shape that openapi-python-client
            could not parse (would silently skip endpoint). See Phase 254 / SDK-01.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        map_id=map_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    map_id: UUID,
    *,
    client: AuthenticatedClient,
    body: ThumbnailUploadRequest,
) -> Any | ProblemDetail | None:
    """Upload Thumbnail

     Upload a base64 thumbnail for a map.

    Accepts a data:image/ URI, decodes the base64 payload, writes the image
    bytes to the configured storage provider, and stores the storage key.

    Args:
        map_id (UUID):
        body (ThumbnailUploadRequest): JSON body for PUT /maps/{map_id}/thumbnail/.

            Replaces a previous text/plain body shape that openapi-python-client
            could not parse (would silently skip endpoint). See Phase 254 / SDK-01.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return sync_detailed(
        map_id=map_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    map_id: UUID,
    *,
    client: AuthenticatedClient,
    body: ThumbnailUploadRequest,
) -> Response[Any | ProblemDetail]:
    """Upload Thumbnail

     Upload a base64 thumbnail for a map.

    Accepts a data:image/ URI, decodes the base64 payload, writes the image
    bytes to the configured storage provider, and stores the storage key.

    Args:
        map_id (UUID):
        body (ThumbnailUploadRequest): JSON body for PUT /maps/{map_id}/thumbnail/.

            Replaces a previous text/plain body shape that openapi-python-client
            could not parse (would silently skip endpoint). See Phase 254 / SDK-01.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        map_id=map_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    map_id: UUID,
    *,
    client: AuthenticatedClient,
    body: ThumbnailUploadRequest,
) -> Any | ProblemDetail | None:
    """Upload Thumbnail

     Upload a base64 thumbnail for a map.

    Accepts a data:image/ URI, decodes the base64 payload, writes the image
    bytes to the configured storage provider, and stores the storage key.

    Args:
        map_id (UUID):
        body (ThumbnailUploadRequest): JSON body for PUT /maps/{map_id}/thumbnail/.

            Replaces a previous text/plain body shape that openapi-python-client
            could not parse (would silently skip endpoint). See Phase 254 / SDK-01.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return (
        await asyncio_detailed(
            map_id=map_id,
            client=client,
            body=body,
        )
    ).parsed
