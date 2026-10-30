from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...models.story_asset_response import StoryAssetResponse
from ...models.upload_story_asset_endpoint_stories_story_id_assets_post_body import (
    UploadStoryAssetEndpointStoriesStoryIdAssetsPostBody,
)
from uuid import UUID


def _get_kwargs(
    story_id: UUID,
    *,
    body: UploadStoryAssetEndpointStoriesStoryIdAssetsPostBody,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/stories/{story_id}/assets".format(
            story_id=quote(str(story_id), safe=""),
        ),
    }

    _kwargs["files"] = body.to_multipart()

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ProblemDetail | StoryAssetResponse | None:
    if response.status_code == 201:
        response_201 = StoryAssetResponse.from_dict(response.json())

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

    if response.status_code == 413:
        response_413 = ProblemDetail.from_dict(response.json())

        return response_413

    if response.status_code == 415:
        response_415 = ProblemDetail.from_dict(response.json())

        return response_415

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
) -> Response[ProblemDetail | StoryAssetResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    story_id: UUID,
    *,
    client: AuthenticatedClient,
    body: UploadStoryAssetEndpointStoriesStoryIdAssetsPostBody,
) -> Response[ProblemDetail | StoryAssetResponse]:
    """Upload Story Asset Endpoint

     Upload an image, the multipart part `file`, for the story's blocks or
    cover (owner or admin).

    PNG, JPEG and WebP, told apart by their bytes. It's stored as sRGB WebP
    without its metadata. 400 `story_image_unreadable`, 413
    `story_image_too_large`, 415 `story_image_unsupported`, 409
    `story_asset_limit` or `story_asset_owner_limit`, 503 `story_image_busy`.
    Readers get it once a published block or the cover uses it.

    Args:
        story_id (UUID):
        body (UploadStoryAssetEndpointStoriesStoryIdAssetsPostBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | StoryAssetResponse]
    """

    kwargs = _get_kwargs(
        story_id=story_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    story_id: UUID,
    *,
    client: AuthenticatedClient,
    body: UploadStoryAssetEndpointStoriesStoryIdAssetsPostBody,
) -> ProblemDetail | StoryAssetResponse | None:
    """Upload Story Asset Endpoint

     Upload an image, the multipart part `file`, for the story's blocks or
    cover (owner or admin).

    PNG, JPEG and WebP, told apart by their bytes. It's stored as sRGB WebP
    without its metadata. 400 `story_image_unreadable`, 413
    `story_image_too_large`, 415 `story_image_unsupported`, 409
    `story_asset_limit` or `story_asset_owner_limit`, 503 `story_image_busy`.
    Readers get it once a published block or the cover uses it.

    Args:
        story_id (UUID):
        body (UploadStoryAssetEndpointStoriesStoryIdAssetsPostBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | StoryAssetResponse
    """

    return sync_detailed(
        story_id=story_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    story_id: UUID,
    *,
    client: AuthenticatedClient,
    body: UploadStoryAssetEndpointStoriesStoryIdAssetsPostBody,
) -> Response[ProblemDetail | StoryAssetResponse]:
    """Upload Story Asset Endpoint

     Upload an image, the multipart part `file`, for the story's blocks or
    cover (owner or admin).

    PNG, JPEG and WebP, told apart by their bytes. It's stored as sRGB WebP
    without its metadata. 400 `story_image_unreadable`, 413
    `story_image_too_large`, 415 `story_image_unsupported`, 409
    `story_asset_limit` or `story_asset_owner_limit`, 503 `story_image_busy`.
    Readers get it once a published block or the cover uses it.

    Args:
        story_id (UUID):
        body (UploadStoryAssetEndpointStoriesStoryIdAssetsPostBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | StoryAssetResponse]
    """

    kwargs = _get_kwargs(
        story_id=story_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    story_id: UUID,
    *,
    client: AuthenticatedClient,
    body: UploadStoryAssetEndpointStoriesStoryIdAssetsPostBody,
) -> ProblemDetail | StoryAssetResponse | None:
    """Upload Story Asset Endpoint

     Upload an image, the multipart part `file`, for the story's blocks or
    cover (owner or admin).

    PNG, JPEG and WebP, told apart by their bytes. It's stored as sRGB WebP
    without its metadata. 400 `story_image_unreadable`, 413
    `story_image_too_large`, 415 `story_image_unsupported`, 409
    `story_asset_limit` or `story_asset_owner_limit`, 503 `story_image_busy`.
    Readers get it once a published block or the cover uses it.

    Args:
        story_id (UUID):
        body (UploadStoryAssetEndpointStoriesStoryIdAssetsPostBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | StoryAssetResponse
    """

    return (
        await asyncio_detailed(
            story_id=story_id,
            client=client,
            body=body,
        )
    ).parsed
