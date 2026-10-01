from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.create_feature_datasets_dataset_id_features_post_geo_json_feature import (
    CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeature,
)
from ...models.feature_create import FeatureCreate
from ...models.problem_detail import ProblemDetail
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    *,
    body: FeatureCreate,
    idempotency_key: str | Unset = UNSET,
    idempotency_attempt: int | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(idempotency_key, Unset):
        headers["Idempotency-Key"] = idempotency_key

    if not isinstance(idempotency_attempt, Unset):
        headers["Idempotency-Attempt"] = str(idempotency_attempt)

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/datasets/{dataset_id}/features/".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeature | ProblemDetail | None:
    if response.status_code == 201:
        response_201 = (
            CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeature.from_dict(
                response.json()
            )
        )

        return response_201

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
) -> Response[CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeature | ProblemDetail]:
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
    body: FeatureCreate,
    idempotency_key: str | Unset = UNSET,
    idempotency_attempt: int | Unset = UNSET,
) -> Response[CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeature | ProblemDetail]:
    """Create Feature

     Insert a new GeoJSON feature into a dataset.

    Send the same `Idempotency-Key` on every attempt to create one feature, and
    `Idempotency-Attempt` numbering the attempts 1, 2, 3 and so on. A repeat
    from the same user on the same dataset never inserts a second feature. It
    answers with the feature as stored, with the same 201 status and body
    shape. If its attempt number is higher than any applied so far, it first
    applies its geometry and the properties it names to that feature, with the
    validation a create gets, unless anyone else has written the feature since
    the last attempt was applied: then it is refused with 409, the stored
    feature in `detail.feature`, and nothing is overwritten. If it is equal or
    lower, the stored feature comes back unchanged, so a request that arrives
    late cannot undo a later one. Two requests with one key never both insert. A key is honored for 24
    hours. If
    the feature it created has been deleted since, or the dataset's data has
    been replaced by a reupload or an overwrite, the repeat is refused with 409
    rather than creating another. Without the key every request inserts, and
    an attempt number sent without one is ignored.

    Args:
        dataset_id (UUID):
        idempotency_key (str | Unset): Optional key that makes a retried create safe. Letters,
            digits and `._:-`, up to 128 characters.
        idempotency_attempt (int | Unset): Attempt number sent with `Idempotency-Key`, counting up
            by one each time the body is sent again. Counts as 1 when omitted.
        body (FeatureCreate): GeoJSON-style feature for insertion.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeature | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        body=body,
        idempotency_key=idempotency_key,
        idempotency_attempt=idempotency_attempt,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    body: FeatureCreate,
    idempotency_key: str | Unset = UNSET,
    idempotency_attempt: int | Unset = UNSET,
) -> CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeature | ProblemDetail | None:
    """Create Feature

     Insert a new GeoJSON feature into a dataset.

    Send the same `Idempotency-Key` on every attempt to create one feature, and
    `Idempotency-Attempt` numbering the attempts 1, 2, 3 and so on. A repeat
    from the same user on the same dataset never inserts a second feature. It
    answers with the feature as stored, with the same 201 status and body
    shape. If its attempt number is higher than any applied so far, it first
    applies its geometry and the properties it names to that feature, with the
    validation a create gets, unless anyone else has written the feature since
    the last attempt was applied: then it is refused with 409, the stored
    feature in `detail.feature`, and nothing is overwritten. If it is equal or
    lower, the stored feature comes back unchanged, so a request that arrives
    late cannot undo a later one. Two requests with one key never both insert. A key is honored for 24
    hours. If
    the feature it created has been deleted since, or the dataset's data has
    been replaced by a reupload or an overwrite, the repeat is refused with 409
    rather than creating another. Without the key every request inserts, and
    an attempt number sent without one is ignored.

    Args:
        dataset_id (UUID):
        idempotency_key (str | Unset): Optional key that makes a retried create safe. Letters,
            digits and `._:-`, up to 128 characters.
        idempotency_attempt (int | Unset): Attempt number sent with `Idempotency-Key`, counting up
            by one each time the body is sent again. Counts as 1 when omitted.
        body (FeatureCreate): GeoJSON-style feature for insertion.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeature | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        client=client,
        body=body,
        idempotency_key=idempotency_key,
        idempotency_attempt=idempotency_attempt,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    body: FeatureCreate,
    idempotency_key: str | Unset = UNSET,
    idempotency_attempt: int | Unset = UNSET,
) -> Response[CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeature | ProblemDetail]:
    """Create Feature

     Insert a new GeoJSON feature into a dataset.

    Send the same `Idempotency-Key` on every attempt to create one feature, and
    `Idempotency-Attempt` numbering the attempts 1, 2, 3 and so on. A repeat
    from the same user on the same dataset never inserts a second feature. It
    answers with the feature as stored, with the same 201 status and body
    shape. If its attempt number is higher than any applied so far, it first
    applies its geometry and the properties it names to that feature, with the
    validation a create gets, unless anyone else has written the feature since
    the last attempt was applied: then it is refused with 409, the stored
    feature in `detail.feature`, and nothing is overwritten. If it is equal or
    lower, the stored feature comes back unchanged, so a request that arrives
    late cannot undo a later one. Two requests with one key never both insert. A key is honored for 24
    hours. If
    the feature it created has been deleted since, or the dataset's data has
    been replaced by a reupload or an overwrite, the repeat is refused with 409
    rather than creating another. Without the key every request inserts, and
    an attempt number sent without one is ignored.

    Args:
        dataset_id (UUID):
        idempotency_key (str | Unset): Optional key that makes a retried create safe. Letters,
            digits and `._:-`, up to 128 characters.
        idempotency_attempt (int | Unset): Attempt number sent with `Idempotency-Key`, counting up
            by one each time the body is sent again. Counts as 1 when omitted.
        body (FeatureCreate): GeoJSON-style feature for insertion.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeature | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        body=body,
        idempotency_key=idempotency_key,
        idempotency_attempt=idempotency_attempt,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    body: FeatureCreate,
    idempotency_key: str | Unset = UNSET,
    idempotency_attempt: int | Unset = UNSET,
) -> CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeature | ProblemDetail | None:
    """Create Feature

     Insert a new GeoJSON feature into a dataset.

    Send the same `Idempotency-Key` on every attempt to create one feature, and
    `Idempotency-Attempt` numbering the attempts 1, 2, 3 and so on. A repeat
    from the same user on the same dataset never inserts a second feature. It
    answers with the feature as stored, with the same 201 status and body
    shape. If its attempt number is higher than any applied so far, it first
    applies its geometry and the properties it names to that feature, with the
    validation a create gets, unless anyone else has written the feature since
    the last attempt was applied: then it is refused with 409, the stored
    feature in `detail.feature`, and nothing is overwritten. If it is equal or
    lower, the stored feature comes back unchanged, so a request that arrives
    late cannot undo a later one. Two requests with one key never both insert. A key is honored for 24
    hours. If
    the feature it created has been deleted since, or the dataset's data has
    been replaced by a reupload or an overwrite, the repeat is refused with 409
    rather than creating another. Without the key every request inserts, and
    an attempt number sent without one is ignored.

    Args:
        dataset_id (UUID):
        idempotency_key (str | Unset): Optional key that makes a retried create safe. Letters,
            digits and `._:-`, up to 128 characters.
        idempotency_attempt (int | Unset): Attempt number sent with `Idempotency-Key`, counting up
            by one each time the body is sent again. Counts as 1 when omitted.
        body (FeatureCreate): GeoJSON-style feature for insertion.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeature | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
            body=body,
            idempotency_key=idempotency_key,
            idempotency_attempt=idempotency_attempt,
        )
    ).parsed
