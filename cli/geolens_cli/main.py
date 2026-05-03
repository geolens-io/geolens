# SPDX-License-Identifier: Apache-2.0
"""GeoLens CLI entrypoint — Typer app + global options + AppState.

Hand-maintained — NOT regenerated. Subcommands are progressively populated
by Plans 02 (auth), 03 (scan), 04 (publish), 05 (export stac). This file
holds the global @app.callback() that builds AppState and the stub bodies
that downstream plans replace.
"""
from __future__ import annotations

import getpass
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.table import Table

from . import auth as _auth
from . import config as _config
from . import export_stac as _export_stac
from . import output as _output
from . import publish as _publish
from . import scan as _scan
from ._sdk_helpers import EXIT_AUTH, EXIT_GENERIC, EXIT_USAGE, call_sdk, unwrap

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
        from geolens import GeolensClient

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
    from geolens import GeolensClient
    from geolens.api.auth import login_auth_login_post
    from geolens.models.body_login_auth_login_post import BodyLoginAuthLoginPost

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

    from geolens.api.auth import me_auth_me_get

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
    directory: Annotated[
        Path,
        typer.Argument(
            help="Directory to scan",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
        ),
    ],
    max_depth: Annotated[
        Optional[int],
        typer.Option("--max-depth", help="Cap recursion at N levels below root", min=0),
    ] = None,
    include_ext: Annotated[
        Optional[str],
        typer.Option(
            "--include-ext",
            help="Comma-separated extension allowlist, e.g. .gpkg,.tif",
        ),
    ] = None,
    json_local: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON array (overrides global --json setting)"),
    ] = False,
) -> None:
    """Walk a directory and report what would be ingested (no upload)."""
    state: AppState = ctx.obj
    include_exts: Optional[set[str]] = None
    if include_ext:
        include_exts = {e.strip().lower() for e in include_ext.split(",") if e.strip()}
        # Add the leading dot if missing.
        include_exts = {e if e.startswith(".") else f".{e}" for e in include_exts}

    items = list(_scan.walk(directory, max_depth=max_depth, include_exts=include_exts))

    json_mode = state.json_mode or json_local
    if json_mode:
        payload = [item.to_dict() for item in items]
        state.output.json(payload)
        return

    # Human-readable rich Table
    table = Table(title=f"Scan: {directory}")
    table.add_column("PATH", overflow="fold")
    table.add_column("FORMAT")
    table.add_column("INGEST?")
    for item in items:
        ingest_marker = "yes" if item.ingest else "no"
        if not item.ingest and item.reason:
            ingest_marker = f"no ({item.reason})"
        try:
            rel = item.path.relative_to(directory)
        except ValueError:
            rel = item.path
        table.add_row(str(rel), item.format, ingest_marker)

    # Use the Formatter's public stdout console so NO_COLOR / quiet are honored.
    # Direct rich.Console.print is fine for tables — Formatter.success is for messages.
    # Plan 01 exposes `console_stdout` as a public property; do NOT touch the
    # underscored `_stdout` attribute (private to Formatter).
    state.output.console_stdout.print(table)
    if not items:
        state.output.info("(no files found)")


@app.command()
def publish(
    ctx: typer.Context,
    file: Annotated[
        Path,
        typer.Argument(
            help="Spatial file to publish",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    name: Annotated[
        Optional[str],
        typer.Option("--name", help="Dataset name (default: filename stem)"),
    ] = None,
    description: Annotated[
        Optional[str],
        typer.Option("--description", help="Dataset description"),
    ] = None,
    tags: Annotated[
        Optional[str],
        typer.Option("--tags", help="Comma-separated keyword tags (currently a no-op; see docs/cli.md)"),
    ] = None,
    collection: Annotated[
        Optional[str],
        typer.Option("--collection", help="Add to this collection after commit (currently a no-op; see docs/cli.md)"),
    ] = None,
    wait: Annotated[
        bool,
        typer.Option("--wait/--no-wait", help="Wait for ingestion to resolve the dataset id"),
    ] = True,
) -> None:
    """Upload a vector or raster file and publish it as a dataset.

    Runs the 3-step ingest flow (upload → preview → commit) via the SDK.
    On success, prints the dataset URL bound by ROADMAP SC#4. With
    ``--wait`` (default), polls the job-status endpoint to resolve the
    dataset_id; ``--no-wait`` returns immediately with a job-search URL.

    Pitfall 6: commit is NOT idempotent. On a duplicate commit (job
    already processed), prints "already committed" and exits 1.
    """
    from rich.progress import Progress, SpinnerColumn, TextColumn

    state: AppState = ctx.obj
    instance = state.active_instance()
    if not instance:
        state.output.error("No instance configured. Run `geolens login <url>` first.")
        raise typer.Exit(EXIT_AUTH)

    sdk = state.sdk()
    title = name or file.stem

    # Deferred-flag warnings (Task 0 Q2 + Q5). These flags exist for forward
    # compatibility but currently no-op; the docs/cli.md note in Plan 06
    # captures the user-facing TODO.
    if tags:
        # TODO(OCCLI-deferred): tags requires a post-commit PATCH or a
        # `keywords` field on CommitRequest; see Phase 216 Open Question 4.
        state.output.debug(
            "tags deferred — CommitRequest does not expose a tags field; see Phase 216 Open Question 4",
        )
    if collection:
        # TODO(OCCLI-deferred): collection-add endpoint not in SDK; see
        # Phase 216 Open Question / CONTEXT.md Deferred Ideas.
        state.output.debug(
            "collection deferred — no add-to-collection endpoint in SDK; see Phase 216 Deferred Ideas",
        )

    # Lazy SDK imports — keeps `geolens --help` snappy.
    from geolens.api.datasets import (
        commit_import_ingest_commit_job_id_post as _commit,
        preview_file_ingest_preview_job_id_post as _preview,
    )

    progress_disabled = state.json_mode or not state.output.is_tty
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        disable=progress_disabled,
    )

    with progress:
        # Stage 1 — Upload (multipart workaround).
        t1 = progress.add_task("Uploading...", total=None)
        upload_resp = _publish.upload_file(sdk.client, file)
        upload = unwrap(upload_resp, expected=_publish.UPLOAD_OK_STATUS)
        job_id = getattr(upload, "job_id", None)
        if job_id is None:
            state.output.error("Upload did not return a job_id; cannot proceed.")
            raise typer.Exit(EXIT_GENERIC)
        progress.update(t1, description=f"Uploaded (job_id={job_id})")

        # Stage 2 — Preview.
        progress.add_task("Previewing...", total=None)
        preview_resp = call_sdk(_preview.sync_detailed, job_id=job_id, client=sdk.client)
        unwrap(preview_resp, expected=_publish.PREVIEW_OK_STATUS)

        # Stage 3 — Commit (NOT idempotent — Pitfall 6).
        progress.add_task("Committing...", total=None)
        commit_body = _publish.build_commit_request(title=title, description=description)
        commit_resp = call_sdk(
            _commit.sync_detailed,
            job_id=job_id,
            client=sdk.client,
            body=commit_body,
        )
        if _publish.is_duplicate_commit_response(commit_resp):
            _publish.handle_commit_already_processed(str(job_id), state.output)
        commit = unwrap(commit_resp, expected=_publish.COMMIT_OK_STATUS)

        # Stage 4 — Resolve dataset URL.
        progress.add_task("Resolving dataset...", total=None)
        dataset_id: Optional[str] = None
        if wait:
            dataset_id = _publish.resolve_dataset_id(sdk.client, job_id)

    dataset_url = _publish.construct_dataset_url(
        instance,
        dataset_id=dataset_id,
        job_id=str(job_id),
    )

    payload = {
        "dataset_url": dataset_url,
        "job_id": str(job_id),
        "dataset_id": str(dataset_id) if dataset_id else None,
        "status": getattr(commit, "status", None),
    }

    if state.json_mode:
        state.output.json(payload)
    else:
        state.output.success(f"Published: {dataset_url}")


@export_app.command("stac")
def export_stac(
    ctx: typer.Context,
    dataset_id: Annotated[str, typer.Argument(help="Dataset id")],
    output: Annotated[
        Optional[Path],
        typer.Option(
            "-o",
            "--output",
            help="Write STAC JSON to FILE (default: stdout)",
        ),
    ] = None,
    compact: Annotated[
        bool,
        typer.Option("--compact", help="Single-line JSON for piping to jq / curl --data"),
    ] = False,
) -> None:
    """Export STAC 1.1 metadata for a raster dataset.

    Pre-flight (D-26): GET /datasets/{id} — non-raster record_types are
    rejected with EXIT_USAGE (2) and a clear message before we ever touch
    /stac/items/{id}, so users see "STAC export is supported for raster
    datasets only" instead of a confusing 404 / 422.

    Output (D-27):
      * Default — pretty-printed JSON (indent=2, sorted keys, trailing
        newline) emitted to stdout.
      * ``-o FILE`` — atomic write (tempfile + os.replace) at mode 0o644.
      * ``--compact`` — single-line JSON suitable for piping into ``jq``
        or ``curl --data @-``.

    No client-side STAC validation (D-28) — the backend already produces
    conformant STAC 1.1.
    """
    state: AppState = ctx.obj
    sdk = state.sdk()

    # Pre-flight: verify the dataset is a raster.
    record_type = _export_stac.fetch_record_type(sdk.client, dataset_id)
    if record_type == "not_found":
        state.output.error(f"Dataset not found: {dataset_id}")
        raise typer.Exit(EXIT_GENERIC)
    if not _export_stac.is_raster(record_type):
        state.output.error(_export_stac.vector_rejection_message(record_type))
        raise typer.Exit(EXIT_USAGE)

    # Fetch the STAC item (caller pre-checked record_type).
    stac_item = _export_stac.fetch_stac_item(sdk.client, dataset_id)

    # Render & emit.
    if output is not None:
        _export_stac.write_stac_to_file(stac_item, output, compact=compact)
        state.output.success(f"Wrote STAC item to {output}")
    else:
        # Direct stdout — use typer.echo to bypass rich's line-wrapping on
        # long lines and to honor --compact's "no trailing newline" contract.
        typer.echo(
            _export_stac.render_stac_json(stac_item, compact=compact),
            nl=False,
        )
