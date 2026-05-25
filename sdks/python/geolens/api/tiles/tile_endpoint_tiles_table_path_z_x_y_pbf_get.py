from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...types import Unset


def _get_kwargs(
    table_path: str,
    z: int,
    x: int,
    y: int,
    *,
    sig: None | str | Unset = UNSET,
    exp: int | None | Unset = UNSET,
    scope: None | str | Unset = UNSET,
    cols: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_sig: None | str | Unset
    if isinstance(sig, Unset):
        json_sig = UNSET
    else:
        json_sig = sig
    params["sig"] = json_sig

    json_exp: int | None | Unset
    if isinstance(exp, Unset):
        json_exp = UNSET
    else:
        json_exp = exp
    params["exp"] = json_exp

    json_scope: None | str | Unset
    if isinstance(scope, Unset):
        json_scope = UNSET
    else:
        json_scope = scope
    params["scope"] = json_scope

    json_cols: None | str | Unset
    if isinstance(cols, Unset):
        json_cols = UNSET
    else:
        json_cols = cols
    params["cols"] = json_cols

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/tiles/{table_path}/{z}/{x}/{y}.pbf".format(
            table_path=quote(str(table_path), safe=""),
            z=quote(str(z), safe=""),
            x=quote(str(x), safe=""),
            y=quote(str(y), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = cast(Any, None)
        return response_200

    if response.status_code == 400:
        response_400 = ProblemDetail.from_dict(response.json())

        return response_400

    if response.status_code == 404:
        response_404 = ProblemDetail.from_dict(response.json())

        return response_404

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
) -> Response[Any | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    table_path: str,
    z: int,
    x: int,
    y: int,
    *,
    client: AuthenticatedClient | Client,
    sig: None | str | Unset = UNSET,
    exp: int | None | Unset = UNSET,
    scope: None | str | Unset = UNSET,
    cols: None | str | Unset = UNSET,
) -> Response[Any | ProblemDetail]:
    """Tile Endpoint

     Serve a vector tile as gzipped MVT binary.

    URL pattern: /tiles/data.{table_name}/{z}/{x}/{y}.pbf

    Non-public datasets require valid HMAC signature params (sig, exp, scope).
    Public datasets can be accessed without any signature.

    `cols` is a runtime opt-in for additional attribute columns the client
    needs at all zooms (e.g. data-driven styling columns referenced by
    MapLibre paint expressions). Format: comma-separated column names.
    Each name is validated against the dataset column list before it
    flows into the MVT projection; invalid names are silently dropped.
    Does not need to be signed — `sig` already authorizes dataset
    access and `cols` can only project columns the caller already has
    REST access to.

    Args:
        table_path (str):
        z (int):
        x (int):
        y (int):
        sig (None | str | Unset):
        exp (int | None | Unset):
        scope (None | str | Unset):
        cols (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        table_path=table_path,
        z=z,
        x=x,
        y=y,
        sig=sig,
        exp=exp,
        scope=scope,
        cols=cols,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    table_path: str,
    z: int,
    x: int,
    y: int,
    *,
    client: AuthenticatedClient | Client,
    sig: None | str | Unset = UNSET,
    exp: int | None | Unset = UNSET,
    scope: None | str | Unset = UNSET,
    cols: None | str | Unset = UNSET,
) -> Any | ProblemDetail | None:
    """Tile Endpoint

     Serve a vector tile as gzipped MVT binary.

    URL pattern: /tiles/data.{table_name}/{z}/{x}/{y}.pbf

    Non-public datasets require valid HMAC signature params (sig, exp, scope).
    Public datasets can be accessed without any signature.

    `cols` is a runtime opt-in for additional attribute columns the client
    needs at all zooms (e.g. data-driven styling columns referenced by
    MapLibre paint expressions). Format: comma-separated column names.
    Each name is validated against the dataset column list before it
    flows into the MVT projection; invalid names are silently dropped.
    Does not need to be signed — `sig` already authorizes dataset
    access and `cols` can only project columns the caller already has
    REST access to.

    Args:
        table_path (str):
        z (int):
        x (int):
        y (int):
        sig (None | str | Unset):
        exp (int | None | Unset):
        scope (None | str | Unset):
        cols (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return sync_detailed(
        table_path=table_path,
        z=z,
        x=x,
        y=y,
        client=client,
        sig=sig,
        exp=exp,
        scope=scope,
        cols=cols,
    ).parsed


async def asyncio_detailed(
    table_path: str,
    z: int,
    x: int,
    y: int,
    *,
    client: AuthenticatedClient | Client,
    sig: None | str | Unset = UNSET,
    exp: int | None | Unset = UNSET,
    scope: None | str | Unset = UNSET,
    cols: None | str | Unset = UNSET,
) -> Response[Any | ProblemDetail]:
    """Tile Endpoint

     Serve a vector tile as gzipped MVT binary.

    URL pattern: /tiles/data.{table_name}/{z}/{x}/{y}.pbf

    Non-public datasets require valid HMAC signature params (sig, exp, scope).
    Public datasets can be accessed without any signature.

    `cols` is a runtime opt-in for additional attribute columns the client
    needs at all zooms (e.g. data-driven styling columns referenced by
    MapLibre paint expressions). Format: comma-separated column names.
    Each name is validated against the dataset column list before it
    flows into the MVT projection; invalid names are silently dropped.
    Does not need to be signed — `sig` already authorizes dataset
    access and `cols` can only project columns the caller already has
    REST access to.

    Args:
        table_path (str):
        z (int):
        x (int):
        y (int):
        sig (None | str | Unset):
        exp (int | None | Unset):
        scope (None | str | Unset):
        cols (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        table_path=table_path,
        z=z,
        x=x,
        y=y,
        sig=sig,
        exp=exp,
        scope=scope,
        cols=cols,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    table_path: str,
    z: int,
    x: int,
    y: int,
    *,
    client: AuthenticatedClient | Client,
    sig: None | str | Unset = UNSET,
    exp: int | None | Unset = UNSET,
    scope: None | str | Unset = UNSET,
    cols: None | str | Unset = UNSET,
) -> Any | ProblemDetail | None:
    """Tile Endpoint

     Serve a vector tile as gzipped MVT binary.

    URL pattern: /tiles/data.{table_name}/{z}/{x}/{y}.pbf

    Non-public datasets require valid HMAC signature params (sig, exp, scope).
    Public datasets can be accessed without any signature.

    `cols` is a runtime opt-in for additional attribute columns the client
    needs at all zooms (e.g. data-driven styling columns referenced by
    MapLibre paint expressions). Format: comma-separated column names.
    Each name is validated against the dataset column list before it
    flows into the MVT projection; invalid names are silently dropped.
    Does not need to be signed — `sig` already authorizes dataset
    access and `cols` can only project columns the caller already has
    REST access to.

    Args:
        table_path (str):
        z (int):
        x (int):
        y (int):
        sig (None | str | Unset):
        exp (int | None | Unset):
        scope (None | str | Unset):
        cols (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return (
        await asyncio_detailed(
            table_path=table_path,
            z=z,
            x=x,
            y=y,
            client=client,
            sig=sig,
            exp=exp,
            scope=scope,
            cols=cols,
        )
    ).parsed
