from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...types import File
from ...types import Unset
from io import BytesIO
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    *,
    size: int | Unset = 256,
    v: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["size"] = size

    json_v: None | str | Unset
    if isinstance(v, Unset):
        json_v = UNSET
    else:
        json_v = v
    params["v"] = json_v

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/datasets/{dataset_id}/quicklook".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> File | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = File(payload=BytesIO(response.content))

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
) -> Response[File | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    size: int | Unset = 256,
    v: None | str | Unset = UNSET,
) -> Response[File | ProblemDetail]:
    """Get Quicklook

     Serve a quicklook PNG image for a dataset.

    Args:
        dataset_id (UUID):
        size (int | Unset): Quicklook size in pixels (256 or 512) Default: 256.
        v (None | str | Unset): The record's `quicklook_version`; it only keys caches and does not
            change the response.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[File | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        size=size,
        v=v,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    size: int | Unset = 256,
    v: None | str | Unset = UNSET,
) -> File | ProblemDetail | None:
    """Get Quicklook

     Serve a quicklook PNG image for a dataset.

    Args:
        dataset_id (UUID):
        size (int | Unset): Quicklook size in pixels (256 or 512) Default: 256.
        v (None | str | Unset): The record's `quicklook_version`; it only keys caches and does not
            change the response.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        File | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        client=client,
        size=size,
        v=v,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    size: int | Unset = 256,
    v: None | str | Unset = UNSET,
) -> Response[File | ProblemDetail]:
    """Get Quicklook

     Serve a quicklook PNG image for a dataset.

    Args:
        dataset_id (UUID):
        size (int | Unset): Quicklook size in pixels (256 or 512) Default: 256.
        v (None | str | Unset): The record's `quicklook_version`; it only keys caches and does not
            change the response.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[File | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        size=size,
        v=v,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    size: int | Unset = 256,
    v: None | str | Unset = UNSET,
) -> File | ProblemDetail | None:
    """Get Quicklook

     Serve a quicklook PNG image for a dataset.

    Args:
        dataset_id (UUID):
        size (int | Unset): Quicklook size in pixels (256 or 512) Default: 256.
        v (None | str | Unset): The record's `quicklook_version`; it only keys caches and does not
            change the response.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        File | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
            size=size,
            v=v,
        )
    ).parsed
