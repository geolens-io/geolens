from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.http_validation_error import HTTPValidationError
from ...models.ogc_feature_collection_response import OGCFeatureCollectionResponse
from ...models.search_datasets_endpoint_search_datasets_get_spatial_predicate import (
    SearchDatasetsEndpointSearchDatasetsGetSpatialPredicate,
)
from ...types import Unset
from uuid import UUID
import datetime


def _get_kwargs(
    *,
    body: list[str] | None | Unset = UNSET,
    q: None | str | Unset = UNSET,
    bbox: None | str | Unset = UNSET,
    geometry_type: None | str | Unset = UNSET,
    srid: int | None | Unset = UNSET,
    source_organization: None | str | Unset = UNSET,
    record_type: None | str | Unset = UNSET,
    date_from: datetime.date | None | Unset = UNSET,
    date_to: datetime.date | None | Unset = UNSET,
    vintage_start: datetime.date | None | Unset = UNSET,
    vintage_end: datetime.date | None | Unset = UNSET,
    sort_by: str | Unset = "relevance",
    sort_desc: bool | None | Unset = UNSET,
    offset: int | Unset = 0,
    limit: int | Unset = 10,
    filter_: None | str | Unset = UNSET,
    cql2_filter_lang: str | Unset = "cql2-text",
    datetime_: None | str | Unset = UNSET,
    exclude_synthetic: bool | Unset = True,
    spatial_predicate: SearchDatasetsEndpointSearchDatasetsGetSpatialPredicate
    | Unset = "intersects",
    geometry: None | str | Unset = UNSET,
    collection_id: None | Unset | UUID = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    params: dict[str, Any] = {}

    json_q: None | str | Unset
    if isinstance(q, Unset):
        json_q = UNSET
    else:
        json_q = q
    params["q"] = json_q

    json_bbox: None | str | Unset
    if isinstance(bbox, Unset):
        json_bbox = UNSET
    else:
        json_bbox = bbox
    params["bbox"] = json_bbox

    json_geometry_type: None | str | Unset
    if isinstance(geometry_type, Unset):
        json_geometry_type = UNSET
    else:
        json_geometry_type = geometry_type
    params["geometry_type"] = json_geometry_type

    json_srid: int | None | Unset
    if isinstance(srid, Unset):
        json_srid = UNSET
    else:
        json_srid = srid
    params["srid"] = json_srid

    json_source_organization: None | str | Unset
    if isinstance(source_organization, Unset):
        json_source_organization = UNSET
    else:
        json_source_organization = source_organization
    params["source_organization"] = json_source_organization

    json_record_type: None | str | Unset
    if isinstance(record_type, Unset):
        json_record_type = UNSET
    else:
        json_record_type = record_type
    params["record_type"] = json_record_type

    json_date_from: None | str | Unset
    if isinstance(date_from, Unset):
        json_date_from = UNSET
    elif isinstance(date_from, datetime.date):
        json_date_from = date_from.isoformat()
    else:
        json_date_from = date_from
    params["date_from"] = json_date_from

    json_date_to: None | str | Unset
    if isinstance(date_to, Unset):
        json_date_to = UNSET
    elif isinstance(date_to, datetime.date):
        json_date_to = date_to.isoformat()
    else:
        json_date_to = date_to
    params["date_to"] = json_date_to

    json_vintage_start: None | str | Unset
    if isinstance(vintage_start, Unset):
        json_vintage_start = UNSET
    elif isinstance(vintage_start, datetime.date):
        json_vintage_start = vintage_start.isoformat()
    else:
        json_vintage_start = vintage_start
    params["vintage_start"] = json_vintage_start

    json_vintage_end: None | str | Unset
    if isinstance(vintage_end, Unset):
        json_vintage_end = UNSET
    elif isinstance(vintage_end, datetime.date):
        json_vintage_end = vintage_end.isoformat()
    else:
        json_vintage_end = vintage_end
    params["vintage_end"] = json_vintage_end

    params["sort_by"] = sort_by

    json_sort_desc: bool | None | Unset
    if isinstance(sort_desc, Unset):
        json_sort_desc = UNSET
    else:
        json_sort_desc = sort_desc
    params["sort_desc"] = json_sort_desc

    params["offset"] = offset

    params["limit"] = limit

    json_filter_: None | str | Unset
    if isinstance(filter_, Unset):
        json_filter_ = UNSET
    else:
        json_filter_ = filter_
    params["filter"] = json_filter_

    params["cql2_filter_lang"] = cql2_filter_lang

    json_datetime_: None | str | Unset
    if isinstance(datetime_, Unset):
        json_datetime_ = UNSET
    else:
        json_datetime_ = datetime_
    params["datetime"] = json_datetime_

    params["exclude_synthetic"] = exclude_synthetic

    json_spatial_predicate: str | Unset = UNSET
    if not isinstance(spatial_predicate, Unset):
        json_spatial_predicate = spatial_predicate

    params["spatial_predicate"] = json_spatial_predicate

    json_geometry: None | str | Unset
    if isinstance(geometry, Unset):
        json_geometry = UNSET
    else:
        json_geometry = geometry
    params["geometry"] = json_geometry

    json_collection_id: None | str | Unset
    if isinstance(collection_id, Unset):
        json_collection_id = UNSET
    elif isinstance(collection_id, UUID):
        json_collection_id = str(collection_id)
    else:
        json_collection_id = collection_id
    params["collection_id"] = json_collection_id

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/search/datasets/",
        "params": params,
    }

    if isinstance(body, list):
        _kwargs["json"] = body

    else:
        _kwargs["json"] = body

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | OGCFeatureCollectionResponse | None:
    if response.status_code == 200:
        response_200 = OGCFeatureCollectionResponse.from_dict(response.json())

        return response_200

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[HTTPValidationError | OGCFeatureCollectionResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: list[str] | None | Unset = UNSET,
    q: None | str | Unset = UNSET,
    bbox: None | str | Unset = UNSET,
    geometry_type: None | str | Unset = UNSET,
    srid: int | None | Unset = UNSET,
    source_organization: None | str | Unset = UNSET,
    record_type: None | str | Unset = UNSET,
    date_from: datetime.date | None | Unset = UNSET,
    date_to: datetime.date | None | Unset = UNSET,
    vintage_start: datetime.date | None | Unset = UNSET,
    vintage_end: datetime.date | None | Unset = UNSET,
    sort_by: str | Unset = "relevance",
    sort_desc: bool | None | Unset = UNSET,
    offset: int | Unset = 0,
    limit: int | Unset = 10,
    filter_: None | str | Unset = UNSET,
    cql2_filter_lang: str | Unset = "cql2-text",
    datetime_: None | str | Unset = UNSET,
    exclude_synthetic: bool | Unset = True,
    spatial_predicate: SearchDatasetsEndpointSearchDatasetsGetSpatialPredicate
    | Unset = "intersects",
    geometry: None | str | Unset = UNSET,
    collection_id: None | Unset | UUID = UNSET,
) -> Response[HTTPValidationError | OGCFeatureCollectionResponse]:
    """Search Datasets Endpoint

     Search datasets with text, spatial, and faceted filters.

    Args:
        q (None | str | Unset):
        bbox (None | str | Unset):
        geometry_type (None | str | Unset):
        srid (int | None | Unset):
        source_organization (None | str | Unset):
        record_type (None | str | Unset):
        date_from (datetime.date | None | Unset):
        date_to (datetime.date | None | Unset):
        vintage_start (datetime.date | None | Unset):
        vintage_end (datetime.date | None | Unset):
        sort_by (str | Unset):  Default: 'relevance'.
        sort_desc (bool | None | Unset):
        offset (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 10.
        filter_ (None | str | Unset):
        cql2_filter_lang (str | Unset):  Default: 'cql2-text'.
        datetime_ (None | str | Unset):
        exclude_synthetic (bool | Unset):  Default: True.
        spatial_predicate (SearchDatasetsEndpointSearchDatasetsGetSpatialPredicate | Unset):
            Default: 'intersects'.
        geometry (None | str | Unset):
        collection_id (None | Unset | UUID):
        body (list[str] | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | OGCFeatureCollectionResponse]
    """

    kwargs = _get_kwargs(
        body=body,
        q=q,
        bbox=bbox,
        geometry_type=geometry_type,
        srid=srid,
        source_organization=source_organization,
        record_type=record_type,
        date_from=date_from,
        date_to=date_to,
        vintage_start=vintage_start,
        vintage_end=vintage_end,
        sort_by=sort_by,
        sort_desc=sort_desc,
        offset=offset,
        limit=limit,
        filter_=filter_,
        cql2_filter_lang=cql2_filter_lang,
        datetime_=datetime_,
        exclude_synthetic=exclude_synthetic,
        spatial_predicate=spatial_predicate,
        geometry=geometry,
        collection_id=collection_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: list[str] | None | Unset = UNSET,
    q: None | str | Unset = UNSET,
    bbox: None | str | Unset = UNSET,
    geometry_type: None | str | Unset = UNSET,
    srid: int | None | Unset = UNSET,
    source_organization: None | str | Unset = UNSET,
    record_type: None | str | Unset = UNSET,
    date_from: datetime.date | None | Unset = UNSET,
    date_to: datetime.date | None | Unset = UNSET,
    vintage_start: datetime.date | None | Unset = UNSET,
    vintage_end: datetime.date | None | Unset = UNSET,
    sort_by: str | Unset = "relevance",
    sort_desc: bool | None | Unset = UNSET,
    offset: int | Unset = 0,
    limit: int | Unset = 10,
    filter_: None | str | Unset = UNSET,
    cql2_filter_lang: str | Unset = "cql2-text",
    datetime_: None | str | Unset = UNSET,
    exclude_synthetic: bool | Unset = True,
    spatial_predicate: SearchDatasetsEndpointSearchDatasetsGetSpatialPredicate
    | Unset = "intersects",
    geometry: None | str | Unset = UNSET,
    collection_id: None | Unset | UUID = UNSET,
) -> HTTPValidationError | OGCFeatureCollectionResponse | None:
    """Search Datasets Endpoint

     Search datasets with text, spatial, and faceted filters.

    Args:
        q (None | str | Unset):
        bbox (None | str | Unset):
        geometry_type (None | str | Unset):
        srid (int | None | Unset):
        source_organization (None | str | Unset):
        record_type (None | str | Unset):
        date_from (datetime.date | None | Unset):
        date_to (datetime.date | None | Unset):
        vintage_start (datetime.date | None | Unset):
        vintage_end (datetime.date | None | Unset):
        sort_by (str | Unset):  Default: 'relevance'.
        sort_desc (bool | None | Unset):
        offset (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 10.
        filter_ (None | str | Unset):
        cql2_filter_lang (str | Unset):  Default: 'cql2-text'.
        datetime_ (None | str | Unset):
        exclude_synthetic (bool | Unset):  Default: True.
        spatial_predicate (SearchDatasetsEndpointSearchDatasetsGetSpatialPredicate | Unset):
            Default: 'intersects'.
        geometry (None | str | Unset):
        collection_id (None | Unset | UUID):
        body (list[str] | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | OGCFeatureCollectionResponse
    """

    return sync_detailed(
        client=client,
        body=body,
        q=q,
        bbox=bbox,
        geometry_type=geometry_type,
        srid=srid,
        source_organization=source_organization,
        record_type=record_type,
        date_from=date_from,
        date_to=date_to,
        vintage_start=vintage_start,
        vintage_end=vintage_end,
        sort_by=sort_by,
        sort_desc=sort_desc,
        offset=offset,
        limit=limit,
        filter_=filter_,
        cql2_filter_lang=cql2_filter_lang,
        datetime_=datetime_,
        exclude_synthetic=exclude_synthetic,
        spatial_predicate=spatial_predicate,
        geometry=geometry,
        collection_id=collection_id,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: list[str] | None | Unset = UNSET,
    q: None | str | Unset = UNSET,
    bbox: None | str | Unset = UNSET,
    geometry_type: None | str | Unset = UNSET,
    srid: int | None | Unset = UNSET,
    source_organization: None | str | Unset = UNSET,
    record_type: None | str | Unset = UNSET,
    date_from: datetime.date | None | Unset = UNSET,
    date_to: datetime.date | None | Unset = UNSET,
    vintage_start: datetime.date | None | Unset = UNSET,
    vintage_end: datetime.date | None | Unset = UNSET,
    sort_by: str | Unset = "relevance",
    sort_desc: bool | None | Unset = UNSET,
    offset: int | Unset = 0,
    limit: int | Unset = 10,
    filter_: None | str | Unset = UNSET,
    cql2_filter_lang: str | Unset = "cql2-text",
    datetime_: None | str | Unset = UNSET,
    exclude_synthetic: bool | Unset = True,
    spatial_predicate: SearchDatasetsEndpointSearchDatasetsGetSpatialPredicate
    | Unset = "intersects",
    geometry: None | str | Unset = UNSET,
    collection_id: None | Unset | UUID = UNSET,
) -> Response[HTTPValidationError | OGCFeatureCollectionResponse]:
    """Search Datasets Endpoint

     Search datasets with text, spatial, and faceted filters.

    Args:
        q (None | str | Unset):
        bbox (None | str | Unset):
        geometry_type (None | str | Unset):
        srid (int | None | Unset):
        source_organization (None | str | Unset):
        record_type (None | str | Unset):
        date_from (datetime.date | None | Unset):
        date_to (datetime.date | None | Unset):
        vintage_start (datetime.date | None | Unset):
        vintage_end (datetime.date | None | Unset):
        sort_by (str | Unset):  Default: 'relevance'.
        sort_desc (bool | None | Unset):
        offset (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 10.
        filter_ (None | str | Unset):
        cql2_filter_lang (str | Unset):  Default: 'cql2-text'.
        datetime_ (None | str | Unset):
        exclude_synthetic (bool | Unset):  Default: True.
        spatial_predicate (SearchDatasetsEndpointSearchDatasetsGetSpatialPredicate | Unset):
            Default: 'intersects'.
        geometry (None | str | Unset):
        collection_id (None | Unset | UUID):
        body (list[str] | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | OGCFeatureCollectionResponse]
    """

    kwargs = _get_kwargs(
        body=body,
        q=q,
        bbox=bbox,
        geometry_type=geometry_type,
        srid=srid,
        source_organization=source_organization,
        record_type=record_type,
        date_from=date_from,
        date_to=date_to,
        vintage_start=vintage_start,
        vintage_end=vintage_end,
        sort_by=sort_by,
        sort_desc=sort_desc,
        offset=offset,
        limit=limit,
        filter_=filter_,
        cql2_filter_lang=cql2_filter_lang,
        datetime_=datetime_,
        exclude_synthetic=exclude_synthetic,
        spatial_predicate=spatial_predicate,
        geometry=geometry,
        collection_id=collection_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: list[str] | None | Unset = UNSET,
    q: None | str | Unset = UNSET,
    bbox: None | str | Unset = UNSET,
    geometry_type: None | str | Unset = UNSET,
    srid: int | None | Unset = UNSET,
    source_organization: None | str | Unset = UNSET,
    record_type: None | str | Unset = UNSET,
    date_from: datetime.date | None | Unset = UNSET,
    date_to: datetime.date | None | Unset = UNSET,
    vintage_start: datetime.date | None | Unset = UNSET,
    vintage_end: datetime.date | None | Unset = UNSET,
    sort_by: str | Unset = "relevance",
    sort_desc: bool | None | Unset = UNSET,
    offset: int | Unset = 0,
    limit: int | Unset = 10,
    filter_: None | str | Unset = UNSET,
    cql2_filter_lang: str | Unset = "cql2-text",
    datetime_: None | str | Unset = UNSET,
    exclude_synthetic: bool | Unset = True,
    spatial_predicate: SearchDatasetsEndpointSearchDatasetsGetSpatialPredicate
    | Unset = "intersects",
    geometry: None | str | Unset = UNSET,
    collection_id: None | Unset | UUID = UNSET,
) -> HTTPValidationError | OGCFeatureCollectionResponse | None:
    """Search Datasets Endpoint

     Search datasets with text, spatial, and faceted filters.

    Args:
        q (None | str | Unset):
        bbox (None | str | Unset):
        geometry_type (None | str | Unset):
        srid (int | None | Unset):
        source_organization (None | str | Unset):
        record_type (None | str | Unset):
        date_from (datetime.date | None | Unset):
        date_to (datetime.date | None | Unset):
        vintage_start (datetime.date | None | Unset):
        vintage_end (datetime.date | None | Unset):
        sort_by (str | Unset):  Default: 'relevance'.
        sort_desc (bool | None | Unset):
        offset (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 10.
        filter_ (None | str | Unset):
        cql2_filter_lang (str | Unset):  Default: 'cql2-text'.
        datetime_ (None | str | Unset):
        exclude_synthetic (bool | Unset):  Default: True.
        spatial_predicate (SearchDatasetsEndpointSearchDatasetsGetSpatialPredicate | Unset):
            Default: 'intersects'.
        geometry (None | str | Unset):
        collection_id (None | Unset | UUID):
        body (list[str] | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | OGCFeatureCollectionResponse
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
            q=q,
            bbox=bbox,
            geometry_type=geometry_type,
            srid=srid,
            source_organization=source_organization,
            record_type=record_type,
            date_from=date_from,
            date_to=date_to,
            vintage_start=vintage_start,
            vintage_end=vintage_end,
            sort_by=sort_by,
            sort_desc=sort_desc,
            offset=offset,
            limit=limit,
            filter_=filter_,
            cql2_filter_lang=cql2_filter_lang,
            datetime_=datetime_,
            exclude_synthetic=exclude_synthetic,
            spatial_predicate=spatial_predicate,
            geometry=geometry,
            collection_id=collection_id,
        )
    ).parsed
