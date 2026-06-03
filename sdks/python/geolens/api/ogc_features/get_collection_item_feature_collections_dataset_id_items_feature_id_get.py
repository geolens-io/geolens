from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.get_collection_item_feature_collections_dataset_id_items_feature_id_get_ogc_single_feature_response import (
    GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponse,
)
from ...models.problem_detail import ProblemDetail
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    feature_id: int,
    *,
    f: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_f: None | str | Unset
    if isinstance(f, Unset):
        json_f = UNSET
    else:
        json_f = f
    params["f"] = json_f

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/collections/{dataset_id}/items/{feature_id}".format(
            dataset_id=quote(str(dataset_id), safe=""),
            feature_id=quote(str(feature_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponse
    | ProblemDetail
    | None
):
    if response.status_code == 200:
        response_200 = GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponse.from_dict(
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
    GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponse
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
    feature_id: int,
    *,
    client: AuthenticatedClient,
    f: None | str | Unset = UNSET,
) -> Response[
    GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponse
    | ProblemDetail
]:
    """Get Collection Item Feature

     OGC API Features single feature endpoint -- returns a GeoJSON Feature.

    Args:
        dataset_id (UUID):
        feature_id (int):
        f (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        feature_id=feature_id,
        f=f,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    feature_id: int,
    *,
    client: AuthenticatedClient,
    f: None | str | Unset = UNSET,
) -> (
    GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponse
    | ProblemDetail
    | None
):
    """Get Collection Item Feature

     OGC API Features single feature endpoint -- returns a GeoJSON Feature.

    Args:
        dataset_id (UUID):
        feature_id (int):
        f (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponse | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        feature_id=feature_id,
        client=client,
        f=f,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    feature_id: int,
    *,
    client: AuthenticatedClient,
    f: None | str | Unset = UNSET,
) -> Response[
    GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponse
    | ProblemDetail
]:
    """Get Collection Item Feature

     OGC API Features single feature endpoint -- returns a GeoJSON Feature.

    Args:
        dataset_id (UUID):
        feature_id (int):
        f (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        feature_id=feature_id,
        f=f,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    feature_id: int,
    *,
    client: AuthenticatedClient,
    f: None | str | Unset = UNSET,
) -> (
    GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponse
    | ProblemDetail
    | None
):
    """Get Collection Item Feature

     OGC API Features single feature endpoint -- returns a GeoJSON Feature.

    Args:
        dataset_id (UUID):
        feature_id (int):
        f (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            feature_id=feature_id,
            client=client,
            f=f,
        )
    ).parsed
