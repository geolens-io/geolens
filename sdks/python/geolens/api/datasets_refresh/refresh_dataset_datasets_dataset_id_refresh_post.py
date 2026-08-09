from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.dataset_refresh_request import DatasetRefreshRequest
from ...models.dataset_refresh_response import DatasetRefreshResponse
from ...models.problem_detail import ProblemDetail
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    *,
    body: DatasetRefreshRequest | None | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/datasets/{dataset_id}/refresh".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
    }

    if isinstance(body, DatasetRefreshRequest):
        _kwargs["json"] = body.to_dict()
    elif not isinstance(body, Unset):
        _kwargs["json"] = body

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> DatasetRefreshResponse | ProblemDetail | None:
    if response.status_code == 202:
        response_202 = DatasetRefreshResponse.from_dict(response.json())

        return response_202

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
) -> Response[DatasetRefreshResponse | ProblemDetail]:
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
    body: DatasetRefreshRequest | None | Unset = UNSET,
) -> Response[DatasetRefreshResponse | ProblemDetail]:
    """Refresh Dataset

     Re-pull this dataset's data from the origin it was imported from.

    One request, no source pointer, no layer selection. The dataset keeps
    serving its current data throughout: the worker loads into an
    attempt-scoped staging table and swaps only once the new data is
    complete, so a refresh that fails leaves the live table and its freshness
    exactly as they were.

    A dataset registered from an existing PostGIS table takes the other
    execution strategy (#1265): its origin IS the table it serves from, so
    there is nothing to pull and nothing to swap, and the refresh re-measures
    the live relation instead — recounting features, recomputing the extent,
    and rebuilding the column schema snapshot and statistics. Admission, the
    run row and the history it writes are identical either way.

    Refuses with 409 ``dataset_busy`` while another refresh or re-upload is
    active for this dataset — v1 rejects rather than queues (Decision 5b), and
    the refusal comes from a partial unique index rather than a check, so two
    simultaneous clicks cannot both be admitted.

    Args:
        dataset_id (UUID):
        body (DatasetRefreshRequest | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DatasetRefreshResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    body: DatasetRefreshRequest | None | Unset = UNSET,
) -> DatasetRefreshResponse | ProblemDetail | None:
    """Refresh Dataset

     Re-pull this dataset's data from the origin it was imported from.

    One request, no source pointer, no layer selection. The dataset keeps
    serving its current data throughout: the worker loads into an
    attempt-scoped staging table and swaps only once the new data is
    complete, so a refresh that fails leaves the live table and its freshness
    exactly as they were.

    A dataset registered from an existing PostGIS table takes the other
    execution strategy (#1265): its origin IS the table it serves from, so
    there is nothing to pull and nothing to swap, and the refresh re-measures
    the live relation instead — recounting features, recomputing the extent,
    and rebuilding the column schema snapshot and statistics. Admission, the
    run row and the history it writes are identical either way.

    Refuses with 409 ``dataset_busy`` while another refresh or re-upload is
    active for this dataset — v1 rejects rather than queues (Decision 5b), and
    the refusal comes from a partial unique index rather than a check, so two
    simultaneous clicks cannot both be admitted.

    Args:
        dataset_id (UUID):
        body (DatasetRefreshRequest | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DatasetRefreshResponse | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    body: DatasetRefreshRequest | None | Unset = UNSET,
) -> Response[DatasetRefreshResponse | ProblemDetail]:
    """Refresh Dataset

     Re-pull this dataset's data from the origin it was imported from.

    One request, no source pointer, no layer selection. The dataset keeps
    serving its current data throughout: the worker loads into an
    attempt-scoped staging table and swaps only once the new data is
    complete, so a refresh that fails leaves the live table and its freshness
    exactly as they were.

    A dataset registered from an existing PostGIS table takes the other
    execution strategy (#1265): its origin IS the table it serves from, so
    there is nothing to pull and nothing to swap, and the refresh re-measures
    the live relation instead — recounting features, recomputing the extent,
    and rebuilding the column schema snapshot and statistics. Admission, the
    run row and the history it writes are identical either way.

    Refuses with 409 ``dataset_busy`` while another refresh or re-upload is
    active for this dataset — v1 rejects rather than queues (Decision 5b), and
    the refusal comes from a partial unique index rather than a check, so two
    simultaneous clicks cannot both be admitted.

    Args:
        dataset_id (UUID):
        body (DatasetRefreshRequest | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DatasetRefreshResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    body: DatasetRefreshRequest | None | Unset = UNSET,
) -> DatasetRefreshResponse | ProblemDetail | None:
    """Refresh Dataset

     Re-pull this dataset's data from the origin it was imported from.

    One request, no source pointer, no layer selection. The dataset keeps
    serving its current data throughout: the worker loads into an
    attempt-scoped staging table and swaps only once the new data is
    complete, so a refresh that fails leaves the live table and its freshness
    exactly as they were.

    A dataset registered from an existing PostGIS table takes the other
    execution strategy (#1265): its origin IS the table it serves from, so
    there is nothing to pull and nothing to swap, and the refresh re-measures
    the live relation instead — recounting features, recomputing the extent,
    and rebuilding the column schema snapshot and statistics. Admission, the
    run row and the history it writes are identical either way.

    Refuses with 409 ``dataset_busy`` while another refresh or re-upload is
    active for this dataset — v1 rejects rather than queues (Decision 5b), and
    the refusal comes from a partial unique index rather than a check, so two
    simultaneous clicks cannot both be admitted.

    Args:
        dataset_id (UUID):
        body (DatasetRefreshRequest | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DatasetRefreshResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
            body=body,
        )
    ).parsed
