from http import HTTPStatus
from typing import Any, cast

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...types import Unset


def _get_kwargs(
    *,
    bbox: None | str | Unset = UNSET,
    datetime_: None | str | Unset = UNSET,
    collections: None | str | Unset = UNSET,
    ids: None | str | Unset = UNSET,
    intersects: None | str | Unset = UNSET,
    limit: int | Unset = 10,
    offset: int | Unset = 0,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_bbox: None | str | Unset
    if isinstance(bbox, Unset):
        json_bbox = UNSET
    else:
        json_bbox = bbox
    params["bbox"] = json_bbox

    json_datetime_: None | str | Unset
    if isinstance(datetime_, Unset):
        json_datetime_ = UNSET
    else:
        json_datetime_ = datetime_
    params["datetime"] = json_datetime_

    json_collections: None | str | Unset
    if isinstance(collections, Unset):
        json_collections = UNSET
    else:
        json_collections = collections
    params["collections"] = json_collections

    json_ids: None | str | Unset
    if isinstance(ids, Unset):
        json_ids = UNSET
    else:
        json_ids = ids
    params["ids"] = json_ids

    json_intersects: None | str | Unset
    if isinstance(intersects, Unset):
        json_intersects = UNSET
    else:
        json_intersects = intersects
    params["intersects"] = json_intersects

    params["limit"] = limit

    params["offset"] = offset

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/stac/search",
        "params": params,
    }

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
    *,
    client: AuthenticatedClient,
    bbox: None | str | Unset = UNSET,
    datetime_: None | str | Unset = UNSET,
    collections: None | str | Unset = UNSET,
    ids: None | str | Unset = UNSET,
    intersects: None | str | Unset = UNSET,
    limit: int | Unset = 10,
    offset: int | Unset = 0,
) -> Response[Any | ProblemDetail]:
    """Search Get

     STAC Item Search (GET).

    Args:
        bbox (None | str | Unset): Bounding box: west,south,east,north
        datetime_ (None | str | Unset): OGC datetime interval
        collections (None | str | Unset): Comma-separated collection IDs
        ids (None | str | Unset): Comma-separated item IDs
        intersects (None | str | Unset): GeoJSON geometry for spatial intersection. SEC-FU-05
            (sec-audit-20260519.md): max_length=10000 caps a multi-megabyte GeoJSON DoS-amplifier —
            fits ~150-vertex polygons at 2-decimal-place lat/lon coordinates.
        limit (int | Unset):  Default: 10.
        offset (int | Unset): Legacy offset-based pagination. Phase 269 H-24 lowered the max limit
            to 200 from 1000 to bound deep-paging cost. Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        bbox=bbox,
        datetime_=datetime_,
        collections=collections,
        ids=ids,
        intersects=intersects,
        limit=limit,
        offset=offset,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    bbox: None | str | Unset = UNSET,
    datetime_: None | str | Unset = UNSET,
    collections: None | str | Unset = UNSET,
    ids: None | str | Unset = UNSET,
    intersects: None | str | Unset = UNSET,
    limit: int | Unset = 10,
    offset: int | Unset = 0,
) -> Any | ProblemDetail | None:
    """Search Get

     STAC Item Search (GET).

    Args:
        bbox (None | str | Unset): Bounding box: west,south,east,north
        datetime_ (None | str | Unset): OGC datetime interval
        collections (None | str | Unset): Comma-separated collection IDs
        ids (None | str | Unset): Comma-separated item IDs
        intersects (None | str | Unset): GeoJSON geometry for spatial intersection. SEC-FU-05
            (sec-audit-20260519.md): max_length=10000 caps a multi-megabyte GeoJSON DoS-amplifier —
            fits ~150-vertex polygons at 2-decimal-place lat/lon coordinates.
        limit (int | Unset):  Default: 10.
        offset (int | Unset): Legacy offset-based pagination. Phase 269 H-24 lowered the max limit
            to 200 from 1000 to bound deep-paging cost. Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return sync_detailed(
        client=client,
        bbox=bbox,
        datetime_=datetime_,
        collections=collections,
        ids=ids,
        intersects=intersects,
        limit=limit,
        offset=offset,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    bbox: None | str | Unset = UNSET,
    datetime_: None | str | Unset = UNSET,
    collections: None | str | Unset = UNSET,
    ids: None | str | Unset = UNSET,
    intersects: None | str | Unset = UNSET,
    limit: int | Unset = 10,
    offset: int | Unset = 0,
) -> Response[Any | ProblemDetail]:
    """Search Get

     STAC Item Search (GET).

    Args:
        bbox (None | str | Unset): Bounding box: west,south,east,north
        datetime_ (None | str | Unset): OGC datetime interval
        collections (None | str | Unset): Comma-separated collection IDs
        ids (None | str | Unset): Comma-separated item IDs
        intersects (None | str | Unset): GeoJSON geometry for spatial intersection. SEC-FU-05
            (sec-audit-20260519.md): max_length=10000 caps a multi-megabyte GeoJSON DoS-amplifier —
            fits ~150-vertex polygons at 2-decimal-place lat/lon coordinates.
        limit (int | Unset):  Default: 10.
        offset (int | Unset): Legacy offset-based pagination. Phase 269 H-24 lowered the max limit
            to 200 from 1000 to bound deep-paging cost. Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        bbox=bbox,
        datetime_=datetime_,
        collections=collections,
        ids=ids,
        intersects=intersects,
        limit=limit,
        offset=offset,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    bbox: None | str | Unset = UNSET,
    datetime_: None | str | Unset = UNSET,
    collections: None | str | Unset = UNSET,
    ids: None | str | Unset = UNSET,
    intersects: None | str | Unset = UNSET,
    limit: int | Unset = 10,
    offset: int | Unset = 0,
) -> Any | ProblemDetail | None:
    """Search Get

     STAC Item Search (GET).

    Args:
        bbox (None | str | Unset): Bounding box: west,south,east,north
        datetime_ (None | str | Unset): OGC datetime interval
        collections (None | str | Unset): Comma-separated collection IDs
        ids (None | str | Unset): Comma-separated item IDs
        intersects (None | str | Unset): GeoJSON geometry for spatial intersection. SEC-FU-05
            (sec-audit-20260519.md): max_length=10000 caps a multi-megabyte GeoJSON DoS-amplifier —
            fits ~150-vertex polygons at 2-decimal-place lat/lon coordinates.
        limit (int | Unset):  Default: 10.
        offset (int | Unset): Legacy offset-based pagination. Phase 269 H-24 lowered the max limit
            to 200 from 1000 to bound deep-paging cost. Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
            bbox=bbox,
            datetime_=datetime_,
            collections=collections,
            ids=ids,
            intersects=intersects,
            limit=limit,
            offset=offset,
        )
    ).parsed
