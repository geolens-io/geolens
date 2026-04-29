# Phase 216: geolens-cli-mvp - Pattern Map

**Mapped:** 2026-04-27
**Files analyzed:** 18 (15 new + 3 modified)
**Analogs found:** 18 / 18 (every new file has a concrete in-repo analog)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `cli/pyproject.toml` (NEW) | config (package manifest) | build-time | `sdks/python/pyproject.toml` | exact |
| `cli/LICENSE` (NEW) | config (license) | static | `sdks/python/LICENSE` | exact |
| `cli/README.md` (NEW) | docs (PyPI-facing) | static | `sdks/python/README.md` | exact |
| `cli/geolens_cli/__init__.py` (NEW) | library (package init / version export) | static | `sdks/python/geolens_sdk/__init__.py` | role-match |
| `cli/geolens_cli/main.py` (NEW) | entrypoint (Typer app + global callback) | request-response (CLI argv → command) | `backend/scripts/dump_openapi.py` (argparse precedent only) | partial — no Typer in repo |
| `cli/geolens_cli/config.py` (NEW) | library (XDG paths + TOML I/O) | file-I/O | `sdks/python/geolens_sdk/auth.py` (hand-maintained library shape) + `scripts/sync_sdk_versions.py` (file write/replace) | role-match |
| `cli/geolens_cli/auth.py` (NEW) | library (keyring + file fallback; SDK client construction) | request-response + file-I/O | `sdks/python/geolens_sdk/auth.py` | exact (auth-wrapper sibling) |
| `cli/geolens_cli/scan.py` (NEW) | command module (filesystem walk + classify) | file-I/O (read-only walk) | none — greenfield (closest distant analog: `backend/app/processing/ingest/validation.py` for allowlist concept) | no analog |
| `cli/geolens_cli/publish.py` (NEW) | command module (3-step ingest orchestration) | request-response (multi-step) | `backend/tests/test_sdks_round_trip.py::test_ingest_upload` (the only existing 3-step caller in repo) | role-match |
| `cli/geolens_cli/export_stac.py` (NEW) | command module (SDK pass-through + atomic file write) | request-response | `backend/scripts/dump_openapi.py` (atomic-ish snapshot write + `--check`) | partial |
| `cli/geolens_cli/output.py` (NEW) | utility (rich Console + JSON formatter + exit-code consts) | transform | none — greenfield | no analog |
| `cli/geolens_cli/_sdk_helpers.py` (NEW) | utility (Response unwrap + httpx-error → exit-code mapping) | transform | none — greenfield | no analog |
| `cli/tests/conftest.py` (NEW) | test (fixtures: CliRunner, mock keyring, tmp XDG) | test fixture | `backend/tests/conftest.py` (fixture style only — no DB needed here) | partial |
| `cli/tests/test_*.py` (NEW — 8 modules) | test (unit) | test | `backend/tests/test_sdks_round_trip.py::TestPythonAuthWrapperUnit` (unit-test class style) | role-match |
| `backend/tests/test_cli_round_trip.py` (NEW) | test (integration) | test | `backend/tests/test_sdks_round_trip.py` | exact (sibling round-trip) |
| `scripts/sync_sdk_versions.py` (MODIFY) | utility (version sync) | file-I/O | itself — extend with one new constant + one extra `_replace_pyproject_version` call | exact |
| `Makefile` (MODIFY) | config (build recipes) | build-time | `Makefile` `sdks` / `sdks-check` / `sdks-test` / `publish-sdks-py` recipes | exact |
| `.github/workflows/ci.yml` (MODIFY) | CI (test job + paths-filter) | CI | `sdks-check` job + `changes.filters.backend` block in same file | exact |
| `.github/workflows/publish-cli.yml` (NEW) | CI (manual publish workflow) | CI | `.github/workflows/publish-sdks.yml` (`publish-python` job) | exact |
| `docs/cli.md` (NEW) | docs (user-facing CLI manual) | static | `docs/sdks.md` | exact |

---

## Pattern Assignments

### `cli/pyproject.toml` (config, package manifest)

**Analog:** `sdks/python/pyproject.toml`

**Build backend + project metadata** (`sdks/python/pyproject.toml` lines 1-37):
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "geolens-sdk"
version = "1.0.0"
description = "..."
readme = "README.md"
license = { text = "Apache-2.0" }
requires-python = ">=3.10"
authors = [{ name = "GeoLens", email = "noreply@geolens.io" }]
keywords = ["geolens", "geospatial", "openapi", "sdk"]
classifiers = [
  "Development Status :: 4 - Beta",
  "Intended Audience :: Developers",
  "License :: OSI Approved :: Apache Software License",
  "Programming Language :: Python :: 3",
  "Programming Language :: Python :: 3.10",
  ...
  "Topic :: Scientific/Engineering :: GIS",
]
dependencies = [
  "httpx >=0.23.0,<0.29.0",
  "attrs >=22.2.0",
  "python-dateutil >=2.8.0,<3.0.0",
]

[project.urls]
Homepage = "https://github.com/geolens-io/geolens"
Repository = "https://github.com/geolens-io/geolens"
Documentation = "https://github.com/geolens-io/geolens/blob/main/docs/sdks.md"

[tool.hatch.build.targets.wheel]
packages = ["geolens_sdk"]
```

**Copy verbatim with these substitutions for the CLI:**
- `name = "geolens"` (not `geolens-sdk` — CLI is the headline package per D-02)
- `requires-python = ">=3.11"` (RESEARCH Pitfall 3 — drops `tomli` shim)
- `dependencies = [` per RESEARCH Standard Stack: `typer>=0.25,<0.26`, `rich>=14,<16`, `keyring>=25,<26`, `tomli_w>=1,<2`, `platformdirs>=4,<5`, `structlog>=25,<26`, `geolens-sdk>=1.0.0,<2.0.0`
- `Documentation = "...docs/cli.md"`
- `[tool.hatch.build.targets.wheel] packages = ["geolens_cli"]`

**NEW section the SDK doesn't have — console-script entry** (D-02):
```toml
[project.scripts]
geolens = "geolens_cli.main:app"
```

**NEW section — pytest config (per RESEARCH Wave 0 Gaps):**
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
```

---

### `cli/LICENSE` (config, license)

**Analog:** `sdks/python/LICENSE`

**Action:** byte-copy from `sdks/python/LICENSE` (which is itself the root `LICENSE` per "Established Patterns" in CONTEXT.md). Apache-2.0 standard text, no edits.

---

### `cli/README.md` (docs, PyPI-facing)

**Analog:** `sdks/python/README.md`

**Full file template** (`sdks/python/README.md` lines 1-16 — entire file):
```markdown
# geolens-sdk (Python)

Auto-generated Python SDK for the [GeoLens](https://github.com/geolens-io/geolens) API.

Apache-2.0 licensed. Typed `attrs`-based dataclasses + `httpx` async-ready client + Bearer-token + API-key auth helpers.

See `docs/sdks.md` in the GeoLens repo for installation, regeneration, and version-pin policy.

## Quickstart

```python
from geolens_sdk import GeolensClient

client = GeolensClient(base_url="https://geolens.example.com", bearer_token="...")
# See ../../docs/sdks.md for endpoint usage examples.
```
```

**CLI substitution:** rename heading to `# geolens (CLI)`, swap "Auto-generated SDK" → "Apache-2.0 command-line interface for the GeoLens API"; quickstart shows `pip install geolens && geolens login <url> && geolens scan .`; link to `docs/cli.md` (D-43).

---

### `cli/geolens_cli/__init__.py` (library, package init)

**Analog:** `sdks/python/geolens_sdk/__init__.py`

**Module docstring + re-export pattern** (`sdks/python/geolens_sdk/__init__.py` lines 1-23):
```python
"""A client library for accessing GeoLens API.

Public exports:
    GeolensClient    — high-level wrapper with bearer/api-key/anonymous auth modes.
    AuthenticatedClient, Client — generator's underlying clients (advanced use).

Typical usage::

    from geolens_sdk import GeolensClient
    client = GeolensClient(base_url="https://geolens.example.com", bearer_token="<JWT>")

This file is hand-maintained alongside ``auth.py``; ``make sdks`` cp-stashes it
across regenerations so the public re-export survives ``--overwrite``.
"""

from .auth import GeolensClient
from .client import AuthenticatedClient, Client

__all__ = (
    "GeolensClient",
    "AuthenticatedClient",
    "Client",
)
```

**CLI variation — version export via `importlib.metadata` (RESEARCH Example D, lines 893-906):**
```python
"""GeoLens CLI."""
from importlib.metadata import version as _pkg_version, PackageNotFoundError

try:
    __version__ = _pkg_version("geolens")
except PackageNotFoundError:
    # Local dev install before `pip install -e .` — fall back to a sentinel
    __version__ = "0.0.0+dev"

__all__ = ["__version__"]
```

---

### `cli/geolens_cli/main.py` (entrypoint, Typer app)

**Analog:** none in this repo (no Typer precedent). Use **RESEARCH Pattern 1 verbatim** (lines 173-233) — sourced from Context7 `/websites/typer_tiangolo`. Argparse precedent in `backend/scripts/dump_openapi.py` is informational only (rejected by D-05).

**Lazy-import precedent for `--version` snappiness** (`backend/scripts/dump_openapi.py` lines 22-26):
```python
def _load_spec() -> dict:
    # Imported lazily so --help / argparse can run without a DB.
    from app.api.main import app

    return app.openapi()
```

**Apply to CLI:** mirror this lazy-import discipline so `geolens --version` and `geolens --help` do NOT import `geolens_sdk` at module top — defer to inside `AppState.sdk()` (per RESEARCH Anti-Pattern "Putting an SDK construction call at module top level").

**Core pattern — RESEARCH Pattern 1 (lines 173-233), reproduced for executor copy:**
```python
# geolens_cli/main.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Annotated, Optional
import typer

from . import config as _config, auth as _auth, output as _output

app = typer.Typer(no_args_is_help=True, rich_markup_mode="rich")
export_app = typer.Typer(no_args_is_help=True, help="Export commands")
app.add_typer(export_app, name="export")


@dataclass
class AppState:
    config: _config.AppConfig
    output: _output.Formatter
    instance_override: Optional[str] = None
    json_mode: bool = False
    verbose: bool = False

    def sdk(self):
        from geolens_sdk import GeolensClient  # lazy
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
        return GeolensClient(base_url=instance)


def _version_callback(value: bool) -> None:
    if value:
        from importlib.metadata import version
        typer.echo(f"geolens {version('geolens')}")
        raise typer.Exit()


@app.callback()
def root(
    ctx: typer.Context,
    json_: Annotated[bool, typer.Option("--json")] = False,
    verbose: Annotated[bool, typer.Option("-v", "--verbose")] = False,
    quiet: Annotated[bool, typer.Option("-q", "--quiet")] = False,
    instance: Annotated[Optional[str], typer.Option("--instance")] = None,
    version: Annotated[
        Optional[bool],
        typer.Option("--version", callback=_version_callback, is_eager=True),
    ] = None,
) -> None:
    """GeoLens CLI."""
    cfg = _config.load_config()
    fmt = _output.Formatter(json_mode=json_, quiet=quiet, verbose=verbose)
    ctx.obj = AppState(config=cfg, output=fmt, instance_override=instance, json_mode=json_, verbose=verbose)
```

`is_eager=True` on `--version` is **mandatory** per RESEARCH Pitfall 9.

---

### `cli/geolens_cli/config.py` (library, XDG + TOML I/O)

**Analog:** `scripts/sync_sdk_versions.py` (file write/replace style + atomic-ish discipline)

**Atomic write pattern (RESEARCH Pattern 4, lines 369-393)** — no in-repo precedent for tempfile+chmod+replace; copy verbatim from RESEARCH:
```python
def atomic_write_text(path: Path, content: str, *, mode: int = 0o600) -> None:
    """Write content to path atomically, with the given file mode."""
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

**File-replace + idempotency precedent** (`scripts/sync_sdk_versions.py` lines 50-62) — apply the same "exact equality check before write" discipline so config writes don't churn mtime:
```python
def _replace_pyproject_version(text: str, version: str) -> str:
    pattern = re.compile(r'^version = "[^"]*"$', re.MULTILINE)
    new_text, count = pattern.subn(f'version = "{version}"', text)
    ...
```

**XDG path resolution:** use `platformdirs.user_config_dir("geolens")` (RESEARCH Don't-Hand-Roll table; Pitfall 8). No in-repo analog.

---

### `cli/geolens_cli/auth.py` (library, keyring + file fallback + SDK client)

**Analog:** `sdks/python/geolens_sdk/auth.py` — sibling auth wrapper, exact pattern match.

**Module docstring style** (`sdks/python/geolens_sdk/auth.py` lines 1-13):
```python
"""Auth wrapper around the generated AuthenticatedClient/Client.

Hand-maintained — NOT regenerated by `make sdks`. The drift gate explicitly
excludes this file via `:!sdks/python/geolens_sdk/auth.py` in the Makefile.

Backend auth precedence (matches `_resolve_api_key()` in
backend/app/modules/auth/dependencies.py):
    header X-API-Key  > JWT Bearer (Authorization)  > anonymous
...
"""
from __future__ import annotations
```

**Precedence + docstring shape** (`sdks/python/geolens_sdk/auth.py` lines 23-71):
```python
class GeolensClient:
    """Single entry-point for the GeoLens Python SDK.

    Configure exactly one of bearer_token or api_key. With neither, the
    underlying client is anonymous and may only call public endpoints.
    ...
    Raises:
        ValueError: if both bearer_token and api_key are provided.
    """

    def __init__(
        self,
        base_url: str,
        *,
        bearer_token: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        if bearer_token and api_key:
            raise ValueError("Provide either bearer_token or api_key, not both.")
        ...
```

**Apply to CLI auth.py:** the same "configure exactly one" discriminator gate for `BearerToken` vs `ApiKey` types; same `from __future__ import annotations` header; same hand-maintained docstring marker (the CLI is NOT regenerated, but mirroring the convention helps a future reader).

**Keyring + fallback core (RESEARCH Pattern 5, lines 401-421):**
```python
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

---

### `cli/geolens_cli/scan.py` (command module, walk + classify)

**Analog:** none in this repo (greenfield). Closest distant reference: `backend/app/processing/ingest/validation.py` (extension allowlist concept only — server-side, magic-byte; CLI does extension-only per D-15).

**Use RESEARCH Example C verbatim (lines 793-886)** — full walk-with-shapefile-grouping logic, dataclass-based `ScanItem`, visited-set symlink protection. Not reproduced here; executor copies from RESEARCH.

**No analog excerpts to extract.** Planner should treat this file as "RESEARCH-driven, no in-repo analog" and budget review time accordingly.

---

### `cli/geolens_cli/publish.py` (command module, 3-step ingest)

**Analog:** `backend/tests/test_sdks_round_trip.py::test_ingest_upload` (lines 217-266) — the only existing 3-step ingest caller in the repo, and it documents the broken `to_multipart()` quirk.

**Generator-quirk acknowledgement** (`backend/tests/test_sdks_round_trip.py` lines 219-227):
```python
"""ROADMAP SC#1: POST /ingest/upload round-trip.

The generated ``BodyUploadFileIngestUploadPost.to_multipart()`` packs
the file field as ``str(self.file).encode()`` with ``text/plain`` MIME
— that's a known generator quirk for OpenAPI ``binary`` form fields.
Backend's ``upload_file`` handler validates filename + extension; we
accept any non-5xx status as proof the SDK's request shape reaches the
handler. ROADMAP SC#1 says "round-trip succeeds" — we read that as
"request reaches the route, gets a structured response".
"""
```

**Multipart workaround (RESEARCH Pattern 3, lines 309-355)** — bypasses the broken `to_multipart()` while staying inside the SDK boundary (OCCLI-06):
```python
def upload_file(client: AuthenticatedClient, path: Path) -> "Response":
    httpx_client = client.get_httpx_client()
    with path.open("rb") as fh:
        files = {"file": (path.name, fh, _guess_mime(path))}
        response = httpx_client.post("/ingest/upload", files=files)
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

**OCCLI-06 verification:** `httpx_client = client.get_httpx_client()` (Phase 215 SDK API) — no `import httpx` at the top of `publish.py`.

**SDK call shape — copy from `sdks/python/geolens_sdk/api/auth/login_auth_login_post.py` lines 89-117** (the canonical `sync_detailed` signature shape):
```python
response = client.get_httpx_client().request(**kwargs)
return _build_response(client=client, response=response)
```

The CLI calls these via `_preview.sync_detailed(...)` and `_commit.sync_detailed(...)` per RESEARCH Example B (lines 727-786) and the "Verbose generated function names" workaround in `docs/sdks.md` lines 245-249 (`as` aliases).

**Open Question 1 (RESEARCH lines 952-955):** `CommitResponse` returns `job_id`, not `dataset_id`. Plan-time spike required before implementing the dataset URL print.

---

### `cli/geolens_cli/export_stac.py` (command module, STAC pass-through)

**Analog:** `backend/scripts/dump_openapi.py` (atomic write + `--check` precedent) for the `-o FILE` output path; SDK call shape from `sdks/python/geolens_sdk/api/stac/get_item_stac_items_item_id_get.py` (referenced in CONTEXT.md `<canonical_refs>`).

**Pretty-printed JSON write** (`backend/scripts/dump_openapi.py` lines 29-31, 55):
```python
def _dump(spec: dict) -> str:
    # Sorted keys + trailing newline → deterministic diff-friendly output.
    return json.dumps(spec, indent=2, sort_keys=True) + "\n"

...
SNAPSHOT_PATH.write_text(text)
```

**Apply to CLI:** same `indent=2, sort_keys=True` for `geolens export stac -o FILE` (D-27 binds 2-space indent + sorted keys for diff stability). Use the `atomic_write_text` helper from `config.py` instead of plain `write_text` (RESEARCH Pattern 4 — D-27 specifies atomic write+rename).

**Vector-guard pre-flight call** (CONTEXT.md D-26): `get_single_dataset_datasets_dataset_id_get.sync_detailed(...)` first; check `record_type`; exit code 2 with clear message if not raster.

---

### `cli/geolens_cli/output.py` (utility, formatters + exit codes)

**Analog:** none in this repo (greenfield).

**Use RESEARCH Pattern 2 verbatim (lines 245-298)** for exit codes + `unwrap()` translator:
```python
EXIT_AUTH = 3
EXIT_NETWORK = 4
EXIT_SERVER = 5

def unwrap(resp: "Response[T | ProblemDetail]", *, expected: int = 200) -> T:
    sc = int(resp.status_code)
    if sc == expected:
        if isinstance(resp.parsed, ProblemDetail):
            typer.secho(f"Error: {resp.parsed.detail}", fg="red", err=True)
            raise typer.Exit(EXIT_SERVER if sc >= 500 else 1)
        return resp.parsed
    ...
```

**No in-repo analog excerpts to extract.**

---

### `cli/tests/conftest.py` (test, fixtures)

**Analog:** `backend/tests/conftest.py` — fixture style only (no DB needed for CLI unit tests).

**Pytest fixture pattern** (`backend/tests/conftest.py` lines 34-37, 288-294):
```python
@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"

@pytest.fixture
async def admin_auth_header(client: AsyncClient) -> dict[str, str]:
    """Return auth headers for the seeded admin user."""
    ...
```

**Apply to CLI conftest:** simpler — no DB, no async. Per RESEARCH Wave 0 Gaps (lines 1037-1039):
```python
import pytest
from typer.testing import CliRunner

@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()

@pytest.fixture
def tmp_xdg_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path

@pytest.fixture
def mock_keyring(monkeypatch):
    store: dict[tuple[str, str], str] = {}
    monkeypatch.setattr("keyring.set_password", lambda s, u, p: store.__setitem__((s, u), p))
    monkeypatch.setattr("keyring.get_password", lambda s, u: store.get((s, u)))
    monkeypatch.setattr("keyring.delete_password", lambda s, u: store.pop((s, u), None))
    return store
```

---

### `cli/tests/test_*.py` (test, unit modules)

**Analog:** `backend/tests/test_sdks_round_trip.py::TestPythonAuthWrapperUnit` (lines 111-154) — plain class-grouped pytest with no fixtures, asserting on constructor behavior.

**Class-grouped unit-test pattern** (`backend/tests/test_sdks_round_trip.py` lines 111-154):
```python
class TestPythonAuthWrapperUnit:
    """7 unit tests for ``GeolensClient`` — no network I/O."""

    def test_construct_with_bearer(self) -> None:
        c = GeolensClient(base_url="http://x", bearer_token="abc")
        assert isinstance(c._client, AuthenticatedClient)
        assert c._client.token == "abc"
        assert c._client.prefix == "Bearer"
        assert c._client.auth_header_name == "Authorization"

    def test_construct_with_api_key(self) -> None:
        ...

    def test_both_auth_modes_raises(self) -> None:
        with pytest.raises(ValueError, match="not both"):
            GeolensClient(base_url="http://x", bearer_token="a", api_key="b")
```

**Apply to CLI tests:** mirror the class-grouped style for each module's test (`TestScanClassification`, `TestConfigRoundTrip`, `TestExitCodes`, etc.). Each test names its OCCLI requirement in its docstring (RESEARCH Validation Architecture table, lines 1014-1027).

**CliRunner invocation pattern (RESEARCH Pattern 6, lines 522-533):**
```python
runner = CliRunner()
result = runner.invoke(app, ["scan", str(tmp_path), "--json"])
assert result.exit_code == 0, result.output
payload = json.loads(result.output)
```

---

### `backend/tests/test_cli_round_trip.py` (test, integration)

**Analog:** `backend/tests/test_sdks_round_trip.py` — exact sibling, copy verbatim with substitutions.

**Module-level guard** (`backend/tests/test_sdks_round_trip.py` lines 47-71):
```python
# Skip the entire module gracefully when sdks/python is not available on the
# filesystem. This is the case inside the docker `api` container ...
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SDK_PY_PATH = _REPO_ROOT / "sdks" / "python"
if not (_SDK_PY_PATH / "geolens_sdk" / "auth.py").is_file():
    pytest.skip(
        "geolens_sdk source tree not present at "
        f"{_SDK_PY_PATH} (expected when running inside the api container; "
        "host pytest and full-checkout CI runners exercise this module)",
        allow_module_level=True,
    )
if str(_SDK_PY_PATH) not in _sys.path:
    _sys.path.insert(0, str(_SDK_PY_PATH))

from geolens_sdk.auth import GeolensClient  # noqa: E402
from geolens_sdk.client import AuthenticatedClient, Client  # noqa: E402
```

**CLI extension** — add a second guard for the CLI source tree (per RESEARCH Pattern 6 / lines 452-462):
```python
_CLI_PATH = _REPO_ROOT / "cli"
if not (_CLI_PATH / "geolens_cli" / "main.py").is_file():
    pytest.skip("geolens_cli source tree not present", allow_module_level=True)
for p in (_SDK_PY_PATH, _CLI_PATH):
    if str(p) not in _sys.path:
        _sys.path.insert(0, str(p))

from geolens_cli.main import app  # noqa: E402
```

**ASGI transport wiring** (`backend/tests/test_sdks_round_trip.py` lines 77-105):
```python
def _wire_asgi_transport(sdk: GeolensClient, app) -> None:
    """Wire the SDK's underlying client to an in-process ASGITransport.

    ``ASGITransport`` only implements ``handle_async_request`` — there is no
    sync counterpart, so the SDK's ``sync_detailed`` calls cannot use this
    transport. The round-trip tests therefore use the SDK's ``asyncio_detailed``
    entrypoints, which call ``client.get_async_httpx_client()``.
    ...
    """
    transport = ASGITransport(app=app)
    headers: dict[str, str] = {}
    underlying = sdk.client
    if isinstance(underlying, AuthenticatedClient):
        token = underlying.token
        prefix = underlying.prefix
        header_name = underlying.auth_header_name
        headers[header_name] = f"{prefix} {token}" if prefix else token
    async_httpx_client = httpx.AsyncClient(
        base_url="http://test",
        transport=transport,
        headers=headers,
    )
    underlying.set_async_httpx_client(async_httpx_client)
```

**Open Question 2 (RESEARCH lines 957-960):** sync vs async ASGI transport. The Phase 215 round-trip used `asyncio_detailed` because `ASGITransport` is async-only. CLI commands call `sync_detailed` naturally — planner spike: either (a) use uvicorn-on-free-port like the TS half (lines 297-391 of test_sdks_round_trip.py — already in-repo proven), or (b) verify httpx >= 0.28 sync ASGI on the SDK's pinned range.

**Round-trip test method shape** (`backend/tests/test_sdks_round_trip.py` lines 169-191):
```python
@pytest.mark.anyio
async def test_search_datasets(self, client, admin_auth_header) -> None:
    from app.api.main import app
    from geolens_sdk.api.search import (
        search_datasets_endpoint_search_datasets_get,
    )
    token = admin_auth_header["Authorization"].removeprefix("Bearer ")
    sdk = GeolensClient(base_url="http://test", bearer_token=token)
    _wire_asgi_transport(sdk, app)
    ...
```

**Mocked-keyring fixture for CLI tests (RESEARCH Pattern 6, lines 466-475):**
```python
@pytest.fixture
def in_memory_keyring(monkeypatch):
    store: dict[tuple[str, str], str] = {}
    monkeypatch.setattr("keyring.set_password", lambda s, u, p: store.__setitem__((s, u), p))
    monkeypatch.setattr("keyring.get_password", lambda s, u: store.get((s, u)))
    monkeypatch.setattr("keyring.delete_password", lambda s, u: store.pop((s, u), None))
    return store
```

---

### `scripts/sync_sdk_versions.py` (MODIFY, version sync)

**Analog:** itself — extend by 6 lines.

**Existing constant block** (`scripts/sync_sdk_versions.py` lines 26-30):
```python
REPO_ROOT = Path(__file__).resolve().parent.parent
OPENAPI_PATH = REPO_ROOT / "backend" / "openapi.json"
PY_PYPROJECT = REPO_ROOT / "sdks" / "python" / "pyproject.toml"
PY_GEN_CONFIG = REPO_ROOT / "sdks" / "python" / ".openapi-python-client.yaml"
TS_PACKAGE = REPO_ROOT / "sdks" / "typescript" / "package.json"
```

**Add one constant + reuse `_replace_pyproject_version`:**
```python
CLI_PYPROJECT = REPO_ROOT / "cli" / "pyproject.toml"
```

**Existing call pattern** (lines 89-94):
```python
# Python pyproject.toml
py_text = PY_PYPROJECT.read_text()
new_py_text = _replace_pyproject_version(py_text, version)
if new_py_text != py_text:
    PY_PYPROJECT.write_text(new_py_text)
    print(f"Updated {PY_PYPROJECT.relative_to(REPO_ROOT)} version → {version}")
```

**Extension — add identical block for CLI** (D-03; CONTEXT.md "Code Insights" line 289):
```python
# CLI pyproject.toml
cli_text = CLI_PYPROJECT.read_text()
new_cli_text = _replace_pyproject_version(cli_text, version)
if new_cli_text != cli_text:
    CLI_PYPROJECT.write_text(new_cli_text)
    print(f"Updated {CLI_PYPROJECT.relative_to(REPO_ROOT)} version → {version}")
```

**Module docstring update** (`scripts/sync_sdk_versions.py` lines 7-10) — change "Touches three files:" to "four files" and add `cli/pyproject.toml` to the list.

---

### `Makefile` (MODIFY, build recipes)

**Analog:** `Makefile` itself — copy `sdks` / `sdks-check` / `sdks-test` / `publish-sdks-py` recipe shapes.

**Existing `.PHONY` line** (`Makefile` line 1):
```makefile
.PHONY: dev down reset-db migrate migration test test-cov e2e logs logs-db logs-api openapi openapi-check sdks sdks-check sdks-test publish-sdks-py publish-sdks-ts
```

**Add:** `cli-build cli-test cli-check publish-cli` to the `.PHONY` list.

**Existing `sdks-test` recipe** (`Makefile` lines 109-110):
```makefile
sdks-test:
	cd backend && PYTHONPATH=. uv run pytest tests/test_sdks_round_trip.py -v
```

**Apply to CLI** — add new `cli-test` recipe (per RESEARCH Validation Architecture):
```makefile
cli-test:
	cd cli && uv run pytest -v
	cd backend && PYTHONPATH=. uv run pytest tests/test_cli_round_trip.py -v
```

**Existing `publish-sdks-py` recipe** (`Makefile` lines 114-115):
```makefile
publish-sdks-py:
	cd sdks/python && uv build && uv publish
```

**Apply to CLI** — add `publish-cli`:
```makefile
publish-cli:
	cd cli && uv build && uv publish
```

**Existing `sdks-check` drift gate** (`Makefile` lines 95-105) — already catches CLI version drift via the extended `sync_sdk_versions.py` (D-39, no Makefile change needed for the drift gate itself):
```makefile
sdks-check:
	$(MAKE) sdks
	git diff --exit-code -- sdks/ \
	  ':!sdks/python/geolens_sdk/auth.py' \
	  ...
```

> The `sync_sdk_versions.py` step inside `sdks` already touches `cli/pyproject.toml`; if the version is stale the diff fails on `cli/pyproject.toml`. Add `cli-check` as an alias if explicit semantics are desired:
> ```makefile
> cli-check: sdks-check
> ```

---

### `.github/workflows/ci.yml` (MODIFY, CI test job)

**Analog:** existing `sdks-check` job (lines 105-142) and `changes.filters` block (lines 27-42) in the same file.

**Existing `changes` filter pattern** (`.github/workflows/ci.yml` lines 14-42):
```yaml
changes:
  name: Detect Changes
  runs-on: ubuntu-latest
  permissions:
    contents: read
    pull-requests: read
  outputs:
    backend: ${{ steps.filter.outputs.backend }}
    frontend: ${{ steps.filter.outputs.frontend }}
    e2e: ${{ steps.filter.outputs.e2e }}
  steps:
    - uses: actions/checkout@v4
    - uses: dorny/paths-filter@v3
      id: filter
      with:
        filters: |
          backend:
            - 'backend/**'
            ...
```

**Apply** — add `cli` to outputs and filters (per RESEARCH lines 1095-1109):
```yaml
outputs:
  ...
  cli: ${{ steps.filter.outputs.cli }}
...
filters: |
  ...
  cli:
    - 'cli/**'
    - 'sdks/python/**'
```

**Existing `sdks-check` job header** (`.github/workflows/ci.yml` lines 105-142) — copy structure:
```yaml
sdks-check:
  name: SDKs Drift Gate
  needs: changes
  if: needs.changes.outputs.backend == 'true' || github.event_name == 'push'
  runs-on: ubuntu-latest
  env:
    JWT_SECRET_KEY: sdks-check-padding-key-32characters-here
    PYTHONPATH: backend
  steps:
    - uses: actions/checkout@v4
    - uses: astral-sh/setup-uv@v6
      with:
        version: "0.10.2"
        enable-cache: true
        cache-dependency-glob: "backend/uv.lock"
    - uses: actions/setup-python@v5
      with:
        python-version: "3.13"
    ...
```

**Apply to new `cli-test` job** (RESEARCH lines 1056-1093) — copy the same `astral-sh/setup-uv@v6` + `actions/setup-python@v5` step pattern; gate on `needs.changes.outputs.cli == 'true' || needs.changes.outputs.backend == 'true'`. Add the OCCLI-06 static check inline:
```yaml
- name: Static OCCLI-06 check (no httpx/requests in CLI)
  working-directory: cli
  run: |
    if grep -rE '^(import|from) (httpx|requests)' geolens_cli/; then
      echo "FAIL: CLI imports httpx or requests directly (OCCLI-06)"; exit 1
    fi
```

---

### `.github/workflows/publish-cli.yml` (NEW, manual publish workflow)

**Analog:** `.github/workflows/publish-sdks.yml` — exact template, especially the `publish-python` job.

**Workflow header + dispatch trigger** (`.github/workflows/publish-sdks.yml` lines 1-29):
```yaml
# Manual-trigger publish workflow for the GeoLens SDKs.
# Phase 215 ships the workflow; running it requires:
#   1. PyPI token in repo secret PYPI_TOKEN ...
# See docs/sdks.md for the full first-publish runbook.
name: Publish SDKs

on:
  workflow_dispatch:
    inputs:
      target:
        description: 'Which SDK to publish'
        required: true
        type: choice
        options:
          - python
          - typescript
          - both
        default: 'both'
      dry_run:
        description: 'Build only, do not publish'
        required: false
        type: boolean
        default: false

permissions:
  contents: read
  id-token: write  # for PyPI Trusted Publishing (future migration)
```

**Apply to publish-cli.yml:** simpler — only one target. Drop the `target` choice; keep `dry_run`. Reference `docs/cli.md` instead of `docs/sdks.md`.

**`publish-python` job — exact template** (`.github/workflows/publish-sdks.yml` lines 32-60):
```yaml
publish-python:
  if: inputs.target == 'python' || inputs.target == 'both'
  name: Publish Python SDK to PyPI
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4

    - uses: astral-sh/setup-uv@v6
      with:
        version: "0.10.2"

    - uses: actions/setup-python@v5
      with:
        python-version: "3.13"

    - name: Build wheel + sdist
      working-directory: sdks/python
      run: uv build

    - name: List built artifacts
      working-directory: sdks/python
      run: ls -la dist/

    - name: Publish to PyPI
      if: ${{ !inputs.dry_run }}
      working-directory: sdks/python
      env:
        UV_PUBLISH_TOKEN: ${{ secrets.PYPI_TOKEN }}
      run: uv publish
```

**CLI substitutions:** drop the `target` conditional (only one target); change `working-directory: sdks/python` → `working-directory: cli`; everything else identical including `UV_PUBLISH_TOKEN: ${{ secrets.PYPI_TOKEN }}` (D-40).

---

### `docs/cli.md` (NEW, user-facing CLI manual)

**Analog:** `docs/sdks.md` (305 lines) — exact structural template per CONTEXT.md D-42.

**Section structure** (extracted from `docs/sdks.md`):
1. **Header + license/source table** (lines 1-11)
2. **Installation** (lines 12-32) — `pip install geolens` / `uv add geolens` (D-42)
3. **Quickstart** (lines 33-111) — login → publish → export (D-42)
4. **Why these generators?** → **Why this CLI?** (lines 113-120) — Typer + rich + keyring rationale
5. **Regeneration** → not applicable; **Lockstep version policy** (lines 168-178) — applies as-is to CLI
6. **Drift gate** (lines 148-166) — replace with "CLI drift caught by `make sdks-check` (sync_sdk_versions extension)"
7. **Publishing** (lines 180-223) — copy `publish-sdks.yml` runbook, swap to `publish-cli.yml`
8. **Known rough edges** (lines 225-282) — replace with CLI-specific: keyring on headless Linux, `tomllib` 3.11 floor, OCCLI-06 dep-list invariant
9. **Troubleshooting** (lines 284-294) — table format
10. **References** (lines 296-301)

**Quickstart code-block style** (`docs/sdks.md` lines 35-58):
```python
from geolens_sdk import GeolensClient
...
client = GeolensClient(
    base_url="https://geolens.example.com",
    bearer_token="<JWT>",
)

response = search_datasets_endpoint_search_datasets_get.sync_detailed(
    client=client.client,
    body=None,
)
```

**Apply to CLI:** swap to shell snippets:
```bash
pip install geolens
geolens login https://geolens.example.com
geolens scan ./data
geolens publish ./data/cities.geojson
geolens export stac <dataset-id> -o cities.stac.json
```

**Troubleshooting table style** (`docs/sdks.md` lines 286-294):
```markdown
| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `ImportError: cannot import name 'GeolensClient'` | Stale package version | `pip install --upgrade geolens-sdk` |
| ...
```

**Apply CLI-specific rows:** keyring `NoKeyringError` → `--no-keyring`; expired token → `geolens login` again; `--version` shows `0.0.0+dev` → not installed (RESEARCH Example D fallback).

---

## Shared Patterns

### Apache-2.0 license discipline
**Source:** root `LICENSE` (verbatim copied to `sdks/python/LICENSE`)
**Apply to:** `cli/LICENSE` — byte-for-byte copy, no edits. Per CONTEXT.md "Established Patterns" line 297.

### `from __future__ import annotations` header
**Source:** every hand-maintained module in the repo (`sdks/python/geolens_sdk/auth.py:14`, `backend/tests/test_sdks_round_trip.py:31`, `scripts/sync_sdk_versions.py:19`)
**Apply to:** every new `cli/geolens_cli/*.py` and every new `cli/tests/test_*.py` file. First import line under the docstring.

### Lockstep version pin (no hardcoded version strings)
**Source:** `scripts/sync_sdk_versions.py` lines 50-62 (the `_replace_pyproject_version` regex)
```python
pattern = re.compile(r'^version = "[^"]*"$', re.MULTILINE)
new_text, count = pattern.subn(f'version = "{version}"', text)
if count != 1:
    sys.stderr.write(...)
    sys.exit(1)
```
**Apply to:** `cli/pyproject.toml` MUST have exactly one `version = "..."` line at the [project] level. NEVER write a version string anywhere else (no `__version__ = "1.0.0"` literals — use `importlib.metadata` per RESEARCH Example D).

### "Hand-maintained — NOT regenerated" docstring marker
**Source:** `sdks/python/geolens_sdk/auth.py` lines 3-5
```python
"""...

Hand-maintained — NOT regenerated by `make sdks`. The drift gate explicitly
excludes this file via `:!sdks/python/geolens_sdk/auth.py` in the Makefile.
"""
```
**Apply to:** every `cli/geolens_cli/*.py` module's top-level docstring — the CLI is fully hand-maintained; the marker helps future maintainers and matches project precedent.

### Module-level skip guard for missing source trees
**Source:** `backend/tests/test_sdks_round_trip.py` lines 47-66
```python
if not (_SDK_PY_PATH / "geolens_sdk" / "auth.py").is_file():
    pytest.skip(
        "geolens_sdk source tree not present at "
        f"{_SDK_PY_PATH} (expected when running inside the api container; "
        "host pytest and full-checkout CI runners exercise this module)",
        allow_module_level=True,
    )
```
**Apply to:** `backend/tests/test_cli_round_trip.py` — duplicate the guard for both `sdks/python/` AND `cli/` paths (RESEARCH Pattern 6 lines 452-462). Same docker-container-skip semantics.

### Drift-gate exempt path discipline
**Source:** `Makefile` lines 95-105 (`sdks-check` `:!` pathspecs)
**Apply to:** `cli/` is fully hand-maintained — no generator touches it — so no `:!cli/...` pathspecs are needed in `sdks-check`. Document in plan that the drift gate's only relationship to CLI is **version sync** (sync_sdk_versions.py writes `cli/pyproject.toml` `version =`; if stale, `git diff --exit-code` in `sdks-check` flags it).

### Manual-trigger workflow_dispatch + `secrets.PYPI_TOKEN`
**Source:** `.github/workflows/publish-sdks.yml` lines 9-29, 55-60
**Apply to:** `.github/workflows/publish-cli.yml` — Phase 215 D-16 / Phase 216 D-40 establish manual-trigger as v13.1 default. NEVER auto-publish on push or tag.

### Lazy-import discipline for CLI startup
**Source:** `backend/scripts/dump_openapi.py` lines 22-26 + RESEARCH Anti-Patterns (line 541)
```python
def _load_spec() -> dict:
    # Imported lazily so --help / argparse can run without a DB.
    from app.api.main import app
    return app.openapi()
```
**Apply to:** every CLI command's body — defer SDK imports until the command actually runs. `geolens --version` and `geolens --help` MUST NOT import `geolens_sdk` at module top.

### OCCLI-06 structural enforcement
**Source:** CONTEXT.md D-04, RESEARCH Pattern 3 verification block (line 358)
**Apply to:** every CLI source file. Two enforcement layers:
1. `cli/pyproject.toml` `[project] dependencies` MUST NOT contain `httpx` or `requests`.
2. Static grep in CI: `grep -rE '^(import|from) (httpx|requests)' cli/geolens_cli/` returns zero matches. Job step in `.github/workflows/ci.yml` `cli-test` (RESEARCH lines 1081-1085).

---

## No Analog Found

Files with no close match in the codebase (planner should use RESEARCH.md patterns directly):

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `cli/geolens_cli/main.py` | entrypoint | request-response | No Typer in repo (rejected argparse precedent in `dump_openapi.py`). RESEARCH Pattern 1 is the source. |
| `cli/geolens_cli/scan.py` | command module | file-I/O | No filesystem-walk-and-classify code in repo. RESEARCH Example C is the source. |
| `cli/geolens_cli/output.py` | utility | transform | No `rich`-based formatter in repo. RESEARCH Pattern 2 + Don't-Hand-Roll guidance. |
| `cli/geolens_cli/_sdk_helpers.py` | utility | transform | No HTTP-error → exit-code translator in repo. RESEARCH Pattern 2. |

---

## Metadata

**Analog search scope:**
- `sdks/python/` (Phase 215 sibling package — primary analog source)
- `backend/tests/` (round-trip + conftest patterns)
- `backend/scripts/` (Python script entrypoint precedent)
- `scripts/` (version-sync script — extension target)
- `Makefile` (recipe shapes)
- `.github/workflows/` (CI + publish workflows)
- `docs/` (user-doc structural template)

**Files scanned:** 14 read in full (CONTEXT.md, RESEARCH.md, sdks/python/{pyproject.toml, README.md, LICENSE, geolens_sdk/{__init__.py, auth.py}, geolens_sdk/api/auth/login_auth_login_post.py}, scripts/sync_sdk_versions.py, backend/tests/test_sdks_round_trip.py, backend/scripts/dump_openapi.py, .github/workflows/{publish-sdks.yml, ci.yml}, docs/sdks.md, Makefile) + 2 partial (backend/tests/conftest.py for fixture shapes only).

**Pattern extraction date:** 2026-04-27

**Key invariants for the planner:**
1. Every CLI file gets `from __future__ import annotations` + a "Hand-maintained" docstring marker.
2. `cli/pyproject.toml` `version =` is the ONLY place a version string appears in the CLI tree (everywhere else uses `importlib.metadata.version("geolens")`).
3. `sync_sdk_versions.py` is the version-sync hub — extending it is the cheapest path to drift-gate coverage.
4. `backend/tests/test_cli_round_trip.py` mirrors `test_sdks_round_trip.py` byte-for-byte in structure (module guard, `_wire_asgi_transport`, `client` + `admin_auth_header` fixtures from `conftest.py`).
5. `publish-cli.yml` is a single-job stripped-down clone of `publish-sdks.yml`'s `publish-python` job.
6. `docs/cli.md` follows `docs/sdks.md`'s 10-section outline exactly.
7. OCCLI-06 enforcement is dep-list + static grep — both go in CI.
