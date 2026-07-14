from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...models.stac_item_collection_response import StacItemCollectionResponse
from ...types import Unset


def _get_kwargs(
    collection_id: str,
    *,
    bbox: None | str | Unset = UNSET,
    datetime_: None | str | Unset = UNSET,
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

    params["limit"] = limit

    params["offset"] = offset

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/stac/collections/{collection_id}/items".format(
            collection_id=quote(str(collection_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ProblemDetail | StacItemCollectionResponse | None:
    if response.status_code == 200:
        response_200 = StacItemCollectionResponse.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = ProblemDetail.from_dict(response.json())

        return response_400

    if response.status_code == 404:
        response_404 = ProblemDetail.from_dict(response.json())

        return response_404

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
) -> Response[ProblemDetail | StacItemCollectionResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    collection_id: str,
    *,
    client: AuthenticatedClient,
    bbox: None | str | Unset = UNSET,
    datetime_: None | str | Unset = UNSET,
    limit: int | Unset = 10,
    offset: int | Unset = 0,
) -> Response[ProblemDetail | StacItemCollectionResponse]:
    """Get Collection Items

     List STAC Items within a collection.

    Args:
        collection_id (str):
        bbox (None | str | Unset): Bounding box: west,south,east,north
        datetime_ (None | str | Unset): OGC datetime interval
        limit (int | Unset):  Default: 10.
        offset (int | Unset): Legacy offset-based pagination. Phase 269 H-24 lowered the max limit
            to 200 and recommends keyset cursors via the rel=next link for deep paging. Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | StacItemCollectionResponse]
    """

    kwargs = _get_kwargs(
        collection_id=collection_id,
        bbox=bbox,
        datetime_=datetime_,
        limit=limit,
        offset=offset,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    collection_id: str,
    *,
    client: AuthenticatedClient,
    bbox: None | str | Unset = UNSET,
    datetime_: None | str | Unset = UNSET,
    limit: int | Unset = 10,
    offset: int | Unset = 0,
) -> ProblemDetail | StacItemCollectionResponse | None:
    """Get Collection Items

     List STAC Items within a collection.

    Args:
        collection_id (str):
        bbox (None | str | Unset): Bounding box: west,south,east,north
        datetime_ (None | str | Unset): OGC datetime interval
        limit (int | Unset):  Default: 10.
        offset (int | Unset): Legacy offset-based pagination. Phase 269 H-24 lowered the max limit
            to 200 and recommends keyset cursors via the rel=next link for deep paging. Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | StacItemCollectionResponse
    """

    return sync_detailed(
        collection_id=collection_id,
        client=client,
        bbox=bbox,
        datetime_=datetime_,
        limit=limit,
        offset=offset,
    ).parsed


async def asyncio_detailed(
    collection_id: str,
    *,
    client: AuthenticatedClient,
    bbox: None | str | Unset = UNSET,
    datetime_: None | str | Unset = UNSET,
    limit: int | Unset = 10,
    offset: int | Unset = 0,
) -> Response[ProblemDetail | StacItemCollectionResponse]:
    """Get Collection Items

     List STAC Items within a collection.

    Args:
        collection_id (str):
        bbox (None | str | Unset): Bounding box: west,south,east,north
        datetime_ (None | str | Unset): OGC datetime interval
        limit (int | Unset):  Default: 10.
        offset (int | Unset): Legacy offset-based pagination. Phase 269 H-24 lowered the max limit
            to 200 and recommends keyset cursors via the rel=next link for deep paging. Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | StacItemCollectionResponse]
    """

    kwargs = _get_kwargs(
        collection_id=collection_id,
        bbox=bbox,
        datetime_=datetime_,
        limit=limit,
        offset=offset,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    collection_id: str,
    *,
    client: AuthenticatedClient,
    bbox: None | str | Unset = UNSET,
    datetime_: None | str | Unset = UNSET,
    limit: int | Unset = 10,
    offset: int | Unset = 0,
) -> ProblemDetail | StacItemCollectionResponse | None:
    """Get Collection Items

     List STAC Items within a collection.

    Args:
        collection_id (str):
        bbox (None | str | Unset): Bounding box: west,south,east,north
        datetime_ (None | str | Unset): OGC datetime interval
        limit (int | Unset):  Default: 10.
        offset (int | Unset): Legacy offset-based pagination. Phase 269 H-24 lowered the max limit
            to 200 and recommends keyset cursors via the rel=next link for deep paging. Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | StacItemCollectionResponse
    """

    return (
        await asyncio_detailed(
            collection_id=collection_id,
            client=client,
            bbox=bbox,
            datetime_=datetime_,
            limit=limit,
            offset=offset,
        )
    ).parsed
