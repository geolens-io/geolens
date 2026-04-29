# Phase 216: geolens-cli-mvp - Context

**Gathered:** 2026-04-27 (auto-mode — Claude judgment for all gray areas)
**Status:** Ready for planning

<domain>
## Phase Boundary

End users install the Apache-2.0 `geolens` CLI from PyPI and exercise the full ingest-and-export round-trip against any GeoLens instance — community or enterprise — without writing a line of HTTP code. The CLI consumes Phase 215's generated Python SDK exclusively (OCCLI-06: zero direct `httpx`/`requests` imports for catalog operations).

**After this phase:**
- `cli/` (NEW top-level monorepo directory, mirrors `sdks/python/` and `sdks/typescript/`) contains the `geolens` CLI as a self-contained Apache-2.0 Python package with its own `pyproject.toml`, importable as `geolens_cli`. Console-script entry point `geolens` is installed by `pip install geolens`.
- Five primary commands shipped: `geolens login <instance-url>`, `geolens scan <dir>`, `geolens publish <file>`, `geolens export stac <dataset-id>`, `geolens --version`.
- `geolens logout` and `geolens whoami` ship as thin support commands so the auth flow round-trips.
- Auth: keyring-by-default for the JWT/access token; `--no-keyring` falls back to `~/.config/geolens/credentials.toml` with mode 0600.
- Config: instance URL + active profile lives in `~/.config/geolens/config.toml` (XDG-compliant; respects `XDG_CONFIG_HOME`). Single profile for MVP; multi-profile is a deferred capability.
- Distribution: PyPI as `geolens` (the CLI). Lockstep version with `geolens-sdk` and the OpenAPI snapshot per Phase 215 D-07. Publish workflow is a manual GitHub Actions trigger (`publish-cli.yml`) mirroring `publish-sdks.yml`; first publish is a user action requiring `PYPI_TOKEN`.
- Round-trip integration test in `backend/tests/test_cli_round_trip.py` exercises login → scan → publish → export stac against an in-process ASGI app (matches Phase 215-04 pattern).

**In scope:**
- The 5 commands above (+ `logout`, `whoami`) wired to the generated SDK.
- Vector-and-raster file detection for `scan` (extension-based, KISS).
- Vector + raster publish via the existing 3-step ingest pipeline (`/ingest/upload` → `/ingest/preview/{job}` → `/ingest/commit/{job}`) using the SDK functions.
- Keyring-with-fallback credential storage.
- Human-readable output via `rich`; `--json` flag for machine-readable output.
- Round-trip test, CI job, manual-trigger publish workflow scaffold, `docs/cli.md` user docs.

**Out of scope:**
- OAuth / OIDC / SAML interactive login flows in the CLI (deferred — login is username/password against `/auth/login`, plus paste-token for headless).
- Bulk publish, watch mode, schema editing, collection management commands, RBAC commands, plugin system.
- Direct-to-S3 presigned upload path (Phase 217+ when needed for >100MB files; MVP uses the streamed `POST /ingest/upload` endpoint).
- Server-side ingest configuration overrides beyond the existing preview/commit user_metadata fields (name, description, tags).
- Frontend changes of any kind.
- Actual v1.0.0 PyPI publication (workflow ready; pressing the trigger is a user action, same pattern as Phase 215 D-16).
- A `geolens.yaml` declarative manifest spec (P2, deferred — see REQUIREMENTS.md OCSDK-05 / `docs-internal/audits/oc-separation-deferred-items-20260426.md`).

</domain>

<decisions>
## Implementation Decisions

### Package layout & distribution

- **D-01:** **Top-level `cli/` directory** — sibling to `sdks/python/` and `sdks/typescript/`. Self-contained Apache-2.0 package with its own `pyproject.toml`. Atomic commits keep CLI + SDK + backend in lockstep.
- **D-02:** **PyPI distribution name `geolens`**, importable as `geolens_cli`. Console-script entry point `geolens = geolens_cli.main:app`. Matches ROADMAP SC#1 wording exactly.
- **D-03:** **Lockstep versioning with `geolens-sdk`** (which is itself locked to `backend/openapi.json` `info.version` per Phase 215 D-07). Extend `scripts/sync_sdk_versions.py` to also write `cli/pyproject.toml`'s `version` field. The `make sdks-check` drift gate catches CLI version skew along with SDK version skew.
- **D-04:** **CLI depends on `geolens-sdk` via `>=X.Y.Z,<X.(Y+1).0`** range (lockstep across patch + minor of the same OpenAPI version). On a backend major-version bump, the CLI gets a coordinated bump too. Closes OCCLI-06: the dependency declaration is the structural enforcement that the CLI cannot fall back to `httpx`/`requests` without an explicit dep change that code review catches.

### CLI framework

- **D-05:** **Typer** — type-hint-driven CLI built on Click. Rationale: idiomatic with the project's Python typing style (FastAPI ecosystem); auto-generates `--help` from docstrings + type annotations; structured subcommands (`geolens export stac …`) work cleanly via Typer apps; integrates with `rich` for free. Trade vs Click (more conservative, more boilerplate) and argparse (stdlib but verbose, no autocomplete). Typer is the modern default and matches CLI ergonomics expected by GIS/Python users.
- **D-06:** **Subcommand structure**:
  ```
  geolens login <instance-url>            # URL is positional (required)
  geolens logout                          # tears down current profile credentials
  geolens whoami                          # GET /auth/me, prints current user/instance
  geolens scan <dir> [--json] [--include-ext .gpkg,.tif] [--max-depth N]
  geolens publish <file> [--name STR] [--description STR] [--tags a,b,c] [--collection ID] [--wait/--no-wait]
  geolens export stac <dataset-id> [-o FILE]
  geolens --version
  geolens --help
  ```
  Multi-word commands (`geolens export stac`) use Typer sub-apps. ROADMAP SC names `geolens export stac <dataset-id>` exactly; bind to that.
- **D-07:** **No interactive shell, no autocompletion bootstrapping in MVP** — `--install-completion` is a Typer freebie and may be exposed, but the phase ROADMAP doesn't bind it. Keep the install footprint minimal.

### Authentication & credential storage

- **D-08:** **`geolens login <instance-url>` interactive flow**:
  1. Validate the URL (https/http scheme, normalize trailing slash).
  2. GET `<url>/auth/config` via the SDK to confirm the URL points at a real GeoLens instance and discover whether OAuth is configured (informational only — OAuth login is out of scope for MVP).
  3. Prompt for **username** (visible) and **password** (hidden via `getpass`).
  4. POST `/auth/login` via SDK, get back access + refresh tokens.
  5. Store the access token in the keyring under service `geolens`, account `<instance_url>`. Store the refresh token alongside it under account `<instance_url>:refresh`.
  6. Update `~/.config/geolens/config.toml` to record `default_instance = "<instance_url>"` and the username (for `whoami` display). NEVER write tokens to the config file.
- **D-09:** **`--token <jwt>` flag** for non-interactive (CI / headless) login. Skips the username/password prompt; stores the supplied bearer JWT directly. Pairs with `--no-keyring` for fully-headless flows.
- **D-10:** **`--api-key <key>` flag** as an alternate auth mode. Stores under keyring account `<url>:api_key`. The SDK wrapper from Phase 215 D-10 already exposes both `bearer_token` and `api_key` modes; the CLI just picks whichever credential the active profile has set.
- **D-11:** **`--no-keyring` fallback** writes to `~/.config/geolens/credentials.toml` (created with mode 0600, parent dir 0700). Schema:
  ```toml
  [default]
  instance = "https://geolens.example.com"
  bearer_token = "..."           # OR api_key, never both
  ```
  When the keyring is unavailable (e.g., headless Linux without dbus), the CLI auto-falls back to the file with a printed warning. `--no-keyring` makes the choice explicit (no warning).
- **D-12:** **Keyring backend** — use `keyring` (industry standard). Optional dep: keyring backends like `keyrings.cryptfile` are NOT shipped; users on headless machines use `--no-keyring`. The `keyring` package itself is a hard dep so the import never fails.
- **D-13:** **Refresh-token handling** — on a 401 from the SDK, if a refresh token is stored, the CLI calls `POST /auth/refresh` once and retries. If refresh also fails, prints "Session expired — run `geolens login` again" and exits with code 3 (auth failure). No silent re-prompting.
- **D-14:** **Single profile for MVP** — config.toml has one `[default]` table. Multi-profile (`geolens login --profile staging`, `geolens --profile staging publish ...`) is captured in Deferred Ideas. KISS first.

### Scan command (OCCLI-03)

- **D-15:** **Extension-based detection only** for MVP. Mirror the backend's `puremagic`-validated allowlist conceptually but skip magic-byte verification client-side (the server re-validates on upload — no client-side bypass risk). Allowlist baseline:
  - **Vector**: `.shp` (with sibling `.dbf`/`.shx`/`.prj`), `.geojson`, `.json` (only if it parses as GeoJSON), `.gpkg`, `.csv` (with detected lat/lon or geometry column — too brittle for MVP, exclude unless a `--csv` flag is set; deferred).
  - **Raster**: `.tif`, `.tiff` (treat both as candidate COG; server validates).
  - **Auxiliary** (skipped, not reported): `.dbf`, `.shx`, `.prj`, `.cpg`, `.qix`, `.sbn`, `.sbx`, `.aux.xml`, `.ovr`, `.tfw` — these belong to a parent dataset.
- **D-16:** **Walk semantics** — recursive by default; `--max-depth N` flag caps recursion. Symlink loops detected via visited-set on canonical paths. Hidden files (`.git/`, `.DS_Store`, `__pycache__/`) skipped by default.
- **D-17:** **Output schema** (default human-readable table via `rich.table.Table`):
  ```
  PATH                            FORMAT       INGEST?
  data/cities.shp                 shapefile    yes
  data/elevation.tif              cog          yes
  data/notes.txt                  unsupported  no
  ```
  With `--json`: emit a JSON array of `{path, format, ingest, reason}` per file. Exit code 0 even if everything is `ingest: no` (it's a dry-run report, not an error).
- **D-18:** **Shapefile sibling-grouping** — when `.shp` is detected, only emit one row for the dataset (the `.shp`); list `.dbf`/`.shx`/`.prj` as required-siblings in the JSON output's `sidecar_files` field. Missing required sidecars → `ingest: no, reason: "missing .dbf"`.

### Publish command (OCCLI-04)

- **D-19:** **3-step ingest flow via SDK**:
  1. `POST /ingest/upload` — streams the file with multipart, returns `job_id`. Use `upload_file_ingest_upload_post` from the SDK.
  2. `POST /ingest/preview/{job_id}` with optional `user_metadata` (name, description, tags from CLI flags). Returns columns/CRS/sample rows.
  3. `POST /ingest/commit/{job_id}` to finalize. Returns dataset record.
  4. Print `https://<instance>/datasets/<dataset_id>` on success (the dataset URL bound by ROADMAP SC#4).
- **D-20:** **Synchronous-by-default with progress UX** — preview + commit are quick (synchronous in the existing API). Commit itself can take longer for raster ingestion (COG conversion). The CLI polls `/ingest/jobs/{job_id}` (if exposed) or treats commit as completed when the response returns; for v0 use whatever the SDK gives us synchronously and add `--wait/--no-wait` flag (default `--wait`, only emits the URL once status is `complete`).
- **D-21:** **Progress display** — `rich.progress.Progress` showing 4 steps (uploading, previewing, committing, done). On `--json` or non-TTY (`stdout` not a terminal), suppress progress UI and just emit the final JSON or URL. Cleanly degrades for CI logs.
- **D-22:** **Ingest type detection** — re-use D-15 extension allowlist client-side. Vector files use the existing vector ingest path; raster files use the same `/ingest/upload` endpoint (the backend dispatches based on `record_type` inferred from MIME / extension server-side). MVP does not expose `--type vector|raster` override; if needed, captured in Deferred Ideas.
- **D-23:** **No presigned-upload path in MVP** — the CLI uses the streamed multipart upload (`POST /ingest/upload`). For files >100MB, `obstore`-backed presigned upload is the future path. MVP rationale: keeps the SDK call simple, no client-side S3 logic, no extra config required. Deferred (see Deferred Ideas).
- **D-24:** **Optional flags**:
  - `--name STR` — override dataset name (default: filename stem).
  - `--description STR` — sets description.
  - `--tags a,b,c` — comma-separated keyword tags.
  - `--collection ID` — after commit, calls `POST /catalog/collections/{id}/datasets` to add the new dataset to a collection.
  - `--wait/--no-wait` — wait for commit completion vs return job_id immediately.
  - All optional; sane defaults make the bare `geolens publish foo.geojson` work end-to-end.

### Export STAC command (OCCLI-05)

- **D-25:** **Source endpoint**: `GET /stac/items/{dataset_id}` via the SDK function `get_item_stac_items_item_id_get`. The backend already emits STAC 1.1 JSON for raster datasets. The CLI is a thin pass-through.
- **D-26:** **Vector / collection guard** — STAC is raster-centric in v13.1 (per PROJECT.md "STAC for vector datasets" — out of scope). CLI checks the dataset's `record_type` (via `GET /datasets/{id}` first or by handling the 404/422 from `/stac/items/{id}`); on non-raster, prints "STAC export is supported for raster datasets only — got record_type=vector_dataset" and exits with code 2.
- **D-27:** **Output**:
  - Default: pretty-printed JSON to stdout (2-space indent, sorted keys for diff stability).
  - `-o FILE` / `--output FILE`: write to file (still pretty-printed). Use atomic `write+rename` to avoid half-written files on Ctrl+C.
  - `--compact`: single-line JSON (no whitespace) for piping into jq, `curl --data`, etc.
- **D-28:** **No client-side STAC validation** — backend already produces conformant STAC 1.1. Validating in the CLI duplicates work and adds a `pystac` dependency for marginal benefit. Deferred (see Deferred Ideas).

### Output, errors, exit codes

- **D-29:** **`rich` for human output**, plain text for `--json` mode. Color disabled when stdout is not a TTY (rich detects this automatically). Respect `NO_COLOR` env var.
- **D-30:** **`--json` global flag** (Typer global option) makes every command emit machine-readable JSON; mutually exclusive with progress bars. Useful for shell pipelines and CI.
- **D-31:** **`-v` / `--verbose` and `-q` / `--quiet`** — verbose adds debug logging via `structlog` (matches backend pattern), quiet suppresses non-error output. Default is "normal" (success + warnings, no debug).
- **D-32:** **Exit codes**:
  - `0` — success.
  - `1` — generic command failure.
  - `2` — invalid arguments / misuse (Typer/Click default).
  - `3` — auth failure (401 from server, expired token, missing credentials).
  - `4` — network error (timeout, connection refused, DNS).
  - `5` — server-side error (5xx from backend).
- **D-33:** **Error formatting** — backend error responses (`{"detail": "..."}`) are rendered as `Error: <detail>` to stderr. SDK exceptions are caught at the command boundary and translated to user-friendly messages; full traceback only with `--verbose`.

### Configuration & XDG

- **D-34:** **Config + credentials live under `XDG_CONFIG_HOME/geolens/`** (default `~/.config/geolens/`). Files:
  - `config.toml` — instance URL, default profile, username (no secrets).
  - `credentials.toml` — used only when `--no-keyring` is set or keyring is unavailable. Mode 0600.
  - `state.json` — last-used dataset id (so `geolens export stac` without an arg can be deferred… but NOT in MVP). Future.
- **D-35:** **`GEOLENS_INSTANCE` and `GEOLENS_TOKEN` env vars** — override config-file values for headless / CI use. Precedence: CLI flag > env var > credentials.toml > keyring.
- **D-36:** **`--instance <url>` flag** — overrides the active instance for a single command invocation. Useful for ad-hoc cross-instance work without re-running `geolens login`.

### Testing

- **D-37:** **Round-trip test pattern** (mirrors Phase 215-04 `backend/tests/test_sdks_round_trip.py`):
  - `backend/tests/test_cli_round_trip.py` (NEW). Uses pytest + Typer's `CliRunner` + `httpx.ASGITransport` against the test FastAPI app.
  - Tests: `login` (mock keyring), `whoami`, `scan` (against a tmp dir with sample fixtures), `publish` (small GeoJSON fixture from `backend/tests/fixtures/`), `export stac` (raster fixture if available; else mark as `skip` with a clear reason).
  - Uses `pyfakefs` or `tmp_path` for file system isolation; mocks `keyring` via `monkeypatch`.
  - 12+ tests, expected to pass under `make sdks-test` extension.
- **D-38:** **Unit tests** in `cli/tests/`:
  - Format detection (D-15) — table-driven test of extension → format mapping.
  - Config file read/write — round-trip with `tomli_w` / stdlib `tomllib`.
  - Exit code matrix — each error scenario maps to the expected code.
  - Output formatters — JSON vs table outputs match snapshots.

### CI / publish

- **D-39:** **Extend `make sdks-check` to also fail on CLI drift** if the CLI shares any generated artifacts (it doesn't — but the version-sync script writes `cli/pyproject.toml`'s version, so the existing drift gate catches version skew automatically).
- **D-40:** **`.github/workflows/publish-cli.yml` (NEW)** — manual `workflow_dispatch` workflow mirroring `publish-sdks.yml`. Builds wheel + sdist with `uv build`, uploads to PyPI via `twine` using `secrets.PYPI_TOKEN`. Same "first publish is a user action" pattern as Phase 215 D-16.
- **D-41:** **CI test job** — extend the existing CI workflow to run `cli/tests/` plus the round-trip test. Tied into the same Python 3.13 + uv setup.

### Documentation

- **D-42:** **`docs/cli.md` (NEW)** documents:
  - Installation (`pip install geolens` / `uv add geolens`).
  - Quickstart: login → publish → export.
  - Command reference (each command, all flags, examples).
  - Auth modes (interactive, `--token`, `--api-key`, `--no-keyring`).
  - XDG config layout + env vars.
  - Troubleshooting (keyring on headless, expired tokens, network errors).
  - Lockstep version policy (the CLI's version is bound to the backend's OpenAPI version; `geolens --version` shows both).
- **D-43:** **`cli/README.md` (NEW)** is the public-facing PyPI README — concise quickstart, link to `docs/cli.md` for full docs (mirrors `sdks/python/README.md` pattern).

### Boundary with Phase 217

- **D-44:** Phase 217 (`auth-saml-enterprise`) does NOT need CLI changes. The CLI's auth flow is username/password against `/auth/login` (already supports OAuth/OIDC server-side); SAML logins go through the browser-based flow on the instance and result in a JWT the user can paste with `geolens login --token <jwt>`. No SAML-specific CLI code paths.

### Claude's Discretion (planner picks)

- **Commit decomposition** — likely 5-6 plans:
  1. **Scaffold `cli/` package** — `pyproject.toml`, console-script entry, `geolens_cli/__init__.py`, `geolens_cli/main.py` (Typer app shell), `cli/README.md`, baseline test layout. Wire `make cli-test` Makefile target.
  2. **Auth + config foundation** — `geolens_cli/config.py` (XDG paths, TOML read/write), `geolens_cli/auth.py` (keyring + file fallback), `geolens login` / `logout` / `whoami` commands, unit tests.
  3. **`scan` command** — `geolens_cli/scan.py` (filesystem walk + format detection), the Typer command, table + JSON output formatters, unit tests.
  4. **`publish` command** — `geolens_cli/publish.py` (3-step ingest flow, progress UI, optional flags), the Typer command, mocked unit tests.
  5. **`export stac` command** — `geolens_cli/export_stac.py` (raster guard + SDK pass-through + output formatting), the Typer command.
  6. **Round-trip test + CI + publish workflow + `docs/cli.md`** — `backend/tests/test_cli_round_trip.py`, extend `sync_sdk_versions.py` to write `cli/pyproject.toml`, add CI job, scaffold `publish-cli.yml`, write user docs, run phase verification gate.
  Planner may collapse 5+6 if both are short.
- **Whether to use `pydantic` for config schemas** — leaning yes (project already uses pydantic v2 across backend); planner decides based on weight vs `dataclasses` + manual validation.
- **`tomllib` vs `tomli`** — Python 3.11+ has `tomllib` for read; `tomli_w` (or `tomlkit` if comment preservation matters) for write. Planner picks based on Python version floor (D-02 says 3.10+; if 3.10 support is required, `tomli` is needed for read too).
- **`rich` vs `colorama` + manual** — `rich` (chosen by D-29) is the modern default; planner can downgrade if `rich`'s install footprint matters more than UX, but unlikely.
- **Whether to ship shell autocompletion** — Typer's `--install-completion` is free; if the planner wants to expose it, fine. Not bound by ROADMAP.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Audit / spec / requirements

- `docs-internal/audits/oc-separation-deferred-items-20260426.md` — P1 row "Ship `geolens` CLI (Apache-2.0)" (1–2 weeks effort). The strategy's adoption wedge.
- `docs-internal/audits/oc-separation-audit-20260426.md` §6 — full OSS-surface audit context. Names this as the developer-adoption-wedge move.
- `.planning/REQUIREMENTS.md` §OCCLI-01..06 — the six requirements this phase closes.
- `.planning/ROADMAP.md` §Phase 216 — goal + 6 success criteria.

### Project / state / preceding phase

- `.planning/PROJECT.md` — milestone overview; v13.1 target grade Boundary B → A−, Seam Quality C → B, OSS Surface D → C. Phase 216 is the OSS-Surface deliverable that consumers will actually run.
- `.planning/STATE.md` — last-shipped state (Phase 215 complete; ready for 216).
- `.planning/phases/215-sdks-from-openapi/215-CONTEXT.md` — **prerequisite phase**. D-07 (lockstep versioning), D-10 (auth wrapper structure), D-13 (drift-gate exemption pattern), D-17 (CLI consumes `geolens-sdk`, not the generated client directly). Read before planning.
- `.planning/phases/215-sdks-from-openapi/215-05-SUMMARY.md` — Phase 215 final summary; documents the round-trip test pattern Phase 216 mirrors.
- `docs/sdks.md` — SDK user docs; `docs/cli.md` (NEW in 216) follows the same structure.

### Code (existing — Phase 215 outputs)

- `sdks/python/geolens_sdk/__init__.py` — exposes `GeolensClient`. The CLI's auth layer constructs this and hands it to every SDK call.
- `sdks/python/geolens_sdk/auth.py` — Bearer + API-key wrapper (Phase 215 D-10). The CLI uses `GeolensClient(...).client` everywhere.
- `sdks/python/geolens_sdk/api/auth/login_auth_login_post.py` — login endpoint binding.
- `sdks/python/geolens_sdk/api/auth/me_auth_me_get.py` — whoami binding.
- `sdks/python/geolens_sdk/api/auth/refresh_auth_refresh_post.py` — refresh-token binding.
- `sdks/python/geolens_sdk/api/datasets/upload_file_ingest_upload_post.py` — multipart upload.
- `sdks/python/geolens_sdk/api/datasets/preview_file_ingest_preview_job_id_post.py` — preview step.
- `sdks/python/geolens_sdk/api/datasets/commit_import_ingest_commit_job_id_post.py` — commit step.
- `sdks/python/geolens_sdk/api/datasets/get_single_dataset_datasets_dataset_id_get.py` — record-type guard for STAC export.
- `sdks/python/geolens_sdk/api/stac/get_item_stac_items_item_id_get.py` — STAC export source.
- `sdks/python/geolens_sdk/api/datasets/get_upload_config_ingest_upload_config_get.py` — upload config (size limits, allowed extensions) for `scan` allowlist sync if planner chooses.
- `scripts/sync_sdk_versions.py` — extend to also write `cli/pyproject.toml`'s version (D-03).

### Code (existing — backend / project precedent)

- `backend/openapi.json` — source of truth for SDK + CLI version pin.
- `backend/scripts/dump_openapi.py` — argparse + `--check` semantics. Precedent for the CLI's flag style if the planner wants stdlib parity (rejected by D-05; Typer chosen).
- `backend/app/processing/ingest/validation.py` — magic-byte validation reference. CLI does extension-only detection (D-15); validation is server-side.
- `backend/app/processing/ingest/constants.py` — extension allowlists. Source for CLI's scan allowlist (D-15) — keep client allowlist a subset of server allowlist.
- `backend/app/modules/ingest/router.py` — the 3-step ingest endpoints.
- `backend/tests/test_sdks_round_trip.py` (Phase 215-04) — exact pattern for `backend/tests/test_cli_round_trip.py` (D-37).
- `backend/tests/conftest.py` — pytest fixtures (in-process ASGI client) reused by the round-trip test.
- `Makefile` (root) — `openapi`, `openapi-check`, `sdks`, `sdks-check`, `sdks-test` targets. Phase 216 adds `cli-build` + `cli-test` and extends `publish-sdks-py` recipe family with `publish-cli`.
- `docs/sdks.md` — structural template for `docs/cli.md`.
- `.github/workflows/publish-sdks.yml` (Phase 215 D-16) — exact template for `publish-cli.yml`.

### Code (new in this phase)

- `cli/pyproject.toml` — NEW Apache-2.0 CLI package manifest.
- `cli/README.md` — NEW PyPI-facing README.
- `cli/geolens_cli/main.py` — NEW Typer app entry + global options.
- `cli/geolens_cli/config.py` — NEW XDG config + TOML I/O.
- `cli/geolens_cli/auth.py` — NEW keyring + file-fallback credential storage; SDK client construction.
- `cli/geolens_cli/scan.py` — NEW directory-walk + format-detection logic.
- `cli/geolens_cli/publish.py` — NEW 3-step ingest + progress UI.
- `cli/geolens_cli/export_stac.py` — NEW STAC pass-through.
- `cli/geolens_cli/output.py` — NEW table + JSON formatters; exit-code constants.
- `cli/tests/` — NEW unit tests.
- `backend/tests/test_cli_round_trip.py` — NEW integration test.
- `.github/workflows/publish-cli.yml` — NEW manual-trigger publish workflow.
- `docs/cli.md` — NEW user docs.

### External libraries (proposed)

- `typer` (https://typer.tiangolo.com) — chosen CLI framework (D-05).
- `rich` (https://rich.readthedocs.io) — output formatting (D-29).
- `keyring` (https://pypi.org/project/keyring/) — credential storage (D-12).
- `tomli_w` (write) + stdlib `tomllib` (read, Py 3.11+) — TOML I/O.
- `geolens-sdk` — Phase 215 output, the only HTTP path (D-04 closes OCCLI-06).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- **`sdks/python/geolens_sdk/auth.py`** — `GeolensClient` already supports both Bearer and API-key modes. The CLI's auth module builds one of these per command and passes `.client` to every SDK function. No reinvention.
- **`scripts/sync_sdk_versions.py`** — Phase 215 wrote this to pin SDK versions to `backend/openapi.json` `info.version`. Extend to also write `cli/pyproject.toml`. Single function, single new line of code.
- **`backend/tests/test_sdks_round_trip.py`** — exact pattern for `test_cli_round_trip.py`: in-process ASGI fixture, monkeypatched HTTP transport, 12 endpoint assertions. Replicate the structure with Typer's `CliRunner`.
- **`backend/scripts/dump_openapi.py`** — uses argparse + `--check`. The CLI uses Typer instead, but the lazy-import pattern (deferring DB-bound imports until subcommands run) is worth replicating to keep `geolens --help` snappy.
- **`Makefile` `sdks` / `sdks-check` / `sdks-test` targets** — exact precedent for `cli-build` / `cli-test` targets.
- **`backend/tests/fixtures/`** — sample GeoJSON / shapefile / COG fixtures usable by the round-trip test. No new fixture creation expected.

### Established Patterns

- **Apache-2.0 license** — root `LICENSE` file copied verbatim into `cli/LICENSE` (matches `sdks/python/LICENSE` pattern).
- **uv-based Python tooling** — `cli/pyproject.toml` declares dependencies; `uv build` for distribution; `uvx geolens` for one-shot execution if a user wants to try without installing.
- **Lockstep versioning** — Phase 215 D-07 establishes the lockstep policy. The CLI inherits it (D-03).
- **Manual-trigger publish workflows** — Phase 215 D-16 establishes `workflow_dispatch` as the v13.1 default. CLI follows suit.
- **`structlog` for logging** — backend pattern. The CLI uses `structlog` for `--verbose` output to keep telemetry consistent.
- **XDG-compliant config** — `~/.config/geolens/` matches Linux conventions; macOS users get the same path (CLI tools that use `Library/Application Support` for macOS are fine but XDG is simpler and matches `aws-cli`, `gcloud`, etc.).

### Integration Points

- **CLI ↔ SDK boundary** — single direction: CLI → SDK → backend. No shared state. The CLI never imports from `geolens_sdk._private`; only the public surface (`GeolensClient`, generated `api.*` functions, generated `models.*`).
- **CLI ↔ backend boundary** — exclusively via the SDK. Closes OCCLI-06 by structural enforcement: there's no `httpx`/`requests` in `cli/pyproject.toml` `dependencies`.
- **CLI ↔ filesystem boundary** — XDG-compliant config + credentials; user-supplied positional paths for `scan` and `publish`. No surprise writes outside `~/.config/geolens/` and the user's chosen `-o FILE` for export.
- **CLI ↔ keyring boundary** — `keyring` is a hard dep; backends are platform-specific (macOS Keychain, Windows Credential Manager, Linux Secret Service / KWallet). Failures fall back to `--no-keyring` file mode with a printed warning (D-11).

### Risk surfaces

- **Keyring on headless Linux without dbus** — common in CI environments. Mitigation: auto-fallback to credentials.toml with warning (D-11). The `--no-keyring` flag makes the choice explicit.
- **`tomllib` is Python 3.11+** — D-02 says 3.10+ minimum. Planner picks `tomli` (3.10 backport) for read OR raises the floor to 3.11. Recommendation: raise to 3.11 to match `geolens-sdk`'s `requires-python = ">=3.10"` realistically — most modern installs are 3.11+. Planner's call.
- **Multipart upload of large files** — `httpx`'s streaming upload works for files up to memory limits; very large files (>1GB) may need chunking. Captured in Deferred (presigned-upload path is the future fix).
- **`rich` progress bars vs piped output** — rich auto-detects TTY; verified by integration test that `geolens publish foo.geojson --json | jq` emits clean JSON without ANSI escapes.
- **CLI version drift relative to SDK / backend** — caught by extending `sync_sdk_versions.py` (D-03) and the existing `make sdks-check` drift gate. No new gate needed.
- **Generated SDK function names are verbose** — e.g., `search_datasets_endpoint_search_datasets__get`. The CLI imports them under aliases inside `geolens_cli` to keep call sites readable; doesn't try to rename the SDK itself.

</code_context>

<specifics>
## Specific Ideas

- **Why Typer over Click** — Typer is Click with type-driven ergonomics; FastAPI users (the project's audience) recognize the pattern instantly. Click is also fine; argparse is rejected as too verbose for the 5+ commands and nested sub-apps (`export stac`).
- **Why XDG config (`~/.config/geolens/`)** — matches `aws-cli`, `gcloud`, `gh`, `kubectl`. Users have muscle memory for this location.
- **Why Apache-2.0 license** — ROADMAP SC#1 binds it. Matches the SDKs (Phase 215) and the open-core repo's overall license.
- **Why "keyring with file fallback" rather than "file-only"** — keyring gets us native OS integration on macOS / Windows / Linux desktops with one dep. The fallback covers headless / CI without forcing every user to type `--no-keyring`. Best of both.
- **Why `geolens login` prompts username/password rather than launching a browser OAuth flow** — MVP scope. OAuth login on the CLI requires either a localhost-redirect server or a device-code flow, and the backend currently does OAuth via the web UI redirect path. Server-side OAuth-via-CLI is its own project. `--token <jwt>` covers the OAuth-via-browser case (paste the resulting JWT). Documented in `docs/cli.md`.
- **Why no `--type vector|raster` override on `publish`** — the backend dispatches based on file format. Forcing the user to pick when the extension already says it (`.tif` → raster, `.shp` → vector) is friction without payoff. Captured in Deferred Ideas in case a real ambiguous case appears (e.g., a `.json` file that's neither GeoJSON nor STAC — but that's then "unsupported" anyway).
- **Why output dataset URL on publish (vs dataset ID alone)** — ROADMAP SC#4 says "prints the resulting dataset URL on success." User experience: the URL is clickable in modern terminals; ID-only forces a manual lookup.

</specifics>

<deferred>
## Deferred Ideas

- **OAuth/OIDC interactive login from the CLI** — device-code flow or localhost-callback flow. Useful but non-trivial; out of MVP. Workaround: `geolens login --token <jwt>` after browser SSO. Future phase if signal demands it.
- **SAML CLI flow** — same as OAuth; SAML overlay in Phase 217 is server-side only. CLI gets `--token` workaround.
- **Multi-profile config** (`[default]`, `[staging]`, `[prod]`) — useful for ops. MVP ships single profile. Future phase: `geolens login --profile prod`, `geolens --profile staging publish ...`.
- **Presigned-upload path for large files** — Phase 215 SDK exposes `request_presigned_upload_*` + `complete_presigned_upload_*`. CLI MVP uses streamed multipart only (D-23). Files >100MB / S3-direct uploads are a future enhancement.
- **`geolens.yaml` declarative manifest spec** — `OCSDK-05` in REQUIREMENTS.md (P2 deferred). Phase 216 ships imperative commands; the manifest is a future opinionated layer on top.
- **Bulk publish** (`geolens publish --recursive <dir>` or `geolens scan ... | geolens publish --stdin`) — useful follow-up; out of MVP. Workaround: shell loop.
- **Watch mode** (`geolens watch <dir>`) — auto-publish on file change. Nice for on-prem ingest workflows but well outside MVP.
- **Schema editor commands** (`geolens schema rename`, `geolens schema alter-type`) — backend exists per Phase 215 audit (PATCH /layers/{id}/columns/...); P2 UI work. CLI version possible but post-MVP.
- **Collection management** (`geolens collection create`, `geolens collection add`) — partially covered by `--collection` flag on publish. Standalone collection commands deferred.
- **RBAC commands** (`geolens user grant`, `geolens api-key create`) — admin-only; backend exists; CLI form is post-MVP.
- **Plugin system** — `geolens plugins install <pkg>` for org-specific commands. Out of MVP scope.
- **Client-side STAC validation** (D-28) — adds `pystac` dep for marginal benefit; backend already produces conformant STAC.
- **CSV publish with auto-detected lat/lon columns** — backend supports it; CLI MVP excludes for cleanliness. Future enhancement on `scan`/`publish`.
- **Dataset list/get commands** (`geolens dataset list`, `geolens dataset get <id>`) — natural to add, but not in ROADMAP SC. Captured for OCCLI-07-style follow-up phase.
- **Shell autocompletion bootstrap** (`geolens --install-completion`) — Typer freebie; ship if cheap, defer otherwise.
- **`geolens --version` showing both CLI and backend versions** — straightforward. Add if the planner wants polish; ROADMAP only requires "compatible with both community and enterprise instances" (D-44 covers compatibility).
- **`--type vector|raster` override on publish** — see specifics above. Add if a real ambiguous case appears.
- **`geolens config show` / `geolens config set`** — convenient but not bound by SC. Workaround: edit `~/.config/geolens/config.toml` directly.

### Reviewed Todos (not folded)

None — no pending todos matched the phase scope per `gsd-sdk query todo.match-phase 216` (zero matches, zero pending todos).

</deferred>

---

*Phase: 216-geolens-cli-mvp*
*Context gathered: 2026-04-27 (auto-mode)*
