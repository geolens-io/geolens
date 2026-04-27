from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.feature_update import FeatureUpdate
from ...models.patch_single_feature_datasets_dataset_id_features_gid_patch_geo_json_feature import (
    PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeature,
)
from ...models.problem_detail import ProblemDetail
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    gid: int,
    *,
    body: FeatureUpdate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/datasets/{dataset_id}/features/{gid}".format(
            dataset_id=quote(str(dataset_id), safe=""),
            gid=quote(str(gid), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeature
    | ProblemDetail
    | None
):
    if response.status_code == 200:
        response_200 = (
            PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeature.from_dict(
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

    if response.status_code == 409:
        response_409 = ProblemDetail.from_dict(response.json())

        return response_409

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
    PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeature | ProblemDetail
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
    body: FeatureUpdate,
) -> Response[
    PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeature | ProblemDetail
]:
    """Patch Single Feature

     Partial update of a feature (PATCH semantics).

    Args:
        dataset_id (UUID):
        gid (int):
        body (FeatureUpdate): Partial feature update (PATCH semantics).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeature | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        gid=gid,
        body=body,
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
    body: FeatureUpdate,
) -> (
    PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeature
    | ProblemDetail
    | None
):
    """Patch Single Feature

     Partial update of a feature (PATCH semantics).

    Args:
        dataset_id (UUID):
        gid (int):
        body (FeatureUpdate): Partial feature update (PATCH semantics).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeature | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        gid=gid,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    gid: int,
    *,
    client: AuthenticatedClient,
    body: FeatureUpdate,
) -> Response[
    PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeature | ProblemDetail
]:
    """Patch Single Feature

     Partial update of a feature (PATCH semantics).

    Args:
        dataset_id (UUID):
        gid (int):
        body (FeatureUpdate): Partial feature update (PATCH semantics).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeature | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        gid=gid,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    gid: int,
    *,
    client: AuthenticatedClient,
    body: FeatureUpdate,
) -> (
    PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeature
    | ProblemDetail
    | None
):
    """Patch Single Feature

     Partial update of a feature (PATCH semantics).

    Args:
        dataset_id (UUID):
        gid (int):
        body (FeatureUpdate): Partial feature update (PATCH semantics).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeature | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            gid=gid,
            client=client,
            body=body,
        )
    ).parsed
