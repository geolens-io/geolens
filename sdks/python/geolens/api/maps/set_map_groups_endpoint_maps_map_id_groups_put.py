from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.map_groups_response import MapGroupsResponse
from ...models.map_groups_update import MapGroupsUpdate
from ...models.problem_detail import ProblemDetail
from uuid import UUID


def _get_kwargs(
    map_id: UUID,
    *,
    body: MapGroupsUpdate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/maps/{map_id}/groups/".format(
            map_id=quote(str(map_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> MapGroupsResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = MapGroupsResponse.from_dict(response.json())

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
) -> Response[MapGroupsResponse | ProblemDetail]:
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
    body: MapGroupsUpdate,
) -> Response[MapGroupsResponse | ProblemDetail]:
    """Set Map Groups Endpoint

     Share a map with exactly these sharing groups (owner or admin).

    An owner may add only groups they belong to (403); an admin may add any.
    A private map shared with a group becomes restricted and its members can
    read it; a restricted one left with no group becomes private. Internal
    and public maps keep their audience. Becoming restricted revokes the
    map's share link and embed tokens. 404 for an unknown group.

    409 (`detail.code` `layers_hidden_from_groups`, the layers under
    `detail.layers`) when new groups can't read some layers; see `confirm`.
    A lock wait that times out also answers 409, without `detail.code`.

    Args:
        map_id (UUID):
        body (MapGroupsUpdate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[MapGroupsResponse | ProblemDetail]
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
    body: MapGroupsUpdate,
) -> MapGroupsResponse | ProblemDetail | None:
    """Set Map Groups Endpoint

     Share a map with exactly these sharing groups (owner or admin).

    An owner may add only groups they belong to (403); an admin may add any.
    A private map shared with a group becomes restricted and its members can
    read it; a restricted one left with no group becomes private. Internal
    and public maps keep their audience. Becoming restricted revokes the
    map's share link and embed tokens. 404 for an unknown group.

    409 (`detail.code` `layers_hidden_from_groups`, the layers under
    `detail.layers`) when new groups can't read some layers; see `confirm`.
    A lock wait that times out also answers 409, without `detail.code`.

    Args:
        map_id (UUID):
        body (MapGroupsUpdate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        MapGroupsResponse | ProblemDetail
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
    body: MapGroupsUpdate,
) -> Response[MapGroupsResponse | ProblemDetail]:
    """Set Map Groups Endpoint

     Share a map with exactly these sharing groups (owner or admin).

    An owner may add only groups they belong to (403); an admin may add any.
    A private map shared with a group becomes restricted and its members can
    read it; a restricted one left with no group becomes private. Internal
    and public maps keep their audience. Becoming restricted revokes the
    map's share link and embed tokens. 404 for an unknown group.

    409 (`detail.code` `layers_hidden_from_groups`, the layers under
    `detail.layers`) when new groups can't read some layers; see `confirm`.
    A lock wait that times out also answers 409, without `detail.code`.

    Args:
        map_id (UUID):
        body (MapGroupsUpdate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[MapGroupsResponse | ProblemDetail]
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
    body: MapGroupsUpdate,
) -> MapGroupsResponse | ProblemDetail | None:
    """Set Map Groups Endpoint

     Share a map with exactly these sharing groups (owner or admin).

    An owner may add only groups they belong to (403); an admin may add any.
    A private map shared with a group becomes restricted and its members can
    read it; a restricted one left with no group becomes private. Internal
    and public maps keep their audience. Becoming restricted revokes the
    map's share link and embed tokens. 404 for an unknown group.

    409 (`detail.code` `layers_hidden_from_groups`, the layers under
    `detail.layers`) when new groups can't read some layers; see `confirm`.
    A lock wait that times out also answers 409, without `detail.code`.

    Args:
        map_id (UUID):
        body (MapGroupsUpdate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        MapGroupsResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            map_id=map_id,
            client=client,
            body=body,
        )
    ).parsed
