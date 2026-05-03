from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.get_collection_items_collections_dataset_id_items_get_ogc_feature_items_response import (
    GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponse,
)
from ...models.problem_detail import ProblemDetail
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    *,
    limit: int | Unset = 10,
    offset: int | Unset = 0,
    bbox: None | str | Unset = UNSET,
    datetime_: None | str | Unset = UNSET,
    f: None | str | Unset = UNSET,
    include_geometry: bool | Unset = True,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["limit"] = limit

    params["offset"] = offset

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

    json_f: None | str | Unset
    if isinstance(f, Unset):
        json_f = UNSET
    else:
        json_f = f
    params["f"] = json_f

    params["include_geometry"] = include_geometry

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/collections/{dataset_id}/items".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponse
    | ProblemDetail
    | None
):
    if response.status_code == 200:
        response_200 = GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponse.from_dict(
            response.json()
        )

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
) -> Response[
    GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponse
    | ProblemDetail
]:
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
    limit: int | Unset = 10,
    offset: int | Unset = 0,
    bbox: None | str | Unset = UNSET,
    datetime_: None | str | Unset = UNSET,
    f: None | str | Unset = UNSET,
    include_geometry: bool | Unset = True,
) -> Response[
    GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponse
    | ProblemDetail
]:
    r"""Get Collection Items

     OGC API Features items endpoint -- returns GeoJSON FeatureCollection for a dataset.

    Note: ``datetime`` is accepted per OGC API Features Core but acts as a
    no-op for per-dataset feature queries.  Per-dataset feature tables contain
    user-uploaded data with no standard temporal column, so the spec provision
    \"if the collection does not include temporal information, the datetime
    parameter SHALL be ignored\" applies (OGC 17-069r4 §7.15.5).

    Args:
        dataset_id (UUID):
        limit (int | Unset):  Default: 10.
        offset (int | Unset):  Default: 0.
        bbox (None | str | Unset): Bounding box: minx,miny,maxx,maxy
        datetime_ (None | str | Unset): OGC datetime interval: instant, start/end, ../end,
            start/..
        f (None | str | Unset):
        include_geometry (bool | Unset): Include geometry in response. Set to false for attribute-
            only queries. Default: True.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        limit=limit,
        offset=offset,
        bbox=bbox,
        datetime_=datetime_,
        f=f,
        include_geometry=include_geometry,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 10,
    offset: int | Unset = 0,
    bbox: None | str | Unset = UNSET,
    datetime_: None | str | Unset = UNSET,
    f: None | str | Unset = UNSET,
    include_geometry: bool | Unset = True,
) -> (
    GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponse
    | ProblemDetail
    | None
):
    r"""Get Collection Items

     OGC API Features items endpoint -- returns GeoJSON FeatureCollection for a dataset.

    Note: ``datetime`` is accepted per OGC API Features Core but acts as a
    no-op for per-dataset feature queries.  Per-dataset feature tables contain
    user-uploaded data with no standard temporal column, so the spec provision
    \"if the collection does not include temporal information, the datetime
    parameter SHALL be ignored\" applies (OGC 17-069r4 §7.15.5).

    Args:
        dataset_id (UUID):
        limit (int | Unset):  Default: 10.
        offset (int | Unset):  Default: 0.
        bbox (None | str | Unset): Bounding box: minx,miny,maxx,maxy
        datetime_ (None | str | Unset): OGC datetime interval: instant, start/end, ../end,
            start/..
        f (None | str | Unset):
        include_geometry (bool | Unset): Include geometry in response. Set to false for attribute-
            only queries. Default: True.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponse | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        client=client,
        limit=limit,
        offset=offset,
        bbox=bbox,
        datetime_=datetime_,
        f=f,
        include_geometry=include_geometry,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 10,
    offset: int | Unset = 0,
    bbox: None | str | Unset = UNSET,
    datetime_: None | str | Unset = UNSET,
    f: None | str | Unset = UNSET,
    include_geometry: bool | Unset = True,
) -> Response[
    GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponse
    | ProblemDetail
]:
    r"""Get Collection Items

     OGC API Features items endpoint -- returns GeoJSON FeatureCollection for a dataset.

    Note: ``datetime`` is accepted per OGC API Features Core but acts as a
    no-op for per-dataset feature queries.  Per-dataset feature tables contain
    user-uploaded data with no standard temporal column, so the spec provision
    \"if the collection does not include temporal information, the datetime
    parameter SHALL be ignored\" applies (OGC 17-069r4 §7.15.5).

    Args:
        dataset_id (UUID):
        limit (int | Unset):  Default: 10.
        offset (int | Unset):  Default: 0.
        bbox (None | str | Unset): Bounding box: minx,miny,maxx,maxy
        datetime_ (None | str | Unset): OGC datetime interval: instant, start/end, ../end,
            start/..
        f (None | str | Unset):
        include_geometry (bool | Unset): Include geometry in response. Set to false for attribute-
            only queries. Default: True.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        limit=limit,
        offset=offset,
        bbox=bbox,
        datetime_=datetime_,
        f=f,
        include_geometry=include_geometry,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 10,
    offset: int | Unset = 0,
    bbox: None | str | Unset = UNSET,
    datetime_: None | str | Unset = UNSET,
    f: None | str | Unset = UNSET,
    include_geometry: bool | Unset = True,
) -> (
    GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponse
    | ProblemDetail
    | None
):
    r"""Get Collection Items

     OGC API Features items endpoint -- returns GeoJSON FeatureCollection for a dataset.

    Note: ``datetime`` is accepted per OGC API Features Core but acts as a
    no-op for per-dataset feature queries.  Per-dataset feature tables contain
    user-uploaded data with no standard temporal column, so the spec provision
    \"if the collection does not include temporal information, the datetime
    parameter SHALL be ignored\" applies (OGC 17-069r4 §7.15.5).

    Args:
        dataset_id (UUID):
        limit (int | Unset):  Default: 10.
        offset (int | Unset):  Default: 0.
        bbox (None | str | Unset): Bounding box: minx,miny,maxx,maxy
        datetime_ (None | str | Unset): OGC datetime interval: instant, start/end, ../end,
            start/..
        f (None | str | Unset):
        include_geometry (bool | Unset): Include geometry in response. Set to false for attribute-
            only queries. Default: True.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
            limit=limit,
            offset=offset,
            bbox=bbox,
            datetime_=datetime_,
            f=f,
            include_geometry=include_geometry,
        )
    ).parsed
