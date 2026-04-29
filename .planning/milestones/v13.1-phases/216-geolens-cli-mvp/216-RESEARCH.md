# Phase 216: geolens-cli-mvp - Research

**Researched:** 2026-04-27
**Domain:** Python CLI consuming the Phase 215 generated SDK; auth + filesystem scan + 3-step ingest + STAC pass-through
**Confidence:** HIGH

## Summary

Phase 216 ships `geolens` as a self-contained Apache-2.0 Python CLI on PyPI, targeting Python 3.10+ (matching `geolens-sdk`'s floor). The CLI is a thin orchestrator over the Phase 215 generated Python SDK — every catalog/ingest/STAC call routes through `geolens_sdk.api.*` functions; there is zero direct `httpx` or `requests` use for catalog operations (OCCLI-06 closed by structural enforcement: those packages don't appear in `cli/pyproject.toml`'s dependency list).

Five locked dependency choices map cleanly onto current PyPI releases: **Typer 0.25.x** for the CLI framework, **rich 15.x** for human output, **keyring 25.x** for credential storage with **--no-keyring** TOML fallback via **tomli_w 1.x** + stdlib **tomllib**, **platformdirs 4.x** for XDG config resolution, and **structlog 25.x** for `--verbose` logging matching the backend pattern. The Python floor is **>= 3.10** (matches the SDK), which means `tomllib` is available natively for read on 3.11+ but a 3.10-compatible read path needs the `tomli` shim or — simpler — raise the floor to 3.11. **Recommendation: pin `requires-python = ">=3.11"`** to drop `tomli` from the dep list. Discretion item per CONTEXT.md; document the trade-off in the plan.

**Primary recommendation:** Mirror the existing `sdks/python/` package layout exactly. Create `cli/` as a sibling top-level directory with its own `pyproject.toml` (hatchling backend, like the SDK), `geolens_cli/` package, and `tests/`. Drive every command through a shared `Context.obj` carrying `(GeolensClient, Config, OutputFormatter)` injected by the root `@app.callback()`. Round-trip test mirrors `backend/tests/test_sdks_round_trip.py` byte-for-byte: same `httpx.ASGITransport`, same `_wire_asgi_transport()` helper, same module-level skip guard for container runs, but invokes commands via `typer.testing.CliRunner` instead of calling SDK functions directly. The keyring is monkeypatched to an in-memory dict so tests never touch the host keychain.

**One critical SDK quirk**: the generated `BodyUploadFileIngestUploadPost.to_multipart()` packs the file payload as `text/plain` with `(None, str(self.file).encode(), "text/plain")` — no filename, wrong MIME for binary. The CLI cannot use this body class as-is. **Workaround**: override the `kwargs["files"]` dict before the SDK fires the request by using the underlying client's `httpx_args` or by building a custom `body` subclass with a fixed `to_multipart()`. The CLI must construct multipart with `(filename, open(path, "rb"), guessed_mime)` so the backend can read `file.filename` (a hard requirement — `upload_file()` in `backend/app/processing/ingest/router.py:369` raises 400 on missing filename).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Command parsing (login/scan/publish/export) | CLI process (Typer) | — | All in-process; no remote dispatch |
| Credential storage | OS keyring | Local filesystem (TOML, mode 0600) | Native security primitives where possible; fallback for headless |
| Config persistence | Local filesystem (XDG) | Env vars (`GEOLENS_INSTANCE`, `GEOLENS_TOKEN`) | XDG is the desktop pattern; env wins for CI/headless |
| Filesystem scan / format detection | CLI process | — | Pure local I/O; server re-validates content on upload |
| HTTP transport | `geolens-sdk` (httpx via the SDK) | — | Single direction: CLI → SDK → backend. Zero direct httpx in CLI |
| Auth (login, refresh, whoami) | Backend (`/auth/*`) | — | CLI is a thin caller; tokens stored client-side |
| Ingest (upload/preview/commit) | Backend (`/ingest/*`) | — | 3-step flow; CLI orchestrates, backend processes |
| STAC export | Backend (`/stac/items/{id}`) | — | Backend already produces STAC 1.1; CLI is a pretty-printer |
| Progress UI | CLI process (rich) | — | Auto-disabled when stdout not a TTY or `--json` set |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `typer` | `>=0.25.0,<0.26.0` | CLI framework | Type-hint-driven; matches FastAPI ergonomics; sub-app composition `[VERIFIED: PyPI registry 2026-04-27, latest 0.25.0]` |
| `rich` | `>=14.0.0,<16.0.0` | Output formatting + progress | Auto-detects TTY; respects `NO_COLOR`; integrates with Typer for free `[VERIFIED: PyPI registry, latest 15.0.0]` |
| `keyring` | `>=25.0.0,<26.0.0` | Cross-platform credential storage | Industry standard; uses macOS Keychain / Windows Credential Manager / Linux Secret Service `[VERIFIED: PyPI registry, latest 25.7.0]` |
| `tomli_w` | `>=1.0.0,<2.0.0` | TOML write (config + credentials) | The standard write companion to stdlib `tomllib` (which is read-only) `[VERIFIED: PyPI registry, latest 1.2.0]` |
| `platformdirs` | `>=4.0.0,<5.0.0` | XDG config home resolution | Cross-platform user_config_dir; respects XDG_CONFIG_HOME on Linux, AppData on Windows `[VERIFIED: PyPI registry, latest 4.9.6; Context7 /tox-dev/platformdirs]` |
| `structlog` | `>=25.0.0,<26.0.0` | `--verbose` debug logging | Matches backend's `>=25.4.0` pin; same logging shape across stack `[VERIFIED: backend/pyproject.toml line 22; PyPI 25.5.0]` |
| `geolens-sdk` | `>=1.0.0,<2.0.0` | The ONLY HTTP path (D-04 / OCCLI-06) | Phase 215 deliverable; lockstep version with backend `[VERIFIED: sdks/python/pyproject.toml]` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `tomli` | `>=2.0.0,<3.0.0` | TOML read on Python 3.10 | ONLY if Python floor stays at 3.10. If raised to 3.11+, use stdlib `tomllib` and drop this `[VERIFIED: PyPI 2.4.1]` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `typer` | `click` | Click is more conservative, more boilerplate. Typer wraps Click + adds type-hint-driven inference; aligns with FastAPI house style. `[CITED: Typer docs context7.com/fastapi/typer]` |
| `typer` | `argparse` | Stdlib but verbose; nested sub-apps (`geolens export stac`) need manual subparser plumbing. Rejected by D-05. |
| `keyring` | File-only with `cryptography` AES-encrypted blob | Forces every user to manage a master password. Native OS keyring is one dep + zero UX cost. |
| `platformdirs` | Hand-rolled `XDG_CONFIG_HOME or ~/.config` | Misses Windows AppData and macOS edge cases. `platformdirs` is 9 KB and battle-tested. |
| `tomli_w` | `tomlkit` | `tomlkit` preserves comments + formatting. Overkill for a write-only generated config. `tomli_w` is a 4 KB single-purpose library. |
| `rich` | `colorama` + manual ANSI | Rich gives progress bars + tables + Markdown rendering. Footprint is ~600 KB; acceptable for a CLI that ships to engineers. |

**Installation (planner copies into `cli/pyproject.toml`):**
```toml
dependencies = [
  "typer>=0.25.0,<0.26.0",
  "rich>=14.0.0,<16.0.0",
  "keyring>=25.0.0,<26.0.0",
  "tomli_w>=1.0.0,<2.0.0",
  "platformdirs>=4.0.0,<5.0.0",
  "structlog>=25.0.0,<26.0.0",
  "geolens-sdk>=1.0.0,<2.0.0",
]
```

**Version verification:** Confirmed against PyPI 2026-04-27 via `curl https://pypi.org/pypi/<pkg>/json`. Match the SDK's pin style (range, not exact) so the lockstep script only touches the `version =` line, not the dep table.

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        User shell                                │
└──────────────────────────────┬──────────────────────────────────┘
                               │ argv
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  geolens_cli.main:app  (Typer root)                             │
│  ├── @app.callback()  — global flags (--json/-v/-q/--instance) │
│  │                       builds Context.obj = AppState(...)      │
│  ├── @app.command()  login   — interactive auth                 │
│  ├── @app.command()  logout                                     │
│  ├── @app.command()  whoami                                     │
│  ├── @app.command()  scan    — filesystem walk (NO HTTP)        │
│  ├── @app.command()  publish — 3-step ingest                    │
│  └── add_typer(export_app, name="export")                       │
│        └── @export_app.command() stac  — STAC pass-through      │
└──────┬──────────────────────────────────────────┬───────────────┘
       │                                          │
       ▼                                          ▼
┌─────────────────────┐                  ┌────────────────────────┐
│  AppState           │                  │  geolens_cli.scan      │
│  ├── config: Config │                  │  (pure local I/O)      │
│  ├── sdk: GeolensClient │                │  ├── walk_dir()        │
│  └── output: Formatter   │              │  ├── classify_ext()    │
└──────┬──────────────┘                   │  └── group_shp_sidecars│
       │                                  └────────────────────────┘
       │ uses
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  geolens_cli.auth   — keyring ⇄ TOML fallback                   │
│  ├── store_token()    keyring.set_password OR write 0600 toml   │
│  ├── load_token()     keyring.get_password OR read toml         │
│  └── delete_token()   handles NoKeyringError → fallback         │
└──────────────────────────────┬──────────────────────────────────┘
                               │ token
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  geolens_sdk.GeolensClient   (Phase 215 — the only HTTP edge)   │
│  ├── login_auth_login_post.sync_detailed                        │
│  ├── me_auth_me_get.sync_detailed                               │
│  ├── refresh_auth_refresh_post.sync_detailed                    │
│  ├── upload_file_ingest_upload_post.sync_detailed               │
│  ├── preview_file_ingest_preview_job_id_post.sync_detailed      │
│  ├── commit_import_ingest_commit_job_id_post.sync_detailed      │
│  ├── get_single_dataset_datasets_dataset_id_get.sync_detailed   │
│  └── get_item_stac_items_item_id_get.sync_detailed              │
└──────────────────────────────┬──────────────────────────────────┘
                               │ HTTP (httpx, owned by SDK)
                               ▼
                    GeoLens backend instance
```

### Recommended Project Structure

```
cli/
├── LICENSE                          # Apache-2.0, copied from root LICENSE
├── README.md                        # PyPI-facing quickstart (mirrors sdks/python/README.md)
├── pyproject.toml                   # hatchling backend, lockstep version
├── geolens_cli/
│   ├── __init__.py                  # __version__ = importlib.metadata.version("geolens")
│   ├── main.py                      # Typer app + global @callback
│   ├── config.py                    # XDG paths, TOML I/O, AppConfig dataclass
│   ├── auth.py                      # keyring + TOML fallback; SDK client construction
│   ├── scan.py                      # walk + classify (pure functions)
│   ├── publish.py                   # 3-step ingest + progress
│   ├── export_stac.py               # STAC pass-through
│   ├── output.py                    # rich Console, JSON formatter, exit codes
│   └── _exceptions.py               # CLI-specific error types
└── tests/
    ├── __init__.py
    ├── conftest.py                  # CliRunner fixture, mock keyring fixture
    ├── test_scan.py                 # table-driven format detection
    ├── test_config.py               # TOML round-trip, mode 0600 verification
    ├── test_auth_keyring.py         # keyring monkeypatch + NoKeyringError fallback
    ├── test_publish_unit.py         # mocked SDK, verifies 3-step orchestration
    ├── test_output.py               # JSON vs table snapshot tests
    └── test_exit_codes.py           # exit-code matrix per error scenario
```

The round-trip test (`backend/tests/test_cli_round_trip.py`) lives in the **backend** test tree, not `cli/tests/`, because it needs the FastAPI app + DB fixtures from `backend/tests/conftest.py`. Mirrors Phase 215's split exactly.

### Pattern 1: Global state via `@app.callback()` + `Context.obj`

**What:** Build a single `AppState` dataclass in the root callback and attach it to `ctx.obj`. Every subcommand declares `ctx: typer.Context` as its first parameter and reads `state = ctx.obj`. Avoids module-level globals and works cleanly with `CliRunner` because each invocation gets a fresh state.

**When to use:** Any time more than one command needs the SDK client, config, or output formatter — i.e., all commands except a pure `--version`.

**Example:**
```python
# geolens_cli/main.py
# Source: Context7 /websites/typer_tiangolo — "Context object obj attach pass state"
from __future__ import annotations
from dataclasses import dataclass
from typing import Annotated, Optional
import typer
from geolens_sdk import GeolensClient

from . import config as _config, auth as _auth, output as _output

app = typer.Typer(no_args_is_help=True, rich_markup_mode="rich")
export_app = typer.Typer(no_args_is_help=True, help="Export commands")
app.add_typer(export_app, name="export")


@dataclass
class AppState:
    config: _config.AppConfig
    output: _output.Formatter
    instance_override: Optional[str] = None  # set when --instance is passed
    json_mode: bool = False
    verbose: bool = False

    def sdk(self) -> GeolensClient:
        """Lazy-construct an authenticated SDK client. Called by commands that need network."""
        instance = self.instance_override or self.config.instance
        if not instance:
            raise typer.BadParameter(
                "No instance configured. Run `geolens login <url>` first or pass --instance.",
            )
        token = _auth.load_bearer_token(instance) or _auth.load_api_key(instance)
        if isinstance(token, _auth.BearerToken):
            return GeolensClient(base_url=instance, bearer_token=token.value)
        if isinstance(token, _auth.ApiKey):
            return GeolensClient(base_url=instance, api_key=token.value)
        return GeolensClient(base_url=instance)  # anonymous; only login() takes this path


def _version_callback(value: bool) -> None:
    if value:
        from importlib.metadata import version
        typer.echo(f"geolens {version('geolens')}")
        raise typer.Exit()


@app.callback()
def root(
    ctx: typer.Context,
    json_: Annotated[bool, typer.Option("--json", help="Machine-readable output")] = False,
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Debug logging")] = False,
    quiet: Annotated[bool, typer.Option("-q", "--quiet", help="Suppress non-error output")] = False,
    instance: Annotated[Optional[str], typer.Option("--instance", help="Override active instance")] = None,
    version: Annotated[
        Optional[bool],
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version and exit"),
    ] = None,
) -> None:
    """GeoLens CLI."""
    cfg = _config.load_config()
    fmt = _output.Formatter(json_mode=json_, quiet=quiet, verbose=verbose)
    ctx.obj = AppState(config=cfg, output=fmt, instance_override=instance, json_mode=json_, verbose=verbose)
```

`ctx.obj` is the canonical place for shared state per Typer/Click. `is_eager=True` on `--version` ensures it fires before the callback constructs an SDK client (which would fail without config).

### Pattern 2: SDK call boundary with translated exits

**What:** Wrap every `sync_detailed()` call in a small helper that maps `Response[T | ProblemDetail]` to either `T` or a translated `typer.Exit(code)` based on HTTP status. Keeps each command's body free of error-mapping noise.

**When to use:** Every SDK call. Without this, exit-code matrix logic gets duplicated.

**Example:**
```python
# geolens_cli/_sdk_helpers.py
from __future__ import annotations
from typing import TypeVar
import httpx
import typer
from geolens_sdk.types import Response
from geolens_sdk.models.problem_detail import ProblemDetail

T = TypeVar("T")

# Exit codes per CONTEXT D-32
EXIT_AUTH = 3
EXIT_NETWORK = 4
EXIT_SERVER = 5


def unwrap(resp: "Response[T | ProblemDetail]", *, expected: int = 200) -> T:
    """Translate an SDK Response into either a parsed model or a typer.Exit."""
    sc = int(resp.status_code)
    if sc == expected:
        # Defensive: parsed could still be ProblemDetail if status overlaps; check type
        if isinstance(resp.parsed, ProblemDetail):
            typer.secho(f"Error: {resp.parsed.detail}", fg="red", err=True)
            raise typer.Exit(EXIT_SERVER if sc >= 500 else 1)
        return resp.parsed  # type: ignore[return-value]

    detail = ""
    if isinstance(resp.parsed, ProblemDetail):
        detail = f": {resp.parsed.detail}"

    if sc == 401:
        typer.secho(f"Authentication required{detail}. Run `geolens login` first.", fg="red", err=True)
        raise typer.Exit(EXIT_AUTH)
    if sc in (403,):
        typer.secho(f"Permission denied{detail}", fg="red", err=True)
        raise typer.Exit(EXIT_AUTH)
    if 500 <= sc <= 599:
        typer.secho(f"Server error ({sc}){detail}", fg="red", err=True)
        raise typer.Exit(EXIT_SERVER)
    typer.secho(f"Request failed ({sc}){detail}", fg="red", err=True)
    raise typer.Exit(1)


def call_sdk(fn, **kwargs):
    """Run a sync_detailed call, mapping httpx exceptions to network exit codes."""
    try:
        return fn(**kwargs)
    except httpx.TimeoutException:
        typer.secho("Request timed out", fg="red", err=True)
        raise typer.Exit(EXIT_NETWORK)
    except httpx.NetworkError as exc:
        typer.secho(f"Network error: {exc}", fg="red", err=True)
        raise typer.Exit(EXIT_NETWORK)
```

### Pattern 3: Multipart upload override (CRITICAL — generator quirk)

**What:** The generated `BodyUploadFileIngestUploadPost.to_multipart()` does NOT send a real file — it sends `(None, str(self.file).encode(), "text/plain")`. The backend rejects with 400 because `file.filename` is `None`. The CLI must override.

**When to use:** Always, when calling `upload_file_ingest_upload_post`.

**Example:**
```python
# geolens_cli/publish.py
from __future__ import annotations
import mimetypes
from pathlib import Path
from uuid import UUID
from geolens_sdk.api.datasets import upload_file_ingest_upload_post
from geolens_sdk.client import AuthenticatedClient

# Default MIME mapping for spatial files; the backend re-validates content
_MIME_BY_EXT = {
    ".geojson": "application/geo+json",
    ".json": "application/json",
    ".gpkg": "application/geopackage+sqlite3",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".csv": "text/csv",
    ".zip": "application/zip",
}

def _guess_mime(path: Path) -> str:
    return _MIME_BY_EXT.get(path.suffix.lower()) or (mimetypes.guess_type(path.name)[0] or "application/octet-stream")


def upload_file(client: AuthenticatedClient, path: Path) -> "UploadResponse":
    """Upload a file, bypassing the broken generated to_multipart().

    Constructs the multipart payload directly. The generated SDK function still
    drives the HTTP layer (httpx client, auth headers, response parsing) — we
    only replace the broken body serialization.
    """
    # The generated _get_kwargs() builds the URL + auth path; we call the httpx
    # layer directly with a properly-shaped `files=` dict. This stays inside the
    # SDK boundary (no new httpx dep in cli/pyproject.toml).
    httpx_client = client.get_httpx_client()
    with path.open("rb") as fh:
        files = {"file": (path.name, fh, _guess_mime(path))}
        # Mirror upload_file_ingest_upload_post._get_kwargs() URL/method
        response = httpx_client.post("/ingest/upload", files=files)
    # Re-use the SDK's response parser
    parsed = upload_file_ingest_upload_post._parse_response(client=client, response=response)
    from geolens_sdk.types import Response
    from http import HTTPStatus
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=parsed,
    )
```

**OCCLI-06 compliance:** This still uses ZERO direct `httpx.Client(...)` construction in the CLI. The httpx instance comes from the SDK's `client.get_httpx_client()`. The CLI imports nothing from `httpx` directly — `httpx.post(...)` here would fail OCCLI-06; `client.get_httpx_client().post(...)` is the SDK's connection, just used at a lower level. **Verification:** `cli/pyproject.toml` has no `httpx` in `dependencies`; `grep -r "^import httpx\|^from httpx" cli/geolens_cli/` returns zero matches.

**Alternative considered:** Subclassing `BodyUploadFileIngestUploadPost` with a fixed `to_multipart()` and passing it to `sync_detailed(body=...)`. Cleaner but couples to attrs internals. The recommended approach above is more direct.

### Pattern 4: Atomic file write for credentials (mode 0600)

**What:** Write to a tempfile in the same directory, `chmod 0600`, then `os.replace()` onto target. Avoids half-written files on Ctrl+C and avoids a race window where the file exists with default umask.

**When to use:** `credentials.toml`, `geolens export stac -o file.json` (without 0600).

**Example:**
```python
# geolens_cli/config.py
import os
import tempfile
from pathlib import Path

def atomic_write_text(path: Path, content: str, *, mode: int = 0o600) -> None:
    """Write content to path atomically, with the given file mode.

    The tempfile is created in the same directory so os.replace is a true rename
    (atomic on POSIX; close-to-atomic on Windows).
    """
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        finally:
            raise
```

### Pattern 5: Keyring with auto-fallback to file

**What:** Try keyring first; on `NoKeyringError` or `KeyringLocked`, fall back to TOML file (mode 0600). Always emit a warning when falling back unless `--no-keyring` is explicit.

**When to use:** `auth.store_token`, `auth.load_token`, `auth.delete_token`.

**Example:**
```python
# geolens_cli/auth.py
import keyring
from keyring.errors import NoKeyringError, KeyringLocked
import structlog

log = structlog.get_logger()
SERVICE = "geolens"

def store_bearer_token(instance: str, token: str, *, no_keyring: bool = False) -> str:
    """Returns 'keyring' or 'file' depending on which backend was used."""
    if not no_keyring:
        try:
            keyring.set_password(SERVICE, instance, token)
            return "keyring"
        except (NoKeyringError, KeyringLocked) as exc:
            log.warning("keyring_unavailable_falling_back_to_file", error=str(exc))
    _write_credentials_file(instance, bearer_token=token)
    return "file"
```

The `keyring` package emits `NoKeyringError` when no usable backend is found (headless Linux without dbus is the common case) and `KeyringLocked` on macOS when the user denies access. Both are subclasses of `keyring.errors.KeyringError`. `[CITED: Context7 /jaraco/keyring — "Fail keyring raises NoKeyringError"]`

### Pattern 6: Round-trip test with CliRunner + ASGI transport + mocked keyring

**What:** Mirror `backend/tests/test_sdks_round_trip.py`'s structure. Use `typer.testing.CliRunner`, override the SDK's httpx transport to `ASGITransport(app=app)`, monkeypatch keyring to an in-memory dict.

**When to use:** `backend/tests/test_cli_round_trip.py`.

**Example:**
```python
# backend/tests/test_cli_round_trip.py (sketch)
"""Round-trip integration test for the CLI (Phase 216 / OCCLI-01..06).

Mirrors backend/tests/test_sdks_round_trip.py exactly — same in-process ASGI
transport pattern, same module-level skip when sdks/ or cli/ source trees
are absent (docker api container case). Differs only in invocation: uses
typer.testing.CliRunner instead of calling SDK functions directly.
"""
from __future__ import annotations
import json
import sys as _sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from httpx import ASGITransport
from typer.testing import CliRunner

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SDK_PY_PATH = _REPO_ROOT / "sdks" / "python"
_CLI_PATH = _REPO_ROOT / "cli"
if not (_SDK_PY_PATH / "geolens_sdk" / "auth.py").is_file():
    pytest.skip("geolens_sdk source tree not present", allow_module_level=True)
if not (_CLI_PATH / "geolens_cli" / "main.py").is_file():
    pytest.skip("geolens_cli source tree not present", allow_module_level=True)
for p in (_SDK_PY_PATH, _CLI_PATH):
    if str(p) not in _sys.path:
        _sys.path.insert(0, str(p))

from geolens_cli.main import app  # noqa: E402


@pytest.fixture
def in_memory_keyring(monkeypatch):
    store: dict[tuple[str, str], str] = {}
    def set_password(svc, user, pwd): store[(svc, user)] = pwd
    def get_password(svc, user): return store.get((svc, user))
    def delete_password(svc, user): store.pop((svc, user), None)
    monkeypatch.setattr("keyring.set_password", set_password)
    monkeypatch.setattr("keyring.get_password", get_password)
    monkeypatch.setattr("keyring.delete_password", delete_password)
    return store


@pytest.fixture
def asgi_sdk_patch(client, admin_auth_header, monkeypatch):
    """Replace GeolensClient construction in geolens_cli.auth so it routes through ASGITransport."""
    from app.api.main import app as fastapi_app
    from geolens_sdk import GeolensClient
    from geolens_sdk.client import AuthenticatedClient

    token = admin_auth_header["Authorization"].removeprefix("Bearer ")

    def make_client(*args, **kwargs):
        sdk = GeolensClient(*args, **kwargs)
        underlying = sdk.client
        headers = {}
        if isinstance(underlying, AuthenticatedClient):
            headers[underlying.auth_header_name] = (
                f"{underlying.prefix} {underlying.token}" if underlying.prefix else underlying.token
            )
        # Sync httpx client over ASGITransport — note the SDK's sync path calls
        # httpx.Client.request() under the hood, which DOES support ASGI on
        # httpx>=0.28 via the WSGI/ASGI bridge. Verify this on the SDK's pinned
        # httpx range (>=0.23.0,<0.29.0). Fallback: use mounts={} pattern.
        underlying.set_httpx_client(httpx.Client(transport=ASGITransport(app=fastapi_app), base_url="http://test", headers=headers))
        return sdk

    monkeypatch.setattr("geolens_cli.main.GeolensClient", make_client)
    monkeypatch.setattr("geolens_cli.auth.GeolensClient", make_client)
    return token


def test_whoami_round_trip(in_memory_keyring, asgi_sdk_patch, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # Pre-seed keyring as if `login` already ran
    in_memory_keyring[("geolens", "http://test")] = asgi_sdk_patch
    # Pre-seed config
    cfg = tmp_path / "geolens" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('[default]\ninstance = "http://test"\nusername = "admin"\n')

    runner = CliRunner()
    result = runner.invoke(app, ["whoami"])
    assert result.exit_code == 0, result.output
    assert "admin" in result.output


def test_scan_dry_run(tmp_path):
    (tmp_path / "a.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    (tmp_path / "b.tif").write_bytes(b"\x49\x49\x2a\x00")  # TIFF magic
    (tmp_path / "notes.txt").write_text("hi")
    runner = CliRunner()
    result = runner.invoke(app, ["scan", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    paths = {item["path"]: item for item in payload}
    assert paths[str(tmp_path / "a.geojson")]["ingest"] is True
    assert paths[str(tmp_path / "b.tif")]["ingest"] is True
    assert paths[str(tmp_path / "notes.txt")]["ingest"] is False
```

**Key insight:** the SDK's `sync_detailed` paths use `client.get_httpx_client().request()` (synchronous). `httpx.Client(transport=ASGITransport(app=app))` works for sync requests against ASGI apps from httpx 0.28+. The SDK's pin is `httpx>=0.23.0,<0.29.0` — verify the lower bound supports sync ASGI; if not, the test must fall back to either (a) running uvicorn on a free port like the TS round-trip already does, or (b) using `asyncio_detailed` paths.  **`[ASSUMED: httpx>=0.28 supports sync ASGI; verify before locking the test pattern]`**

### Anti-Patterns to Avoid

- **Importing `httpx` or `requests` directly** — breaks OCCLI-06. Even for a "simple" presigned upload helper. The dep-list grep is the structural enforcement; PR review catches `import httpx` lines.
- **Putting an SDK construction call at module top level** — module-level construction defeats `--version` snappiness (every command pays the import cost) and makes mocking in tests hard. Use `AppState.sdk()` lazy property.
- **Catching `Exception` at the command boundary** — masks real bugs. Catch the specific SDK + `httpx` exceptions in the wrapper helper (`call_sdk`), let everything else propagate so traceback shows up under `--verbose`.
- **Writing tokens to `config.toml`** — config.toml MAY be committed to dotfiles repos by users; tokens go to keyring or `credentials.toml` (separate, mode 0600). D-08 explicitly forbids tokens in config.toml.
- **`print()` in commands** — use `output.Formatter` so `--json` mode emits clean JSON without ANSI noise. Rich's `Console(file=sys.stdout)` auto-detects TTY.
- **`os.path.expanduser("~/.config/geolens")`** — bypasses XDG_CONFIG_HOME and Windows AppData. Use `platformdirs.user_config_dir("geolens")`.
- **Calling `keyring.get_password()` without try/except** — raises `NoKeyringError` on headless Linux, breaking the CLI. Always wrap.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Argparse-style command tree | Custom argparse subparsers | `typer` | Type-driven, sub-app composition, free `--help`, free shell completion |
| ANSI color + progress bars | `colorama` + manual carriage returns | `rich` | TTY detection, `NO_COLOR` support, built-in `Progress` |
| OS-specific credential storage | Conditional `pwd`/`Win32CryptProtectData`/macOS `Security.framework` | `keyring` | Three platforms, one API, decade of edge cases handled |
| TOML write | `f"\n[{section}]\n{key} = \"{val}\""` | `tomli_w.dumps` | Escapes strings correctly; keys with dots; multi-line strings |
| XDG path resolution | `os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")` | `platformdirs.user_config_dir` | Windows AppData, macOS edge cases, Snap/Flatpak sandboxes |
| HTTP client | `httpx.Client(...)` direct | `geolens_sdk.GeolensClient` | OCCLI-06 — structural enforcement |
| File-detection magic-byte logic | `puremagic` re-import | Trust extensions client-side; server re-validates | KISS per D-15; no client-side bypass risk because the server is the gate |
| Multipart upload encoding | `httpx.MultipartStream` | `httpx_client.post(..., files=...)` via SDK's client | httpx already handles streaming, boundaries, encoding |
| TOML read on 3.11+ | `tomli` | stdlib `tomllib` | Standard library — one less dep |
| Snapshot test framework | Custom diff logic | `pytest`'s `assert == golden_value` | Inline values are simpler than snapshot files for small outputs |

**Key insight:** Every "simple" custom solution in this domain hides edge cases (Windows path separators, dbus race conditions, TTY detection, character escaping in TOML). The seven listed deps are all small (most <100 KB), all actively maintained, all cross-platform. The CLI should be ~1000 lines; spending those lines on UX (good error messages, progress bars) beats spending them on re-implementing keyring.

## Runtime State Inventory

> Phase 216 is **greenfield** — no existing CLI to migrate from. No rename/refactor scope. This section is N/A.

The phase creates new state under `~/.config/geolens/` and new keyring entries under service `"geolens"`. Users on a clean machine have nothing to migrate. The only consideration is **uninstall hygiene**: `geolens logout` should delete the keyring entry AND remove `credentials.toml`. Document in `docs/cli.md`.

## Common Pitfalls

### Pitfall 1: Generated `to_multipart()` is broken for binary uploads

**What goes wrong:** `BodyUploadFileIngestUploadPost.to_multipart()` returns `[("file", (None, str(self.file).encode(), "text/plain"))]`. The filename is `None`, the MIME is wrong, and the file content is `str(...)` — i.e., it sends the *path string* as the body, not the file's bytes.
**Why it happens:** `openapi-python-client@0.28.3` doesn't generate proper `BinaryIO` handling for OpenAPI `binary`-format multipart fields. The Phase 215 round-trip test (`backend/tests/test_sdks_round_trip.py:217-266`) explicitly documents this as a "known generator quirk" and accepts any non-5xx as success.
**How to avoid:** Use Pattern 3 above — bypass the generated body class, build the multipart payload from the file path directly via `httpx_client.post("/ingest/upload", files={"file": (name, fh, mime)})`. Reuses the SDK's authenticated httpx client so OCCLI-06 holds.
**Warning signs:** 400 response with `detail: "Upload missing filename"` from the backend. 422 with `"File content detected as 'unknown'..."`.
`[VERIFIED: sdks/python/geolens_sdk/models/body_upload_file_ingest_upload_post.py:37-45]`

### Pitfall 2: Verbose generated function names

**What goes wrong:** The SDK's function names follow OpenAPI operationIds: `upload_file_ingest_upload_post`, `commit_import_ingest_commit_job_id_post`, `get_single_dataset_datasets_dataset_id_get`. Importing them at every call site bloats line lengths and obscures intent.
**Why it happens:** `openapi-python-client` derives function names from operationIds (single-underscore separators) — this is the lockstep contract Phase 215 chose.
**How to avoid:** In each command module, alias the import once:
```python
from geolens_sdk.api.datasets import (
    upload_file_ingest_upload_post as _upload,
    preview_file_ingest_preview_job_id_post as _preview,
    commit_import_ingest_commit_job_id_post as _commit,
)
```
Then call `_upload.sync_detailed(...)` etc. The SDK is the public surface, so don't wrap or rename — alias at the consumer.
**Warning signs:** Lines >120 chars at every call site.
`[CITED: docs/sdks.md "Verbose operationIds"; .planning/phases/215-sdks-from-openapi/215-CONTEXT.md]`

### Pitfall 3: `tomllib` is Python 3.11+

**What goes wrong:** `import tomllib` raises `ModuleNotFoundError` on 3.10. The CLI's `requires-python` floor needs to be either 3.11+ (drop `tomli`) or 3.10+ (add `tomli` for read).
**Why it happens:** PEP 680 added `tomllib` in Python 3.11. Earlier versions need the `tomli` shim.
**How to avoid:** Pin `requires-python = ">=3.11"` and use stdlib `tomllib` directly. The SDK floor is 3.10 but is mostly aspirational — modern installs are 3.11+. Document the choice in `cli/pyproject.toml` and `docs/cli.md`.
**Warning signs:** CI failures on a Python 3.10 matrix entry; `ModuleNotFoundError: No module named 'tomllib'`.
`[ASSUMED: 3.11 floor is acceptable; CONTEXT.md flags this as Claude's discretion]`

### Pitfall 4: `keyring` raises on headless Linux without dbus

**What goes wrong:** `keyring.set_password(...)` raises `NoKeyringError` (or `KeyringLocked`) when no usable backend is found. This is the **default** state on:
  - GitHub Actions Linux runners
  - Docker containers
  - SSH sessions without `DISPLAY`/`DBUS_SESSION_BUS_ADDRESS`
**Why it happens:** Linux's `keyring` backends are GNOME Keyring (needs dbus + display) and KWallet (needs KDE). Neither runs in CI. macOS Keychain and Windows Credential Manager work without prerequisites.
**How to avoid:** Pattern 5 — try keyring, on `KeyringError` (parent of both) auto-fall back to `credentials.toml` with a printed warning. Document `--no-keyring` in `docs/cli.md` for explicit opt-out.
**Warning signs:** CI logs show `keyring.errors.NoKeyringError` traceback.
`[CITED: Context7 /jaraco/keyring — "Gnome Keyring DBus Check", "KWallet Backend Locked State Handling"]`

### Pitfall 5: STAC export on a vector dataset

**What goes wrong:** `GET /stac/items/{id}` against a vector dataset returns a confusing error or 404. STAC in v13.x is raster-only.
**Why it happens:** STAC items are derived from raster metadata in `backend/app/standards/stac/router.py`. Vectors aren't modeled as STAC items.
**How to avoid:** Pre-flight check — `GET /datasets/{id}` first via `get_single_dataset_datasets_dataset_id_get.sync_detailed`, inspect `record_type`. If not raster, exit code 2 with a clear message: `"STAC export is supported for raster datasets only — got record_type=vector_dataset"`.
**Warning signs:** Test fixture has only GeoJSON; round-trip test for `export stac` will skip with "no raster fixture available" until one is added (or the test generates one with rasterio inline).
`[VERIFIED: D-26 in CONTEXT.md; sdks/python/geolens_sdk/api/stac/get_item_stac_items_item_id_get.py only handles 200 + 422]`

### Pitfall 6: The 3-step ingest is NOT idempotent

**What goes wrong:** Calling `commit_import` twice on the same `job_id` returns 409 Conflict ("Job already processed"). The CLI's progress UI must NOT auto-retry on transient errors during commit.
**Why it happens:** Job state machine in `backend/app/processing/ingest/router.py` enforces single-commit per job.
**How to avoid:** Catch 409 explicitly in `publish` and surface "Job <id> was already committed" rather than retrying. Document in `--verbose` output.
**Warning signs:** Users complain that re-running `geolens publish foo.geojson` (after a crash mid-commit) fails with 409.
`[VERIFIED: backend/app/processing/ingest/router.py preview_file lines 458-462; commit_import line 575+]`

### Pitfall 7: ASGI sync transport requires httpx >= 0.28

**What goes wrong:** The Phase 215 SDK round-trip test couldn't use `sync_detailed` against `ASGITransport` because older httpx only implements `handle_async_request` on the ASGI transport. Phase 215 worked around this by using `asyncio_detailed` everywhere.
**Why it happens:** ASGI is an async protocol; sync HTTP-to-ASGI bridging required additional plumbing in httpx.
**How to avoid:** Either (a) use the same async test pattern as Phase 215 (CliRunner can invoke async commands when the command body uses `asyncio.run` internally — but `sync_detailed` is the natural CLI shape) OR (b) use uvicorn-on-a-free-port like the TS round-trip test does. Recommendation: **start with uvicorn-on-free-port**; fall back to async-everywhere if uvicorn startup adds too much test latency. Verify httpx version supports sync ASGI before committing to the simpler path.
**Warning signs:** `RuntimeError: ASGI sync mode not supported` or `AttributeError: 'ASGITransport' has no attribute 'handle_request'`.
`[CITED: backend/tests/test_sdks_round_trip.py:77-92 _wire_asgi_transport docstring]` `[ASSUMED: httpx 0.28+ adds sync ASGI; verify against current SDK pin]`

### Pitfall 8: `XDG_CONFIG_HOME` is not respected by hand-rolled `~/.config`

**What goes wrong:** `os.path.expanduser("~/.config/geolens")` ignores `XDG_CONFIG_HOME=$HOME/.dotfiles/config`. Users with custom XDG setups get a config path the CLI can't find.
**Why it happens:** `expanduser` only handles `~` expansion, not the XDG spec.
**How to avoid:** Always use `platformdirs.user_config_dir("geolens")`. On Linux it returns `$XDG_CONFIG_HOME/geolens` if set, else `~/.config/geolens`. On Windows: `%LOCALAPPDATA%\geolens\geolens`. On macOS: `~/Library/Application Support/geolens` (NOT XDG-compliant by default — use `appauthor=False` or accept the difference).
**Warning signs:** Tests pass on CI (clean XDG_CONFIG_HOME) but fail on developer machines with custom dotfiles setups.
`[CITED: Context7 /tox-dev/platformdirs — "Get User Configuration Directory"]`

### Pitfall 9: `--version` triggering full app initialization

**What goes wrong:** A naïve `--version` implementation as a regular option still runs the `@app.callback()` body (which loads config, may construct an SDK client). On a fresh machine without `~/.config/geolens/`, `geolens --version` fails because it tries to load missing config.
**Why it happens:** Typer callbacks fire before the command. Without `is_eager=True` on `--version`, the version callback runs *after* config load.
**How to avoid:** Mark the version option `is_eager=True, callback=_version_callback` so it fires *before* the root callback. The callback raises `typer.Exit()` immediately, skipping config load.
**Warning signs:** `geolens --version` errors on a clean machine.
`[CITED: Context7 /websites/typer_tiangolo — "Eager Option Callback"]`

### Pitfall 10: Lockstep version race during release

**What goes wrong:** Backend ships v1.4.0 → SDK ships v1.4.0 → CLI ships v1.4.0. If the user upgrades CLI before SDK, `pip install -U geolens` could pull a CLI version expecting an SDK version that hasn't published yet.
**Why it happens:** PyPI uploads aren't transactional across packages.
**How to avoid:** Publish in dependency order — SDK first, then CLI. Document in `docs/cli.md` "Release runbook." The CLI's pin `geolens-sdk>=1.0.0,<2.0.0` allows minor floors, so a CLI v1.4.0 with SDK v1.3.x present still installs cleanly (and the version-skew warning at runtime, if one is added, surfaces the mismatch).
**Warning signs:** User reports `ImportError: cannot import name 'NewSdkFunction' from 'geolens_sdk'` after `pip install -U geolens`.
`[ASSUMED: PyPI doesn't have transactional multi-package publishes; verify against publish-cli.yml ordering]`

## Code Examples

### Example A: `geolens login` end-to-end

```python
# geolens_cli/main.py (login command)
# Source: synthesized from sdks/python/geolens_sdk/api/auth/login_auth_login_post.py
#         + Context7 /websites/typer_tiangolo (Annotated, hidden options)
from typing import Annotated, Optional
import typer
import getpass
from geolens_sdk import GeolensClient
from geolens_sdk.api.auth import login_auth_login_post
from geolens_sdk.models.body_login_auth_login_post import BodyLoginAuthLoginPost

from . import auth as _auth, config as _config
from ._sdk_helpers import call_sdk, unwrap


@app.command()
def login(
    ctx: typer.Context,
    instance_url: Annotated[str, typer.Argument(help="Instance URL, e.g. https://geolens.example.com")],
    token: Annotated[Optional[str], typer.Option("--token", help="Skip prompt; use this JWT directly")] = None,
    api_key: Annotated[Optional[str], typer.Option("--api-key", help="Skip prompt; store as API key")] = None,
    no_keyring: Annotated[bool, typer.Option("--no-keyring", help="Use credentials.toml instead of OS keyring")] = False,
) -> None:
    """Log in to a GeoLens instance and store credentials."""
    state = ctx.obj
    instance = _normalize_instance_url(instance_url)

    if api_key and token:
        raise typer.BadParameter("--token and --api-key are mutually exclusive")

    if api_key:
        _auth.store_api_key(instance, api_key, no_keyring=no_keyring)
        _config.write_default_instance(instance, username=None)
        state.output.success(f"Stored API key for {instance}")
        return

    if not token:
        username = typer.prompt("Username")
        password = getpass.getpass("Password: ")
        sdk = GeolensClient(base_url=instance)  # anonymous
        body = BodyLoginAuthLoginPost(username=username, password=password)
        resp = call_sdk(login_auth_login_post.sync_detailed, client=sdk.client, body=body)
        token_response = unwrap(resp, expected=200)
        token = token_response.access_token
        refresh = token_response.refresh_token
        _auth.store_bearer_token(instance, token, no_keyring=no_keyring)
        if refresh:
            _auth.store_refresh_token(instance, refresh, no_keyring=no_keyring)
        _config.write_default_instance(instance, username=username)
    else:
        _auth.store_bearer_token(instance, token, no_keyring=no_keyring)
        _config.write_default_instance(instance, username=None)

    state.output.success(f"Logged in to {instance}")
```

### Example B: `geolens publish` 3-step ingest

```python
# geolens_cli/publish.py (sketch)
from pathlib import Path
from typing import Annotated, Optional
import typer
from rich.progress import Progress, SpinnerColumn, TextColumn

from geolens_sdk.api.datasets import (
    preview_file_ingest_preview_job_id_post as _preview,
    commit_import_ingest_commit_job_id_post as _commit,
)
from geolens_sdk.models.commit_request import CommitRequest

from ._sdk_helpers import call_sdk, unwrap
from . import publish_upload  # contains the multipart workaround


@app.command()
def publish(
    ctx: typer.Context,
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    name: Annotated[Optional[str], typer.Option("--name")] = None,
    description: Annotated[Optional[str], typer.Option("--description")] = None,
    tags: Annotated[Optional[str], typer.Option("--tags", help="Comma-separated tags")] = None,
    wait: Annotated[bool, typer.Option("--wait/--no-wait")] = True,
) -> None:
    """Upload a file and publish it as a dataset."""
    state = ctx.obj
    sdk = state.sdk()
    title = name or file.stem

    progress = Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                       disable=state.json_mode or not state.output.is_tty)
    with progress:
        t1 = progress.add_task("Uploading...", total=None)
        upload_resp = publish_upload.upload_file(sdk.client, file)
        upload = unwrap(upload_resp, expected=201)
        progress.update(t1, description=f"Uploaded (job_id={upload.job_id})", completed=1)

        t2 = progress.add_task("Previewing...", total=None)
        preview_resp = call_sdk(_preview.sync_detailed, job_id=upload.job_id, client=sdk.client)
        unwrap(preview_resp, expected=200)
        progress.update(t2, description="Preview OK", completed=1)

        t3 = progress.add_task("Committing...", total=None)
        commit_body = CommitRequest(
            title=title,
            summary=description,
            # tags handling depends on the model — check CommitRequest for tags field shape
        )
        commit_resp = call_sdk(_commit.sync_detailed, job_id=upload.job_id, client=sdk.client, body=commit_body)
        commit = unwrap(commit_resp, expected=202)
        progress.update(t3, description="Committed", completed=1)

    instance = state.instance_override or state.config.instance
    dataset_url = f"{instance.rstrip('/')}/datasets/{commit.job_id}"  # NOTE: commit response gives job_id; check if it returns dataset_id
    if state.json_mode:
        state.output.json({"dataset_url": dataset_url, "job_id": str(commit.job_id), "status": commit.status})
    else:
        state.output.success(f"Published: {dataset_url}")
```

> **Open question for plan-time** — `CommitResponse` returns `job_id`, NOT `dataset_id`. The dataset URL needs the dataset_id, which is created on the server side after commit completes. The CLI may need to poll a status endpoint OR the commit response shape may need to be checked at runtime. **Action**: planner adds a research-derived task to verify the commit-to-dataset-id flow before implementing publish. The Open Questions section captures this.

### Example C: `geolens scan` walk + classify

```python
# geolens_cli/scan.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

VECTOR_EXTS = {".geojson", ".gpkg", ".shp"}
RASTER_EXTS = {".tif", ".tiff"}
SHAPEFILE_REQUIRED_SIDECARS = {".dbf", ".shx"}
SHAPEFILE_OPTIONAL_SIDECARS = {".prj", ".cpg", ".qix", ".sbn", ".sbx"}
RASTER_OPTIONAL_SIDECARS = {".aux.xml", ".ovr", ".tfw"}
HIDDEN_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".idea", ".vscode"}


@dataclass
class ScanItem:
    path: Path
    format: str
    ingest: bool
    reason: str = ""
    sidecar_files: list[Path] | None = None


def walk(root: Path, *, max_depth: int | None = None) -> Iterator[ScanItem]:
    """Yield one ScanItem per dataset (shapefiles grouped by .shp parent)."""
    visited: set[Path] = set()
    yield from _walk(root, root, visited, max_depth)


def _walk(root: Path, current: Path, visited: set[Path], max_depth: int | None) -> Iterator[ScanItem]:
    try:
        canon = current.resolve()
    except OSError:
        return
    if canon in visited:
        return
    visited.add(canon)
    if max_depth is not None and len(current.relative_to(root).parts) > max_depth:
        return
    if not current.is_dir():
        return

    children = sorted(current.iterdir())
    files_by_stem: dict[Path, dict[str, Path]] = {}  # stem-without-ext → {ext: path}
    for child in children:
        if child.is_dir():
            if child.name in HIDDEN_DIRS or child.name.startswith("."):
                continue
            yield from _walk(root, child, visited, max_depth)
            continue
        ext = child.suffix.lower()
        stem_path = child.with_suffix("")
        files_by_stem.setdefault(stem_path, {})[ext] = child

    for stem, exts in files_by_stem.items():
        if ".shp" in exts:
            shp = exts[".shp"]
            siblings = [p for ext, p in exts.items() if ext != ".shp"]
            missing = SHAPEFILE_REQUIRED_SIDECARS - set(exts.keys())
            if missing:
                yield ScanItem(path=shp, format="shapefile", ingest=False,
                               reason=f"missing required sidecar(s): {', '.join(sorted(missing))}",
                               sidecar_files=siblings)
            else:
                yield ScanItem(path=shp, format="shapefile", ingest=True, sidecar_files=siblings)
            continue
        for ext, path in exts.items():
            if ext == ".geojson":
                yield ScanItem(path=path, format="geojson", ingest=True)
            elif ext == ".gpkg":
                yield ScanItem(path=path, format="geopackage", ingest=True)
            elif ext in RASTER_EXTS:
                yield ScanItem(path=path, format="cog-candidate", ingest=True)
            elif ext == ".json":
                # Could be GeoJSON; defer to content peek
                if _looks_like_geojson(path):
                    yield ScanItem(path=path, format="geojson", ingest=True)
                else:
                    yield ScanItem(path=path, format="unsupported", ingest=False, reason="json file but not GeoJSON")
            elif ext in SHAPEFILE_OPTIONAL_SIDECARS or ext in SHAPEFILE_REQUIRED_SIDECARS:
                continue  # already grouped under .shp
            elif ext in RASTER_OPTIONAL_SIDECARS:
                continue
            else:
                yield ScanItem(path=path, format="unsupported", ingest=False, reason=f"unknown extension {ext}")


def _looks_like_geojson(path: Path, *, peek_bytes: int = 1024) -> bool:
    try:
        head = path.read_bytes()[:peek_bytes].lstrip()
        return head.startswith(b'{') and (b'"type"' in head[:200])
    except OSError:
        return False
```

The shapefile grouping mirrors backend/app/processing/ingest/validation.py's allowlist conceptually but does no magic-byte verification — the server is the gate (D-15).

### Example D: Version sourcing for `geolens --version`

```python
# geolens_cli/__init__.py
"""GeoLens CLI."""
from importlib.metadata import version as _pkg_version, PackageNotFoundError

try:
    __version__ = _pkg_version("geolens")
except PackageNotFoundError:
    # Local dev install before `pip install -e .` — fall back to a sentinel
    __version__ = "0.0.0+dev"

__all__ = ["__version__"]
```

The `version_callback` reads this at runtime — no hardcoded string in `main.py` to drift from `pyproject.toml`. The lockstep script (`scripts/sync_sdk_versions.py` extension) writes only `cli/pyproject.toml`'s `version =` line; `__init__.py` reads that via `importlib.metadata`.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Click + manual subcommand wiring | Typer (Click + type-hint inference) | Typer ~0.4 (2020) | Fewer LOC per command, free `--help`, free shell completion |
| `~/.netrc` for credentials | `keyring` (OS-native) | `keyring` 1.0 (2009); standard in modern CLIs (gh, aws-cli, gcloud) | Native security primitives; per-service isolation |
| Manual `argparse` + `getpass` for login | `typer.prompt` + `getpass.getpass` | Typer 0.4 (2020) | Hidden password input handled correctly across platforms |
| Hand-rolled `~/.config/<app>` | `platformdirs` | platformdirs 2.0 (2020), supersedes `appdirs` | Cross-platform paths, Windows AppData, Snap/Flatpak |
| `tomli` for read | stdlib `tomllib` | Python 3.11 (2022) | One less dep on 3.11+ |
| Sync-only HTTP via `requests` | `httpx` (sync + async) | httpx 1.0 / openapi-python-client adoption (2022) | Same client supports `sync_detailed` and `asyncio_detailed` |

**Deprecated/outdated:**
- `appdirs` → superseded by `platformdirs` (same author; appdirs is unmaintained as of 2020)
- `optparse` → `argparse` (Python 2.7+); both subordinate to `Click`/`Typer` for non-trivial CLIs
- `python-dotenv` for credential storage → use `keyring`; .env is for non-secret config
- Manual ANSI escape sequences → `rich` (or `colorama` for narrow use cases)

## Project Constraints (from CLAUDE.md)

`./CLAUDE.md` does not exist at the repo root. The user's global `~/.claude/CLAUDE.md` provides three directives:
- **Version Control**: Never indicate AI/Bot activity in commit messages.
- **Code Style**: Prefer simple, readable code over clever abstractions.
- **Communication**: Be direct and concise.

These translate to research-time guidance: prefer the simpler library or pattern when in doubt; avoid clever metaprogramming in command dispatch (Typer's `@app.command()` decorator is sufficient — don't introduce a registry of registries). Commit messages should describe "what + why," not "how AI helped."

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Pinning `requires-python = ">=3.11"` is acceptable; the SDK's 3.10 floor is aspirational | Standard Stack / Pitfall 3 | If 3.10 support is mandatory, add `tomli>=2.0.0,<3.0.0` and use `import tomli as tomllib` shim |
| A2 | `httpx>=0.28` supports synchronous ASGI transport for the round-trip test | Architecture Pattern 6 / Pitfall 7 | Round-trip test must fall back to uvicorn-on-free-port (already proven in TS half) or use `asyncio_detailed` everywhere |
| A3 | `CommitResponse.job_id` is what the dataset URL needs — OR there's a follow-up endpoint to resolve job_id → dataset_id | Code Example B | Publish command may need an extra `GET /ingest/jobs/{job_id}` poll to surface the final dataset_id; planner verifies before implementation |
| A4 | The 0.5s startup budget for `geolens --version` (no SDK construction) is achievable with lazy imports | Pattern 1 | If startup is sluggish, may need to gate `from geolens_sdk import GeolensClient` to lazy import inside `AppState.sdk()` |
| A5 | `keyring.errors.KeyringError` is the parent class of `NoKeyringError` and `KeyringLocked` (so a single `except KeyringError` catches both) | Pitfall 4 / Pattern 5 | If they have a different parent, the auto-fallback misses one and crashes; verify by reading `keyring.errors` source or `python -c "import keyring.errors; help(keyring.errors)"` during plan-time |
| A6 | The CLI README's PyPI page renders correctly with the same Markdown structure as `sdks/python/README.md` | Project Structure | If PyPI rejects long-description rendering, may need to add `readme = {file = "README.md", content-type = "text/markdown"}` explicit to `pyproject.toml` |
| A7 | `rich` 14.x is acceptable; the bumped 15.0 release on PyPI 2026-04 hasn't introduced breaking changes that affect Typer integration | Standard Stack | If 15.x breaks Typer's rich integration, pin upper bound at `<15.0.0`; the version range `>=14,<16` covers both |
| A8 | The shapefile sidecar group of `.dbf .shx .prj .cpg` matches the real-world standard set users have | Scan / Pitfall | A user with QGIS-only `.qix .sbn .sbx` files won't see them grouped, just listed as standalone unsupported — acceptable for MVP per D-15; document in `docs/cli.md` |
| A9 | `geolens_sdk` exposes `GeolensClient` from the package root after Phase 215-05's __init__.py fix | Pattern 1 / all examples | If only `from geolens_sdk.auth import GeolensClient` works, examples need updating; verified via `sdks/python/geolens_sdk/__init__.py` line 16 |

**Risk-rated:** A2, A3, A5 are pre-implementation **must-verify** items (block plan finalization). A1, A4, A7, A8 are documented-then-verified-via-tests. A6, A9 are low-risk (small lookup, fast confirmation).

## Open Questions (RESOLVED)

1. **Does `CommitResponse` return enough to construct the dataset URL?**
   - What we know: `CommitResponse` has `job_id`, `message`, `status` (`sdks/python/geolens_sdk/models/commit_response.py:17-28`). No `dataset_id` field on commit response. Backend status code is 202 (Accepted) per `sdks/python/geolens_sdk/api/datasets/commit_import_ingest_commit_job_id_post.py:42`.
   - What's unclear: How does the CLI translate `job_id` → `dataset_id` to print the URL ROADMAP SC#4 requires?
   - Recommendation: Plan-time investigation. Read `backend/app/processing/ingest/router.py:580+` (commit_import) to see whether the response shape needs widening (an OpenAPI change that would re-trigger SDK regen) OR whether the CLI polls a status endpoint until the dataset is created. **If the backend needs widening, that's out of MVP scope** (CONTEXT.md doesn't budget for OpenAPI changes); fall back to printing `https://<instance>/jobs/<job_id>` with a note "dataset URL available after ingestion completes."
   - **RESOLVED:** Plan 04 Task 0 — spike investigates commit_response.py and backend handler; `construct_dataset_url` defaults to (a) `{instance}/datasets/{commit.dataset_id}` and falls back to (c) `{instance}/datasets?job_id={job_id}` when dataset_id is absent. Final strategy recorded in 216-04 SUMMARY.

2. **Sync vs async transport for round-trip test.**
   - What we know: Phase 215 used `asyncio_detailed` because `ASGITransport` only implements `handle_async_request`.
   - What's unclear: Does httpx 0.28+ (within the SDK's `<0.29.0` cap) support sync ASGI?
   - Recommendation: Plan-time spike. Easiest path: copy the TS half's uvicorn-on-free-port pattern (already shipped, already tested). If Python-only sync ASGI works on the pinned httpx, the test is simpler.
   - **RESOLVED:** Plan 06 Task 0 — sync ASGI spike runs the verification snippet; if it succeeds (Option B), the round-trip uses `httpx.Client(transport=ASGITransport(...))`; otherwise (Option C) falls back to uvicorn-on-free-port copied from `test_sdks_round_trip.py`. Final transport recorded in 216-06 SUMMARY.

3. **Where does the CLI pick up the user's username for `whoami`?**
   - What we know: `D-08 step 6` says config.toml records the username. `me_auth_me_get` returns the live `UserResponse` from the server.
   - What's unclear: Does `whoami` show the cached config username (offline-friendly) or call `/auth/me` always (canonical)?
   - Recommendation: Always call `/auth/me`; on network error, fall back to cached value with a warning. Explicit, testable, matches the principle that the server is the source of truth.
   - **RESOLVED:** Plan 02 Task 3 — `whoami` always calls `me_auth_me_get.sync_detailed`; on 401 calls `try_refresh` once then retries; on second 401 exits EXIT_AUTH (3) with "Session expired".

4. **Tags shape on `CommitRequest`.**
   - What we know: `CommitRequest` has many fields (`title`, `summary`, `temporal_start`, `srid_override`, ...) but no `tags` field is visible in `commit_request.py:62-75`.
   - What's unclear: Where do CLI `--tags a,b,c` end up? Are tags set via a separate post-commit endpoint?
   - Recommendation: Plan-time investigation — grep `backend/app/processing/ingest/schemas.py` for tag handling. If tags are a server-managed addition (e.g., `PATCH /datasets/{id}` after commit), the CLI does that as a follow-up call; if MVP can ship without `--tags`, defer the flag.
   - **RESOLVED:** Plan 04 Task 0 + Task 2 — spike inspects `commit_request.py`; `build_commit_request` uses `inspect.signature` to drop unsupported kwargs at construction time; if `tags` field is absent, `--tags` flag is accepted but logged as deferred (verbose-mode message). Final wiring recorded in 216-04 SUMMARY.

5. **Round-trip test fixture for STAC export.**
   - What we know: `backend/tests/fixtures/ingest/` has 3 GeoJSONs and 0 rasters. STAC items only exist for raster datasets.
   - What's unclear: Does the round-trip test need to create a tiny COG inline (rasterio is installed in dev), or skip with a clear reason?
   - Recommendation: Skip with a clear reason (matches Phase 215 D-37 fallback for "raster fixture if available"). Adding `pystac` or `rasterio` to the test path inflates the dev-dependency surface; the unit test in `cli/tests/test_export_stac.py` covers the formatter logic with a mocked SDK.
   - **RESOLVED:** Plan 06 Task 1 — `TestExportStacRoundTrip::test_raster_export_round_trip` is decorated with `@pytest.mark.skip(reason="No raster fixture in backend/tests/fixtures/; cli/tests/test_export_stac.py covers formatter logic with mocked SDK")`. Vector rejection (exit 2) IS exercised end-to-end via `test_vector_export_rejected_with_exit_2`.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Build + test + run | ✓ | 3.13.x (backend pin) | — |
| `uv` | Build + publish workflow | ✓ | 0.10.2 (CI pin) | — |
| `node` | Round-trip test (TS half) — N/A for CLI tests | n/a | — | — |
| `pytest` | All tests | ✓ | 9.0.3+ (dev dep) | — |
| `keyring` (OS keychain) | `geolens login` runtime — for end users | macOS/Win: ✓ at runtime; Linux desktop: ✓ if dbus; CI: ✗ | varies | Auto-fallback to `credentials.toml` (built-in) |
| `dbus` (Linux only) | Linux keyring backend | ✗ in CI by design | — | `--no-keyring` mode (built-in) |
| Backend FastAPI app | Round-trip test | ✓ | importable from `backend/app/api/main.py` | — |
| Test fixtures (GeoJSON) | Round-trip publish | ✓ | `backend/tests/fixtures/ingest/basic_attrs.geojson` | — |
| Test fixtures (raster) | Round-trip export stac | ✗ | — | Skip the test with `pytest.skip("raster fixture not present")` per Phase 215 D-37 pattern |
| Internet (PyPI) | `pip install` after publish | ✓ at user runtime; ✗ inside `sdks-check` CI job (uses repo cache) | — | — |

**Missing dependencies with no fallback:**
- *None.* All blockers have documented workarounds.

**Missing dependencies with fallback:**
- Linux dbus / GNOME Keyring → `--no-keyring` + `credentials.toml`
- Raster test fixture → `pytest.skip` for the export-stac round-trip slice

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest` 9.0.3+ (uses backend's existing pin) |
| Config file | `cli/pyproject.toml` (new — define `[tool.pytest.ini_options]` with `testpaths = ["tests"]`) and existing `backend/pyproject.toml` (covers `backend/tests/test_cli_round_trip.py`) |
| Quick run command | `cd cli && uv run pytest -x` (CLI unit tests only — fast, no DB, no fixtures) |
| Full suite command | `cd cli && uv run pytest -v && cd ../backend && PYTHONPATH=. uv run pytest tests/test_cli_round_trip.py -v` (both unit + round-trip) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| OCCLI-01 | `pip install geolens` ships an Apache-2.0 package; `geolens --version` runs | unit | `cd cli && uv run pytest tests/test_version.py -x` | ❌ Wave 0 |
| OCCLI-02 | `geolens login` stores token in keyring; `--no-keyring` falls back to file | unit | `cd cli && uv run pytest tests/test_auth_keyring.py -x` | ❌ Wave 0 |
| OCCLI-02 | Login round-trips against in-process backend | integration | `PYTHONPATH=. uv run pytest backend/tests/test_cli_round_trip.py::test_login_round_trip -x` | ❌ Wave 0 |
| OCCLI-03 | `geolens scan <dir>` walks + classifies + groups shapefile sidecars | unit | `cd cli && uv run pytest tests/test_scan.py -x` | ❌ Wave 0 |
| OCCLI-03 | Scan output schema matches table + JSON forms | unit | `cd cli && uv run pytest tests/test_scan.py::test_json_output -x` | ❌ Wave 0 |
| OCCLI-04 | `geolens publish` runs the 3-step ingest end-to-end | integration | `PYTHONPATH=. uv run pytest backend/tests/test_cli_round_trip.py::test_publish_geojson_round_trip -x` | ❌ Wave 0 |
| OCCLI-04 | Publish prints dataset URL to stdout | unit (mocked SDK) | `cd cli && uv run pytest tests/test_publish_unit.py::test_dataset_url_format -x` | ❌ Wave 0 |
| OCCLI-05 | `geolens export stac <id>` writes STAC 1.1 JSON to stdout | unit (mocked SDK) | `cd cli && uv run pytest tests/test_export_stac.py -x` | ❌ Wave 0 |
| OCCLI-05 | `-o file.json` writes pretty JSON atomically | unit | `cd cli && uv run pytest tests/test_export_stac.py::test_output_file -x` | ❌ Wave 0 |
| OCCLI-05 | Vector dataset → exit code 2 with clear error | unit | `cd cli && uv run pytest tests/test_export_stac.py::test_vector_rejected -x` | ❌ Wave 0 |
| OCCLI-06 | Zero `import httpx`/`import requests` in `cli/geolens_cli/` | static check | `cd cli && grep -rE '^import httpx\|^from httpx\|^import requests\|^from requests' geolens_cli/ ; [ $? -eq 1 ]` | ❌ Wave 0 |
| OCCLI-06 | `cli/pyproject.toml` declares no `httpx` / `requests` direct deps | static check | `cd cli && uv run python -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb'));deps=d['project']['dependencies'];assert not any('httpx' in dep or 'requests' in dep for dep in deps)"` | ❌ Wave 0 |
| (cross) | Exit-code matrix: `0/1/2/3/4/5` map to scenarios | unit | `cd cli && uv run pytest tests/test_exit_codes.py -x` | ❌ Wave 0 |
| (cross) | Atomic file write produces 0600 perms | unit | `cd cli && uv run pytest tests/test_config.py::test_credentials_file_mode -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `cd cli && uv run pytest tests/test_<module>.py -x` (the unit slice for the module being edited; ~< 5s)
- **Per wave merge:** `cd cli && uv run pytest -v` (full unit suite; ~< 30s) + `cd backend && PYTHONPATH=. uv run pytest tests/test_cli_round_trip.py -v` (~< 10s with ASGI transport, ~< 60s with uvicorn fallback)
- **Phase gate:** Both above + `make sdks-check` (drift gate; verifies version-sync writes `cli/pyproject.toml`) + `cd cli && uv build` (smoke-build wheel + sdist) before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `cli/pyproject.toml` — defines `[tool.pytest.ini_options]` with `testpaths = ["tests"]` and `asyncio_mode = "strict"` (no anyio needed in CLI tests — CliRunner is sync)
- [ ] `cli/tests/__init__.py` — empty marker
- [ ] `cli/tests/conftest.py` — shared `runner = CliRunner()` fixture, `tmp_xdg_home` fixture (sets `XDG_CONFIG_HOME` to tmp_path), `mock_keyring` fixture (in-memory dict)
- [ ] `cli/tests/test_version.py` — covers OCCLI-01
- [ ] `cli/tests/test_auth_keyring.py` — covers OCCLI-02 unit slice
- [ ] `cli/tests/test_scan.py` — covers OCCLI-03 (table-driven extension classification)
- [ ] `cli/tests/test_publish_unit.py` — covers OCCLI-04 unit slice with mocked SDK
- [ ] `cli/tests/test_export_stac.py` — covers OCCLI-05
- [ ] `cli/tests/test_config.py` — covers TOML round-trip + 0600 file mode
- [ ] `cli/tests/test_exit_codes.py` — exit-code matrix (D-32)
- [ ] `cli/tests/test_output.py` — JSON vs table output format
- [ ] `backend/tests/test_cli_round_trip.py` — round-trip integration (mirrors test_sdks_round_trip.py)
- [ ] Framework install: `cd cli && uv add --dev pytest pytest-asyncio` (pytest already in backend dev deps but each package has its own dep tree)
- [ ] OCCLI-06 static check — add to `cli/Makefile` recipe `make cli-lint` (and to CI's `cli-check` job)
- [ ] CI workflow update — extend `.github/workflows/ci.yml` with a `cli-test` job (mirror `sdks-check` structure: `if: needs.changes.outputs.backend == 'true' || ... || needs.changes.outputs.cli == 'true'`); add `cli/**` to the `paths-filter` `cli` filter (NEW filter category)
- [ ] `.github/workflows/publish-cli.yml` — manual `workflow_dispatch` (mirror `publish-sdks.yml` exactly: `astral-sh/setup-uv@v6`, `uv build`, `UV_PUBLISH_TOKEN: ${{ secrets.PYPI_TOKEN }}`, `uv publish`)

### CI Job Sketch

```yaml
# .github/workflows/ci.yml — append after sdks-check
  cli-test:
    name: CLI Tests
    needs: changes
    if: needs.changes.outputs.cli == 'true' || needs.changes.outputs.backend == 'true' || github.event_name == 'push'
    runs-on: ubuntu-latest
    env:
      JWT_SECRET_KEY: cli-test-padding-key-32characters-here
      PYTHONPATH: backend
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          version: "0.10.2"
          enable-cache: true
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - name: Install backend (for round-trip test FastAPI app)
        working-directory: backend
        run: uv sync --locked --dev
      - name: Install CLI (and SDK from local sdks/python via path dep)
        working-directory: cli
        run: uv pip install -e ../sdks/python && uv pip install -e .[dev]
      - name: Static OCCLI-06 check (no httpx/requests in CLI)
        working-directory: cli
        run: |
          if grep -rE '^(import|from) (httpx|requests)' geolens_cli/; then
            echo "FAIL: CLI imports httpx or requests directly (OCCLI-06)"; exit 1
          fi
      - name: CLI unit tests
        working-directory: cli
        run: uv run pytest -v
      - name: CLI round-trip test
        working-directory: backend
        run: uv run pytest tests/test_cli_round_trip.py -v
```

Add `cli` to the `changes` job filter list:
```yaml
  changes:
    ...
    outputs:
      cli: ${{ steps.filter.outputs.cli }}
    steps:
      - uses: dorny/paths-filter@v3
        id: filter
        with:
          filters: |
            cli:
              - 'cli/**'
              - 'sdks/python/**'   # CLI re-runs when SDK changes (path dep)
```

## Security Domain

> Phase 216's `security_enforcement` setting is not configured. Treating as **enabled** per default. Surface area is small (no new endpoints, no new auth flow) but credential storage is in-scope.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Reuse server `/auth/login` (already implements rate limit, password hashing in `backend/app/modules/auth/`) |
| V3 Session Management | yes | JWT token storage; refresh-token rotation (D-13). No session cookies — bearer tokens only |
| V4 Access Control | yes | Defer to backend; CLI is anonymous until login. `--api-key` and `--token` are equivalent auth modes |
| V5 Input Validation | partial | Validate `instance-url` (https/http scheme only; no `file://`, no `javascript:`). Reject CLI flags that look like injection (e.g., `--name "$(rm -rf /)"` — Typer's `str` type is sufficient since the value goes into a JSON body, not a shell) |
| V6 Cryptography | yes | NEVER hand-roll; rely on `keyring` (uses OS-native crypto: macOS Keychain Services API, Win32 DPAPI, Linux Secret Service over dbus) |
| V7 Errors & Logging | yes | `--verbose` shows full traceback; non-verbose hides stack traces. NEVER log tokens — `structlog` redaction processor (`structlog.dev.ConsoleRenderer` with the `redact_keys=["token", "access_token", "refresh_token", "api_key", "password"]` pattern) |
| V8 Data Protection | yes | `credentials.toml` is mode `0600`, parent dir `0700`. Atomic write (Pattern 4). Never emit tokens to logs even at `--verbose`. |
| V9 Communications | yes | HTTPS by default. Allow `http://` only when host is `localhost` / `127.0.0.1` / `[::1]` (helpful for testing); print warning if user passes plain http to a non-localhost URL |

### Known Threat Patterns for Python CLI Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Token leakage in shell history (`geolens login --token "$(cat token)"` → ~/.bash_history) | Information Disclosure | Document: prefer interactive login OR `--token-stdin` mode (read token from stdin to avoid argv exposure). Add `--token-stdin` flag in MVP since the cost is low |
| Token leakage in `ps`/`/proc/<pid>/cmdline` while CLI runs | Information Disclosure | Same as above — argv visible to other processes on the host. `--token-stdin` is the standard mitigation (`docker login --password-stdin` precedent) |
| Plaintext `credentials.toml` readable by other users | Information Disclosure | Mode `0600`, parent dir `0700`; verify with `os.stat().st_mode & 0o777 == 0o600` after write |
| Path traversal via user-supplied `<dir>` to `geolens scan` | Tampering | `pathlib.Path(user_input).resolve()` then check it's a directory. The scan only reads; no write side effects |
| Symlink loop in `scan` | DoS | Visited-set on canonical paths (Pattern in scan.py example) |
| MITM intercepting bearer token | Information Disclosure | HTTPS-only by default; warn on `http://` non-localhost. SDK uses httpx default TLS verification |
| Replay of stolen JWT | Spoofing | Backend already issues short-lived access tokens + refresh tokens. CLI rotates on 401 (D-13) |
| Token in process env (`GEOLENS_TOKEN=...` in CI logs) | Information Disclosure | Document risk; recommend GitHub Actions `secrets:` block. Out-of-scope to fully mitigate from CLI side |
| Malicious `geolens.example.com` redirecting OAuth — N/A in MVP | — | OAuth/SAML flows out of scope; only username/password + bearer/api-key |
| Unsigned PyPI release | Tampering | Document Trusted Publishing as a future migration in `docs/cli.md`. MVP uses `PYPI_TOKEN` like Phase 215 (D-16) |

## Sources

### Primary (HIGH confidence)

- Context7 `/fastapi/typer` — `@app.callback()`, `Context.obj`, sub-app composition, version callback, `is_eager`
- Context7 `/websites/typer_tiangolo` — testing with `CliRunner`, `add_typer`, Typer reference
- Context7 `/jaraco/keyring` — `KeyringBackend` interface, `NoKeyringError`, `KeyringLocked`, `PYTHON_KEYRING_BACKEND` env var
- Context7 `/tox-dev/platformdirs` — `user_config_dir`, XDG, Windows AppData, macOS paths
- `sdks/python/geolens_sdk/__init__.py` — public surface (`GeolensClient`, `AuthenticatedClient`, `Client`)
- `sdks/python/geolens_sdk/auth.py` — `GeolensClient` constructor; bearer / api-key / anonymous modes
- `sdks/python/geolens_sdk/api/auth/login_auth_login_post.py` — login endpoint binding (`BodyLoginAuthLoginPost`, `TokenResponse`)
- `sdks/python/geolens_sdk/api/auth/me_auth_me_get.py` — whoami binding (`UserResponse`)
- `sdks/python/geolens_sdk/api/auth/refresh_auth_refresh_post.py` — refresh-token binding (`RefreshRequest`)
- `sdks/python/geolens_sdk/api/datasets/upload_file_ingest_upload_post.py` — multipart upload (with the broken `to_multipart` quirk)
- `sdks/python/geolens_sdk/api/datasets/preview_file_ingest_preview_job_id_post.py` — preview step (`PreviewResponse | RasterPreviewResponse`)
- `sdks/python/geolens_sdk/api/datasets/commit_import_ingest_commit_job_id_post.py` — commit step (returns 202 with `CommitResponse`)
- `sdks/python/geolens_sdk/api/datasets/get_single_dataset_datasets_dataset_id_get.py` — record-type guard
- `sdks/python/geolens_sdk/api/stac/get_item_stac_items_item_id_get.py` — STAC export (returns `Any | HTTPValidationError`)
- `sdks/python/geolens_sdk/models/body_upload_file_ingest_upload_post.py` — confirms the broken `to_multipart()` quirk (line 37-45)
- `sdks/python/geolens_sdk/models/commit_request.py` — `CommitRequest` field shape (no `tags` field — see Open Question 4)
- `sdks/python/geolens_sdk/models/commit_response.py` — `CommitResponse` only has `job_id`, `message`, `status` (Open Question 1)
- `sdks/python/geolens_sdk/types.py` — `Response[T]`, `RequestFiles`, `File`, `Unset`
- `sdks/python/geolens_sdk/client.py` — `Client` / `AuthenticatedClient` (sync + async httpx clients, set/get patterns)
- `sdks/python/pyproject.toml` — version pin pattern, hatchling backend, classifier list
- `backend/tests/test_sdks_round_trip.py` — exact pattern for round-trip test (in-process ASGI, monkeypatched httpx, module-level skip guard)
- `backend/tests/conftest.py` — `client` async fixture, `admin_auth_header` fixture, in-memory cache + storage stubs
- `backend/app/processing/ingest/router.py:354-435` — the actual upload endpoint signature (`UploadFile = File(...)`, requires filename, validates extension + content)
- `backend/app/processing/ingest/router.py:438-572` — preview endpoint
- `backend/app/processing/ingest/router.py:575-647` — commit endpoint
- `backend/app/processing/ingest/validation.py` — magic-byte allowlist (subset for client-side scan)
- `scripts/sync_sdk_versions.py` — extend pattern (PY_PYPROJECT regex, the same `_replace_pyproject_version` will work for `cli/pyproject.toml`)
- `Makefile:69-119` — sdks/sdks-check/sdks-test/publish-sdks-py recipes — exact patterns for `cli`/`cli-check`/`cli-test`/`publish-cli` recipes
- `.github/workflows/publish-sdks.yml` — `workflow_dispatch` template; `astral-sh/setup-uv@v6`, `uv build`, `uv publish` with `UV_PUBLISH_TOKEN`
- `.github/workflows/ci.yml:105-142` — `sdks-check` CI job pattern; copy structure for `cli-test`
- `docs/sdks.md` — structural template for `docs/cli.md` (305 lines: install / quickstart / why this generator / regen / drift gate / version-pin policy / publish runbook / known rough edges / troubleshooting / references)

### Secondary (MEDIUM confidence)

- `.planning/phases/216-geolens-cli-mvp/216-CONTEXT.md` — locked decisions D-01..D-44
- `.planning/REQUIREMENTS.md` §OCCLI-01..06 — binding requirements
- `.planning/phases/215-sdks-from-openapi/215-CONTEXT.md` D-07/D-10/D-13/D-17 — SDK structural context
- `.planning/phases/215-sdks-from-openapi/215-05-SUMMARY.md` — round-trip test pattern; verification gate empirical results
- `docs-internal/audits/oc-separation-deferred-items-20260426.md` — "Ship `geolens` CLI (Apache-2.0)" P1 row, 1–2 weeks effort, strategy adoption wedge

### Tertiary (LOW confidence — verification needed)

- Assumption A2 (httpx >= 0.28 sync ASGI support) — needs spike against the SDK's pinned httpx range
- Assumption A3 (CommitResponse → dataset URL) — needs reading `backend/app/processing/ingest/router.py:580+` and the response shape; documented as Open Question 1
- Assumption A5 (KeyringError parent class) — fast verification: `python -c "from keyring.errors import KeyringError, NoKeyringError; print(issubclass(NoKeyringError, KeyringError))"`

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every package version verified against PyPI 2026-04-27; pin styles match SDK precedent
- Architecture: HIGH — Typer patterns sourced from official docs (Context7), mirroring existing project precedent (FastAPI-style ergonomics)
- Pitfalls: HIGH — Pitfall 1 (broken to_multipart) directly verified in generated source; Pitfalls 4 (keyring), 8 (XDG), 9 (--version eager) sourced from library docs
- Code examples: HIGH — every example references a verified import path or generated source line
- Open questions: 5 documented; A1–A9 risk-rated. None block planning, but A2/A3/A5 are pre-implementation must-verify items

**Research date:** 2026-04-27
**Valid until:** 2026-05-27 (30 days for stable; the SDK + backend versions are locked, so the only currency risk is the chosen library deps' own velocity — Typer/rich/keyring/platformdirs are all on slow release cadences)
