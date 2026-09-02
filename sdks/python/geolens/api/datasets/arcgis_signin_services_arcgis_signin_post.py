from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.arc_gis_sign_in_request import ArcGISSignInRequest
from ...models.arc_gis_sign_in_response import ArcGISSignInResponse
from ...models.problem_detail import ProblemDetail


def _get_kwargs(
    *,
    body: ArcGISSignInRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/services/arcgis/signin/",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ArcGISSignInResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = ArcGISSignInResponse.from_dict(response.json())

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

    if response.status_code == 502:
        response_502 = ProblemDetail.from_dict(response.json())

        return response_502

    if response.status_code == 503:
        response_503 = ProblemDetail.from_dict(response.json())

        return response_503

    if response.status_code == 504:
        response_504 = ProblemDetail.from_dict(response.json())

        return response_504

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[ArcGISSignInResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: ArcGISSignInRequest,
) -> Response[ArcGISSignInResponse | ProblemDetail]:
    """Arcgis Signin

     Sign in to an ArcGIS portal and return a short-lived token.

    Asks the portal's own token service for a token valid for 60 minutes and
    returns it. Put that token in the `token` field on probe, preview, commit
    and refresh; an import that runs longer than the token lives fails with a
    credential error and has to start over.

    An account that signs in through an identity provider, or that has
    multifactor authentication turned on, cannot use this. Paste a token or
    an API key instead. A portal on a private network is unreachable either
    way.

    Args:
        body (ArcGISSignInRequest): Portal address plus the credentials one generateToken call
            needs.

            No character policy on the two credential fields, deliberately. They are
            form-encoded into the outbound body, which percent-escapes every value,
            so neither a control character nor a separator can smuggle a second field
            into the request the way one can into a header line. The length bounds
            are here to keep an absurd body from reaching the portal at all.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ArcGISSignInResponse | ProblemDetail]
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
    body: ArcGISSignInRequest,
) -> ArcGISSignInResponse | ProblemDetail | None:
    """Arcgis Signin

     Sign in to an ArcGIS portal and return a short-lived token.

    Asks the portal's own token service for a token valid for 60 minutes and
    returns it. Put that token in the `token` field on probe, preview, commit
    and refresh; an import that runs longer than the token lives fails with a
    credential error and has to start over.

    An account that signs in through an identity provider, or that has
    multifactor authentication turned on, cannot use this. Paste a token or
    an API key instead. A portal on a private network is unreachable either
    way.

    Args:
        body (ArcGISSignInRequest): Portal address plus the credentials one generateToken call
            needs.

            No character policy on the two credential fields, deliberately. They are
            form-encoded into the outbound body, which percent-escapes every value,
            so neither a control character nor a separator can smuggle a second field
            into the request the way one can into a header line. The length bounds
            are here to keep an absurd body from reaching the portal at all.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ArcGISSignInResponse | ProblemDetail
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: ArcGISSignInRequest,
) -> Response[ArcGISSignInResponse | ProblemDetail]:
    """Arcgis Signin

     Sign in to an ArcGIS portal and return a short-lived token.

    Asks the portal's own token service for a token valid for 60 minutes and
    returns it. Put that token in the `token` field on probe, preview, commit
    and refresh; an import that runs longer than the token lives fails with a
    credential error and has to start over.

    An account that signs in through an identity provider, or that has
    multifactor authentication turned on, cannot use this. Paste a token or
    an API key instead. A portal on a private network is unreachable either
    way.

    Args:
        body (ArcGISSignInRequest): Portal address plus the credentials one generateToken call
            needs.

            No character policy on the two credential fields, deliberately. They are
            form-encoded into the outbound body, which percent-escapes every value,
            so neither a control character nor a separator can smuggle a second field
            into the request the way one can into a header line. The length bounds
            are here to keep an absurd body from reaching the portal at all.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ArcGISSignInResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: ArcGISSignInRequest,
) -> ArcGISSignInResponse | ProblemDetail | None:
    """Arcgis Signin

     Sign in to an ArcGIS portal and return a short-lived token.

    Asks the portal's own token service for a token valid for 60 minutes and
    returns it. Put that token in the `token` field on probe, preview, commit
    and refresh; an import that runs longer than the token lives fails with a
    credential error and has to start over.

    An account that signs in through an identity provider, or that has
    multifactor authentication turned on, cannot use this. Paste a token or
    an API key instead. A portal on a private network is unreachable either
    way.

    Args:
        body (ArcGISSignInRequest): Portal address plus the credentials one generateToken call
            needs.

            No character policy on the two credential fields, deliberately. They are
            form-encoded into the outbound body, which percent-escapes every value,
            so neither a control character nor a separator can smuggle a second field
            into the request the way one can into a header line. The length bounds
            are here to keep an absurd body from reaching the portal at all.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ArcGISSignInResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
