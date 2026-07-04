from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    *,
    x_embed_token: None | str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(x_embed_token, Unset):
        headers["X-Embed-Token"] = x_embed_token

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/datasets/{dataset_id}/features.geojson".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
    }

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = cast(Any, None)
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
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    x_embed_token: None | str | Unset = UNSET,
) -> Response[Any | ProblemDetail]:
    """Get Features Geojson Z Endpoint

     Return up to 5,000 features as RFC 7946 GeoJSON with Z coordinates.

    fix(#394) codex P2: the viewer's bounded-GeoJSON path (small 3D layers,
    eligible cluster layers) already sends ``X-Embed-Token``, and the B-023
    shared-map union now exposes embed-scoped private layers to embeds — so
    this endpoint accepts the token as fallback authorization via the SAME
    ``validate_embed_token_access`` capability check as tile serving.

    fix(#390): the non-embed path uses ``check_dataset_access_or_anonymous``
    so public+published datasets serve to anonymous callers (matching vector
    tiles and the dataset-detail read path); private/restricted datasets still
    404 for anon and follow full RBAC for credentialed callers. This unblocks
    client clustering for anonymous public-map viewers.

    Args:
        dataset_id (UUID):
        x_embed_token (None | str | Unset): Optional embed token. Datasets in the token's scope
            are authorized even without user credentials (embed viewers).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        x_embed_token=x_embed_token,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    x_embed_token: None | str | Unset = UNSET,
) -> Any | ProblemDetail | None:
    """Get Features Geojson Z Endpoint

     Return up to 5,000 features as RFC 7946 GeoJSON with Z coordinates.

    fix(#394) codex P2: the viewer's bounded-GeoJSON path (small 3D layers,
    eligible cluster layers) already sends ``X-Embed-Token``, and the B-023
    shared-map union now exposes embed-scoped private layers to embeds — so
    this endpoint accepts the token as fallback authorization via the SAME
    ``validate_embed_token_access`` capability check as tile serving.

    fix(#390): the non-embed path uses ``check_dataset_access_or_anonymous``
    so public+published datasets serve to anonymous callers (matching vector
    tiles and the dataset-detail read path); private/restricted datasets still
    404 for anon and follow full RBAC for credentialed callers. This unblocks
    client clustering for anonymous public-map viewers.

    Args:
        dataset_id (UUID):
        x_embed_token (None | str | Unset): Optional embed token. Datasets in the token's scope
            are authorized even without user credentials (embed viewers).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        client=client,
        x_embed_token=x_embed_token,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    x_embed_token: None | str | Unset = UNSET,
) -> Response[Any | ProblemDetail]:
    """Get Features Geojson Z Endpoint

     Return up to 5,000 features as RFC 7946 GeoJSON with Z coordinates.

    fix(#394) codex P2: the viewer's bounded-GeoJSON path (small 3D layers,
    eligible cluster layers) already sends ``X-Embed-Token``, and the B-023
    shared-map union now exposes embed-scoped private layers to embeds — so
    this endpoint accepts the token as fallback authorization via the SAME
    ``validate_embed_token_access`` capability check as tile serving.

    fix(#390): the non-embed path uses ``check_dataset_access_or_anonymous``
    so public+published datasets serve to anonymous callers (matching vector
    tiles and the dataset-detail read path); private/restricted datasets still
    404 for anon and follow full RBAC for credentialed callers. This unblocks
    client clustering for anonymous public-map viewers.

    Args:
        dataset_id (UUID):
        x_embed_token (None | str | Unset): Optional embed token. Datasets in the token's scope
            are authorized even without user credentials (embed viewers).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        x_embed_token=x_embed_token,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    x_embed_token: None | str | Unset = UNSET,
) -> Any | ProblemDetail | None:
    """Get Features Geojson Z Endpoint

     Return up to 5,000 features as RFC 7946 GeoJSON with Z coordinates.

    fix(#394) codex P2: the viewer's bounded-GeoJSON path (small 3D layers,
    eligible cluster layers) already sends ``X-Embed-Token``, and the B-023
    shared-map union now exposes embed-scoped private layers to embeds — so
    this endpoint accepts the token as fallback authorization via the SAME
    ``validate_embed_token_access`` capability check as tile serving.

    fix(#390): the non-embed path uses ``check_dataset_access_or_anonymous``
    so public+published datasets serve to anonymous callers (matching vector
    tiles and the dataset-detail read path); private/restricted datasets still
    404 for anon and follow full RBAC for credentialed callers. This unblocks
    client clustering for anonymous public-map viewers.

    Args:
        dataset_id (UUID):
        x_embed_token (None | str | Unset): Optional embed token. Datasets in the token's scope
            are authorized even without user credentials (embed viewers).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
            x_embed_token=x_embed_token,
        )
    ).parsed
