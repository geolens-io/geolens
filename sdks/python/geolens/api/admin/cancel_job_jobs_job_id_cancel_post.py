from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.job_cancel_response import JobCancelResponse
from ...models.problem_detail import ProblemDetail
from uuid import UUID


def _get_kwargs(
    job_id: UUID,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/jobs/{job_id}/cancel".format(
            job_id=quote(str(job_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> JobCancelResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = JobCancelResponse.from_dict(response.json())

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
) -> Response[JobCancelResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    job_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[JobCancelResponse | ProblemDetail]:
    """Cancel Job

     Cancel a pending or running ingest job (imports, refreshes, and every
    other IngestJob-shaped run — feat(#1677)).

    The DB compare-and-swap here is the correctness mechanism: the job row
    (fenced on the attempt id read pre-CAS) and its bound refresh run flip to
    ``cancelled`` and COMMIT before anything touches the queue. A worker that
    never hears the abort still cannot install data afterwards, because every
    finalize site runs its fenced job update inside the swap transaction and
    ``require_ingest_job_update`` raises on the cancelled row, rolling the
    swap back. The Procrastinate ``abort=True`` request afterwards is
    best-effort acceleration only.

    Authorization: the job's creator, a holder of the cross-user job
    capability (same arm view/retry use), or — wider than retry, on purpose —
    anyone with write access to the job's dataset, so a dataset's owner can
    always unblock their own dataset from a run someone else started.

    Args:
        job_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[JobCancelResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        job_id=job_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    job_id: UUID,
    *,
    client: AuthenticatedClient,
) -> JobCancelResponse | ProblemDetail | None:
    """Cancel Job

     Cancel a pending or running ingest job (imports, refreshes, and every
    other IngestJob-shaped run — feat(#1677)).

    The DB compare-and-swap here is the correctness mechanism: the job row
    (fenced on the attempt id read pre-CAS) and its bound refresh run flip to
    ``cancelled`` and COMMIT before anything touches the queue. A worker that
    never hears the abort still cannot install data afterwards, because every
    finalize site runs its fenced job update inside the swap transaction and
    ``require_ingest_job_update`` raises on the cancelled row, rolling the
    swap back. The Procrastinate ``abort=True`` request afterwards is
    best-effort acceleration only.

    Authorization: the job's creator, a holder of the cross-user job
    capability (same arm view/retry use), or — wider than retry, on purpose —
    anyone with write access to the job's dataset, so a dataset's owner can
    always unblock their own dataset from a run someone else started.

    Args:
        job_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        JobCancelResponse | ProblemDetail
    """

    return sync_detailed(
        job_id=job_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    job_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[JobCancelResponse | ProblemDetail]:
    """Cancel Job

     Cancel a pending or running ingest job (imports, refreshes, and every
    other IngestJob-shaped run — feat(#1677)).

    The DB compare-and-swap here is the correctness mechanism: the job row
    (fenced on the attempt id read pre-CAS) and its bound refresh run flip to
    ``cancelled`` and COMMIT before anything touches the queue. A worker that
    never hears the abort still cannot install data afterwards, because every
    finalize site runs its fenced job update inside the swap transaction and
    ``require_ingest_job_update`` raises on the cancelled row, rolling the
    swap back. The Procrastinate ``abort=True`` request afterwards is
    best-effort acceleration only.

    Authorization: the job's creator, a holder of the cross-user job
    capability (same arm view/retry use), or — wider than retry, on purpose —
    anyone with write access to the job's dataset, so a dataset's owner can
    always unblock their own dataset from a run someone else started.

    Args:
        job_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[JobCancelResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        job_id=job_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    job_id: UUID,
    *,
    client: AuthenticatedClient,
) -> JobCancelResponse | ProblemDetail | None:
    """Cancel Job

     Cancel a pending or running ingest job (imports, refreshes, and every
    other IngestJob-shaped run — feat(#1677)).

    The DB compare-and-swap here is the correctness mechanism: the job row
    (fenced on the attempt id read pre-CAS) and its bound refresh run flip to
    ``cancelled`` and COMMIT before anything touches the queue. A worker that
    never hears the abort still cannot install data afterwards, because every
    finalize site runs its fenced job update inside the swap transaction and
    ``require_ingest_job_update`` raises on the cancelled row, rolling the
    swap back. The Procrastinate ``abort=True`` request afterwards is
    best-effort acceleration only.

    Authorization: the job's creator, a holder of the cross-user job
    capability (same arm view/retry use), or — wider than retry, on purpose —
    anyone with write access to the job's dataset, so a dataset's owner can
    always unblock their own dataset from a run someone else started.

    Args:
        job_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        JobCancelResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            job_id=job_id,
            client=client,
        )
    ).parsed
