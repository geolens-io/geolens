from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...models.upload_response import UploadResponse
from ...models.url_upload_request import UrlUploadRequest


def _get_kwargs(
    *,
    body: UrlUploadRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/ingest/upload/url",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ProblemDetail | UploadResponse | None:
    if response.status_code == 201:
        response_201 = UploadResponse.from_dict(response.json())

        return response_201

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

    if response.status_code == 413:
        response_413 = ProblemDetail.from_dict(response.json())

        return response_413

    if response.status_code == 422:
        response_422 = ProblemDetail.from_dict(response.json())

        return response_422

    if response.status_code == 429:
        response_429 = ProblemDetail.from_dict(response.json())

        return response_429

    if response.status_code == 500:
        response_500 = ProblemDetail.from_dict(response.json())

        return response_500

    if response.status_code == 502:
        response_502 = ProblemDetail.from_dict(response.json())

        return response_502

    if response.status_code == 503:
        response_503 = ProblemDetail.from_dict(response.json())

        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[ProblemDetail | UploadResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: UrlUploadRequest,
) -> Response[ProblemDetail | UploadResponse]:
    """Upload From Url

     Import a geospatial file from an HTTP(S) URL for staging.

    feat(#1705): the URL variant of ``POST /ingest/upload`` — NOT a new
    source type. The server fetches the file itself and the staged bytes
    enter the normal pipeline unchanged (preview → commit). Rule 2 posture:
    ``validate_url_for_ssrf`` gates the URL at submission, the download runs
    through ``make_safe_client()`` (connect-time IP pinning plus per-hop
    redirect revalidation), the size cap is enforced while streaming, the
    staged file passes the same extension allowlist and content sniff as a
    direct upload, and GDAL only ever sees the staged local file.

    Args:
        body (UrlUploadRequest): Request body for the URL variant of upload (feat #1705).

            The server fetches the file itself (SSRF-validated, size-capped) and
            stages it exactly like a direct upload — preview and commit take over
            unchanged.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | UploadResponse]
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
    body: UrlUploadRequest,
) -> ProblemDetail | UploadResponse | None:
    """Upload From Url

     Import a geospatial file from an HTTP(S) URL for staging.

    feat(#1705): the URL variant of ``POST /ingest/upload`` — NOT a new
    source type. The server fetches the file itself and the staged bytes
    enter the normal pipeline unchanged (preview → commit). Rule 2 posture:
    ``validate_url_for_ssrf`` gates the URL at submission, the download runs
    through ``make_safe_client()`` (connect-time IP pinning plus per-hop
    redirect revalidation), the size cap is enforced while streaming, the
    staged file passes the same extension allowlist and content sniff as a
    direct upload, and GDAL only ever sees the staged local file.

    Args:
        body (UrlUploadRequest): Request body for the URL variant of upload (feat #1705).

            The server fetches the file itself (SSRF-validated, size-capped) and
            stages it exactly like a direct upload — preview and commit take over
            unchanged.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | UploadResponse
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: UrlUploadRequest,
) -> Response[ProblemDetail | UploadResponse]:
    """Upload From Url

     Import a geospatial file from an HTTP(S) URL for staging.

    feat(#1705): the URL variant of ``POST /ingest/upload`` — NOT a new
    source type. The server fetches the file itself and the staged bytes
    enter the normal pipeline unchanged (preview → commit). Rule 2 posture:
    ``validate_url_for_ssrf`` gates the URL at submission, the download runs
    through ``make_safe_client()`` (connect-time IP pinning plus per-hop
    redirect revalidation), the size cap is enforced while streaming, the
    staged file passes the same extension allowlist and content sniff as a
    direct upload, and GDAL only ever sees the staged local file.

    Args:
        body (UrlUploadRequest): Request body for the URL variant of upload (feat #1705).

            The server fetches the file itself (SSRF-validated, size-capped) and
            stages it exactly like a direct upload — preview and commit take over
            unchanged.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | UploadResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: UrlUploadRequest,
) -> ProblemDetail | UploadResponse | None:
    """Upload From Url

     Import a geospatial file from an HTTP(S) URL for staging.

    feat(#1705): the URL variant of ``POST /ingest/upload`` — NOT a new
    source type. The server fetches the file itself and the staged bytes
    enter the normal pipeline unchanged (preview → commit). Rule 2 posture:
    ``validate_url_for_ssrf`` gates the URL at submission, the download runs
    through ``make_safe_client()`` (connect-time IP pinning plus per-hop
    redirect revalidation), the size cap is enforced while streaming, the
    staged file passes the same extension allowlist and content sniff as a
    direct upload, and GDAL only ever sees the staged local file.

    Args:
        body (UrlUploadRequest): Request body for the URL variant of upload (feat #1705).

            The server fetches the file itself (SSRF-validated, size-capped) and
            stages it exactly like a direct upload — preview and commit take over
            unchanged.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | UploadResponse
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
