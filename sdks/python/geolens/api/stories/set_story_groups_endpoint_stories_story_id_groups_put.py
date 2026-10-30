from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...models.story_groups_response import StoryGroupsResponse
from ...models.story_groups_update import StoryGroupsUpdate
from uuid import UUID


def _get_kwargs(
    story_id: UUID,
    *,
    body: StoryGroupsUpdate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/stories/{story_id}/groups/".format(
            story_id=quote(str(story_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ProblemDetail | StoryGroupsResponse | None:
    if response.status_code == 200:
        response_200 = StoryGroupsResponse.from_dict(response.json())

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
) -> Response[ProblemDetail | StoryGroupsResponse]:
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
    body: StoryGroupsUpdate,
) -> Response[ProblemDetail | StoryGroupsResponse]:
    """Set Story Groups Endpoint

     Share a story with exactly these sharing groups (owner or admin).

    An owner may add only groups they belong to (403); an admin may add any.
    A private story shared with a group becomes restricted, and once
    published its members can read it; a restricted one left with no group
    becomes private. Internal and public stories keep their audience. 404 for
    an unknown group.

    409 `maps_narrower_than_story` when the published story uses maps some
    member of a new group can't read: `detail.maps` names the ones you can
    read, each with `can_share`, and `detail.unreadable_maps` counts the
    rest; see `confirm`.

    Args:
        story_id (UUID):
        body (StoryGroupsUpdate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | StoryGroupsResponse]
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
    body: StoryGroupsUpdate,
) -> ProblemDetail | StoryGroupsResponse | None:
    """Set Story Groups Endpoint

     Share a story with exactly these sharing groups (owner or admin).

    An owner may add only groups they belong to (403); an admin may add any.
    A private story shared with a group becomes restricted, and once
    published its members can read it; a restricted one left with no group
    becomes private. Internal and public stories keep their audience. 404 for
    an unknown group.

    409 `maps_narrower_than_story` when the published story uses maps some
    member of a new group can't read: `detail.maps` names the ones you can
    read, each with `can_share`, and `detail.unreadable_maps` counts the
    rest; see `confirm`.

    Args:
        story_id (UUID):
        body (StoryGroupsUpdate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | StoryGroupsResponse
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
    body: StoryGroupsUpdate,
) -> Response[ProblemDetail | StoryGroupsResponse]:
    """Set Story Groups Endpoint

     Share a story with exactly these sharing groups (owner or admin).

    An owner may add only groups they belong to (403); an admin may add any.
    A private story shared with a group becomes restricted, and once
    published its members can read it; a restricted one left with no group
    becomes private. Internal and public stories keep their audience. 404 for
    an unknown group.

    409 `maps_narrower_than_story` when the published story uses maps some
    member of a new group can't read: `detail.maps` names the ones you can
    read, each with `can_share`, and `detail.unreadable_maps` counts the
    rest; see `confirm`.

    Args:
        story_id (UUID):
        body (StoryGroupsUpdate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | StoryGroupsResponse]
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
    body: StoryGroupsUpdate,
) -> ProblemDetail | StoryGroupsResponse | None:
    """Set Story Groups Endpoint

     Share a story with exactly these sharing groups (owner or admin).

    An owner may add only groups they belong to (403); an admin may add any.
    A private story shared with a group becomes restricted, and once
    published its members can read it; a restricted one left with no group
    becomes private. Internal and public stories keep their audience. 404 for
    an unknown group.

    409 `maps_narrower_than_story` when the published story uses maps some
    member of a new group can't read: `detail.maps` names the ones you can
    read, each with `can_share`, and `detail.unreadable_maps` counts the
    rest; see `confirm`.

    Args:
        story_id (UUID):
        body (StoryGroupsUpdate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | StoryGroupsResponse
    """

    return (
        await asyncio_detailed(
            story_id=story_id,
            client=client,
            body=body,
        )
    ).parsed
