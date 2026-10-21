from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.job_status_batch_request import JobStatusBatchRequest
from ...models.job_status_batch_response import JobStatusBatchResponse
from ...models.problem_detail import ProblemDetail


def _get_kwargs(
    *,
    body: JobStatusBatchRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/jobs/status/",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> JobStatusBatchResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = JobStatusBatchResponse.from_dict(response.json())

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
) -> Response[JobStatusBatchResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: JobStatusBatchRequest,
) -> Response[JobStatusBatchResponse | ProblemDetail]:
    """Get Job Statuses

     Get the status of up to 100 ingestion jobs in one request.

    Applies the same access rule as `GET /jobs/{id}`: the job creator, or a
    caller the effective permission policy lets read other users' jobs. An
    unknown id and a job the caller may not read both come back as
    `not_found`, so the response does not reveal which jobs exist.

    Args:
        body (JobStatusBatchRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[JobStatusBatchResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: JobStatusBatchRequest,
) -> JobStatusBatchResponse | ProblemDetail | None:
    """Get Job Statuses

     Get the status of up to 100 ingestion jobs in one request.

    Applies the same access rule as `GET /jobs/{id}`: the job creator, or a
    caller the effective permission policy lets read other users' jobs. An
    unknown id and a job the caller may not read both come back as
    `not_found`, so the response does not reveal which jobs exist.

    Args:
        body (JobStatusBatchRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        JobStatusBatchResponse | ProblemDetail
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: JobStatusBatchRequest,
) -> Response[JobStatusBatchResponse | ProblemDetail]:
    """Get Job Statuses

     Get the status of up to 100 ingestion jobs in one request.

    Applies the same access rule as `GET /jobs/{id}`: the job creator, or a
    caller the effective permission policy lets read other users' jobs. An
    unknown id and a job the caller may not read both come back as
    `not_found`, so the response does not reveal which jobs exist.

    Args:
        body (JobStatusBatchRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[JobStatusBatchResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: JobStatusBatchRequest,
) -> JobStatusBatchResponse | ProblemDetail | None:
    """Get Job Statuses

     Get the status of up to 100 ingestion jobs in one request.

    Applies the same access rule as `GET /jobs/{id}`: the job creator, or a
    caller the effective permission policy lets read other users' jobs. An
    unknown id and a job the caller may not read both come back as
    `not_found`, so the response does not reveal which jobs exist.

    Args:
        body (JobStatusBatchRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        JobStatusBatchResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
