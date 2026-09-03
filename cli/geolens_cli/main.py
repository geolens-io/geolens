# SPDX-License-Identifier: Apache-2.0
"""GeoLens CLI entrypoint — Typer app + global options + AppState.

Hand-maintained — NOT regenerated. Subcommands are progressively populated
by Plans 02 (auth), 03 (scan), 04 (publish), 05 (export stac). This file
holds the global @app.callback() that builds AppState and the stub bodies
that downstream plans replace.
"""

from __future__ import annotations

import getpass
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Optional

import typer
from rich.table import Table

from . import analysis as _analysis
from . import auth as _auth
from . import config as _config
from . import export_stac as _export_stac
from . import manifest_apply as _manifest_apply
from . import output as _output
from . import publish as _publish
from . import refresh as _refresh
from . import replace as _replace
from . import scan as _scan
from ._sdk_helpers import (
    EXIT_AUTH,
    EXIT_GENERIC,
    EXIT_NETWORK,
    EXIT_USAGE,
    call_sdk,
    call_sdk_with_reauth,
    make_client,
    unwrap,
)

app = typer.Typer(no_args_is_help=True, rich_markup_mode="rich", help="GeoLens CLI")
export_app = typer.Typer(no_args_is_help=True, help="Export commands")
app.add_typer(export_app, name="export")
analysis_app = typer.Typer(no_args_is_help=True, help="Analysis commands")
app.add_typer(analysis_app, name="analysis")


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
        """Return the instance to use, honoring D-35 precedence.

        BUG-033: the --instance override and GEOLENS_INSTANCE env value are
        canonicalized through the SAME normalizer login uses, so a
        trailing-slash or missing-/api variant resolves to the identical
        stored credential key. config.instance is already canonical (login
        normalized it before storing) so it is returned as-is.
        """
        raw = self.instance_override or _config.get_instance_from_env()
        if raw:
            try:
                return _config.normalize_instance_url(raw)
            except ValueError:
                # Malformed override (e.g. bad scheme): pass it through
                # verbatim as before so downstream login/sdk surface the
                # original validation/connection error rather than this
                # resolver swallowing it.
                return raw
        return self.config.instance

    def sdk(self):
        """Lazy-construct an authenticated SDK client for the active instance."""
        instance = self.active_instance()
        if not instance:
            raise typer.BadParameter(
                "No instance configured. Run `geolens login <url>` first or pass --instance.",
            )
        bearer = _auth.load_bearer_token(instance)
        api_key = _auth.load_api_key(instance)
        # fix(#1778, #1787): make_client() binds every request to
        # DEFAULT_HTTP_TIMEOUT_SECONDS — the SDK's generated transport
        # otherwise carries timeout=None (unbounded), so every command
        # would hang forever against a black-holed host instead of
        # exiting EXIT_NETWORK. Commands that poll (publish --wait,
        # analysis materialize --wait) bound each individual request
        # further still — see publish.resolve_dataset_id.
        if bearer:
            return make_client(instance, bearer_token=bearer.value)
        if api_key:
            return make_client(instance, api_key=api_key.value)
        return make_client(instance)


def _version_callback(value: bool) -> None:
    if value:
        from importlib.metadata import PackageNotFoundError, version

        try:
            # BUG-031: the CLI's own distribution is `geolens-cli`; `geolens`
            # is the SDK dependency whose version may diverge at install time.
            ver = version("geolens-cli")
        except PackageNotFoundError:
            ver = "0.0.0+dev"
        typer.echo(f"geolens {ver}")
        raise typer.Exit()


@app.callback()
def root(
    ctx: typer.Context,
    json_: Annotated[
        bool, typer.Option("--json", help="Machine-readable JSON output")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("-v", "--verbose", help="Debug logging to stderr")
    ] = False,
    quiet: Annotated[
        bool, typer.Option("-q", "--quiet", help="Suppress non-error output")
    ] = False,
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
def init(
    ctx: typer.Context,
    path: Annotated[
        Path,
        typer.Argument(help="Manifest path to create"),
    ] = Path("geolens.yaml"),
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing manifest"),
    ] = False,
) -> None:
    """Create a starter geolens.yaml manifest."""
    from .manifest.template import write_minimal_manifest

    state: AppState = ctx.obj
    try:
        created = write_minimal_manifest(path, force=force)
    except FileExistsError:
        state.output.error(
            f"Manifest already exists: {path}. Use --force to overwrite."
        )
        raise typer.Exit(EXIT_USAGE)
    except OSError as exc:
        state.output.error(f"Could not create manifest at {path}: {exc}")
        raise typer.Exit(EXIT_USAGE)

    state.output.success(f"Created manifest: {created}")


@app.command()
def validate(
    ctx: typer.Context,
    path: Annotated[
        Path,
        typer.Argument(help="Manifest path to validate"),
    ] = Path("geolens.yaml"),
) -> None:
    """Validate a geolens.yaml manifest without contacting an API."""
    from .manifest.reporting import (
        format_validation_error_lines,
        validation_report_payload,
    )
    from .manifest.schema import load_manifest, validate_manifest

    state: AppState = ctx.obj
    try:
        document = load_manifest(path)
    except ValueError as exc:
        if state.json_mode:
            state.output.json(
                {
                    "error": str(exc),
                    "ok": False,
                    "path": str(path),
                }
            )
        else:
            state.output.error(f"{path}: {exc}")
        raise typer.Exit(EXIT_USAGE)

    errors = validate_manifest(document)
    if not errors:
        if state.json_mode:
            state.output.json(validation_report_payload(path, errors))
        else:
            state.output.success(f"Manifest valid: {path}")
        return

    if state.json_mode:
        state.output.json(validation_report_payload(path, errors))
    else:
        for line in format_validation_error_lines(path, errors):
            state.output.error(line)
    raise typer.Exit(EXIT_USAGE)


@app.command("schema")
def print_manifest_schema(
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Write the versioned manifest JSON Schema to a file",
        ),
    ] = None,
) -> None:
    """Print the packaged geolens.yaml JSON Schema without contacting an API."""
    from .manifest.schema import manifest_schema

    rendered = json.dumps(manifest_schema(), indent=2, sort_keys=True) + "\n"
    if output is None:
        typer.echo(rendered, nl=False)
        return
    try:
        output.write_text(rendered, encoding="utf-8")
    except OSError as exc:
        raise typer.BadParameter(f"Could not write schema to {output}: {exc}") from exc
    typer.echo(str(output))


@app.command("apply")
def apply_manifest_command(
    ctx: typer.Context,
    path: Annotated[
        Path,
        typer.Argument(help="Manifest path to apply"),
    ] = Path("geolens.yaml"),
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview backend apply outcomes without writes"),
    ] = False,
) -> None:
    """Apply a geolens.yaml manifest through the configured GeoLens API.

    NOTE: apply only POSTs the manifest document — it does NOT upload local
    data files. Manifest sources must reference data the server can already
    reach (http(s)/s3/gs/az/abfs URIs, or files pre-staged server-side). To
    publish a LOCAL file, use `geolens publish <file>` instead. apply errors
    early (GAP-020) if any source URI is a local path.
    """
    from .manifest.reporting import (
        format_validation_error_lines,
        validation_report_payload,
    )
    from .manifest.schema import load_manifest, validate_manifest

    state: AppState = ctx.obj
    try:
        document = load_manifest(path)
    except ValueError as exc:
        if state.json_mode:
            state.output.json(
                {
                    "error": str(exc),
                    "ok": False,
                    "path": str(path),
                }
            )
        else:
            state.output.error(f"{path}: {exc}")
        raise typer.Exit(EXIT_USAGE)

    errors = validate_manifest(document)
    if errors:
        if state.json_mode:
            state.output.json(validation_report_payload(path, errors))
        else:
            for line in format_validation_error_lines(path, errors):
                state.output.error(line)
        raise typer.Exit(EXIT_USAGE)

    # GAP-020: `apply` POSTs the manifest JSON; the SERVER resolves scheme-less
    # source URIs against its OWN upload-staging dir (an operator pre-populates it,
    # or `publish` does). That server-staging round-trip is a documented, supported
    # flow — so apply must NOT block on local sources. We only WARN (humans get it
    # on stderr; --json stays silent so automation isn't broken): if the server's
    # staging can't actually see the file the source will skip/404 server-side, and
    # `geolens publish <file>` is the way to push a CLI-local file.
    local_uris = _manifest_apply.find_local_source_uris(document)
    if local_uris:
        sample = ", ".join(local_uris[:5])
        if len(local_uris) > 5:
            sample += f", … (+{len(local_uris) - 5} more)"
        state.output.warn(
            f"{len(local_uris)} manifest source(s) reference local files ({sample}). "
            "`apply` does not upload them — the server resolves scheme-less paths from "
            "its own staging dir. If it can't see them, run `geolens publish <file>` "
            "first or use a remote URL (http(s)/s3/gs/az/abfs)."
        )

    sdk = state.sdk()
    payload = _manifest_apply.build_apply_payload(document, dry_run=dry_run)
    try:
        response = _manifest_apply.post_manifest_apply(sdk.client, payload)
    except _manifest_apply.ManifestApplyRequestError as exc:
        state.output.error(exc.message)
        raise typer.Exit(exc.exit_code)

    report = _manifest_apply.apply_report_payload(path, response)
    if state.json_mode:
        state.output.json(report)
    else:
        _manifest_apply.render_apply_summary(
            state.output.console_stdout,
            path,
            response,
        )

    if not response.get("accepted", False):
        state.output.error("Manifest apply response had accepted=false.")
        raise typer.Exit(EXIT_GENERIC)
    if _manifest_apply.has_apply_errors(response):
        raise typer.Exit(EXIT_GENERIC)


def _read_secret_from_stdin() -> str:
    """Read a secret from stdin (strips trailing newline/whitespace).

    Supports piping: echo $TOKEN | geolens login <url> --token -
    """
    import sys

    return sys.stdin.readline().rstrip("\r\n")


@app.command()
def login(
    ctx: typer.Context,
    instance_url: Annotated[
        str, typer.Argument(help="Instance URL, e.g. https://geolens.example.com")
    ],
    token: Annotated[
        Optional[str],
        typer.Option(
            "--token",
            help=(
                "Skip prompt; store this JWT directly. "
                "Pass '-' to read from stdin (e.g. echo $TOKEN | geolens login <url> --token -). "
                "Prefer the GEOLENS_TOKEN env var for non-interactive use."
            ),
        ),
    ] = None,
    api_key: Annotated[
        Optional[str],
        typer.Option(
            "--api-key",
            help=("Skip prompt; store as API key. Pass '-' to read from stdin."),
        ),
    ] = None,
    no_keyring: Annotated[
        bool,
        typer.Option("--no-keyring", help="Use credentials.toml instead of OS keyring"),
    ] = False,
) -> None:
    """Log in to a GeoLens instance and store credentials.

    Secrets can be passed on the command line (--token <value>) or read
    from stdin by passing the special value '-' (--token -). The preferred
    non-interactive approach is the GEOLENS_TOKEN environment variable,
    which avoids the secret appearing in argv or shell history.
    """
    state: AppState = ctx.obj

    try:
        instance = _config.normalize_instance_url(instance_url)
    except ValueError as exc:
        state.output.error(str(exc))
        raise typer.Exit(2)

    if token and api_key:
        state.output.error("--token and --api-key are mutually exclusive")
        raise typer.Exit(2)

    # SEC-016: '-' sentinel reads the secret from stdin so it does not appear
    # in argv or shell history.
    if token == "-":
        token = _read_secret_from_stdin()
    if api_key == "-":
        api_key = _read_secret_from_stdin()

    if api_key:
        # fix(#1778): AppState.sdk() prefers a stored bearer token over an
        # API key (main.py's own D-35 precedence), so a stale JWT (or a
        # leftover GEOLENS_TOKEN env var) left over from an earlier login
        # silently outranked the API key this call just stored — every
        # command then used the old credential with no error. Evict the
        # other credential types for this instance first so the one just
        # stored is the only one that can be resolved.
        #
        # fix(#1778 review round 4): replace_credentials() stores the new
        # credential BEFORE evicting the others — see its docstring
        # (auth.py) for why deleting first left a user logged out on a
        # storage failure. Never call delete_credentials() directly from
        # login (tests/test_client_construction.py's sibling structural
        # gate — see test_login_atomic_swap.py — checks this file for it).
        try:
            backend = _auth.replace_credentials(
                instance, "api_key", api_key, no_keyring=no_keyring
            )
        except Exception as exc:
            state.output.error(f"Could not store the API key: {exc}")
            raise typer.Exit(EXIT_GENERIC) from exc
        _config.write_default_instance(instance, username=None)
        state.output.success(f"Stored API key for {instance} ({backend})")
        return

    if token:
        try:
            backend = _auth.replace_credentials(
                instance, "bearer", token, no_keyring=no_keyring
            )
        except Exception as exc:
            state.output.error(f"Could not store the bearer token: {exc}")
            raise typer.Exit(EXIT_GENERIC) from exc
        _config.write_default_instance(instance, username=None)
        state.output.success(f"Stored bearer token for {instance} ({backend})")
        return

    # Interactive flow (D-08)
    from geolens.api.auth import login_auth_login_post
    from geolens.models.body_login_auth_login_post import BodyLoginAuthLoginPost

    username = typer.prompt("Username")
    password = getpass.getpass("Password: ")
    # fix(#1778 review round 2): this used to build its own GeolensClient
    # directly with the SDK's default timeout=None (unbounded), so
    # `geolens login` could still hang on a host that accepts a
    # connection and then stalls, despite the bound added elsewhere in
    # this PR. make_client() is the single construction point for every
    # GeolensClient in this package (see _sdk_helpers.make_client).
    sdk = make_client(instance)
    body = BodyLoginAuthLoginPost(username=username, password=password)
    resp = call_sdk(login_auth_login_post.sync_detailed, client=sdk.client, body=body)
    token_response = unwrap(resp, expected=200)
    access_token = token_response.access_token
    try:
        backend = _auth.replace_credentials(
            instance, "bearer", access_token, no_keyring=no_keyring
        )
    except Exception as exc:
        state.output.error(f"Could not store the bearer token: {exc}")
        raise typer.Exit(EXIT_GENERIC) from exc
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
    # BUG-032: only clear config.toml when we are logging out of the DEFAULT
    # instance it stores. With a --instance / GEOLENS_INSTANCE override active,
    # the resolved instance may differ from config.instance — unlinking then
    # would wipe the unrelated default-instance configuration the user is
    # still logged into.
    if instance == state.config.instance:
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

    # D-13: refresh-retries once on 401 via the shared helper — see
    # _sdk_helpers.call_sdk_with_reauth (fix(#1778): this used to be
    # open-coded here only, so every other command hard-failed instead of
    # spending a stored refresh token).
    sdk = state.sdk()
    resp = call_sdk_with_reauth(
        me_auth_me_get.sync_detailed,
        instance=instance,
        credential_kind=sdk.credential_kind,
        client=sdk.client,
    )
    user = unwrap(resp, expected=200)
    email = (
        getattr(user, "email", None) or getattr(user, "username", None) or "<unknown>"
    )
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


@app.command()
def status(
    ctx: typer.Context,
    dataset_id: Annotated[
        str,
        typer.Argument(help="Dataset UUID"),
    ],
) -> None:
    """Show a dataset's catalog and source status."""
    state: AppState = ctx.obj
    try:
        from uuid import UUID

        dataset_uuid = UUID(dataset_id)
    except ValueError as exc:
        raise typer.BadParameter(
            "Dataset id must be a UUID", param_hint="dataset_id"
        ) from exc

    sdk = state.sdk()
    # fix(#1778): refresh-retry once on 401 (D-13) rather than hard-
    # failing a scripted `status` check on an access token that expired
    # since login.
    dataset = _refresh.fetch_dataset_status(
        sdk.client,
        dataset_uuid,
        instance=state.active_instance(),
        credential_kind=sdk.credential_kind,
    )
    payload = _refresh.dataset_status_payload(dataset)
    if state.json_mode:
        state.output.json(payload)
    elif not state.quiet:
        _refresh.render_dataset_status(state.output.console_stdout, payload)


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
        typer.Option(
            "--json", help="Emit JSON array (overrides global --json setting)"
        ),
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
        typer.Option(
            "--tags",
            help="Comma-separated keywords added to the dataset after commit (requires --wait)",
        ),
    ] = None,
    collection: Annotated[
        Optional[str],
        typer.Option(
            "--collection",
            help="Collection id or exact name to add the dataset to after commit (requires --wait)",
        ),
    ] = None,
    wait: Annotated[
        bool,
        typer.Option(
            "--wait/--no-wait", help="Wait for ingestion to resolve the dataset id"
        ),
    ] = True,
) -> None:
    """Upload a vector or raster file and publish it as a dataset.

    Runs the 3-step ingest flow (upload → preview → commit) via the SDK.
    On success, prints the dataset URL bound by ROADMAP SC#4. With
    ``--wait`` (default), polls the job-status endpoint to resolve the
    dataset_id; ``--no-wait`` returns immediately with a job-search URL.

    fix(#1778): with ``--wait``, a job that fails, is cancelled, or does not
    finish within the poll window exits non-zero and prints a failure line
    instead of "Published:"; ``--json`` carries the terminal status. A job
    that fanned out into one import per layer is a success (exit 0), not a
    failure — ``--json`` status is ``"fanned_out"`` and no single dataset id
    is printed.

    Pitfall 6: commit is NOT idempotent. On a duplicate commit (job
    already processed), prints "already committed" and exits 1.
    """
    from rich.progress import Progress, SpinnerColumn, TextColumn

    state: AppState = ctx.obj
    instance = state.active_instance()
    if not instance:
        state.output.error("No instance configured. Run `geolens login <url>` first.")
        raise typer.Exit(EXIT_AUTH)

    # fix(#569): --tags / --collection are wired post-commit, which needs the
    # resolved dataset id — fail fast instead of silently dropping them.
    if (tags or collection) and not wait:
        state.output.error(
            "--tags/--collection require --wait (the dataset id is resolved by waiting)"
        )
        raise typer.Exit(EXIT_USAGE)

    sdk = state.sdk()
    title = name or file.stem

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
        # BUG-034: route through call_sdk so a network failure during the
        # upload (the longest, most failure-prone stage) maps to EXIT_NETWORK
        # (4) per D-32 instead of dumping a raw httpx traceback and exiting 1.
        t1 = progress.add_task("Uploading...", total=None)
        upload_resp = call_sdk(_publish.upload_file, client=sdk.client, path=file)
        upload = unwrap(upload_resp, expected=_publish.UPLOAD_OK_STATUS)
        job_id = getattr(upload, "job_id", None)
        if job_id is None:
            state.output.error("Upload did not return a job_id; cannot proceed.")
            raise typer.Exit(EXIT_GENERIC)
        progress.update(t1, description=f"Uploaded (job_id={job_id})")

        # Stage 2: Preview.
        progress.add_task("Previewing...", total=None)
        preview_resp = call_sdk(
            _preview.sync_detailed, job_id=job_id, client=sdk.client
        )
        unwrap(preview_resp, expected=_publish.PREVIEW_OK_STATUS)

        # Stage 3 — Commit (NOT idempotent — Pitfall 6).
        progress.add_task("Committing...", total=None)
        commit_body = _publish.build_commit_request(
            title=title, description=description
        )
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
        publish_status: Optional[str] = None
        publish_stopped_because: Optional[str] = None
        publish_failure: Optional[str] = None
        publish_message: Optional[str] = None
        publish_exit_code = EXIT_GENERIC
        publish_extras_skipped: list[str] = []
        wait_outcome_known = False
        if wait:
            outcome = _publish.resolve_dataset_id(sdk.client, job_id)
            dataset_id = outcome.dataset_id
            late_status: Optional[str] = None
            if dataset_id is None and outcome.stopped_because in (
                "timeout",
                "poll_failed",
            ):
                # fix(#1778, codex round 3): resolve_dataset_id now reports
                # WHY it stopped (outcome.stopped_because) instead of
                # collapsing every reason into None, so the wording below no
                # longer has to be guessed from a second, possibly-
                # contradictory read — a transient poll failure followed by a
                # lucky pending/running re-read used to be reported as a
                # false "still running after 120s" timeout. This extra read
                # is skipped for "terminal" (a terminal status cannot later
                # gain a dataset_id) and "token_expired" (retrying the same
                # dead token is pointless).
                #
                # fix(#1778, codex round 5): sdk.client's generated transport
                # defaults to timeout=None (unbounded), so a stalled
                # connection on THIS read would hang the command forever
                # instead of reporting the outcome the poll already reached.
                # Bind it to a short, named bound; if that ALSO times out,
                # treat this one-shot diagnostic read as unreadable rather
                # than letting the network error abort the command outright
                # — the original outcome is still worth reporting.
                #
                # fix(#1778, codex round 6): `client.with_timeout()` MUTATES
                # the already-constructed httpx transport in place before
                # returning an "evolved" wrapper (sdks/python/geolens/
                # client.py) — the evolved wrapper is a decoy; sdk.client's
                # OWN transport keeps the 5s bound for the rest of the
                # command's lifetime. Stage 5 (extras) reuses sdk.client, so
                # that mutation silently capped every tags/collection
                # request at 5s too. get_httpx_client() is the SDK's own
                # public escape hatch (OCCLI-06, used the same way by
                # upload_file() above); save its timeout, bound it for this
                # one read, and restore it unconditionally.
                snapshot_transport = sdk.client.get_httpx_client()
                original_timeout = snapshot_transport.timeout
                snapshot_transport.timeout = (
                    _publish._SNAPSHOT_REQUEST_TIMEOUT_SECONDS
                )
                try:
                    late_status, late_dataset_id = _analysis.job_snapshot(
                        sdk.client, job_id
                    )
                except typer.Exit as exc:
                    if exc.exit_code != EXIT_NETWORK:
                        raise
                    late_status, late_dataset_id = None, None
                finally:
                    snapshot_transport.timeout = original_timeout
                if late_dataset_id:
                    dataset_id = late_dataset_id
            if dataset_id is None:
                wait_outcome_known = True
                # fix(#1778, codex round 4): the job can finish between
                # resolve_dataset_id's last look and now (fix(#685 review)),
                # but it can just as well have reached a DEFINITIVE terminal
                # status by then — failed, cancelled, or fanned out. That is
                # real information the original poll didn't have and must
                # win over the stale timeout/poll_failed wording; only a
                # pending/running (or unreadable) snapshot leaves the job's
                # fate genuinely unresolved, so only THAT keeps the original
                # outcome's wording.
                if late_status in _publish._TERMINAL_NO_DATASET_STATUSES:
                    effective_status = late_status
                    reason = "terminal"
                else:
                    effective_status = outcome.status
                    reason = outcome.stopped_because
                publish_status = effective_status
                publish_stopped_because = reason
                if reason == "terminal" and effective_status == "failed":
                    publish_failure = (
                        f"Publish job {job_id} failed. Its error is on the "
                        f"job record: GET /jobs/{job_id}."
                    )
                elif reason == "terminal" and effective_status == "cancelled":
                    publish_failure = (
                        f"Publish job {job_id} was cancelled. "
                        f"Check GET /jobs/{job_id}."
                    )
                elif reason == "terminal" and effective_status == "fanned_out":
                    # fanned_out is TERMINAL and a SUCCESS, not a timeout —
                    # the parent job of a multi-layer commit lands here the
                    # moment each layer's own import is queued
                    # (commit_fan_out, backend/app/processing/ingest/
                    # router.py), and never gets a dataset_id of its own.
                    publish_message = (
                        f"Publish job {job_id} fanned out into one import "
                        f"per layer; each layer is importing as its own "
                        f"dataset. Check GET /jobs/{job_id} or the datasets "
                        f"list for progress."
                    )
                    # fix(#1778, codex round 9): a note appended only to
                    # publish_message was cosmetic — extras_failures stayed
                    # empty, so Stage 5 below never ran and the command
                    # exited 0 even though --tags/--collection were
                    # requested and never applied. --json showed
                    # extras_failures: [] too, telling automation nothing
                    # was skipped. Recording the omission as an extras
                    # failure instead routes it through the existing
                    # extras-failure path: non-zero exit, and present in
                    # the --json payload, same as any other partial
                    # publish failure.
                    if tags:
                        publish_extras_skipped.append(
                            "tags not applied: job fanned out into "
                            "per-layer datasets"
                        )
                    if collection:
                        publish_extras_skipped.append(
                            "collection not applied: job fanned out into "
                            "per-layer datasets"
                        )
                elif reason == "terminal":
                    # A future terminal status this CLI has no specific
                    # wording for yet.
                    publish_failure = (
                        f"Publish job {job_id} reached status "
                        f"{effective_status!r}, which will not produce a "
                        f"dataset. Check GET /jobs/{job_id}."
                    )
                elif reason == "token_expired":
                    publish_exit_code = EXIT_AUTH
                    publish_failure = (
                        f"Authentication failed while reading job {job_id}'s "
                        f"status. Run `geolens login` first."
                    )
                elif reason == "poll_failed":
                    # fix(#1778, codex round 7): a poll_failed outcome
                    # collapsed EVERY non-200 into the same generic exit
                    # code, hiding a 5xx server outage from a script that
                    # checks the exit code — match the same status matrix
                    # unwrap() already uses elsewhere in this CLI.
                    publish_exit_code = _publish.poll_failed_exit_code(
                        outcome.http_status
                    )
                    publish_failure = (
                        f"Publish job {job_id}'s status could not be read "
                        f"({outcome.detail}). Check GET /jobs/{job_id}."
                    )
                else:  # "timeout"
                    publish_failure = (
                        f"Publish job {job_id} was still {effective_status} "
                        f"after {int(_publish._DEFAULT_POLL_TIMEOUT_SECONDS)}s "
                        f"and has not finished. Check GET /jobs/{job_id}."
                    )

        # Stage 5 — fix(#569): apply --tags / --collection now that the
        # dataset id exists. Failures here are PARTIAL: the dataset was
        # created, so report honestly and exit non-zero below.
        #
        # fix(#1778): when dataset_id is still None here, wait was True (a
        # bare --no-wait with tags/collection already exits EXIT_USAGE above)
        # and publish_failure or publish_message is already set, explaining
        # why. Tags/collection were never attempted against a dataset that
        # does not exist (or does not exist as a single id, for fanned_out),
        # so skip the API call — but fix(#1778, codex round 9):
        # publish_extras_skipped still carries one entry per requested
        # extra when fanned_out is the reason, so the omission still counts
        # as an extras failure below instead of silently exiting 0.
        extras_failures: list[str] = []
        if (tags or collection) and dataset_id is not None:
            progress.add_task("Applying tags/collection...", total=None)
            extras_failures = _publish.apply_publish_extras(
                sdk.client, dataset_id, tags, collection
            )
        elif publish_extras_skipped:
            extras_failures = publish_extras_skipped

    dataset_url = _publish.construct_dataset_url(
        instance,
        dataset_id=dataset_id,
        job_id=str(job_id),
    )

    commit_status = getattr(commit, "status", None)
    payload = {
        "dataset_url": dataset_url,
        "job_id": str(job_id),
        "dataset_id": str(dataset_id) if dataset_id else None,
        "status": publish_status if wait_outcome_known else commit_status,
        "stopped_because": publish_stopped_because,
    }
    if tags or collection:
        payload["extras_failures"] = extras_failures

    if state.json_mode:
        state.output.json(payload)
    else:
        if publish_failure:
            state.output.error(publish_failure)
        elif publish_message:
            state.output.success(publish_message)
        else:
            state.output.success(f"Published: {dataset_url}")
        for failure in extras_failures:
            state.output.warn(f"Dataset created, but: {failure}")
    if publish_failure or extras_failures:
        raise typer.Exit(publish_exit_code if publish_failure else EXIT_GENERIC)


@app.command()
def refresh(
    ctx: typer.Context,
    dataset_id: Annotated[str, typer.Argument(help="Dataset UUID")],
    token: Annotated[
        Optional[str],
        typer.Option(
            "--token",
            prompt="Service token",
            prompt_required=False,
            hide_input=True,
            help=(
                "Transient protected-service token. Pass --token with no value "
                "for a hidden prompt; an explicit value may be visible in shell history."
            ),
        ),
    ] = None,
    wait: Annotated[
        bool,
        typer.Option("--wait/--no-wait", help="Wait for the refresh job to finish"),
    ] = False,
    timeout: Annotated[
        Optional[float],
        typer.Option(
            "--timeout",
            help=(
                "Seconds to wait before giving up (only with --wait; default: "
                "until the job finishes)"
            ),
        ),
    ] = None,
) -> None:
    """Re-pull a dataset from its server-stored source binding.

    Queue time has no upper bound, so ``--wait`` follows the job to a terminal
    state by default. Pass ``--timeout`` when automation needs a finite bound.
    """
    state: AppState = ctx.obj
    try:
        from uuid import UUID

        dataset_uuid = UUID(dataset_id)
    except ValueError as exc:
        raise typer.BadParameter(
            "Dataset id must be a UUID", param_hint="dataset_id"
        ) from exc
    if timeout is not None and (timeout <= 0 or not math.isfinite(timeout)):
        state.output.error("--timeout must be a finite number greater than 0")
        raise typer.Exit(EXIT_USAGE)
    if not wait and timeout is not None:
        state.output.error("--timeout requires --wait")
        raise typer.Exit(EXIT_USAGE)
    if token == "":
        state.output.error("Service token must not be empty")
        raise typer.Exit(EXIT_USAGE)

    sdk = state.sdk()
    try:
        accepted = _refresh.start_refresh(sdk.client, dataset_uuid, token)
    except _refresh.RefreshRequestError as exc:
        state.output.error(exc.message)
        raise typer.Exit(exc.exit_code)

    poll = None
    if wait:
        poll = _refresh.wait_for_refresh(
            sdk.client,
            accepted.job_id,
            token=token,
            timeout=timeout,
        )

    payload = _refresh.refresh_payload(accepted, poll)
    if state.json_mode:
        state.output.json(payload)
    elif poll is None:
        state.output.success(
            f"Refresh queued for dataset {payload['dataset_id']} "
            f"(job {payload['job_id']}, run {payload['run_id']}; "
            f"origin={payload['origin_kind']}, trigger={payload['trigger']}, "
            f"status={payload['status']})"
        )
        state.output.info(str(payload["message"]))
    elif poll.succeeded:
        state.output.success(
            f"Refresh complete for dataset {payload['dataset_id']} "
            f"(job {payload['job_id']}, run {payload['run_id']})"
        )
    else:
        message = poll.error_message or f"Refresh job ended with status {poll.status}."
        state.output.error(message)

    if poll is not None and not poll.succeeded:
        raise typer.Exit(EXIT_GENERIC)


@app.command()
def replace(
    ctx: typer.Context,
    dataset_id: Annotated[str, typer.Argument(help="Dataset UUID")],
    file: Annotated[
        Path,
        typer.Argument(
            help="Replacement spatial file",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    layer: Annotated[
        Optional[str],
        typer.Option(
            "--layer",
            help=(
                "Layer to commit. Required when the file has more than one "
                "layer; the CLI refuses to commit an unnamed default."
            ),
        ),
    ] = None,
    srid: Annotated[
        Optional[int],
        typer.Option("--srid", help="Override the detected SRID"),
    ] = None,
    wait: Annotated[
        bool,
        typer.Option("--wait/--no-wait", help="Wait for the replace job to finish"),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes", "-y", help="Skip the confirmation prompt (required with --json)"
        ),
    ] = False,
) -> None:
    """Replace this dataset's data from a file.

    Runs the same upload, preview, commit flow ``publish`` uses, pointed at
    the dataset's reupload endpoints instead of the ingest ones. Prints the
    preview (layer, feature count, detected SRID) before committing and
    prompts for confirmation unless ``--yes`` is passed. ``--json`` is a
    scripting mode and never prompts, so it requires ``--yes``.

    A dataset whose data comes from a server-stored source binding rather
    than a file cannot be replaced this way; use ``geolens refresh``
    instead. A file with more than one layer requires ``--layer``; the CLI
    refuses to commit an unnamed default rather than silently picking the
    first one.
    """
    from uuid import UUID

    state: AppState = ctx.obj
    try:
        dataset_uuid = UUID(dataset_id)
    except ValueError as exc:
        raise typer.BadParameter(
            "Dataset id must be a UUID", param_hint="dataset_id"
        ) from exc

    # fix(#1767 review): --json is a non-interactive scripting mode, so an
    # interactive confirm prompt inside it is the wrong contract (Click's
    # confirm() writes part of the exchange to stdout regardless of
    # err=True, which corrupts the JSON payload). Refuse before any network
    # call rather than prompting.
    if state.json_mode and not yes:
        state.output.error("--json requires --yes to confirm a replace.")
        raise typer.Exit(EXIT_USAGE)

    sdk = state.sdk()

    from geolens.api.datasets_reupload import (
        reupload_commit_datasets_dataset_id_reupload_job_id_commit_post as _rcommit,
        reupload_preview_datasets_dataset_id_reupload_job_id_preview_post as _rpreview,
    )

    try:
        # Stage 0: fetch the dataset so origin and record_type gate the flow
        # before any upload request reaches the server.
        dataset_resp = _replace.fetch_dataset(sdk.client, dataset_uuid)
        dataset = _replace.unwrap_or_raise(
            dataset_resp, expected=_replace.GET_DATASET_OK_STATUS
        )

        refusal = _replace.origin_refusal_message(getattr(dataset, "origin", None))
        if refusal is not None:
            state.output.error(refusal)
            raise typer.Exit(EXIT_GENERIC)

        is_raster = _replace.is_raster_dataset(dataset)
        if is_raster and layer is not None:
            state.output.error("--layer does not apply to raster datasets.")
            raise typer.Exit(EXIT_USAGE)

        # Stage 1: Upload (multipart workaround).
        # fix(#1739): route through call_sdk so a network failure during
        # upload maps to EXIT_NETWORK instead of a raw traceback.
        upload_resp = call_sdk(
            _replace.upload_file, client=sdk.client, dataset_id=dataset_uuid, path=file
        )
        upload = _replace.unwrap_or_raise(upload_resp, expected=_replace.UPLOAD_OK_STATUS)
        job_id = upload.job_id

        if is_raster:
            # Raster datasets have no schema to preview (router_reupload.py);
            # the supported flow is upload then commit with nothing between.
            state.output.info("Raster dataset: committing without preview.")
            summary: dict[str, Any] = {
                "layer_name": None,
                "feature_count": None,
                "srid": None,
                "geometry_type": None,
            }
        else:
            # Stage 2: Preview.
            preview_resp = call_sdk(
                _rpreview.sync_detailed,
                dataset_id=dataset_uuid,
                job_id=job_id,
                client=sdk.client,
                body=_replace.build_preview_request(layer),
            )
            preview = _replace.unwrap_or_raise(
                preview_resp, expected=_replace.PREVIEW_OK_STATUS
            )

            layers = _replace.layer_summaries(preview)
            if layers and layer is None:
                state.output.error(_replace.multi_layer_refusal_message(layers))
                raise typer.Exit(EXIT_USAGE)

            summary = _replace.preview_summary(preview)
            state.output.info(
                f"Layer '{summary['layer_name']}': {summary['feature_count']} "
                f"features, SRID {summary['srid'] if summary['srid'] is not None else 'unknown'}"
            )

        if not yes and not typer.confirm(
            f"Replace dataset {dataset_uuid}'s data with {file}?", err=True
        ):
            state.output.error("Replace cancelled; no changes were made.")
            raise typer.Exit(EXIT_GENERIC)

        # Stage 3: Commit.
        commit_resp = call_sdk(
            _rcommit.sync_detailed,
            dataset_id=dataset_uuid,
            job_id=job_id,
            client=sdk.client,
            body=_replace.build_commit_request(layer_name=layer, srid_override=srid),
        )
        commit = _replace.unwrap_or_raise(commit_resp, expected=_replace.COMMIT_OK_STATUS)
    except _replace.ReplaceRequestError as exc:
        state.output.error(exc.message)
        raise typer.Exit(exc.exit_code)

    payload: dict[str, Any] = {
        "job_id": str(job_id),
        "dataset_id": str(dataset_uuid),
        "preview": summary,
        "status": getattr(commit, "status", None),
    }

    if not wait:
        if state.json_mode:
            state.output.json(payload)
        else:
            state.output.success(f"Replace queued for dataset {dataset_uuid} (job {job_id})")
        return

    poll = _refresh.wait_for_refresh(sdk.client, job_id)
    payload["status"] = poll.status
    if poll.error_message:
        payload["error_message"] = poll.error_message

    if state.json_mode:
        state.output.json(payload)
    elif poll.succeeded:
        state.output.success(
            f"Replace complete for dataset {dataset_uuid} (job {job_id})"
        )
    else:
        state.output.error(
            poll.error_message or f"Replace job ended with status {poll.status}."
        )

    if not poll.succeeded:
        raise typer.Exit(EXIT_GENERIC)


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
        typer.Option(
            "--compact", help="Single-line JSON for piping to jq / curl --data"
        ),
    ] = False,
) -> None:
    """Export STAC API 1.0 metadata for a raster dataset.

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
    conformant STAC API 1.0.
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


@analysis_app.command("preview")
def analysis_preview(
    ctx: typer.Context,
    dataset_id: Annotated[str, typer.Argument(help="Source dataset id")],
    operation: Annotated[
        str,
        typer.Option(
            "--operation",
            help=(
                "buffer, centroid, clip, spatial_join, measure, "
                "select_by_location or intersect (the server rejects anything "
                "else; dissolve is materialize-only)"
            ),
        ),
    ],
    distance: Annotated[
        Optional[float],
        typer.Option("--distance", help="Buffer distance in METRES (buffer only)"),
    ] = None,
    mask_dataset: Annotated[
        Optional[str],
        typer.Option(
            "--mask-dataset",
            help=(
                "Polygon dataset id supplying the second layer (clip and "
                "select_by_location; required for intersect)"
            ),
        ),
    ] = None,
    join_dataset_id: Annotated[
        Optional[str],
        typer.Option(
            "--join-dataset-id",
            help="Dataset id to join against (spatial_join only; required for it)",
        ),
    ] = None,
    join_fields: Annotated[
        Optional[str],
        typer.Option(
            "--join-fields",
            help=(
                "Comma-separated columns to copy from the matched join "
                "feature, prefixed 'join_' in the output (spatial_join only)"
            ),
        ),
    ] = None,
    compact: Annotated[
        bool,
        typer.Option("--compact", help="Single-line JSON for piping to jq"),
    ] = False,
) -> None:
    """Run an analysis operation and print the resulting GeoJSON.

    Nothing is created: the preview is computed and returned, capped at the
    server's preview limit. The cap is announced on stderr so stdout stays a
    valid GeoJSON document you can redirect straight into a file.
    """
    state: AppState = ctx.obj
    # fix(#685 review): without this, state.sdk() raises BadParameter and the
    # missing instance exits 2 (usage) while the sibling materialize command
    # exits 3 (auth) for the identical condition.
    if not state.active_instance():
        state.output.error("No instance configured. Run `geolens login <url>` first.")
        raise typer.Exit(EXIT_AUTH)
    sdk = state.sdk()

    try:
        request = _analysis.build_preview_request(
            operation,
            distance_meters=distance,
            mask_dataset_id=mask_dataset,
            join_dataset_id=join_dataset_id,
            join_fields=join_fields,
        )
    except ValueError as exc:
        state.output.error(str(exc))
        raise typer.Exit(EXIT_USAGE) from exc

    response = _analysis.run_preview(sdk.client, dataset_id, request)

    warning = _analysis.truncation_warning(response)
    if warning:
        state.output.warn(warning)

    typer.echo(
        _analysis.render_geojson(_analysis.preview_geojson(response), compact=compact),
        nl=False,
    )


@analysis_app.command("materialize")
def analysis_materialize(
    ctx: typer.Context,
    dataset_id: Annotated[str, typer.Argument(help="Source dataset id")],
    operation: Annotated[
        str,
        typer.Option(
            "--operation",
            help=(
                "buffer, centroid, clip, dissolve, spatial_join, measure, "
                "select_by_location or intersect (the server rejects anything "
                "else)"
            ),
        ),
    ],
    title: Annotated[
        str, typer.Option("--title", help="Title for the dataset that will be created")
    ],
    distance: Annotated[
        Optional[float],
        typer.Option("--distance", help="Buffer distance in METRES (buffer only)"),
    ] = None,
    mask_dataset: Annotated[
        Optional[str],
        typer.Option(
            "--mask-dataset",
            help=(
                "Polygon dataset id supplying the second layer (clip and "
                "select_by_location; required for intersect)"
            ),
        ),
    ] = None,
    by_field: Annotated[
        Optional[str],
        typer.Option("--by-field", help="Group-by column (dissolve only)"),
    ] = None,
    join_dataset_id: Annotated[
        Optional[str],
        typer.Option(
            "--join-dataset-id",
            help="Dataset id to join against (spatial_join only; required for it)",
        ),
    ] = None,
    join_fields: Annotated[
        Optional[str],
        typer.Option(
            "--join-fields",
            help=(
                "Comma-separated columns to copy from the matched join "
                "feature, prefixed 'join_' in the output (spatial_join only)"
            ),
        ),
    ] = None,
    wait: Annotated[
        bool,
        typer.Option("--wait/--no-wait", help="Poll the job until the dataset exists"),
    ] = True,
    timeout: Annotated[
        Optional[float],
        typer.Option(
            "--timeout",
            help=(
                "Seconds to wait before giving up (default: until the job "
                "finishes, however long it queues)"
            ),
        ),
    ] = None,
) -> None:
    """Run an analysis operation over the whole dataset and save the result.

    The work is queued, and analysis is queued BELOW uploads on purpose, so a
    healthy job can wait behind a busy instance's backlog with no upper bound.
    ``--wait`` (the default) therefore waits for the job to finish rather than
    for a fixed number of seconds; pass ``--timeout`` to bound it, or Ctrl+C.
    """
    state: AppState = ctx.obj
    instance = state.active_instance()
    if not instance:
        state.output.error("No instance configured. Run `geolens login <url>` first.")
        raise typer.Exit(EXIT_AUTH)
    # fix(#685 review): `timeout or POLL_FOREVER` read an explicit 0 as "no
    # bound", the opposite of what it asks for. A zero or negative wait is a
    # usage error — --no-wait is the way to not wait.
    # `inf` and overflowing literals like 1e309 parse as a real float, so a
    # bound the caller asked for would silently become no bound at all.
    if timeout is not None and (timeout <= 0 or not math.isfinite(timeout)):
        state.output.error(
            "--timeout must be a finite number greater than 0; "
            "use --no-wait to skip waiting."
        )
        raise typer.Exit(EXIT_USAGE)
    sdk = state.sdk()

    try:
        request = _analysis.build_materialize_request(
            operation,
            title,
            distance_meters=distance,
            mask_dataset_id=mask_dataset,
            by_field=by_field,
            join_dataset_id=join_dataset_id,
            join_fields=join_fields,
        )
    except ValueError as exc:
        state.output.error(str(exc))
        raise typer.Exit(EXIT_USAGE) from exc

    response = _analysis.run_materialize(sdk.client, dataset_id, request)
    job_id = str(getattr(response, "job_id", "") or "")

    if not wait:
        # Nothing was polled, so there is no dataset to name yet — report the
        # job id rather than a URL for a dataset that may not exist.
        if state.output.json_mode:
            state.output.json({"job_id": job_id, "dataset_id": None, "url": None})
        else:
            state.output.success(f"Analysis job queued: {job_id}")
        return

    # fix(#685 review): the deadline below is only checked BETWEEN polls, so a
    # request that stalls after connecting would outlive the bound the caller
    # asked for. The SDK builds its httpx client with timeout=None (no limit at
    # all, not httpx's 5s default), so give the polling client the same bound.
    # A float rather than an httpx.Timeout because OCCLI-06 forbids importing
    # httpx here; httpx accepts either.
    poll_client = sdk.client if timeout is None else sdk.client.with_timeout(timeout)
    outcome = _publish.resolve_dataset_id(
        poll_client,
        job_id,
        timeout=_analysis.POLL_FOREVER if timeout is None else timeout,
    )
    resolved = outcome.dataset_id
    materialize_status: Optional[str] = None
    materialize_stopped_because: Optional[str] = None
    materialize_failure: Optional[str] = None
    materialize_message: Optional[str] = None
    materialize_exit_code = EXIT_GENERIC
    if resolved is None:
        late_status: Optional[str] = None
        if outcome.stopped_because in ("timeout", "poll_failed"):
            # fix(#1778, codex round 3): resolve_dataset_id now reports WHY
            # it stopped instead of collapsing every reason into None — see
            # publish()'s equivalent comment above for the bug this fixes
            # (a transient poll failure followed by a lucky pending/running
            # re-read used to be reported as a false timeout). This extra
            # read is skipped for "terminal" and "token_expired" for the
            # same reasons as there.
            #
            # fix(#1778, codex round 5): bind a short timeout for this
            # one-shot diagnostic read rather than reusing poll_client
            # as-is, which may be unbounded (the default --wait with no
            # --timeout) or bound to a long caller-supplied --timeout —
            # either way a stalled connection here would hang the command
            # past the outcome it already reached. If it ALSO times out,
            # treat the read as unreadable rather than letting the network
            # error abort the command — see publish()'s equivalent comment.
            #
            # fix(#1778, codex round 6): `client.with_timeout()` MUTATES
            # the already-constructed httpx transport in place before
            # returning an "evolved" wrapper (sdks/python/geolens/
            # client.py) — the evolved wrapper is a decoy. Bind sdk.client
            # (not poll_client, so this can't alias whatever transport the
            # explicit-timeout path above already constructed) via its own
            # transport directly: get_httpx_client() is the SDK's public
            # escape hatch (OCCLI-06); save its timeout, bound it for this
            # one read, and restore it unconditionally — matching
            # publish()'s fix, and cheap insurance against a future
            # materialize change reusing sdk.client after this block the
            # way publish()'s Stage 5 already does.
            snapshot_transport = sdk.client.get_httpx_client()
            original_timeout = snapshot_transport.timeout
            snapshot_transport.timeout = _publish._SNAPSHOT_REQUEST_TIMEOUT_SECONDS
            try:
                late_status, late_dataset_id = _analysis.job_snapshot(
                    sdk.client, job_id
                )
            except typer.Exit as exc:
                if exc.exit_code != EXIT_NETWORK:
                    raise
                late_status, late_dataset_id = None, None
            finally:
                snapshot_transport.timeout = original_timeout
            if late_dataset_id:
                # The job finished between the poll's last look and this one
                # (fix(#685 review)). Reporting a completed job as
                # unfinished would be the worst answer of the bunch.
                resolved = late_dataset_id
        if resolved is None:
            # fix(#1778, codex round 4): the job can just as well have
            # reached a DEFINITIVE terminal status by the time of the
            # follow-up read — failed, cancelled, or fanned out. That real
            # information must win over the stale timeout/poll_failed
            # wording; only a pending/running (or unreadable) snapshot
            # leaves the job's fate genuinely unresolved, so only THAT
            # keeps the original outcome's wording.
            if late_status in _publish._TERMINAL_NO_DATASET_STATUSES:
                effective_status = late_status
                reason = "terminal"
            else:
                effective_status = outcome.status
                reason = outcome.stopped_because
            materialize_status = effective_status
            materialize_stopped_because = reason
            if reason == "terminal" and effective_status == "failed":
                materialize_failure = (
                    f"Analysis job {job_id} failed. Its error is on the job "
                    f"record: GET /jobs/{job_id}."
                )
            elif reason == "terminal" and effective_status == "cancelled":
                # fix(#1778): reachable now that resolve_dataset_id treats
                # cancelled as terminal — say so plainly instead of falling
                # into the "still {status}" wording below, which would
                # wrongly imply the job might still finish.
                materialize_failure = (
                    f"Analysis job {job_id} was cancelled. "
                    f"Check GET /jobs/{job_id}."
                )
            elif reason == "terminal" and effective_status == "fanned_out":
                # A fanned-out job is a SUCCESS whose children each carry
                # their own dataset — see publish()'s equivalent branch.
                # materialize jobs are never fanned out by the current
                # backend (fan-out is ingest-only), so this is defensive,
                # not reachable today.
                materialize_message = (
                    f"Analysis job {job_id} fanned out into one import per "
                    f"layer; check GET /jobs/{job_id} or the datasets list "
                    f"for the resulting datasets."
                )
            elif reason == "terminal":
                materialize_failure = (
                    f"Analysis job {job_id} reached status "
                    f"{effective_status!r}, which will not produce a "
                    f"dataset. Check GET /jobs/{job_id}."
                )
            elif reason == "token_expired":
                materialize_exit_code = EXIT_AUTH
                materialize_failure = (
                    f"Authentication failed while reading job {job_id}'s "
                    f"status. Run `geolens login` first."
                )
            elif reason == "poll_failed":
                # fix(#1778, codex round 7): a poll_failed outcome collapsed
                # EVERY non-200 into the same generic exit code, hiding a
                # 5xx server outage from a script that checks the exit code
                # — match the same status matrix unwrap() already uses
                # elsewhere in this CLI.
                materialize_exit_code = _publish.poll_failed_exit_code(
                    outcome.http_status
                )
                materialize_failure = (
                    f"Analysis job {job_id}'s status could not be read "
                    f"({outcome.detail}). Check GET /jobs/{job_id}."
                )
            else:
                # Only reachable with an explicit --timeout: the default
                # waits for a terminal state. Unfinished is not failed, and
                # the wording says so (fix(#685 review)).
                materialize_failure = (
                    f"Analysis job {job_id} was still {effective_status} "
                    f"after {int(timeout or 0)}s and has not finished. "
                    f"Check GET /jobs/{job_id}."
                )

    url = _publish.construct_dataset_url(
        instance, dataset_id=resolved, job_id=job_id
    )
    payload = {
        "job_id": job_id,
        "dataset_id": resolved,
        "url": url,
        "status": materialize_status,
        "stopped_because": materialize_stopped_because,
    }
    if state.output.json_mode:
        state.output.json(payload)
    else:
        if materialize_failure:
            state.output.error(materialize_failure)
        elif materialize_message:
            state.output.success(materialize_message)
        else:
            state.output.success(url)
    if materialize_failure:
        raise typer.Exit(materialize_exit_code)
