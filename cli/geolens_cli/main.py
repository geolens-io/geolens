"""GeoLens CLI entrypoint — Typer app + global options + AppState.

Hand-maintained — NOT regenerated. Subcommands are progressively populated
by Plans 02 (auth), 03 (scan), 04 (publish), 05 (export stac). This file
holds the global @app.callback() that builds AppState and the stub bodies
that downstream plans replace.
"""
from __future__ import annotations

import getpass
from dataclasses import dataclass
from typing import Annotated, Optional

import typer

from . import auth as _auth
from . import config as _config
from . import output as _output
from ._sdk_helpers import EXIT_AUTH, call_sdk, unwrap

app = typer.Typer(no_args_is_help=True, rich_markup_mode="rich", help="GeoLens CLI")
export_app = typer.Typer(no_args_is_help=True, help="Export commands")
app.add_typer(export_app, name="export")


@dataclass
class AppState:
    """Shared state attached to typer.Context.obj.

    Plans 04 (publish) and 05 (export stac) consume AppState.sdk() to obtain
    a constructed GeolensClient using the highest-precedence credential
    available (CLI flag > GEOLENS_TOKEN env > credentials.toml > keyring per
    CONTEXT.md D-35).
    """
    output: _output.Formatter
    config: _config.AppConfig
    instance_override: Optional[str] = None
    json_mode: bool = False
    verbose: bool = False
    quiet: bool = False

    def active_instance(self) -> Optional[str]:
        """Return the instance to use, honoring D-35 precedence."""
        return (
            self.instance_override
            or _config.get_instance_from_env()
            or self.config.instance
        )

    def sdk(self):
        """Lazy-construct an authenticated SDK client for the active instance."""
        from geolens_sdk import GeolensClient

        instance = self.active_instance()
        if not instance:
            raise typer.BadParameter(
                "No instance configured. Run `geolens login <url>` first or pass --instance.",
            )
        bearer = _auth.load_bearer_token(instance)
        api_key = _auth.load_api_key(instance)
        if bearer:
            return GeolensClient(base_url=instance, bearer_token=bearer.value)
        if api_key:
            return GeolensClient(base_url=instance, api_key=api_key.value)
        return GeolensClient(base_url=instance)


def _version_callback(value: bool) -> None:
    if value:
        from importlib.metadata import PackageNotFoundError, version
        try:
            ver = version("geolens")
        except PackageNotFoundError:
            ver = "0.0.0+dev"
        typer.echo(f"geolens {ver}")
        raise typer.Exit()


@app.callback()
def root(
    ctx: typer.Context,
    json_: Annotated[bool, typer.Option("--json", help="Machine-readable JSON output")] = False,
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Debug logging to stderr")] = False,
    quiet: Annotated[bool, typer.Option("-q", "--quiet", help="Suppress non-error output")] = False,
    instance: Annotated[
        Optional[str],
        typer.Option("--instance", help="Override active instance for this command"),
    ] = None,
    version: Annotated[
        Optional[bool],
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit",
        ),
    ] = None,
) -> None:
    """GeoLens CLI."""
    fmt = _output.Formatter(json_mode=json_, quiet=quiet, verbose=verbose)
    cfg = _config.load_config()
    ctx.obj = AppState(
        output=fmt,
        config=cfg,
        instance_override=instance,
        json_mode=json_,
        verbose=verbose,
        quiet=quiet,
    )


@app.command()
def login(
    ctx: typer.Context,
    instance_url: Annotated[str, typer.Argument(help="Instance URL, e.g. https://geolens.example.com")],
    token: Annotated[Optional[str], typer.Option("--token", help="Skip prompt; store this JWT directly")] = None,
    api_key: Annotated[Optional[str], typer.Option("--api-key", help="Skip prompt; store as API key")] = None,
    no_keyring: Annotated[bool, typer.Option("--no-keyring", help="Use credentials.toml instead of OS keyring")] = False,
) -> None:
    """Log in to a GeoLens instance and store credentials."""
    state: AppState = ctx.obj

    try:
        instance = _config.normalize_instance_url(instance_url)
    except ValueError as exc:
        state.output.error(str(exc))
        raise typer.Exit(2)

    if token and api_key:
        state.output.error("--token and --api-key are mutually exclusive")
        raise typer.Exit(2)

    if api_key:
        backend = _auth.store_api_key(instance, api_key, no_keyring=no_keyring)
        _config.write_default_instance(instance, username=None)
        state.output.success(f"Stored API key for {instance} ({backend})")
        return

    if token:
        backend = _auth.store_bearer_token(instance, token, no_keyring=no_keyring)
        _config.write_default_instance(instance, username=None)
        state.output.success(f"Stored bearer token for {instance} ({backend})")
        return

    # Interactive flow (D-08)
    from geolens_sdk import GeolensClient
    from geolens_sdk.api.auth import login_auth_login_post
    from geolens_sdk.models.body_login_auth_login_post import BodyLoginAuthLoginPost

    username = typer.prompt("Username")
    password = getpass.getpass("Password: ")
    sdk = GeolensClient(base_url=instance)
    body = BodyLoginAuthLoginPost(username=username, password=password)
    resp = call_sdk(login_auth_login_post.sync_detailed, client=sdk.client, body=body)
    token_response = unwrap(resp, expected=200)
    access_token = token_response.access_token
    backend = _auth.store_bearer_token(instance, access_token, no_keyring=no_keyring)
    refresh_token = getattr(token_response, "refresh_token", None)
    if refresh_token:
        _auth.store_refresh_token(instance, refresh_token, no_keyring=no_keyring)
    _config.write_default_instance(instance, username=username)
    state.output.success(f"Logged in to {instance} as {username} ({backend})")


@app.command()
def logout(ctx: typer.Context) -> None:
    """Tear down credentials for the active instance."""
    state: AppState = ctx.obj
    instance = state.active_instance()
    if not instance:
        state.output.error("No active instance — nothing to log out from.")
        raise typer.Exit(2)
    _auth.delete_credentials(instance)
    # Also clear config.toml so a stale instance URL doesn't linger.
    try:
        _config.config_path().unlink()
    except FileNotFoundError:
        pass
    state.output.success(f"Logged out of {instance}")


@app.command()
def whoami(ctx: typer.Context) -> None:
    """Print the current user/instance (calls /auth/me; refresh-retries once on 401)."""
    state: AppState = ctx.obj
    instance = state.active_instance()
    if not instance:
        state.output.error("No active instance. Run `geolens login <url>` first.")
        raise typer.Exit(EXIT_AUTH)

    from geolens_sdk.api.auth import me_auth_me_get

    sdk = state.sdk()
    resp = call_sdk(me_auth_me_get.sync_detailed, client=sdk.client)
    if int(resp.status_code) == 401:
        # D-13: refresh-retry once
        new_access = _auth.try_refresh(instance)
        if not new_access:
            state.output.error("Session expired — run `geolens login` again")
            raise typer.Exit(EXIT_AUTH)
        sdk = state.sdk()  # re-construct with the rotated token
        resp = call_sdk(me_auth_me_get.sync_detailed, client=sdk.client)
    user = unwrap(resp, expected=200)
    email = getattr(user, "email", None) or getattr(user, "username", None) or "<unknown>"
    if state.json_mode:
        payload = {
            "instance": instance,
            "email": email,
            "id": getattr(user, "id", None),
            "role": getattr(user, "role", None),
        }
        state.output.json(payload)
    else:
        state.output.success(f"{email} @ {instance}")


# Stub subcommands so `geolens --help` lists them and exit-code tests can run
# before Plans 03-05 fill them in. Each raises Exit(2) (EXIT_USAGE) with
# "not yet implemented" — replaced atomically when its plan lands.

@app.command()
def scan(
    ctx: typer.Context,
    directory: Annotated[str, typer.Argument(help="Directory to scan")],
) -> None:
    """Walk a directory and report what would be ingested (stub — Plan 03)."""
    ctx.obj.output.error("scan not yet implemented (Plan 03)")
    raise typer.Exit(2)


@app.command()
def publish(
    ctx: typer.Context,
    file: Annotated[str, typer.Argument(help="File to publish")],
) -> None:
    """Publish a vector or raster file (stub — Plan 04)."""
    ctx.obj.output.error("publish not yet implemented (Plan 04)")
    raise typer.Exit(2)


@export_app.command("stac")
def export_stac(
    ctx: typer.Context,
    dataset_id: Annotated[str, typer.Argument(help="Dataset id")],
) -> None:
    """Export STAC 1.1 metadata for a raster dataset (stub — Plan 05)."""
    ctx.obj.output.error("export stac not yet implemented (Plan 05)")
    raise typer.Exit(2)
