from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.get_single_feature_datasets_dataset_id_features_gid_get_geo_json_feature import (
    GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeature,
)
from ...models.problem_detail import ProblemDetail
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    gid: int,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/datasets/{dataset_id}/features/{gid}".format(
            dataset_id=quote(str(dataset_id), safe=""),
            gid=quote(str(gid), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeature | ProblemDetail | None
):
    if response.status_code == 200:
        response_200 = (
            GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeature.from_dict(
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
    GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeature | ProblemDetail
]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    dataset_id: UUID,
    gid: int,
    *,
    client: AuthenticatedClient,
) -> Response[
    GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeature | ProblemDetail
]:
    """Get Single Feature

     Get a single GeoJSON feature by gid.

    Args:
        dataset_id (UUID):
        gid (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeature | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        gid=gid,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    gid: int,
    *,
    client: AuthenticatedClient,
) -> (
    GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeature | ProblemDetail | None
):
    """Get Single Feature

     Get a single GeoJSON feature by gid.

    Args:
        dataset_id (UUID):
        gid (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeature | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        gid=gid,
        client=client,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    gid: int,
    *,
    client: AuthenticatedClient,
) -> Response[
    GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeature | ProblemDetail
]:
    """Get Single Feature

     Get a single GeoJSON feature by gid.

    Args:
        dataset_id (UUID):
        gid (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeature | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        gid=gid,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    gid: int,
    *,
    client: AuthenticatedClient,
) -> (
    GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeature | ProblemDetail | None
):
    """Get Single Feature

     Get a single GeoJSON feature by gid.

    Args:
        dataset_id (UUID):
        gid (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeature | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            gid=gid,
            client=client,
        )
    ).parsed
