from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.og_image_upload_request import OgImageUploadRequest
from ...models.problem_detail import ProblemDetail
from uuid import UUID


def _get_kwargs(
    map_id: UUID,
    *,
    body: OgImageUploadRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/maps/{map_id}/og-image/".format(
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

    if response.status_code == 429:
        response_429 = ProblemDetail.from_dict(response.json())

        return response_429

    if response.status_code == 500:
        response_500 = ProblemDetail.from_dict(response.json())

        return response_500

    if response.status_code == 502:
        response_502 = ProblemDetail.from_dict(response.json())

        return response_502

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
    map_id: UUID,
    *,
    client: AuthenticatedClient,
    body: OgImageUploadRequest,
) -> Response[Any | ProblemDetail]:
    """Upload Og Image

     Upload a base64 OG social-card image (up to 750KB) for a map.

    Accepts a data:image/ URI, decodes the base64 payload, validates the
    bytes are a real image (PIL verify), writes to storage under
    ``maps/og-images/{map_id}.{ext}``, and persists the storage key to
    ``catalog.maps.og_image_uri``.

    Intended for 1200x630 JPEG captures (SHARE-08). The payload cap
    (750KB) is larger than the thumbnail cap (100KB) to accommodate the
    larger canvas export — they are separate schemas (OgImageUploadRequest
    vs ThumbnailUploadRequest) to avoid relaxing the locked thumbnail
    contract. Auth and PIL-verify rules are identical to upload_thumbnail.

    Args:
        map_id (UUID):
        body (OgImageUploadRequest): JSON body for PUT /maps/{map_id}/og-image/ (SHARE-08 Path A).

            Accepts a base64 data URI up to 750 KB (as a string). This generous
            ceiling accommodates a 1200x630 JPEG at quality 0.85, which encodes
            to roughly 150-400 KB raw and ~200-540 KB as a base64 string.

            - ``min_length=22``: same floor as ThumbnailUploadRequest — rejects
              empty/clearly-malformed URIs without false-positives.
            - ``max_length=750_000``: ~562 KB decoded — generous for 1200x630 JPEG.
              DO NOT raise ThumbnailUploadRequest.max_length to match this value;
              the 100KB thumbnail cap is a locked contract (Phase 254 / D-03).

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
    body: OgImageUploadRequest,
) -> Any | ProblemDetail | None:
    """Upload Og Image

     Upload a base64 OG social-card image (up to 750KB) for a map.

    Accepts a data:image/ URI, decodes the base64 payload, validates the
    bytes are a real image (PIL verify), writes to storage under
    ``maps/og-images/{map_id}.{ext}``, and persists the storage key to
    ``catalog.maps.og_image_uri``.

    Intended for 1200x630 JPEG captures (SHARE-08). The payload cap
    (750KB) is larger than the thumbnail cap (100KB) to accommodate the
    larger canvas export — they are separate schemas (OgImageUploadRequest
    vs ThumbnailUploadRequest) to avoid relaxing the locked thumbnail
    contract. Auth and PIL-verify rules are identical to upload_thumbnail.

    Args:
        map_id (UUID):
        body (OgImageUploadRequest): JSON body for PUT /maps/{map_id}/og-image/ (SHARE-08 Path A).

            Accepts a base64 data URI up to 750 KB (as a string). This generous
            ceiling accommodates a 1200x630 JPEG at quality 0.85, which encodes
            to roughly 150-400 KB raw and ~200-540 KB as a base64 string.

            - ``min_length=22``: same floor as ThumbnailUploadRequest — rejects
              empty/clearly-malformed URIs without false-positives.
            - ``max_length=750_000``: ~562 KB decoded — generous for 1200x630 JPEG.
              DO NOT raise ThumbnailUploadRequest.max_length to match this value;
              the 100KB thumbnail cap is a locked contract (Phase 254 / D-03).

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
    body: OgImageUploadRequest,
) -> Response[Any | ProblemDetail]:
    """Upload Og Image

     Upload a base64 OG social-card image (up to 750KB) for a map.

    Accepts a data:image/ URI, decodes the base64 payload, validates the
    bytes are a real image (PIL verify), writes to storage under
    ``maps/og-images/{map_id}.{ext}``, and persists the storage key to
    ``catalog.maps.og_image_uri``.

    Intended for 1200x630 JPEG captures (SHARE-08). The payload cap
    (750KB) is larger than the thumbnail cap (100KB) to accommodate the
    larger canvas export — they are separate schemas (OgImageUploadRequest
    vs ThumbnailUploadRequest) to avoid relaxing the locked thumbnail
    contract. Auth and PIL-verify rules are identical to upload_thumbnail.

    Args:
        map_id (UUID):
        body (OgImageUploadRequest): JSON body for PUT /maps/{map_id}/og-image/ (SHARE-08 Path A).

            Accepts a base64 data URI up to 750 KB (as a string). This generous
            ceiling accommodates a 1200x630 JPEG at quality 0.85, which encodes
            to roughly 150-400 KB raw and ~200-540 KB as a base64 string.

            - ``min_length=22``: same floor as ThumbnailUploadRequest — rejects
              empty/clearly-malformed URIs without false-positives.
            - ``max_length=750_000``: ~562 KB decoded — generous for 1200x630 JPEG.
              DO NOT raise ThumbnailUploadRequest.max_length to match this value;
              the 100KB thumbnail cap is a locked contract (Phase 254 / D-03).

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
    body: OgImageUploadRequest,
) -> Any | ProblemDetail | None:
    """Upload Og Image

     Upload a base64 OG social-card image (up to 750KB) for a map.

    Accepts a data:image/ URI, decodes the base64 payload, validates the
    bytes are a real image (PIL verify), writes to storage under
    ``maps/og-images/{map_id}.{ext}``, and persists the storage key to
    ``catalog.maps.og_image_uri``.

    Intended for 1200x630 JPEG captures (SHARE-08). The payload cap
    (750KB) is larger than the thumbnail cap (100KB) to accommodate the
    larger canvas export — they are separate schemas (OgImageUploadRequest
    vs ThumbnailUploadRequest) to avoid relaxing the locked thumbnail
    contract. Auth and PIL-verify rules are identical to upload_thumbnail.

    Args:
        map_id (UUID):
        body (OgImageUploadRequest): JSON body for PUT /maps/{map_id}/og-image/ (SHARE-08 Path A).

            Accepts a base64 data URI up to 750 KB (as a string). This generous
            ceiling accommodates a 1200x630 JPEG at quality 0.85, which encodes
            to roughly 150-400 KB raw and ~200-540 KB as a base64 string.

            - ``min_length=22``: same floor as ThumbnailUploadRequest — rejects
              empty/clearly-malformed URIs without false-positives.
            - ``max_length=750_000``: ~562 KB decoded — generous for 1200x630 JPEG.
              DO NOT raise ThumbnailUploadRequest.max_length to match this value;
              the 100KB thumbnail cap is a locked contract (Phase 254 / D-03).

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
