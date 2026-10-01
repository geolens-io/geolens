from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    gid: int,
    *,
    table_id: str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["table_id"] = table_id

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "delete",
        "url": "/datasets/{dataset_id}/features/{gid}".format(
            dataset_id=quote(str(dataset_id), safe=""),
            gid=quote(str(gid), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | ProblemDetail | None:
    if response.status_code == 204:
        response_204 = cast(Any, None)
        return response_204

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
) -> Response[Any | ProblemDetail]:
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
    table_id: str | Unset = UNSET,
) -> Response[Any | ProblemDetail]:
    """Delete Single Feature

     Delete a feature by gid (hard delete).

    The X-GeoLens-Tile-Cache-Version response header carries the dataset's
    tile_cache_version after the delete committed; a 204 response has no
    body to carry it in, unlike the create, replace and patch endpoints,
    which return it as a field of the written feature.

    Args:
        dataset_id (UUID):
        gid (int):
        table_id (str | Unset): The `table_id` the feature was read with. If the dataset's data
            has been replaced since, the request is refused with 409 and code `dataset_replaced`, and
            nothing is written.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        gid=gid,
        table_id=table_id,
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
    table_id: str | Unset = UNSET,
) -> Any | ProblemDetail | None:
    """Delete Single Feature

     Delete a feature by gid (hard delete).

    The X-GeoLens-Tile-Cache-Version response header carries the dataset's
    tile_cache_version after the delete committed; a 204 response has no
    body to carry it in, unlike the create, replace and patch endpoints,
    which return it as a field of the written feature.

    Args:
        dataset_id (UUID):
        gid (int):
        table_id (str | Unset): The `table_id` the feature was read with. If the dataset's data
            has been replaced since, the request is refused with 409 and code `dataset_replaced`, and
            nothing is written.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        gid=gid,
        client=client,
        table_id=table_id,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    gid: int,
    *,
    client: AuthenticatedClient,
    table_id: str | Unset = UNSET,
) -> Response[Any | ProblemDetail]:
    """Delete Single Feature

     Delete a feature by gid (hard delete).

    The X-GeoLens-Tile-Cache-Version response header carries the dataset's
    tile_cache_version after the delete committed; a 204 response has no
    body to carry it in, unlike the create, replace and patch endpoints,
    which return it as a field of the written feature.

    Args:
        dataset_id (UUID):
        gid (int):
        table_id (str | Unset): The `table_id` the feature was read with. If the dataset's data
            has been replaced since, the request is refused with 409 and code `dataset_replaced`, and
            nothing is written.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        gid=gid,
        table_id=table_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    gid: int,
    *,
    client: AuthenticatedClient,
    table_id: str | Unset = UNSET,
) -> Any | ProblemDetail | None:
    """Delete Single Feature

     Delete a feature by gid (hard delete).

    The X-GeoLens-Tile-Cache-Version response header carries the dataset's
    tile_cache_version after the delete committed; a 204 response has no
    body to carry it in, unlike the create, replace and patch endpoints,
    which return it as a field of the written feature.

    Args:
        dataset_id (UUID):
        gid (int):
        table_id (str | Unset): The `table_id` the feature was read with. If the dataset's data
            has been replaced since, the request is refused with 409 and code `dataset_replaced`, and
            nothing is written.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            gid=gid,
            client=client,
            table_id=table_id,
        )
    ).parsed
