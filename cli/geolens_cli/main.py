"""GeoLens CLI entrypoint — Typer app + global options + AppState.

Hand-maintained — NOT regenerated. Subcommands are progressively populated
by Plans 02 (auth), 03 (scan), 04 (publish), 05 (export stac). This file
holds the global @app.callback() that builds AppState and the stub bodies
that downstream plans replace.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Optional

import typer

from . import output as _output

app = typer.Typer(no_args_is_help=True, rich_markup_mode="rich", help="GeoLens CLI")
export_app = typer.Typer(no_args_is_help=True, help="Export commands")
app.add_typer(export_app, name="export")


@dataclass
class AppState:
    """Shared state attached to typer.Context.obj.

    Plans 02-05 will use AppState.sdk() (see ctx.obj.sdk()) which is a
    thin lazy property added in Plan 02 once auth.py exists. For now the
    state carries only output/instance/json_mode/verbose so test_version
    and test_output can exercise the callback without auth.
    """
    output: _output.Formatter
    instance_override: Optional[str] = None
    json_mode: bool = False
    verbose: bool = False
    quiet: bool = False


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
    ctx.obj = AppState(
        output=fmt,
        instance_override=instance,
        json_mode=json_,
        verbose=verbose,
        quiet=quiet,
    )


# Stub subcommands so `geolens --help` lists them and exit-code tests can run
# before Plans 02-05 fill them in. Each raises Exit(2) (EXIT_USAGE) with
# "not yet implemented" — replaced atomically when its plan lands.

@app.command()
def login(
    ctx: typer.Context,
    instance_url: Annotated[str, typer.Argument(help="Instance URL")],
) -> None:
    """Log in to a GeoLens instance (stub — implemented in Plan 02)."""
    ctx.obj.output.error("login not yet implemented (Plan 02)")
    raise typer.Exit(2)


@app.command()
def logout(ctx: typer.Context) -> None:
    """Tear down credentials (stub — implemented in Plan 02)."""
    ctx.obj.output.error("logout not yet implemented (Plan 02)")
    raise typer.Exit(2)


@app.command()
def whoami(ctx: typer.Context) -> None:
    """Print current user/instance (stub — implemented in Plan 02)."""
    ctx.obj.output.error("whoami not yet implemented (Plan 02)")
    raise typer.Exit(2)


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
