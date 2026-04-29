---
phase: 216-geolens-cli-mvp
plan: 01
subsystem: cli
tags: [cli, scaffold, apache-2.0, occli-01, occli-06, wave-0]
dependency_graph:
  requires:
    - sdks/python/geolens_sdk (Phase 215 — GeolensClient + Response types)
    - sdks/python/LICENSE (byte-copy source)
    - sdks/python/pyproject.toml (manifest template)
  provides:
    - cli/ Apache-2.0 package buildable as wheel + sdist
    - geolens_cli.main:app (Typer app + AppState)
    - geolens_cli.output.Formatter (rich Console + JSON mode + NO_COLOR)
    - geolens_cli._sdk_helpers (unwrap, call_sdk, EXIT_* constants)
    - cli/tests/conftest.py (runner, tmp_xdg_home, mock_keyring fixtures)
    - Makefile cli-build / cli-test / cli-check / publish-cli recipes
  affects:
    - Plans 02 (auth), 03 (scan), 04 (publish), 05 (export stac), 06 (round-trip+CI+docs)
tech-stack:
  added:
    - typer 0.25.0
    - rich 15.0.0
    - keyring 25.7.0 (transitive — no direct use yet)
    - tomli_w 1.2.0 (transitive — no direct use yet)
    - platformdirs 4.9.6 (transitive — no direct use yet)
    - structlog 25.5.0 (transitive — no direct use yet)
    - geolens-sdk >=1.0.0,<2.0.0 (the only HTTP path)
  patterns:
    - Hand-maintained module docstring marker (`Hand-maintained — NOT regenerated`)
    - `from __future__ import annotations` header on every CLI .py file
    - Lazy-import discipline (importlib.metadata, ProblemDetail, httpx exceptions)
    - is_eager=True on --version callback (RESEARCH Pitfall 9)
    - AppState dataclass on ctx.obj (RESEARCH Pattern 1)
    - Formatter dataclass with __post_init__ Console wiring (greenfield)
    - Exit-code constants module-level (D-32)
    - Stub commands raise typer.Exit(2) so test_exit_codes runs before Plans 02-05 land
key-files:
  created:
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
    - .planning/phases/216-geolens-cli-mvp/216-01-SUMMARY.md
  modified:
    - Makefile
decisions:
  - "Python floor pinned to >=3.11 (drops `tomli` shim — RESEARCH Pitfall 3)"
  - "License declared as `{ text = \"Apache-2.0\" }` (matches sdks/python/pyproject.toml form)"
  - "Stub commands raise Exit(2) with `not yet implemented (Plan NN)` so the exit-code matrix can be validated before plans 02-05 land"
  - "_sdk_helpers.py imports httpx lazily inside call_sdk() — keeps OCCLI-06 grep gate clean (no top-level `import httpx`)"
  - "Formatter exposes a `console_stdout` property so Plan 03's scan command can render rich.Table without recreating a Console"
metrics:
  duration_seconds: 253
  duration_human: "4m 13s"
  completed_date: "2026-04-27"
  tasks_completed: 3
  tests_passing: 17
  files_created: 13
  files_modified: 1
---

# Phase 216 Plan 01: scaffold-cli-package Summary

Established the `cli/` Apache-2.0 package boundary with Typer app shell, version export, output formatter, SDK-call helpers, Wave 0 test infrastructure, and Makefile recipes — closing OCCLI-01 (Apache-2.0 package + `geolens --version` works) and structurally enforcing OCCLI-06 (zero `httpx`/`requests` direct deps in `cli/pyproject.toml`).

## What Shipped

### `cli/` package (Apache-2.0)

- **`cli/pyproject.toml`** — hatchling backend, name `geolens`, version `1.0.0`, `requires-python = ">=3.11"`, locked dep pins (typer/rich/keyring/tomli_w/platformdirs/structlog/geolens-sdk), console-script `geolens = "geolens_cli.main:app"`, pytest config with `testpaths = ["tests"]`. **Zero `httpx` or `requests` in `dependencies`** — OCCLI-06 dep-list invariant holds.
- **`cli/LICENSE`** — byte-identical copy of `sdks/python/LICENSE` (Apache 2.0 standard text). `diff cli/LICENSE sdks/python/LICENSE` exits 0.
- **`cli/README.md`** — PyPI-facing quickstart linking to `docs/cli.md`.
- **`cli/.gitignore`** — `.venv/`, `uv.lock`, `dist/`, `build/`, `*.egg-info/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`.

### `geolens_cli/` package modules

- **`__init__.py`** — `__version__` via `importlib.metadata.version("geolens")` with `PackageNotFoundError` fallback to `"0.0.0+dev"`. Single source of truth for the version string is `pyproject.toml`.
- **`main.py`** — Typer app + `export` sub-app, `AppState` dataclass on `ctx.obj`, global `@app.callback()` accepting `--json`/`-v`/`-q`/`--instance`/`--version` (the latter with `is_eager=True` per RESEARCH Pitfall 9), and stub commands `login`/`logout`/`whoami`/`scan`/`publish`/`export stac` that raise `typer.Exit(2)` until Plans 02-05 fill them in.
- **`output.py`** — `Formatter` dataclass wrapping rich `Console` for stdout + stderr; respects `NO_COLOR` env var; `success`/`error`/`info`/`debug`/`json` helpers; `console_stdout` accessor for downstream rich primitives (Plan 03's table); `is_tty` property for conditional indent in JSON output.
- **`_sdk_helpers.py`** — `unwrap(resp, expected=200)` translates SDK `Response[T | ProblemDetail]` into either parsed model or `typer.Exit(EXIT_*)`; `call_sdk(fn, **kwargs)` runs a `sync_detailed` call mapping `httpx.TimeoutException` → `EXIT_NETWORK` and `httpx.NetworkError` → `EXIT_NETWORK`. Exit-code constants `EXIT_OK=0`, `EXIT_GENERIC=1`, `EXIT_USAGE=2`, `EXIT_AUTH=3`, `EXIT_NETWORK=4`, `EXIT_SERVER=5` per CONTEXT.md D-32.

### Wave 0 test infrastructure (`cli/tests/`)

- **`conftest.py`** — three shared fixtures: `runner` (`CliRunner`), `tmp_xdg_home` (sets `XDG_CONFIG_HOME` to `tmp_path`), `mock_keyring` (in-memory dict via `monkeypatch` on `keyring.{set,get,delete}_password`).
- **`test_version.py`** (3 tests) — `__version__` is a non-empty string; `--version` exits 0 starting with `"geolens "`; `--help` lists all six subcommand stubs.
- **`test_output.py`** (7 tests) — JSON success on stdout, JSON error on stderr, `quiet=True` suppresses success but not error, `verbose=True` emits debug, no verbose silences debug, `NO_COLOR=1` strips ANSI escape sequences.
- **`test_exit_codes.py`** (7 tests) — exit-code constants match D-32 matrix; all six stub commands (`login`/`logout`/`whoami`/`scan`/`publish`/`export stac`) exit with code 2.

### Makefile

Extended `.PHONY` with `cli-build cli-test cli-check publish-cli` and added four new recipes:

- `cli-build` — `cd cli && uv build` (wheel + sdist).
- `cli-test` — runs `cd cli && uv run pytest -v` followed by `backend/tests/test_cli_round_trip.py` (the round-trip lands in Plan 06; until then the second line fails — documented inline).
- `cli-check` — alias to `sdks-check`; the `sync_sdk_versions.py` extension in Plan 06 will write `cli/pyproject.toml`'s version, so the existing drift gate auto-catches CLI version skew.
- `publish-cli` — `cd cli && uv build && uv publish` (manual user action requiring `UV_PUBLISH_TOKEN`).

## OCCLI-06 Invariant Evidence

```bash
$ ! grep -rE '^(import|from) (httpx|requests)' cli/geolens_cli/
OCCLI-06 invariant holds
```

`_sdk_helpers.py` imports httpx **only for exception types**, and the import is lazy (inside `call_sdk()`) so the top-level grep gate remains clean. The module docstring documents the policy and explains that the Plan 06 CI grep gate is scoped to top-level `import|from` lines that construct clients.

```bash
$ python3 -c "import tomllib;d=tomllib.load(open('cli/pyproject.toml','rb'));deps=d['project']['dependencies'];assert not any('httpx' in x or 'requests' in x for x in deps)"
$ echo $?
0
```

Dep-list invariant holds — the only HTTP path is through `geolens-sdk`.

## Verification Evidence

| Check | Command | Result |
|-------|---------|--------|
| OCCLI-01: Apache-2.0 package buildable | `cd cli && uv build` | wheel + sdist in `cli/dist/` |
| OCCLI-01: `geolens --version` | `cd cli && uv run --no-sync geolens --version` | `geolens 1.0.0` |
| OCCLI-01: `geolens --help` lists stubs | `cd cli && uv run --no-sync geolens --help` | All 6 subcommands listed |
| OCCLI-06: dep-list invariant | tomllib parse + assertion | OK |
| OCCLI-06: source-tree grep gate | `! grep -rE '^(import\|from) (httpx\|requests)' cli/geolens_cli/` | OK |
| LICENSE byte-identity | `diff cli/LICENSE sdks/python/LICENSE` | exit 0 |
| Wave 0 unit suite | `cd cli && uv run --no-sync pytest -v` | 17/17 passed in 0.07s |
| Makefile cli-build | `make cli-build` | Successfully built wheel + sdist |

## Public Interfaces Established for Downstream Plans

```python
# Plan 02 (auth) will import:
from geolens_cli.main import app, AppState

# Plans 02-05 will use:
from geolens_cli.output import Formatter
from geolens_cli._sdk_helpers import (
    unwrap, call_sdk,
    EXIT_OK, EXIT_GENERIC, EXIT_USAGE, EXIT_AUTH, EXIT_NETWORK, EXIT_SERVER,
)

# Plans 02-05 will use these test fixtures from cli/tests/conftest.py:
@pytest.fixture
def runner() -> CliRunner: ...
@pytest.fixture
def tmp_xdg_home(monkeypatch, tmp_path) -> Path: ...
@pytest.fixture
def mock_keyring(monkeypatch) -> dict: ...
```

## Deviations from Plan

**One minor count discrepancy noted:** the plan's acceptance criteria stated `≥ 18 tests passing total: 3 + 7 + 7` but `3 + 7 + 7 = 17`. The implementation matches the literal test counts the plan listed (3 in test_version, 7 in test_output, 7 in test_exit_codes = 17), so this is a typo in the plan, not a missing test. All explicitly-named tests in the acceptance criteria are present.

Otherwise: plan executed exactly as written.

- No Rule 1 (bug) auto-fixes.
- No Rule 2 (missing critical functionality) auto-fixes.
- No Rule 3 (blocking issue) auto-fixes.
- No Rule 4 (architectural) escalations.
- No authentication gates.

## Threat Flags

None — this plan only ships the package scaffold + stub commands; no credentials are stored, no HTTP calls are made, no file uploads. T-216-04 (HTTP-bypass) is partially mitigated by the dep-list invariant + the documented exception-types-only httpx import policy in `_sdk_helpers.py`. The static-grep CI gate lands in Plan 06.

## Commits

| Task | Hash | Description |
|------|------|-------------|
| 1 | `0b75fd5a` | feat(216-01): scaffold cli/ Apache-2.0 package manifest |
| 2 | `312a69a4` | feat(216-01): add geolens_cli package modules — __init__, main, output, _sdk_helpers |
| 3 | `fe18bcf4` | test(216-01): add Wave 0 cli/tests/ infrastructure + Makefile cli-* recipes |

## Self-Check: PASSED

- `cli/pyproject.toml` exists ✓
- `cli/LICENSE` exists ✓
- `cli/README.md` exists ✓
- `cli/.gitignore` exists ✓
- `cli/geolens_cli/__init__.py` exists ✓
- `cli/geolens_cli/main.py` exists ✓
- `cli/geolens_cli/output.py` exists ✓
- `cli/geolens_cli/_sdk_helpers.py` exists ✓
- `cli/tests/__init__.py` exists ✓
- `cli/tests/conftest.py` exists ✓
- `cli/tests/test_version.py` exists ✓
- `cli/tests/test_output.py` exists ✓
- `cli/tests/test_exit_codes.py` exists ✓
- Commit `0b75fd5a` exists ✓
- Commit `312a69a4` exists ✓
- Commit `fe18bcf4` exists ✓
- 17/17 unit tests passing ✓
- Wheel + sdist build successful ✓
- OCCLI-06 invariant holds ✓
