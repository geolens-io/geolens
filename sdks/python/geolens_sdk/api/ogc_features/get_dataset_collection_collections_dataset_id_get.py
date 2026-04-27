from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.ogc_collection_metadata import OGCCollectionMetadata
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
        "url": "/collections/{dataset_id}".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> OGCCollectionMetadata | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = OGCCollectionMetadata.from_dict(response.json())

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
) -> Response[OGCCollectionMetadata | ProblemDetail]:
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
) -> Response[OGCCollectionMetadata | ProblemDetail]:
    """Get Dataset Collection

     Per-dataset OGC collection metadata with extent, CRS, and items link.

    Args:
        dataset_id (UUID):
        f (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[OGCCollectionMetadata | ProblemDetail]
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
) -> OGCCollectionMetadata | ProblemDetail | None:
    """Get Dataset Collection

     Per-dataset OGC collection metadata with extent, CRS, and items link.

    Args:
        dataset_id (UUID):
        f (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        OGCCollectionMetadata | ProblemDetail
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
) -> Response[OGCCollectionMetadata | ProblemDetail]:
    """Get Dataset Collection

     Per-dataset OGC collection metadata with extent, CRS, and items link.

    Args:
        dataset_id (UUID):
        f (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[OGCCollectionMetadata | ProblemDetail]
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
) -> OGCCollectionMetadata | ProblemDetail | None:
    """Get Dataset Collection

     Per-dataset OGC collection metadata with extent, CRS, and items link.

    Args:
        dataset_id (UUID):
        f (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        OGCCollectionMetadata | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
            f=f,
        )
    ).parsed
