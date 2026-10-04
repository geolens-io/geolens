from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...models.restore_previous_version_request import RestorePreviousVersionRequest
from ...models.restore_previous_version_response import RestorePreviousVersionResponse
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    *,
    body: RestorePreviousVersionRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/datasets/{dataset_id}/previous-version/restore".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ProblemDetail | RestorePreviousVersionResponse | None:
    if response.status_code == 202:
        response_202 = RestorePreviousVersionResponse.from_dict(response.json())

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
) -> Response[ProblemDetail | RestorePreviousVersionResponse]:
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
    body: RestorePreviousVersionRequest,
) -> Response[ProblemDetail | RestorePreviousVersionResponse]:
    """Restore Previous Version

     Publish the dataset's previous version as its live data again.

    The previous version is the data the last replacement or restore
    replaced. The restore runs as a job and a refresh run with origin kind
    ``restore``, and publishes a new version that names the restored one in
    ``restored_from_version``. The data it replaces, including any feature
    edits made since, becomes the previous version in turn. Scheduled
    refreshes of the dataset are held afterwards.

    Refuses with 422 ``restore_not_applicable`` for a dataset without a
    feature table, 404 ``no_previous_version`` when there is none, 409
    ``previous_version_changed`` when it is not ``expected_version_number``,
    and 409 ``dataset_busy`` while another refresh, replacement or restore is
    active.

    Args:
        dataset_id (UUID):
        body (RestorePreviousVersionRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | RestorePreviousVersionResponse]
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
    body: RestorePreviousVersionRequest,
) -> ProblemDetail | RestorePreviousVersionResponse | None:
    """Restore Previous Version

     Publish the dataset's previous version as its live data again.

    The previous version is the data the last replacement or restore
    replaced. The restore runs as a job and a refresh run with origin kind
    ``restore``, and publishes a new version that names the restored one in
    ``restored_from_version``. The data it replaces, including any feature
    edits made since, becomes the previous version in turn. Scheduled
    refreshes of the dataset are held afterwards.

    Refuses with 422 ``restore_not_applicable`` for a dataset without a
    feature table, 404 ``no_previous_version`` when there is none, 409
    ``previous_version_changed`` when it is not ``expected_version_number``,
    and 409 ``dataset_busy`` while another refresh, replacement or restore is
    active.

    Args:
        dataset_id (UUID):
        body (RestorePreviousVersionRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | RestorePreviousVersionResponse
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
    body: RestorePreviousVersionRequest,
) -> Response[ProblemDetail | RestorePreviousVersionResponse]:
    """Restore Previous Version

     Publish the dataset's previous version as its live data again.

    The previous version is the data the last replacement or restore
    replaced. The restore runs as a job and a refresh run with origin kind
    ``restore``, and publishes a new version that names the restored one in
    ``restored_from_version``. The data it replaces, including any feature
    edits made since, becomes the previous version in turn. Scheduled
    refreshes of the dataset are held afterwards.

    Refuses with 422 ``restore_not_applicable`` for a dataset without a
    feature table, 404 ``no_previous_version`` when there is none, 409
    ``previous_version_changed`` when it is not ``expected_version_number``,
    and 409 ``dataset_busy`` while another refresh, replacement or restore is
    active.

    Args:
        dataset_id (UUID):
        body (RestorePreviousVersionRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | RestorePreviousVersionResponse]
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
    body: RestorePreviousVersionRequest,
) -> ProblemDetail | RestorePreviousVersionResponse | None:
    """Restore Previous Version

     Publish the dataset's previous version as its live data again.

    The previous version is the data the last replacement or restore
    replaced. The restore runs as a job and a refresh run with origin kind
    ``restore``, and publishes a new version that names the restored one in
    ``restored_from_version``. The data it replaces, including any feature
    edits made since, becomes the previous version in turn. Scheduled
    refreshes of the dataset are held afterwards.

    Refuses with 422 ``restore_not_applicable`` for a dataset without a
    feature table, 404 ``no_previous_version`` when there is none, 409
    ``previous_version_changed`` when it is not ``expected_version_number``,
    and 409 ``dataset_busy`` while another refresh, replacement or restore is
    active.

    Args:
        dataset_id (UUID):
        body (RestorePreviousVersionRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | RestorePreviousVersionResponse
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
            body=body,
        )
    ).parsed
