from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.list_features_datasets_dataset_id_features_get_geo_json_feature_collection import (
    ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollection,
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

    params["include_geometry"] = include_geometry

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/datasets/{dataset_id}/features/".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollection
    | ProblemDetail
    | None
):
    if response.status_code == 200:
        response_200 = (
            ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollection.from_dict(
                response.json()
            )
        )

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
) -> Response[
    ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollection | ProblemDetail
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
    include_geometry: bool | Unset = True,
) -> Response[
    ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollection | ProblemDetail
]:
    """List Features

     Get paginated GeoJSON features for a dataset.

    Args:
        dataset_id (UUID):
        limit (int | Unset):  Default: 10.
        offset (int | Unset):  Default: 0.
        bbox (None | str | Unset): Bounding box: minx,miny,maxx,maxy
        include_geometry (bool | Unset): Include geometry in response Default: True.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollection | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        limit=limit,
        offset=offset,
        bbox=bbox,
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
    include_geometry: bool | Unset = True,
) -> (
    ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollection
    | ProblemDetail
    | None
):
    """List Features

     Get paginated GeoJSON features for a dataset.

    Args:
        dataset_id (UUID):
        limit (int | Unset):  Default: 10.
        offset (int | Unset):  Default: 0.
        bbox (None | str | Unset): Bounding box: minx,miny,maxx,maxy
        include_geometry (bool | Unset): Include geometry in response Default: True.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollection | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        client=client,
        limit=limit,
        offset=offset,
        bbox=bbox,
        include_geometry=include_geometry,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 10,
    offset: int | Unset = 0,
    bbox: None | str | Unset = UNSET,
    include_geometry: bool | Unset = True,
) -> Response[
    ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollection | ProblemDetail
]:
    """List Features

     Get paginated GeoJSON features for a dataset.

    Args:
        dataset_id (UUID):
        limit (int | Unset):  Default: 10.
        offset (int | Unset):  Default: 0.
        bbox (None | str | Unset): Bounding box: minx,miny,maxx,maxy
        include_geometry (bool | Unset): Include geometry in response Default: True.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollection | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        limit=limit,
        offset=offset,
        bbox=bbox,
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
    include_geometry: bool | Unset = True,
) -> (
    ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollection
    | ProblemDetail
    | None
):
    """List Features

     Get paginated GeoJSON features for a dataset.

    Args:
        dataset_id (UUID):
        limit (int | Unset):  Default: 10.
        offset (int | Unset):  Default: 0.
        bbox (None | str | Unset): Bounding box: minx,miny,maxx,maxy
        include_geometry (bool | Unset): Include geometry in response Default: True.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollection | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
            limit=limit,
            offset=offset,
            bbox=bbox,
            include_geometry=include_geometry,
        )
    ).parsed
