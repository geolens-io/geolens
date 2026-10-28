from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...models.story_draft_response import StoryDraftResponse
from ...models.story_draft_update import StoryDraftUpdate
from uuid import UUID


def _get_kwargs(
    story_id: UUID,
    *,
    body: StoryDraftUpdate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/stories/{story_id}/draft".format(
            story_id=quote(str(story_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ProblemDetail | StoryDraftResponse | None:
    if response.status_code == 200:
        response_200 = StoryDraftResponse.from_dict(response.json())

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
) -> Response[ProblemDetail | StoryDraftResponse]:
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
    body: StoryDraftUpdate,
) -> Response[ProblemDetail | StoryDraftResponse]:
    """Save Story Draft Endpoint

     Replace the whole draft (owner or admin). Readers keep the published
    document until Publish.

    `revision` must match the stored draft's, or 409 `stale_revision`. 422
    for an unknown or invalid block, or for a scene on a map you can't read
    (`detail.code` `story_maps_not_found`). Blocks you can't see and scenes
    sent back with `scene_hidden` are kept as stored.

    Args:
        story_id (UUID):
        body (StoryDraftUpdate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | StoryDraftResponse]
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
    body: StoryDraftUpdate,
) -> ProblemDetail | StoryDraftResponse | None:
    """Save Story Draft Endpoint

     Replace the whole draft (owner or admin). Readers keep the published
    document until Publish.

    `revision` must match the stored draft's, or 409 `stale_revision`. 422
    for an unknown or invalid block, or for a scene on a map you can't read
    (`detail.code` `story_maps_not_found`). Blocks you can't see and scenes
    sent back with `scene_hidden` are kept as stored.

    Args:
        story_id (UUID):
        body (StoryDraftUpdate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | StoryDraftResponse
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
    body: StoryDraftUpdate,
) -> Response[ProblemDetail | StoryDraftResponse]:
    """Save Story Draft Endpoint

     Replace the whole draft (owner or admin). Readers keep the published
    document until Publish.

    `revision` must match the stored draft's, or 409 `stale_revision`. 422
    for an unknown or invalid block, or for a scene on a map you can't read
    (`detail.code` `story_maps_not_found`). Blocks you can't see and scenes
    sent back with `scene_hidden` are kept as stored.

    Args:
        story_id (UUID):
        body (StoryDraftUpdate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | StoryDraftResponse]
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
    body: StoryDraftUpdate,
) -> ProblemDetail | StoryDraftResponse | None:
    """Save Story Draft Endpoint

     Replace the whole draft (owner or admin). Readers keep the published
    document until Publish.

    `revision` must match the stored draft's, or 409 `stale_revision`. 422
    for an unknown or invalid block, or for a scene on a map you can't read
    (`detail.code` `story_maps_not_found`). Blocks you can't see and scenes
    sent back with `scene_hidden` are kept as stored.

    Args:
        story_id (UUID):
        body (StoryDraftUpdate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | StoryDraftResponse
    """

    return (
        await asyncio_detailed(
            story_id=story_id,
            client=client,
            body=body,
        )
    ).parsed
