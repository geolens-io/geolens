"""SDK call helpers — Response → T translator + httpx-error → exit-code mapper.

Hand-maintained — NOT regenerated. Centralizes the SDK call boundary so each
command's body is free of error-mapping noise (CONTEXT.md D-32, D-33).

Note on httpx import: this module imports httpx ONLY for exception types
used in error mapping. The httpx instance comes from the SDK
(client.get_httpx_client()); the CLI never constructs an httpx.Client.
OCCLI-06 enforcement is on the dep list (cli/pyproject.toml has no httpx
direct dep — it's transitive via geolens-sdk). The `cli-lint` grep gate
in Plan 06 is scoped to `^(import|from) (httpx|requests)` lines that
construct clients; httpx exception imports here are explicitly allowed.
"""
from __future__ import annotations

from typing import Any, Callable, TypeVar

import typer

T = TypeVar("T")

# Exit codes per CONTEXT.md D-32
EXIT_OK = 0
EXIT_GENERIC = 1
EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_NETWORK = 4
EXIT_SERVER = 5


def unwrap(resp: Any, *, expected: int = 200) -> Any:
    """Translate an SDK Response into either parsed model or typer.Exit.

    Maps HTTP status to exit codes:
      expected (default 200) → return resp.parsed
      401, 403 → exit 3 (EXIT_AUTH)
      5xx      → exit 5 (EXIT_SERVER)
      other    → exit 1 (EXIT_GENERIC)
    """
    from geolens_sdk.models.problem_detail import ProblemDetail  # lazy

    sc = int(resp.status_code)
    if sc == expected:
        if isinstance(resp.parsed, ProblemDetail):
            typer.secho(f"Error: {resp.parsed.detail}", fg="red", err=True)
            raise typer.Exit(EXIT_SERVER if sc >= 500 else EXIT_GENERIC)
        return resp.parsed

    detail = ""
    if isinstance(resp.parsed, ProblemDetail):
        detail = f": {resp.parsed.detail}"

    if sc == 401:
        typer.secho(f"Authentication required{detail}. Run `geolens login` first.", fg="red", err=True)
        raise typer.Exit(EXIT_AUTH)
    if sc == 403:
        typer.secho(f"Permission denied{detail}", fg="red", err=True)
        raise typer.Exit(EXIT_AUTH)
    if 500 <= sc <= 599:
        typer.secho(f"Server error ({sc}){detail}", fg="red", err=True)
        raise typer.Exit(EXIT_SERVER)
    typer.secho(f"Request failed ({sc}){detail}", fg="red", err=True)
    raise typer.Exit(EXIT_GENERIC)


def call_sdk(fn: Callable[..., Any], **kwargs: Any) -> Any:
    """Run a sync_detailed call, mapping httpx exceptions to exit codes."""
    import httpx  # lazy — only for exception types

    try:
        return fn(**kwargs)
    except httpx.TimeoutException:
        typer.secho("Request timed out", fg="red", err=True)
        raise typer.Exit(EXIT_NETWORK)
    except httpx.NetworkError as exc:
        typer.secho(f"Network error: {exc}", fg="red", err=True)
        raise typer.Exit(EXIT_NETWORK)
