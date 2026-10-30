from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.get_story_asset_endpoint_stories_story_id_assets_asset_id_get_variant_type_0 import (
    GetStoryAssetEndpointStoriesStoryIdAssetsAssetIdGetVariantType0,
)
from ...models.problem_detail import ProblemDetail
from ...types import File
from ...types import Unset
from io import BytesIO
from uuid import UUID


def _get_kwargs(
    story_id: UUID,
    asset_id: UUID,
    *,
    variant: GetStoryAssetEndpointStoriesStoryIdAssetsAssetIdGetVariantType0
    | None
    | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_variant: None | str | Unset
    if isinstance(variant, Unset):
        json_variant = UNSET
    elif isinstance(variant, str):
        json_variant = variant
    else:
        json_variant = variant
    params["variant"] = json_variant

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/stories/{story_id}/assets/{asset_id}".format(
            story_id=quote(str(story_id), safe=""),
            asset_id=quote(str(asset_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | File | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = File(payload=BytesIO(response.content))

        return response_200

    if response.status_code == 304:
        response_304 = cast(Any, None)
        return response_304

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
) -> Response[Any | File | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    story_id: UUID,
    asset_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    variant: GetStoryAssetEndpointStoriesStoryIdAssetsAssetIdGetVariantType0
    | None
    | Unset = UNSET,
) -> Response[Any | File | ProblemDetail]:
    """Get Story Asset Endpoint

     Serve one of the story's images, as WebP unless `variant` says otherwise.

    Its owner and admins get any of them. Anyone else who can read the story
    gets the cover and the images its published document uses. 404 otherwise.

    Args:
        story_id (UUID):
        asset_id (UUID):
        variant (GetStoryAssetEndpointStoriesStoryIdAssetsAssetIdGetVariantType0 | None | Unset):
            `card`: at most 640 pixels wide, as WebP. `social`: 1200 by 630, cropped to fill, as JPEG.
            An image uploaded before these sizes existed answers with the original.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | File | ProblemDetail]
    """

    kwargs = _get_kwargs(
        story_id=story_id,
        asset_id=asset_id,
        variant=variant,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    story_id: UUID,
    asset_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    variant: GetStoryAssetEndpointStoriesStoryIdAssetsAssetIdGetVariantType0
    | None
    | Unset = UNSET,
) -> Any | File | ProblemDetail | None:
    """Get Story Asset Endpoint

     Serve one of the story's images, as WebP unless `variant` says otherwise.

    Its owner and admins get any of them. Anyone else who can read the story
    gets the cover and the images its published document uses. 404 otherwise.

    Args:
        story_id (UUID):
        asset_id (UUID):
        variant (GetStoryAssetEndpointStoriesStoryIdAssetsAssetIdGetVariantType0 | None | Unset):
            `card`: at most 640 pixels wide, as WebP. `social`: 1200 by 630, cropped to fill, as JPEG.
            An image uploaded before these sizes existed answers with the original.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | File | ProblemDetail
    """

    return sync_detailed(
        story_id=story_id,
        asset_id=asset_id,
        client=client,
        variant=variant,
    ).parsed


async def asyncio_detailed(
    story_id: UUID,
    asset_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    variant: GetStoryAssetEndpointStoriesStoryIdAssetsAssetIdGetVariantType0
    | None
    | Unset = UNSET,
) -> Response[Any | File | ProblemDetail]:
    """Get Story Asset Endpoint

     Serve one of the story's images, as WebP unless `variant` says otherwise.

    Its owner and admins get any of them. Anyone else who can read the story
    gets the cover and the images its published document uses. 404 otherwise.

    Args:
        story_id (UUID):
        asset_id (UUID):
        variant (GetStoryAssetEndpointStoriesStoryIdAssetsAssetIdGetVariantType0 | None | Unset):
            `card`: at most 640 pixels wide, as WebP. `social`: 1200 by 630, cropped to fill, as JPEG.
            An image uploaded before these sizes existed answers with the original.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | File | ProblemDetail]
    """

    kwargs = _get_kwargs(
        story_id=story_id,
        asset_id=asset_id,
        variant=variant,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    story_id: UUID,
    asset_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    variant: GetStoryAssetEndpointStoriesStoryIdAssetsAssetIdGetVariantType0
    | None
    | Unset = UNSET,
) -> Any | File | ProblemDetail | None:
    """Get Story Asset Endpoint

     Serve one of the story's images, as WebP unless `variant` says otherwise.

    Its owner and admins get any of them. Anyone else who can read the story
    gets the cover and the images its published document uses. 404 otherwise.

    Args:
        story_id (UUID):
        asset_id (UUID):
        variant (GetStoryAssetEndpointStoriesStoryIdAssetsAssetIdGetVariantType0 | None | Unset):
            `card`: at most 640 pixels wide, as WebP. `social`: 1200 by 630, cropped to fill, as JPEG.
            An image uploaded before these sizes existed answers with the original.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | File | ProblemDetail
    """

    return (
        await asyncio_detailed(
            story_id=story_id,
            asset_id=asset_id,
            client=client,
            variant=variant,
        )
    ).parsed
