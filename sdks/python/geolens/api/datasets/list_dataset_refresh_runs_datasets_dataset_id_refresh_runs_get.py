from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.dataset_refresh_run_list_response import DatasetRefreshRunListResponse
from ...models.problem_detail import ProblemDetail
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    *,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["skip"] = skip

    params["limit"] = limit

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/datasets/{dataset_id}/refresh-runs".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> DatasetRefreshRunListResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = DatasetRefreshRunListResponse.from_dict(response.json())

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
) -> Response[DatasetRefreshRunListResponse | ProblemDetail]:
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
    skip: int | Unset = 0,
    limit: int | Unset = 50,
) -> Response[DatasetRefreshRunListResponse | ProblemDetail]:
    """List Dataset Refresh Runs

     Refresh history for a dataset: every attempt, including the failures.

    Durable across the `ingest_jobs` retention purge — that purge is why this
    table exists rather than the jobs table serving as the record (#1219).

    Access follows Rule 1 on the read path, and ADR-002 Decision 4e adds field
    redaction on top: a caller who is neither the dataset owner nor an admin
    sees the timeline and outcomes but not who triggered each run, nor the
    failure text, nor the schema diff. Without that, a PUBLIC dataset's
    history enumerates its editors and leaks origin detail through error
    strings. The redaction is tested against a NAMED signed-in third party as
    well as an anonymous reader; a requester-scoped check that only exercises
    the anonymous case reads as complete and is not.

    The owner-or-admin predicate (`can_view_dataset_provenance`) was extracted
    to `authorization.py` under #1316, which applies the same rule to dataset
    reads and `/versions/` — this endpoint's redaction is no longer the odd
    one out among the three.

    Args:
        dataset_id (UUID):
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DatasetRefreshRunListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        skip=skip,
        limit=limit,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
) -> DatasetRefreshRunListResponse | ProblemDetail | None:
    """List Dataset Refresh Runs

     Refresh history for a dataset: every attempt, including the failures.

    Durable across the `ingest_jobs` retention purge — that purge is why this
    table exists rather than the jobs table serving as the record (#1219).

    Access follows Rule 1 on the read path, and ADR-002 Decision 4e adds field
    redaction on top: a caller who is neither the dataset owner nor an admin
    sees the timeline and outcomes but not who triggered each run, nor the
    failure text, nor the schema diff. Without that, a PUBLIC dataset's
    history enumerates its editors and leaks origin detail through error
    strings. The redaction is tested against a NAMED signed-in third party as
    well as an anonymous reader; a requester-scoped check that only exercises
    the anonymous case reads as complete and is not.

    The owner-or-admin predicate (`can_view_dataset_provenance`) was extracted
    to `authorization.py` under #1316, which applies the same rule to dataset
    reads and `/versions/` — this endpoint's redaction is no longer the odd
    one out among the three.

    Args:
        dataset_id (UUID):
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DatasetRefreshRunListResponse | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        client=client,
        skip=skip,
        limit=limit,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
) -> Response[DatasetRefreshRunListResponse | ProblemDetail]:
    """List Dataset Refresh Runs

     Refresh history for a dataset: every attempt, including the failures.

    Durable across the `ingest_jobs` retention purge — that purge is why this
    table exists rather than the jobs table serving as the record (#1219).

    Access follows Rule 1 on the read path, and ADR-002 Decision 4e adds field
    redaction on top: a caller who is neither the dataset owner nor an admin
    sees the timeline and outcomes but not who triggered each run, nor the
    failure text, nor the schema diff. Without that, a PUBLIC dataset's
    history enumerates its editors and leaks origin detail through error
    strings. The redaction is tested against a NAMED signed-in third party as
    well as an anonymous reader; a requester-scoped check that only exercises
    the anonymous case reads as complete and is not.

    The owner-or-admin predicate (`can_view_dataset_provenance`) was extracted
    to `authorization.py` under #1316, which applies the same rule to dataset
    reads and `/versions/` — this endpoint's redaction is no longer the odd
    one out among the three.

    Args:
        dataset_id (UUID):
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DatasetRefreshRunListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        skip=skip,
        limit=limit,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 50,
) -> DatasetRefreshRunListResponse | ProblemDetail | None:
    """List Dataset Refresh Runs

     Refresh history for a dataset: every attempt, including the failures.

    Durable across the `ingest_jobs` retention purge — that purge is why this
    table exists rather than the jobs table serving as the record (#1219).

    Access follows Rule 1 on the read path, and ADR-002 Decision 4e adds field
    redaction on top: a caller who is neither the dataset owner nor an admin
    sees the timeline and outcomes but not who triggered each run, nor the
    failure text, nor the schema diff. Without that, a PUBLIC dataset's
    history enumerates its editors and leaks origin detail through error
    strings. The redaction is tested against a NAMED signed-in third party as
    well as an anonymous reader; a requester-scoped check that only exercises
    the anonymous case reads as complete and is not.

    The owner-or-admin predicate (`can_view_dataset_provenance`) was extracted
    to `authorization.py` under #1316, which applies the same rule to dataset
    reads and `/versions/` — this endpoint's redaction is no longer the odd
    one out among the three.

    Args:
        dataset_id (UUID):
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DatasetRefreshRunListResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
            skip=skip,
            limit=limit,
        )
    ).parsed
