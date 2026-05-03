from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.facet_count_response import FacetCountResponse
from ...models.http_validation_error import HTTPValidationError
from ...models.search_facets_endpoint_search_facets_get_spatial_predicate import (
    SearchFacetsEndpointSearchFacetsGetSpatialPredicate,
)
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    *,
    q: None | str | Unset = UNSET,
    bbox: None | str | Unset = UNSET,
    keywords: list[str] | None | Unset = UNSET,
    geometry_type: None | str | Unset = UNSET,
    srid: int | None | Unset = UNSET,
    source_organization: None | str | Unset = UNSET,
    datetime_: None | str | Unset = UNSET,
    exclude_synthetic: bool | Unset = True,
    spatial_predicate: SearchFacetsEndpointSearchFacetsGetSpatialPredicate
    | Unset = "intersects",
    geometry: None | str | Unset = UNSET,
    collection_id: None | Unset | UUID = UNSET,
) -> dict[str, Any]:

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

    json_keywords: list[str] | None | Unset
    if isinstance(keywords, Unset):
        json_keywords = UNSET
    elif isinstance(keywords, list):
        json_keywords = keywords

    else:
        json_keywords = keywords
    params["keywords"] = json_keywords

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
        "url": "/search/facets/",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> FacetCountResponse | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = FacetCountResponse.from_dict(response.json())

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
) -> Response[FacetCountResponse | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    q: None | str | Unset = UNSET,
    bbox: None | str | Unset = UNSET,
    keywords: list[str] | None | Unset = UNSET,
    geometry_type: None | str | Unset = UNSET,
    srid: int | None | Unset = UNSET,
    source_organization: None | str | Unset = UNSET,
    datetime_: None | str | Unset = UNSET,
    exclude_synthetic: bool | Unset = True,
    spatial_predicate: SearchFacetsEndpointSearchFacetsGetSpatialPredicate
    | Unset = "intersects",
    geometry: None | str | Unset = UNSET,
    collection_id: None | Unset | UUID = UNSET,
) -> Response[FacetCountResponse | HTTPValidationError]:
    """Search Facets Endpoint

     Return record_type facet counts for the given filters.

    Args:
        q (None | str | Unset): Full-text search query
        bbox (None | str | Unset): Bounding box: minx,miny,maxx,maxy
        keywords (list[str] | None | Unset): Filter by keywords
        geometry_type (None | str | Unset): Filter by geometry type
        srid (int | None | Unset): Filter by SRID
        source_organization (None | str | Unset): Filter by source organization
        datetime_ (None | str | Unset): OGC datetime interval
        exclude_synthetic (bool | Unset): Exclude synthetic/test datasets Default: True.
        spatial_predicate (SearchFacetsEndpointSearchFacetsGetSpatialPredicate | Unset): Spatial
            predicate: intersects or within Default: 'intersects'.
        geometry (None | str | Unset): GeoJSON geometry for spatial filter
        collection_id (None | Unset | UUID): Filter by collection membership

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[FacetCountResponse | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        q=q,
        bbox=bbox,
        keywords=keywords,
        geometry_type=geometry_type,
        srid=srid,
        source_organization=source_organization,
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
    q: None | str | Unset = UNSET,
    bbox: None | str | Unset = UNSET,
    keywords: list[str] | None | Unset = UNSET,
    geometry_type: None | str | Unset = UNSET,
    srid: int | None | Unset = UNSET,
    source_organization: None | str | Unset = UNSET,
    datetime_: None | str | Unset = UNSET,
    exclude_synthetic: bool | Unset = True,
    spatial_predicate: SearchFacetsEndpointSearchFacetsGetSpatialPredicate
    | Unset = "intersects",
    geometry: None | str | Unset = UNSET,
    collection_id: None | Unset | UUID = UNSET,
) -> FacetCountResponse | HTTPValidationError | None:
    """Search Facets Endpoint

     Return record_type facet counts for the given filters.

    Args:
        q (None | str | Unset): Full-text search query
        bbox (None | str | Unset): Bounding box: minx,miny,maxx,maxy
        keywords (list[str] | None | Unset): Filter by keywords
        geometry_type (None | str | Unset): Filter by geometry type
        srid (int | None | Unset): Filter by SRID
        source_organization (None | str | Unset): Filter by source organization
        datetime_ (None | str | Unset): OGC datetime interval
        exclude_synthetic (bool | Unset): Exclude synthetic/test datasets Default: True.
        spatial_predicate (SearchFacetsEndpointSearchFacetsGetSpatialPredicate | Unset): Spatial
            predicate: intersects or within Default: 'intersects'.
        geometry (None | str | Unset): GeoJSON geometry for spatial filter
        collection_id (None | Unset | UUID): Filter by collection membership

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        FacetCountResponse | HTTPValidationError
    """

    return sync_detailed(
        client=client,
        q=q,
        bbox=bbox,
        keywords=keywords,
        geometry_type=geometry_type,
        srid=srid,
        source_organization=source_organization,
        datetime_=datetime_,
        exclude_synthetic=exclude_synthetic,
        spatial_predicate=spatial_predicate,
        geometry=geometry,
        collection_id=collection_id,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    q: None | str | Unset = UNSET,
    bbox: None | str | Unset = UNSET,
    keywords: list[str] | None | Unset = UNSET,
    geometry_type: None | str | Unset = UNSET,
    srid: int | None | Unset = UNSET,
    source_organization: None | str | Unset = UNSET,
    datetime_: None | str | Unset = UNSET,
    exclude_synthetic: bool | Unset = True,
    spatial_predicate: SearchFacetsEndpointSearchFacetsGetSpatialPredicate
    | Unset = "intersects",
    geometry: None | str | Unset = UNSET,
    collection_id: None | Unset | UUID = UNSET,
) -> Response[FacetCountResponse | HTTPValidationError]:
    """Search Facets Endpoint

     Return record_type facet counts for the given filters.

    Args:
        q (None | str | Unset): Full-text search query
        bbox (None | str | Unset): Bounding box: minx,miny,maxx,maxy
        keywords (list[str] | None | Unset): Filter by keywords
        geometry_type (None | str | Unset): Filter by geometry type
        srid (int | None | Unset): Filter by SRID
        source_organization (None | str | Unset): Filter by source organization
        datetime_ (None | str | Unset): OGC datetime interval
        exclude_synthetic (bool | Unset): Exclude synthetic/test datasets Default: True.
        spatial_predicate (SearchFacetsEndpointSearchFacetsGetSpatialPredicate | Unset): Spatial
            predicate: intersects or within Default: 'intersects'.
        geometry (None | str | Unset): GeoJSON geometry for spatial filter
        collection_id (None | Unset | UUID): Filter by collection membership

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[FacetCountResponse | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        q=q,
        bbox=bbox,
        keywords=keywords,
        geometry_type=geometry_type,
        srid=srid,
        source_organization=source_organization,
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
    q: None | str | Unset = UNSET,
    bbox: None | str | Unset = UNSET,
    keywords: list[str] | None | Unset = UNSET,
    geometry_type: None | str | Unset = UNSET,
    srid: int | None | Unset = UNSET,
    source_organization: None | str | Unset = UNSET,
    datetime_: None | str | Unset = UNSET,
    exclude_synthetic: bool | Unset = True,
    spatial_predicate: SearchFacetsEndpointSearchFacetsGetSpatialPredicate
    | Unset = "intersects",
    geometry: None | str | Unset = UNSET,
    collection_id: None | Unset | UUID = UNSET,
) -> FacetCountResponse | HTTPValidationError | None:
    """Search Facets Endpoint

     Return record_type facet counts for the given filters.

    Args:
        q (None | str | Unset): Full-text search query
        bbox (None | str | Unset): Bounding box: minx,miny,maxx,maxy
        keywords (list[str] | None | Unset): Filter by keywords
        geometry_type (None | str | Unset): Filter by geometry type
        srid (int | None | Unset): Filter by SRID
        source_organization (None | str | Unset): Filter by source organization
        datetime_ (None | str | Unset): OGC datetime interval
        exclude_synthetic (bool | Unset): Exclude synthetic/test datasets Default: True.
        spatial_predicate (SearchFacetsEndpointSearchFacetsGetSpatialPredicate | Unset): Spatial
            predicate: intersects or within Default: 'intersects'.
        geometry (None | str | Unset): GeoJSON geometry for spatial filter
        collection_id (None | Unset | UUID): Filter by collection membership

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        FacetCountResponse | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            client=client,
            q=q,
            bbox=bbox,
            keywords=keywords,
            geometry_type=geometry_type,
            srid=srid,
            source_organization=source_organization,
            datetime_=datetime_,
            exclude_synthetic=exclude_synthetic,
            spatial_predicate=spatial_predicate,
            geometry=geometry,
            collection_id=collection_id,
        )
    ).parsed
