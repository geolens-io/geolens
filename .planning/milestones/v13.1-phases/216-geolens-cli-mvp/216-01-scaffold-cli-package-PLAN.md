---
phase: 216-geolens-cli-mvp
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - cli/pyproject.toml
  - cli/LICENSE
  - cli/README.md
  - cli/.gitignore
  - cli/geolens_cli/__init__.py
  - cli/geolens_cli/main.py
  - cli/geolens_cli/output.py
  - cli/geolens_cli/_sdk_helpers.py
  - cli/tests/__init__.py
  - cli/tests/conftest.py
  - cli/tests/test_version.py
  - cli/tests/test_output.py
  - cli/tests/test_exit_codes.py
  - Makefile
autonomous: true
requirements:
  - OCCLI-01
  - OCCLI-06
must_haves:
  decisions_covered:
    - "D-01: Top-level `cli/` directory sibling to `sdks/python/` and `sdks/typescript/` (Apache-2.0, own pyproject.toml)"
    - "D-02: PyPI distribution name `geolens`, importable as `geolens_cli`, console-script `geolens = geolens_cli.main:app`"
    - "D-03: Lockstep versioning with `geolens-sdk` and backend OpenAPI version (sync extension lands in Plan 06)"
    - "D-04: CLI depends on `geolens-sdk` via `>=X.Y.Z,<X.(Y+1).0` range; no direct httpx/requests deps"
    - "D-05: Typer as CLI framework (type-hint-driven, integrates with rich)"
    - "D-06: Subcommand structure with global `--json`/`-v`/`-q`/`--instance` flags and `export` sub-app"
    - "D-07: No interactive shell or autocompletion bootstrap in MVP"
  truths:
    - "Apache-2.0 `geolens` package is buildable as a wheel + sdist via `cd cli && uv build`"
    - "`geolens --version` prints `geolens <version>` and exits 0 (without loading config or constructing the SDK)"
    - "`geolens --help` lists the planned subcommand stubs (login, logout, whoami, scan, publish, export)"
    - "Console-script entry point `geolens = geolens_cli.main:app` is registered in pyproject.toml"
    - "Wave 0 test infrastructure (CliRunner fixture, mock_keyring fixture, tmp_xdg_home fixture) exists and is importable"
    - "OCCLI-06 invariant holds today: zero `import httpx` / `import requests` lines in `cli/geolens_cli/`"
  artifacts:
    - path: cli/pyproject.toml
      provides: "package manifest, console-script entry, pytest config, dependency declarations"
      contains: "[project.scripts]"
    - path: cli/LICENSE
      provides: "Apache-2.0 license text byte-copied from sdks/python/LICENSE"
      min_lines: 200
    - path: cli/README.md
      provides: "PyPI-facing README"
    - path: cli/geolens_cli/__init__.py
      provides: "__version__ via importlib.metadata, with PackageNotFoundError fallback"
      contains: "importlib.metadata"
    - path: cli/geolens_cli/main.py
      provides: "Typer app + global @callback + AppState dataclass + export sub-app + version_callback (is_eager=True)"
      contains: "app = typer.Typer"
    - path: cli/geolens_cli/output.py
      provides: "Formatter class (rich Console + JSON) + EXIT_* constants"
    - path: cli/geolens_cli/_sdk_helpers.py
      provides: "unwrap() Response→T translator + call_sdk() httpx-error mapper"
    - path: cli/tests/conftest.py
      provides: "shared fixtures: runner, tmp_xdg_home, mock_keyring"
      contains: "CliRunner"
    - path: Makefile
      provides: "cli-build + cli-test recipes; .PHONY extended"
      contains: "cli-test:"
  key_links:
    - from: "cli/pyproject.toml"
      to: "geolens_cli.main:app"
      via: "[project.scripts] geolens entry"
      pattern: "geolens = \"geolens_cli.main:app\""
    - from: "cli/geolens_cli/__init__.py"
      to: "cli/pyproject.toml"
      via: "importlib.metadata.version('geolens')"
      pattern: "importlib.metadata"
    - from: "cli/geolens_cli/main.py"
      to: "geolens_cli.output, geolens_cli._sdk_helpers"
      via: "intra-package imports for Formatter + exit codes"
      pattern: "from \\. import"
---

<objective>
Scaffold the `cli/` top-level package as a sibling to `sdks/python/` with the Apache-2.0 manifest, Typer app shell, version export, output formatter, SDK-call helper, Wave 0 test infrastructure, and Makefile recipes. After this plan: `geolens --version` and `geolens --help` work; the wheel builds; the test harness is ready for downstream plans to populate.

Purpose: Establish the package boundary and tooling that closes OCCLI-01 (Apache-2.0 PyPI package, `geolens --version`) and structurally enforces OCCLI-06 (no `httpx`/`requests` direct deps in pyproject; CI grep gate added in Plan 06). Every later plan in Phase 216 plugs into the AppState + Formatter + unwrap() helpers established here.

Output: Buildable `cli/` package with stubs for every subcommand (login/logout/whoami/scan/publish/export stac), Wave 0 test files (test_version.py, test_output.py, test_exit_codes.py, conftest.py), and Makefile targets `cli-build` + `cli-test`.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/216-geolens-cli-mvp/216-CONTEXT.md
@.planning/phases/216-geolens-cli-mvp/216-RESEARCH.md
@.planning/phases/216-geolens-cli-mvp/216-PATTERNS.md
@.planning/phases/216-geolens-cli-mvp/216-VALIDATION.md
@sdks/python/pyproject.toml
@sdks/python/README.md
@sdks/python/geolens_sdk/__init__.py
@sdks/python/LICENSE

<interfaces>
<!-- Public surface from sdks/python/geolens_sdk that this scaffold and downstream plans consume -->

From sdks/python/geolens_sdk/__init__.py (Phase 215-05 cp-stash fix):
```python
from geolens_sdk import GeolensClient            # high-level wrapper, bearer/api-key/anonymous
from geolens_sdk import AuthenticatedClient, Client  # generator's underlying clients
```

From sdks/python/geolens_sdk/auth.py — GeolensClient signature (D-10 / D-11):
```python
class GeolensClient:
    def __init__(
        self,
        base_url: str,
        *,
        bearer_token: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        # Raises ValueError if both bearer_token and api_key provided.
        # .client property exposes the underlying AuthenticatedClient/Client.
```

From sdks/python/geolens_sdk/types.py:
```python
class Response[T]:
    status_code: HTTPStatus
    content: bytes
    headers: Headers
    parsed: Optional[T]
```

From sdks/python/geolens_sdk/models/problem_detail.py — ProblemDetail (RFC 7807 error shape returned by SDK on non-2xx).

From AuthenticatedClient (used by lower-level multipart workaround in Plan 04):
```python
client.get_httpx_client() -> httpx.Client       # returns the SDK-owned httpx client (sync)
client.get_async_httpx_client() -> httpx.AsyncClient
client.set_httpx_client(c: httpx.Client) -> None
client.set_async_httpx_client(c: httpx.AsyncClient) -> None
```

These are the contracts every downstream Plan 02/04/05 will use.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Create cli/ package manifest, license, README, gitignore</name>
  <files>cli/pyproject.toml, cli/LICENSE, cli/README.md, cli/.gitignore</files>
  <read_first>
    - sdks/python/pyproject.toml (lines 1-37 — exact template; copy verbatim with name/version/deps/scripts substitutions per PATTERNS.md §`cli/pyproject.toml`)
    - sdks/python/LICENSE (byte-copy target)
    - sdks/python/README.md (lines 1-16 — full template per PATTERNS.md)
    - sdks/python/.gitignore (template — drop `.venv/` and `uv.lock` for library packages per Phase 215-05)
    - .planning/phases/216-geolens-cli-mvp/216-CONTEXT.md (D-01, D-02, D-04, D-12 — package layout, console-script entry, dependency floor)
    - .planning/phases/216-geolens-cli-mvp/216-RESEARCH.md (Standard Stack table — exact dep version pins; Pitfall 3 — Python 3.11 floor decision)
    - .planning/phases/216-geolens-cli-mvp/216-PATTERNS.md (§`cli/pyproject.toml` — exact substitutions to apply)
  </read_first>
  <behavior>
    - cli/pyproject.toml: declares name="geolens", license=Apache-2.0, requires-python=">=3.11", console-script `geolens = "geolens_cli.main:app"`, hatch wheel package=["geolens_cli"], pytest testpaths=["tests"], EXACT dependency pins from RESEARCH (no httpx, no requests)
    - cli/LICENSE: Apache-2.0 text identical (byte-for-byte) to sdks/python/LICENSE
    - cli/README.md: PyPI-facing quickstart (~16 lines) per PATTERNS.md template with shell snippets (pip install / login / scan / publish / export stac)
    - cli/.gitignore: contains `.venv/`, `uv.lock`, `dist/`, `__pycache__/`, `*.egg-info/`
  </behavior>
  <action>
    Create `cli/pyproject.toml` with the EXACT content below (substitutions applied from PATTERNS.md §`cli/pyproject.toml`):
    ```toml
    [build-system]
    requires = ["hatchling"]
    build-backend = "hatchling.build"

    [project]
    name = "geolens"
    version = "1.0.0"
    description = "Apache-2.0 command-line interface for the GeoLens API. Login, scan, publish, and export STAC against any GeoLens instance."
    readme = "README.md"
    license = { text = "Apache-2.0" }
    requires-python = ">=3.11"
    authors = [{ name = "GeoLens", email = "noreply@geolens.io" }]
    keywords = ["geolens", "geospatial", "cli", "stac", "openapi"]
    classifiers = [
      "Development Status :: 4 - Beta",
      "Environment :: Console",
      "Intended Audience :: Developers",
      "Intended Audience :: Science/Research",
      "License :: OSI Approved :: Apache Software License",
      "Operating System :: OS Independent",
      "Programming Language :: Python :: 3",
      "Programming Language :: Python :: 3.11",
      "Programming Language :: Python :: 3.12",
      "Programming Language :: Python :: 3.13",
      "Topic :: Scientific/Engineering :: GIS",
    ]
    dependencies = [
      "typer>=0.25.0,<0.26.0",
      "rich>=14.0.0,<16.0.0",
      "keyring>=25.0.0,<26.0.0",
      "tomli_w>=1.0.0,<2.0.0",
      "platformdirs>=4.0.0,<5.0.0",
      "structlog>=25.0.0,<26.0.0",
      "geolens-sdk>=1.0.0,<2.0.0",
    ]

    [project.optional-dependencies]
    dev = [
      "pytest>=9.0.0,<10.0.0",
    ]

    [project.scripts]
    geolens = "geolens_cli.main:app"

    [project.urls]
    Homepage = "https://github.com/geolens-io/geolens"
    Repository = "https://github.com/geolens-io/geolens"
    Documentation = "https://github.com/geolens-io/geolens/blob/main/docs/cli.md"

    [tool.hatch.build.targets.wheel]
    packages = ["geolens_cli"]

    [tool.pytest.ini_options]
    testpaths = ["tests"]
    ```

    Create `cli/LICENSE` by byte-copying `sdks/python/LICENSE` (the Apache-2.0 standard text). DO NOT modify, regenerate, or "format" — the contents must be identical to enable tooling that diffs licenses. Use `cp sdks/python/LICENSE cli/LICENSE` semantics via the Write tool (read sdks/python/LICENSE first, write the same content to cli/LICENSE).

    Create `cli/README.md`:
    ```markdown
    # geolens (CLI)

    Apache-2.0 command-line interface for the [GeoLens](https://github.com/geolens-io/geolens) API.

    Login, scan local directories of spatial data, publish vector or raster files, and export STAC metadata against any GeoLens instance — community or enterprise.

    See `docs/cli.md` in the GeoLens repo for the full command reference.

    ## Quickstart

    ```bash
    pip install geolens
    geolens login https://geolens.example.com
    geolens scan ./data
    geolens publish ./data/cities.geojson
    geolens export stac <dataset-id> -o cities.stac.json
    ```

    The CLI consumes the [`geolens-sdk`](https://github.com/geolens-io/geolens/blob/main/docs/sdks.md) Python package — there is no hand-rolled HTTP client.
    ```

    Create `cli/.gitignore`:
    ```
    .venv/
    uv.lock
    dist/
    build/
    *.egg-info/
    __pycache__/
    .pytest_cache/
    .ruff_cache/
    ```
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && python -c "import tomllib; d=tomllib.load(open('cli/pyproject.toml','rb')); deps=d['project']['dependencies']; assert d['project']['name']=='geolens', d['project']['name']; assert d['project']['license']=={'text':'Apache-2.0'}; assert d['project']['scripts']['geolens']=='geolens_cli.main:app'; assert d['project']['requires-python']=='>=3.11'; assert not any('httpx' in x or 'requests' in x for x in deps), deps; assert any('geolens-sdk' in x for x in deps); assert any('typer' in x for x in deps); assert any('rich' in x for x in deps); assert any('keyring' in x for x in deps); assert any('tomli_w' in x for x in deps); assert any('platformdirs' in x for x in deps); assert any('structlog' in x for x in deps); print('OK')"</automated>
    <automated>diff /Users/ishiland/Code/geolens/cli/LICENSE /Users/ishiland/Code/geolens/sdks/python/LICENSE</automated>
    <automated>test -f /Users/ishiland/Code/geolens/cli/README.md && grep -q "geolens (CLI)" /Users/ishiland/Code/geolens/cli/README.md && grep -q "Apache-2.0" /Users/ishiland/Code/geolens/cli/README.md && grep -q "pip install geolens" /Users/ishiland/Code/geolens/cli/README.md</automated>
    <automated>grep -q "^.venv/$" /Users/ishiland/Code/geolens/cli/.gitignore && grep -q "^uv.lock$" /Users/ishiland/Code/geolens/cli/.gitignore && grep -q "^dist/$" /Users/ishiland/Code/geolens/cli/.gitignore</automated>
  </verify>
  <acceptance_criteria>
    - cli/pyproject.toml exists with `name = "geolens"` exactly
    - cli/pyproject.toml has `license = { text = "Apache-2.0" }`
    - cli/pyproject.toml has `requires-python = ">=3.11"`
    - cli/pyproject.toml `[project].dependencies` contains `typer`, `rich`, `keyring`, `tomli_w`, `platformdirs`, `structlog`, `geolens-sdk`
    - cli/pyproject.toml `[project].dependencies` contains NO `httpx` and NO `requests` substrings (OCCLI-06 structural)
    - cli/pyproject.toml `[project.scripts]` defines `geolens = "geolens_cli.main:app"`
    - cli/pyproject.toml `[tool.hatch.build.targets.wheel].packages` equals `["geolens_cli"]`
    - cli/pyproject.toml `[tool.pytest.ini_options].testpaths` equals `["tests"]`
    - cli/LICENSE is byte-identical to sdks/python/LICENSE (`diff` exit 0)
    - cli/README.md contains heading `# geolens (CLI)` and the strings `Apache-2.0`, `pip install geolens`, `docs/cli.md`
    - cli/.gitignore contains lines `.venv/`, `uv.lock`, `dist/`
  </acceptance_criteria>
  <done>cli/ has the canonical Apache-2.0 manifest with locked dep pins, the console-script entry, pytest config, byte-identical LICENSE, PyPI-facing README, and gitignore. Validators confirm OCCLI-06 invariant in dep list.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Create geolens_cli package modules — __init__, main, output, _sdk_helpers</name>
  <files>cli/geolens_cli/__init__.py, cli/geolens_cli/main.py, cli/geolens_cli/output.py, cli/geolens_cli/_sdk_helpers.py</files>
  <read_first>
    - sdks/python/geolens_sdk/__init__.py (lines 1-23 — module docstring + re-export style)
    - sdks/python/geolens_sdk/auth.py (lines 1-71 — "Hand-maintained — NOT regenerated" docstring marker, GeolensClient ValueError-on-both gate)
    - .planning/phases/216-geolens-cli-mvp/216-RESEARCH.md (Pattern 1 lines 173-233 verbatim — main.py Typer app skeleton; Pattern 2 lines 245-298 verbatim — _sdk_helpers; Example D lines 893-906 verbatim — __init__.py importlib.metadata; Pitfall 9 — is_eager=True is mandatory)
    - .planning/phases/216-geolens-cli-mvp/216-PATTERNS.md (§`cli/geolens_cli/__init__.py`, §`cli/geolens_cli/main.py`, §`cli/geolens_cli/output.py`, §`cli/geolens_cli/_sdk_helpers.py`)
    - .planning/phases/216-geolens-cli-mvp/216-CONTEXT.md (D-29, D-30, D-31, D-32, D-33 — output formatter + exit-code matrix)
    - backend/scripts/dump_openapi.py (lines 22-26 — lazy-import precedent)
  </read_first>
  <behavior>
    - `geolens --version` exits 0 and prints `geolens <version>` (no config load, no SDK construction)
    - `geolens --help` exits 0 and shows top-level help text including "export" sub-app
    - `from geolens_cli import __version__` returns a non-empty string (real version when installed; `0.0.0+dev` fallback in editable/dev tree)
    - `from geolens_cli._sdk_helpers import unwrap, call_sdk, EXIT_AUTH, EXIT_NETWORK, EXIT_SERVER` succeeds; constants equal 3, 4, 5 respectively per D-32
    - Stub commands `login`, `logout`, `whoami`, `scan`, `publish`, and `export stac` exist and raise typer.Exit(2) with "not yet implemented" message (so test_exit_codes.py can verify the matrix shape)
  </behavior>
  <action>
    Create `cli/geolens_cli/__init__.py` per RESEARCH Example D (lines 893-906):
    ```python
    """GeoLens CLI.

    Hand-maintained — NOT regenerated. Version is sourced from package metadata
    so cli/pyproject.toml is the single source of truth for the version string.
    """
    from __future__ import annotations

    from importlib.metadata import PackageNotFoundError, version as _pkg_version

    try:
        __version__ = _pkg_version("geolens")
    except PackageNotFoundError:
        # Local dev tree before `pip install -e .` — fall back to a sentinel.
        __version__ = "0.0.0+dev"

    __all__ = ["__version__"]
    ```

    Create `cli/geolens_cli/output.py` (greenfield — no in-repo analog; per RESEARCH Don't-Hand-Roll table):
    ```python
    """Output formatter — rich Console + JSON mode + exit-code constants.

    Hand-maintained — NOT regenerated. Centralizes stdout/stderr formatting so
    every command respects --json / --quiet / --verbose / NO_COLOR.
    """
    from __future__ import annotations

    import json as _json
    import os
    import sys
    from dataclasses import dataclass
    from typing import Any

    import typer
    from rich.console import Console


    @dataclass
    class Formatter:
        json_mode: bool = False
        quiet: bool = False
        verbose: bool = False

        def __post_init__(self) -> None:
            no_color = bool(os.environ.get("NO_COLOR"))
            self._stdout = Console(no_color=no_color, file=sys.stdout, force_terminal=False if self.json_mode else None)
            self._stderr = Console(no_color=no_color, file=sys.stderr, stderr=True, force_terminal=False if self.json_mode else None)

        @property
        def is_tty(self) -> bool:
            return sys.stdout.isatty() and not self.json_mode

        @property
        def console_stdout(self) -> Console:
            """Public accessor for the underlying stdout Console.

            Used by commands that need to render rich primitives (tables, trees)
            beyond the success/error/info/json/debug message helpers — e.g.,
            Plan 03 (scan) renders a rich.Table for human output.
            """
            return self._stdout

        def success(self, message: str) -> None:
            if self.json_mode:
                typer.echo(_json.dumps({"ok": True, "message": message}))
                return
            if not self.quiet:
                self._stdout.print(message)

        def error(self, message: str) -> None:
            if self.json_mode:
                typer.echo(_json.dumps({"ok": False, "error": message}), err=True)
                return
            self._stderr.print(f"[red]Error:[/red] {message}")

        def json(self, payload: Any) -> None:
            typer.echo(_json.dumps(payload, indent=2 if self.is_tty else None, sort_keys=True, default=str))

        def info(self, message: str) -> None:
            if self.json_mode or self.quiet:
                return
            self._stdout.print(message)

        def debug(self, message: str) -> None:
            if self.verbose and not self.json_mode:
                self._stderr.print(f"[dim]debug:[/dim] {message}")
    ```

    Create `cli/geolens_cli/_sdk_helpers.py` per RESEARCH Pattern 2 lines 245-298 verbatim:
    ```python
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
    ```

    Create `cli/geolens_cli/main.py` per RESEARCH Pattern 1 lines 173-233 verbatim, EXTENDED with stub commands so test_exit_codes.py can run before Plans 02/03/04/05 land:
    ```python
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
    ```

    Note: in main.py `--version` uses `is_eager=True` (RESEARCH Pitfall 9 — mandatory).
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv pip install -e ../sdks/python --quiet 2>/dev/null || true; cd /Users/ishiland/Code/geolens/cli && uv pip install -e . --quiet 2>/dev/null && uv run python -c "from geolens_cli import __version__; print(__version__)" | grep -E "^(0\.0\.0\+dev|[0-9]+\.[0-9]+\.[0-9]+)$"</automated>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run python -c "from geolens_cli._sdk_helpers import unwrap, call_sdk, EXIT_AUTH, EXIT_NETWORK, EXIT_SERVER, EXIT_USAGE, EXIT_GENERIC; assert EXIT_AUTH==3 and EXIT_NETWORK==4 and EXIT_SERVER==5 and EXIT_USAGE==2 and EXIT_GENERIC==1; print('OK')"</automated>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run python -c "from geolens_cli.main import app, AppState; assert app is not None; print('OK')"</automated>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run geolens --version 2>&1 | grep -E "^geolens "</automated>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run geolens --help 2>&1 | grep -E "(login|logout|whoami|scan|publish|export)"</automated>
    <automated>! grep -rE '^(import|from) (httpx|requests)' /Users/ishiland/Code/geolens/cli/geolens_cli/__init__.py /Users/ishiland/Code/geolens/cli/geolens_cli/main.py /Users/ishiland/Code/geolens/cli/geolens_cli/output.py</automated>
  </verify>
  <acceptance_criteria>
    - cli/geolens_cli/__init__.py exports `__version__` via `importlib.metadata` with `PackageNotFoundError` fallback to `"0.0.0+dev"`
    - cli/geolens_cli/__init__.py contains `from __future__ import annotations`
    - cli/geolens_cli/main.py contains `app = typer.Typer(`
    - cli/geolens_cli/main.py contains `export_app = typer.Typer(`
    - cli/geolens_cli/main.py contains `app.add_typer(export_app, name="export")`
    - cli/geolens_cli/main.py `_version_callback` is registered with `is_eager=True` (Pitfall 9)
    - cli/geolens_cli/main.py defines stub commands: `login`, `logout`, `whoami`, `scan`, `publish`, `export stac`
    - cli/geolens_cli/_sdk_helpers.py exports `unwrap`, `call_sdk`, `EXIT_OK=0`, `EXIT_GENERIC=1`, `EXIT_USAGE=2`, `EXIT_AUTH=3`, `EXIT_NETWORK=4`, `EXIT_SERVER=5`
    - cli/geolens_cli/output.py defines `Formatter` dataclass with `success`, `error`, `json`, `info`, `debug`, `is_tty`, `console_stdout` members
    - `geolens --version` exits 0 with output matching `^geolens .+$`
    - `geolens --help` lists `login`, `logout`, `whoami`, `scan`, `publish`, `export` (verified by grep)
    - Zero `^(import|from) (httpx|requests)` lines in `__init__.py`, `main.py`, `output.py` (httpx exception imports in `_sdk_helpers.py` are intentional and explicitly documented)
  </acceptance_criteria>
  <done>The package imports cleanly, `geolens --version` and `geolens --help` work without config or SDK construction, the SDK helpers + Formatter are ready for downstream plans, and the OCCLI-06 invariant holds in this scaffold (output.py, main.py, __init__.py have zero httpx/requests imports; _sdk_helpers.py has only the documented exception-type imports).</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Wave 0 test infrastructure — conftest, test_version, test_output, test_exit_codes; Makefile recipes</name>
  <files>cli/tests/__init__.py, cli/tests/conftest.py, cli/tests/test_version.py, cli/tests/test_output.py, cli/tests/test_exit_codes.py, Makefile</files>
  <read_first>
    - .planning/phases/216-geolens-cli-mvp/216-VALIDATION.md (Wave 0 Requirements section — full list of fixtures + test files this plan must seed)
    - .planning/phases/216-geolens-cli-mvp/216-RESEARCH.md (Pattern 6 lines 466-475 — in_memory_keyring fixture; lines 522-533 — CliRunner invocation)
    - .planning/phases/216-geolens-cli-mvp/216-PATTERNS.md (§`cli/tests/conftest.py`, §`cli/tests/test_*.py`)
    - backend/tests/test_sdks_round_trip.py (lines 111-154 — class-grouped unit-test pattern style)
    - Makefile (lines 1, 109-115 — existing .PHONY line + sdks-test/publish-sdks-py recipes; PATTERNS.md §`Makefile`)
    - .planning/phases/216-geolens-cli-mvp/216-CONTEXT.md (D-32 — exit-code matrix)
  </read_first>
  <behavior>
    - `cd cli && uv run pytest -x` exits 0 with all Task 3 tests passing
    - `make cli-test` runs unit tests AND the round-trip test (round-trip will skip until Plan 06 lands the file — graceful skip via test collection)
    - test_version.py asserts: (a) `geolens --version` exits 0, (b) output starts with `"geolens "`, (c) `from geolens_cli import __version__` returns non-empty string
    - test_output.py asserts: (a) `Formatter(json_mode=True).success("x")` emits `{"ok": true, ...}`, (b) NO_COLOR env var disables ANSI, (c) `Formatter(quiet=True).success("x")` emits nothing
    - test_exit_codes.py asserts the matrix per D-32: EXIT_OK=0, EXIT_GENERIC=1, EXIT_USAGE=2, EXIT_AUTH=3, EXIT_NETWORK=4, EXIT_SERVER=5; stub commands all exit with 2 (the "not yet implemented" placeholder)
  </behavior>
  <action>
    Create `cli/tests/__init__.py` as an empty file.

    Create `cli/tests/conftest.py` per RESEARCH Pattern 6 lines 466-475 + PATTERNS.md verbatim:
    ```python
    """Shared pytest fixtures for cli/tests/.

    Hand-maintained — NOT regenerated. Provides CliRunner + tmp_xdg_home +
    mock_keyring fixtures used across every test module in this package.
    """
    from __future__ import annotations

    from pathlib import Path

    import pytest
    from typer.testing import CliRunner


    @pytest.fixture
    def runner() -> CliRunner:
        return CliRunner()


    @pytest.fixture
    def tmp_xdg_home(monkeypatch, tmp_path) -> Path:
        """Point XDG_CONFIG_HOME at a tmp_path so config writes are isolated."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        return tmp_path


    @pytest.fixture
    def mock_keyring(monkeypatch) -> dict:
        """In-memory keyring backend so tests never touch the host keychain."""
        store: dict[tuple[str, str], str] = {}

        def set_password(svc: str, user: str, pwd: str) -> None:
            store[(svc, user)] = pwd

        def get_password(svc: str, user: str) -> str | None:
            return store.get((svc, user))

        def delete_password(svc: str, user: str) -> None:
            store.pop((svc, user), None)

        monkeypatch.setattr("keyring.set_password", set_password)
        monkeypatch.setattr("keyring.get_password", get_password)
        monkeypatch.setattr("keyring.delete_password", delete_password)
        return store
    ```

    Create `cli/tests/test_version.py`:
    ```python
    """OCCLI-01: `geolens --version` prints version and exits 0 (no config, no SDK)."""
    from __future__ import annotations

    from geolens_cli import __version__
    from geolens_cli.main import app


    class TestVersion:
        def test_module_version_is_string(self) -> None:
            assert isinstance(__version__, str)
            assert __version__  # non-empty

        def test_version_flag_prints_and_exits(self, runner) -> None:
            result = runner.invoke(app, ["--version"])
            assert result.exit_code == 0, result.output
            assert result.output.startswith("geolens "), result.output

        def test_help_lists_subcommands(self, runner) -> None:
            result = runner.invoke(app, ["--help"])
            assert result.exit_code == 0, result.output
            for cmd in ("login", "logout", "whoami", "scan", "publish", "export"):
                assert cmd in result.output, f"missing {cmd} in --help"
    ```

    Create `cli/tests/test_output.py`:
    ```python
    """Output formatter — JSON vs human; NO_COLOR honored; quiet/verbose toggles."""
    from __future__ import annotations

    import json
    import os

    import pytest

    from geolens_cli.output import Formatter


    class TestFormatter:
        def test_json_success_emits_json(self, capsys) -> None:
            fmt = Formatter(json_mode=True)
            fmt.success("done")
            out = capsys.readouterr().out.strip()
            payload = json.loads(out)
            assert payload == {"ok": True, "message": "done"}

        def test_json_error_emits_json_to_stderr(self, capsys) -> None:
            fmt = Formatter(json_mode=True)
            fmt.error("boom")
            err = capsys.readouterr().err.strip()
            payload = json.loads(err)
            assert payload == {"ok": False, "error": "boom"}

        def test_quiet_suppresses_success(self, capsys) -> None:
            fmt = Formatter(json_mode=False, quiet=True)
            fmt.success("done")
            assert capsys.readouterr().out == ""

        def test_quiet_does_not_suppress_error(self, capsys) -> None:
            fmt = Formatter(json_mode=False, quiet=True)
            fmt.error("boom")
            assert "boom" in capsys.readouterr().err

        def test_verbose_emits_debug(self, capsys) -> None:
            fmt = Formatter(json_mode=False, verbose=True)
            fmt.debug("hint")
            assert "hint" in capsys.readouterr().err

        def test_no_verbose_silences_debug(self, capsys) -> None:
            fmt = Formatter(json_mode=False, verbose=False)
            fmt.debug("hint")
            assert "hint" not in capsys.readouterr().err

        def test_no_color_env_var_disables_ansi(self, monkeypatch, capsys) -> None:
            monkeypatch.setenv("NO_COLOR", "1")
            fmt = Formatter(json_mode=False)
            fmt.error("boom")
            err = capsys.readouterr().err
            assert "\x1b[" not in err  # no ANSI escape sequences
    ```

    Create `cli/tests/test_exit_codes.py`:
    ```python
    """Exit-code matrix (CONTEXT.md D-32)."""
    from __future__ import annotations

    from geolens_cli._sdk_helpers import (
        EXIT_AUTH,
        EXIT_GENERIC,
        EXIT_NETWORK,
        EXIT_OK,
        EXIT_SERVER,
        EXIT_USAGE,
    )
    from geolens_cli.main import app


    class TestExitCodeConstants:
        def test_constants_match_d32(self) -> None:
            assert EXIT_OK == 0
            assert EXIT_GENERIC == 1
            assert EXIT_USAGE == 2
            assert EXIT_AUTH == 3
            assert EXIT_NETWORK == 4
            assert EXIT_SERVER == 5


    class TestStubCommandsExitWithUsage:
        """Stub bodies in main.py exit with EXIT_USAGE (2) until plans 02-05 land.

        These tests guard the matrix shape; they will be replaced by real
        per-command behavior tests in plans 02-05.
        """

        def test_login_stub_exits_2(self, runner) -> None:
            result = runner.invoke(app, ["login", "https://example.com"])
            assert result.exit_code == 2

        def test_logout_stub_exits_2(self, runner) -> None:
            result = runner.invoke(app, ["logout"])
            assert result.exit_code == 2

        def test_whoami_stub_exits_2(self, runner) -> None:
            result = runner.invoke(app, ["whoami"])
            assert result.exit_code == 2

        def test_scan_stub_exits_2(self, runner, tmp_path) -> None:
            result = runner.invoke(app, ["scan", str(tmp_path)])
            assert result.exit_code == 2

        def test_publish_stub_exits_2(self, runner, tmp_path) -> None:
            f = tmp_path / "x.geojson"
            f.write_text("{}")
            result = runner.invoke(app, ["publish", str(f)])
            assert result.exit_code == 2

        def test_export_stac_stub_exits_2(self, runner) -> None:
            result = runner.invoke(app, ["export", "stac", "abc"])
            assert result.exit_code == 2
    ```

    Modify `Makefile` — extend the `.PHONY` line at line 1 and add the new recipes after `publish-sdks-ts` recipe (per PATTERNS.md §`Makefile`):

    1. Find the existing `.PHONY:` line (line 1) and append `cli-build cli-test cli-check publish-cli` to its targets list.
    2. After the existing `publish-sdks-ts:` recipe block (search for `publish-sdks-ts:` and find the end of that recipe), add the following four recipes:
    ```makefile

    cli-build: ## Build the geolens CLI wheel + sdist
    	cd cli && uv build

    cli-test: ## Run CLI unit tests + round-trip integration test
    	cd cli && uv run pytest -v
    	cd backend && PYTHONPATH=. uv run pytest tests/test_cli_round_trip.py -v

    cli-check: sdks-check ## Alias — version drift in cli/pyproject.toml is caught by sdks-check
    	@echo "cli-check OK (drift gate is sdks-check; sync_sdk_versions extension catches CLI version drift)"

    publish-cli: ## Build + publish geolens CLI to PyPI (requires UV_PUBLISH_TOKEN)
    	cd cli && uv build && uv publish
    ```

    Note: at this plan's commit time `backend/tests/test_cli_round_trip.py` does NOT exist (Plan 06 creates it). The `cli-test` recipe will fail on the second line until Plan 06 lands. This is intentional — downstream plans use `cd cli && uv run pytest -v` for the unit slice, and `make cli-test` only becomes green at end-of-phase. Document this with an inline comment in the recipe:
    ```makefile
    cli-test: ## Run CLI unit tests + round-trip integration test (round-trip lands in Plan 06)
    	cd cli && uv run pytest -v
    	cd backend && PYTHONPATH=. uv run pytest tests/test_cli_round_trip.py -v
    ```
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run pytest tests/test_version.py tests/test_output.py tests/test_exit_codes.py -x -v 2>&1 | tail -30</automated>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run pytest -v 2>&1 | grep -E "(passed|failed)" | tail -5</automated>
    <automated>grep -E "^\.PHONY:.*cli-build.*cli-test" /Users/ishiland/Code/geolens/Makefile</automated>
    <automated>grep -E "^cli-build:" /Users/ishiland/Code/geolens/Makefile && grep -E "^cli-test:" /Users/ishiland/Code/geolens/Makefile && grep -E "^cli-check:" /Users/ishiland/Code/geolens/Makefile && grep -E "^publish-cli:" /Users/ishiland/Code/geolens/Makefile</automated>
    <automated>test -f /Users/ishiland/Code/geolens/cli/tests/conftest.py && grep -q "CliRunner" /Users/ishiland/Code/geolens/cli/tests/conftest.py && grep -q "mock_keyring" /Users/ishiland/Code/geolens/cli/tests/conftest.py && grep -q "tmp_xdg_home" /Users/ishiland/Code/geolens/cli/tests/conftest.py</automated>
    <automated>cd /Users/ishiland/Code/geolens && make cli-build 2>&1 | grep -E "(Successfully|geolens-1.0.0)"</automated>
  </verify>
  <acceptance_criteria>
    - `cd cli && uv run pytest -v` exits 0 with all tests in test_version.py, test_output.py, test_exit_codes.py passing (≥ 18 tests passing total: 3 + 7 + 7)
    - cli/tests/conftest.py defines fixtures `runner`, `tmp_xdg_home`, `mock_keyring`
    - cli/tests/test_version.py contains class `TestVersion` with `test_version_flag_prints_and_exits`, `test_help_lists_subcommands`
    - cli/tests/test_output.py contains class `TestFormatter` with at minimum 6 test methods covering json/quiet/verbose/NO_COLOR
    - cli/tests/test_exit_codes.py asserts EXIT_OK=0, EXIT_GENERIC=1, EXIT_USAGE=2, EXIT_AUTH=3, EXIT_NETWORK=4, EXIT_SERVER=5
    - Makefile `.PHONY` line contains `cli-build`, `cli-test`, `cli-check`, `publish-cli`
    - Makefile contains recipes `cli-build:`, `cli-test:`, `cli-check:`, `publish-cli:` (verified by grep)
    - `make cli-build` succeeds and produces `cli/dist/geolens-1.0.0-py3-none-any.whl` + `cli/dist/geolens-1.0.0.tar.gz`
  </acceptance_criteria>
  <done>Wave 0 unit-test surface is green. The CLI builds. Makefile has cli-build/cli-test/cli-check/publish-cli targets. Plans 02-05 can drop their unit tests into cli/tests/ and run `cd cli && uv run pytest tests/test_<module>.py -x` for the per-task feedback loop documented in VALIDATION.md.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Shell argv → Typer | User input crosses into the Python process; Typer validates types but business-level validation is in commands |
| Build process → PyPI metadata | The wheel/sdist is published; classifiers, license, and dep declarations become public |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-216-04 | Tampering | cli/pyproject.toml dep list | mitigate | Dep list omits `httpx` and `requests`; Plan 06 adds CI grep gate to enforce structurally (OCCLI-06). Validated in Task 1 acceptance criteria via tomllib assertion. |
| T-216-04 | Tampering | cli/geolens_cli/*.py imports | mitigate | This plan establishes the no-direct-httpx-construction discipline; `_sdk_helpers.py` documents the exception-type-only httpx import policy. Plan 06 adds the static grep CI gate. |

**Not Applicable in this plan:**
- T-216-01 (token-at-rest): Not applicable — this plan only ships the package scaffold + stub commands; no credentials are stored. Plan 02 owns credential storage and re-asserts T-216-01.
- T-216-02 (replay): Not applicable — no auth or token handling in this scaffold; stub commands exit with EXIT_USAGE before any HTTP call. Plan 02 owns refresh-retry on 401.
- T-216-03 (file-content spoof): Not applicable — this plan does no file uploads or extension classification. Plans 03 (scan) and 04 (publish) own server-side validation deference.
- T-216-05 (token-in-shell-history): Not applicable — this plan defines no `--token` flag (stub login raises Exit(2) before reading args). Plan 02 owns the `--token` flag and Plan 06 owns the docs/cli.md user-facing warning.
</threat_model>

<verification>
Phase-level checks for this plan:
- `cd cli && uv build` produces wheel + sdist successfully
- `cd cli && uv run pytest -v` exits 0 with ≥18 tests passing
- `geolens --version` and `geolens --help` work without config or SDK construction
- OCCLI-06 dep-list invariant holds: `python -c "import tomllib;d=tomllib.load(open('cli/pyproject.toml','rb'));assert not any('httpx' in x or 'requests' in x for x in d['project']['dependencies'])"` exits 0
- LICENSE byte-identical to sdks/python/LICENSE
</verification>

<success_criteria>
- OCCLI-01 partial: Apache-2.0 PyPI-shaped package builds; `geolens --version` exits 0 with version output (full PyPI publish is a user action per CONTEXT D-40)
- OCCLI-06 partial: dep-list invariant holds in cli/pyproject.toml; downstream plans inherit the AppState/Formatter/SDK-helper discipline; Plan 06 closes the CI grep gate
- Wave 0 test infrastructure ready: 18+ tests passing on the unit slice
- Makefile `cli-build`/`cli-test`/`cli-check`/`publish-cli` recipes wired
</success_criteria>

<output>
After completion, create `.planning/phases/216-geolens-cli-mvp/216-01-SUMMARY.md` capturing: artifacts created, OCCLI-06 invariant evidence, Wave 0 test count, the AppState/Formatter/unwrap interfaces published for downstream plans.
</output>
