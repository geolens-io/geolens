from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...models.validation_result_response import ValidationResultResponse
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    *,
    refresh: bool | Unset = False,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["refresh"] = refresh

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/datasets/{dataset_id}/validate/".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ProblemDetail | ValidationResultResponse | None:
    if response.status_code == 200:
        response_200 = ValidationResultResponse.from_dict(response.json())

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
) -> Response[ProblemDetail | ValidationResultResponse]:
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
    refresh: bool | Unset = False,
) -> Response[ProblemDetail | ValidationResultResponse]:
    """Validate Dataset

     Get validation status for a dataset. Shows hard errors and soft warnings.

    By default returns the quality score persisted at ingest time. Pass
    ``?refresh=true`` to recompute and persist a fresh score (expensive on
    large tables — issues a full scan per non-geometry column coalesced into
    a single query).

    Args:
        dataset_id (UUID):
        refresh (bool | Unset): Recompute the quality score instead of returning the cached value.
            Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | ValidationResultResponse]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        refresh=refresh,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    refresh: bool | Unset = False,
) -> ProblemDetail | ValidationResultResponse | None:
    """Validate Dataset

     Get validation status for a dataset. Shows hard errors and soft warnings.

    By default returns the quality score persisted at ingest time. Pass
    ``?refresh=true`` to recompute and persist a fresh score (expensive on
    large tables — issues a full scan per non-geometry column coalesced into
    a single query).

    Args:
        dataset_id (UUID):
        refresh (bool | Unset): Recompute the quality score instead of returning the cached value.
            Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | ValidationResultResponse
    """

    return sync_detailed(
        dataset_id=dataset_id,
        client=client,
        refresh=refresh,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    refresh: bool | Unset = False,
) -> Response[ProblemDetail | ValidationResultResponse]:
    """Validate Dataset

     Get validation status for a dataset. Shows hard errors and soft warnings.

    By default returns the quality score persisted at ingest time. Pass
    ``?refresh=true`` to recompute and persist a fresh score (expensive on
    large tables — issues a full scan per non-geometry column coalesced into
    a single query).

    Args:
        dataset_id (UUID):
        refresh (bool | Unset): Recompute the quality score instead of returning the cached value.
            Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | ValidationResultResponse]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        refresh=refresh,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    refresh: bool | Unset = False,
) -> ProblemDetail | ValidationResultResponse | None:
    """Validate Dataset

     Get validation status for a dataset. Shows hard errors and soft warnings.

    By default returns the quality score persisted at ingest time. Pass
    ``?refresh=true`` to recompute and persist a fresh score (expensive on
    large tables — issues a full scan per non-geometry column coalesced into
    a single query).

    Args:
        dataset_id (UUID):
        refresh (bool | Unset): Recompute the quality score instead of returning the cached value.
            Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | ValidationResultResponse
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
            refresh=refresh,
        )
    ).parsed
