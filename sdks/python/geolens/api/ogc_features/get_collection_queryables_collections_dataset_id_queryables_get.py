from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.get_collection_queryables_collections_dataset_id_queryables_get_response_202 import (
    GetCollectionQueryablesCollectionsDatasetIdQueryablesGetResponse202,
)
from ...models.problem_detail import ProblemDetail
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
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
        "url": "/collections/{dataset_id}/queryables".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    Any
    | GetCollectionQueryablesCollectionsDatasetIdQueryablesGetResponse202
    | ProblemDetail
    | None
):
    if response.status_code == 200:
        response_200 = response.json()
        return response_200

    if response.status_code == 202:
        response_202 = GetCollectionQueryablesCollectionsDatasetIdQueryablesGetResponse202.from_dict(
            response.json()
        )

        return response_202

    if response.status_code == 400:
        response_400 = ProblemDetail.from_dict(response.json())

        return response_400

    if response.status_code == 401:
        response_401 = ProblemDetail.from_dict(response.json())

        return response_401

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
) -> Response[
    Any
    | GetCollectionQueryablesCollectionsDatasetIdQueryablesGetResponse202
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
    f: None | str | Unset = UNSET,
) -> Response[
    Any
    | GetCollectionQueryablesCollectionsDatasetIdQueryablesGetResponse202
    | ProblemDetail
]:
    """Get Collection Queryables

     Queryable properties for one feature collection (OGC Features Part 3).

    feat(#1614): derived from the live table schema (never the stored
    column_info snapshot) so the advertised set always matches what `filter=`
    on /items validates against. `additionalProperties: false` is what makes
    rejecting filters on unlisted properties spec-conformant.

    Args:
        dataset_id (UUID):
        f (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | GetCollectionQueryablesCollectionsDatasetIdQueryablesGetResponse202 | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        f=f,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    f: None | str | Unset = UNSET,
) -> (
    Any
    | GetCollectionQueryablesCollectionsDatasetIdQueryablesGetResponse202
    | ProblemDetail
    | None
):
    """Get Collection Queryables

     Queryable properties for one feature collection (OGC Features Part 3).

    feat(#1614): derived from the live table schema (never the stored
    column_info snapshot) so the advertised set always matches what `filter=`
    on /items validates against. `additionalProperties: false` is what makes
    rejecting filters on unlisted properties spec-conformant.

    Args:
        dataset_id (UUID):
        f (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | GetCollectionQueryablesCollectionsDatasetIdQueryablesGetResponse202 | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        client=client,
        f=f,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    f: None | str | Unset = UNSET,
) -> Response[
    Any
    | GetCollectionQueryablesCollectionsDatasetIdQueryablesGetResponse202
    | ProblemDetail
]:
    """Get Collection Queryables

     Queryable properties for one feature collection (OGC Features Part 3).

    feat(#1614): derived from the live table schema (never the stored
    column_info snapshot) so the advertised set always matches what `filter=`
    on /items validates against. `additionalProperties: false` is what makes
    rejecting filters on unlisted properties spec-conformant.

    Args:
        dataset_id (UUID):
        f (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | GetCollectionQueryablesCollectionsDatasetIdQueryablesGetResponse202 | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        f=f,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    f: None | str | Unset = UNSET,
) -> (
    Any
    | GetCollectionQueryablesCollectionsDatasetIdQueryablesGetResponse202
    | ProblemDetail
    | None
):
    """Get Collection Queryables

     Queryable properties for one feature collection (OGC Features Part 3).

    feat(#1614): derived from the live table schema (never the stored
    column_info snapshot) so the advertised set always matches what `filter=`
    on /items validates against. `additionalProperties: false` is what makes
    rejecting filters on unlisted properties spec-conformant.

    Args:
        dataset_id (UUID):
        f (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | GetCollectionQueryablesCollectionsDatasetIdQueryablesGetResponse202 | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
            f=f,
        )
    ).parsed
