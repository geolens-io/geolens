# GeoLens CLI

`geolens` is the Apache-2.0 command-line interface for the GeoLens API. Log in, scan local directories, publish vector and raster files, and export STAC metadata against any GeoLens instance — community or enterprise — without writing a line of HTTP code.

| | Value |
|---|---|
| Package | `geolens-cli` (PyPI) |
| License | Apache-2.0 |
| Source | `cli/` in [geolens-io/geolens](https://github.com/geolens-io/geolens) |
| SDK | Built on [`geolens`](sdks.md) — no hand-rolled HTTP client (OCCLI-06) |
| Python | ≥ 3.11 |

## Installation

```bash
pip install geolens-cli
# or:
uv add geolens-cli
# or one-shot, no install:
uvx --from geolens-cli geolens --help
```

Verify the install:

```bash
geolens --version
```

If the version reads `0.0.0+dev`, you are running from a source checkout without an editable install — `pip install -e cli/` from the repo root or `pip install geolens-cli` from PyPI.

## Quickstart

```bash
# Log in (prompts for username + password)
geolens login https://geolens.example.com

# Inventory a directory before publishing
geolens scan ./data --json | jq

# Publish a vector or raster file
geolens publish ./data/cities.geojson
geolens publish ./data/elevation.tif --name "Bay Area DEM"

# Export STAC 1.1 metadata for a raster dataset
geolens export stac <dataset-id> -o cities.stac.json

# Start a manifest-driven catalog
geolens init
geolens validate geolens.yaml
geolens apply --dry-run geolens.yaml
geolens apply geolens.yaml
```

## Commands

### `geolens login <instance-url>`

Authenticates against the instance and stores the resulting token.

| Flag | Purpose |
|---|---|
| `--token <jwt>` | Skip prompt; store this JWT directly. Useful after a browser-based SAML/OAuth flow. **Security: avoid passing tokens on the command line where shell history may persist them.** A `--token-stdin` follow-up is captured as a deferred enhancement (T-216-05). |
| `--api-key <key>` | Store an API key instead of a bearer token. Mutually exclusive with `--token`; passing both exits with code 2. |
| `--no-keyring` | Write to `~/.config/geolens/credentials.toml` (mode 0600) instead of the OS keyring. Useful for CI or headless boxes without dbus. |

The interactive flow:

1. Validates the URL (https/http scheme, normalized trailing slash).
2. Prompts for **username** (visible) and **password** (via `getpass`, hidden).
3. POSTs to `/auth/login` via the SDK; stores the access token in the keyring under service `geolens`, account `<instance_url>`. The refresh token, if returned, lands under account `<instance_url>:refresh`.
4. Updates `~/.config/geolens/config.toml` with the active instance and username for `whoami` display. **Tokens are never written to `config.toml`.**

### `geolens logout`

Clears credentials for the active instance from both the keyring and `credentials.toml`. Idempotent — missing entries are silently ignored.

### `geolens whoami`

Calls `GET /auth/me` and prints the current user. Refreshes the access token once on a 401 if a refresh token is stored; if refresh fails, prints `Session expired — run \`geolens login\` again` and exits with code 3 (auth failure).

### `geolens scan <dir>`

Walks a directory and reports what would be ingested.

| Flag | Purpose |
|---|---|
| `--json` | Emit a machine-readable JSON array instead of a `rich` table |
| `--max-depth N` | Cap recursion at N levels below the root |
| `--include-ext .gpkg,.tif` | Filter to specific extensions (case-insensitive; leading dot optional) |

Vector formats detected: `.geojson`, `.json` (parsed as GeoJSON), `.gpkg`, `.shp` (with sibling-grouping for `.dbf`/`.shx`/`.prj`/`.cpg`).
Raster formats: `.tif`, `.tiff` (treated as candidate COG; the server validates).

The CLI's allowlist is informational — the GeoLens server validates content via `puremagic` on upload, so file-type spoofing is caught server-side. `geolens scan` is a pure-local dry-run; it never uploads anything and exits with code 0 even when every entry is `ingest: no`.

Shapefile sibling-grouping: when a `.shp` is detected, the scan emits a single row for the dataset and lists the sidecars under `sidecar_files` in the JSON output. Missing required sidecars produce `ingest: no, reason: "missing .dbf"` (or `.shx`, `.prj`).

### `geolens init [path]`

Creates a starter manifest. The default path is `geolens.yaml`.

| Flag | Purpose |
|---|---|
| `--force` | Overwrite an existing manifest |

The generated file is intentionally minimal and validates offline with `geolens validate`.

### `geolens validate [path]`

Validates a manifest without contacting an API. The default path is `geolens.yaml`.

Validation uses the committed manifest v1 JSON Schema and returns deterministic errors with schema paths and remediation text. Invalid YAML, a non-mapping document root, missing files, and schema errors exit with code 2.

### `geolens apply [path]`

Applies a validated manifest through the configured GeoLens API. The default path is `geolens.yaml`.

| Flag | Purpose |
|---|---|
| `--dry-run` | Ask the backend to preview create/update/skip/error outcomes without writes |

`geolens apply` always loads and validates the manifest locally before constructing an SDK client. Local validation failures exit with code 2 and use the same human or JSON report shape as `geolens validate`.

After local validation passes, the CLI POSTs the manifest to `POST /ingest/manifest/apply` through the SDK-owned HTTP client (`client.get_httpx_client()`). The endpoint is present in the committed OpenAPI snapshot and generated SDKs as `ManifestApplyRequest` / `ManifestApplyResponse`; the CLI still does not construct its own HTTP client.

Backend result actions:

| Action | Meaning |
|---|---|
| `create` | A new dataset ingest job was queued, or would be queued in dry-run mode |
| `update` | An existing manifest-managed dataset would be reuploaded or was queued for reupload |
| `skip` | The matching manifest dataset is already queued/running or already up to date |
| `error` | That dataset entry could not be applied; the result includes a message and errors |

Human output prints a summary count and a table with `DATASET`, `ACTION`, `DATASET ID`, `JOB ID`, and `MESSAGE`. `--dry-run` labels the output as a dry run.

JSON output is enabled with the global flag:

```bash
geolens --json apply geolens.yaml --dry-run
```

The JSON payload includes:

```json
{
  "accepted": true,
  "counts": {"create": 1, "error": 0, "skip": 0, "update": 0},
  "dry_run": true,
  "ok": true,
  "path": "geolens.yaml",
  "results": []
}
```

Exit behavior:

| Code | Meaning for apply |
|---|---|
| 0 | Backend accepted the manifest and no result action is `error` |
| 1 | Backend returned `accepted=false`, any result action is `error`, or another generic command failure occurred |
| 2 | Local validation failed, arguments were invalid, or the backend returned 422 |
| 3 | Auth failed or credentials are missing |
| 4 | Network error, timeout, DNS failure, or refused connection |
| 5 | Backend/server failure |

#### First-catalog walkthrough

This path is covered by the automated `TestManifestApplyRoundTrip` smoke: `geolens apply` authenticates against live FastAPI, queues the `city-parks` job, the test completes that job, and `/search/datasets/?q=City parks` returns the created catalog dataset.

Start the local stack and log the CLI into the API:

```bash
docker compose up -d --wait
geolens login http://localhost:8000
```

Stage the sample data where the API container can read it:

```bash
docker compose exec api mkdir -p /app/staging
docker compose cp examples/manifests/first-catalog/city-parks.geojson api:/app/staging/city-parks.geojson
```

Validate, preview, and apply the manifest:

```bash
geolens validate examples/manifests/first-catalog/geolens.yaml
geolens apply --dry-run examples/manifests/first-catalog/geolens.yaml
geolens apply examples/manifests/first-catalog/geolens.yaml
```

Manifest local paths are backend-local paths. The first-catalog manifest references `staging/city-parks.geojson`, which resolves inside the GeoLens API process/container as `/app/staging/city-parks.geojson`; `geolens apply` does not upload manifest source files from your shell.

After the worker processes the queued ingest job, browse the catalog at `http://localhost:8080` and search for `City parks`.

#### Public manifest examples

Public examples live under `examples/manifests/` and are validated by the same offline validator used by `geolens validate` and `geolens apply`.

| Example | What it shows |
|---|---|
| `examples/manifests/first-catalog/geolens.yaml` | Backend-local vector source path plus sample GeoJSON data |
| `examples/manifests/url-source.yaml` | HTTP(S) vector source |
| `examples/manifests/s3-source.yaml` | S3 raster COG source; requires storage configuration such as `STORAGE_PROVIDER=s3` and matching bucket settings |
| `examples/manifests/publication-states.yaml` | Community-safe publication intents: `draft`, `ready`, `internal`, and `published` |

### `geolens publish <file>`

Uploads a vector or raster file via the 3-step ingest flow (upload → preview → commit) and prints the resulting dataset URL.

| Flag | Purpose |
|---|---|
| `--name STR` | Override dataset name (default: filename stem) |
| `--description STR` | Set description |
| `--tags a,b,c` | Comma-separated keyword tags. **Currently a no-op pending a `tags`/`keywords` field on `CommitRequest`** — captured as Phase 216 Open Question 4. |
| `--collection ID` | Add to a collection after commit. **Currently a no-op pending an add-to-collection endpoint in the SDK** — captured in Phase 216 Deferred Ideas. |
| `--wait/--no-wait` | Wait for ingestion to resolve the dataset id (default: `--wait`). With `--no-wait`, the URL falls back to a job-search form. |

Successful output prints `https://<instance>/datasets/<dataset_id>`. With `--no-wait` and a still-pending commit, the URL is `<instance>/datasets?job_id=<id>`.

The CLI uses a **multipart-upload workaround** for the broken generated `BodyUploadFileIngestUploadPost.to_multipart()` (RESEARCH Pitfall 1): it calls the SDK's underlying httpx client directly via `client.get_httpx_client()`. OCCLI-06 still holds — the httpx instance comes from the SDK and `cli/pyproject.toml` declares no httpx direct dependency.

Commit is **not idempotent** (RESEARCH Pitfall 6): re-running publish on a job that has already committed prints "already committed" and exits with code 1.

### `geolens export stac <dataset-id>`

Exports STAC 1.1 JSON for a raster dataset. STAC export is **raster-only** in v13.x; vector datasets exit with code 2 and a clear error message.

| Flag | Purpose |
|---|---|
| `-o FILE` / `--output FILE` | Write to file (default: stdout). Atomic write — Ctrl+C never leaves a half-written file. Mode 0o644 (STAC payloads are not secrets per the threat model). |
| `--compact` | Single-line JSON for piping into `jq` or `curl --data` (no trailing newline). |

Default output is pretty-printed (`indent=2`, sorted keys, trailing newline) for diff stability.

Pre-flight: the CLI fetches `GET /datasets/{id}` first to confirm `record_type`, so non-raster types yield a clean message instead of a confusing 404/422 from `/stac/items/{id}`.

## Auth Modes

1. **Interactive (default)** — `geolens login <url>` prompts for username + password.
2. **Paste a JWT** — after a browser SSO flow (Google, Microsoft, SAML), copy the JWT from the GeoLens UI and run `geolens login <url> --token <jwt>`. SAML and OAuth interactive CLI flows are deferred; the paste-token path covers them.
3. **API key** — `geolens login <url> --api-key <key>`. Stored separately from JWTs in the keyring under account `<url>:api_key`.
4. **Headless / CI** — `geolens login <url> --token <jwt> --no-keyring`. The token lands in `~/.config/geolens/credentials.toml` (mode 0600) instead of the OS keyring.
5. **Env var override** — `GEOLENS_INSTANCE` and `GEOLENS_TOKEN` override config-file values for one-off runs.

## Configuration

### XDG-compliant paths

| OS | Config location |
|---|---|
| Linux | `$XDG_CONFIG_HOME/geolens/` (default `~/.config/geolens/`) |
| macOS | `~/Library/Application Support/geolens/` |
| Windows | `%LOCALAPPDATA%\geolens\geolens\` |

Two files (only the first always exists):

- `config.toml` — instance URL, default profile, username (no secrets).
- `credentials.toml` — only created when `--no-keyring` is set or the keyring is unavailable. Mode 0600; parent directory mode 0700.

### Environment variables

| Var | Purpose |
|---|---|
| `GEOLENS_INSTANCE` | Override the active instance URL |
| `GEOLENS_TOKEN` | Override the stored bearer token |
| `XDG_CONFIG_HOME` | Move the config directory off `~/.config/` |
| `NO_COLOR` | Disable ANSI colors (also auto-detected when stdout is not a TTY) |

Precedence: **CLI flag > env var > `credentials.toml` > keyring**.

## Lockstep Version Policy

The CLI version is bound to the GeoLens backend's OpenAPI version. For example, `geolens-cli` v1.0.0 ships against the backend's v1.0.x OpenAPI snapshot; the CLI's `geolens` SDK dependency pins to `>=1.0.0,<2.0.0` (lockstep across patch + minor of the same OpenAPI version).

On a backend major-version bump, the CLI gets a coordinated bump too. `make sdks-check` catches version skew in CI on every PR — the `scripts/sync_sdk_versions.py` extension landed in Phase 216 / Plan 06 writes `cli/pyproject.toml`'s version field along with the two SDK targets, so the existing drift gate now covers the CLI automatically (CONTEXT.md D-39).

See [`docs/sdks.md`](sdks.md#lockstep-version-policy) for the full SDK policy this inherits from.

## Drift Gate

`make sdks-check` regenerates the SDKs and verifies that:

- Generated source under `sdks/python/geolens/`, `sdks/typescript/src/`, and `sdks/typescript/test/` matches the committed copies (modulo the hand-written wrapper carve-outs).
- `sdks/python/pyproject.toml`, `sdks/typescript/package.json`, **and `cli/pyproject.toml`** all have the same `version` value as `backend/openapi.json`'s `info.version`.

The CLI is fully hand-maintained — there is no generator that touches `cli/geolens_cli/*.py` — but version drift is caught by the same gate that catches SDK drift.

The CI `cli-test` job adds two further structural gates:

1. `grep -rE '^(import|from) (httpx|requests)' cli/geolens_cli/` returns no matches (OCCLI-06: zero direct HTTP imports).
2. A `tomllib` assertion that `cli/pyproject.toml` declares no `httpx`/`requests` direct dep (transitive via the `geolens` SDK is fine).

Both gates fire on every PR that touches `cli/**` or `sdks/python/**`, so a regression cannot land silently.

## Publishing

Publishing runbook (mirrors `docs/sdks.md`):

1. Configure PyPI Trusted Publishing for project `geolens-cli`, owner `geolens-io`, repository `geolens`, workflow `publish-cli.yml`, environment blank.
2. Trigger the **Publish CLI** workflow from the GitHub Actions UI:
   - Select `dry_run: true` to build the wheel + sdist without uploading.
   - Select `dry_run: false` for the real publish.

Publishing is a manual user action — there is no auto-publish on push or tag (per CONTEXT.md D-40 and Phase 215 D-16). PyPI authentication is through Trusted Publishing; no `PYPI_TOKEN` is stored in GitHub. The first public CLI release has shipped as `geolens-cli==1.0.0`.

## Known Rough Edges

### Multipart upload generator quirk

The generated `BodyUploadFileIngestUploadPost.to_multipart()` in the Python SDK is broken — it sends `(None, str(path).encode(), 'text/plain')` instead of the file bytes. The CLI bypasses this by calling the SDK's underlying httpx client directly (`client.get_httpx_client().post('/ingest/upload', files={...})`). OCCLI-06 still holds: the httpx instance comes from the SDK, and `cli/pyproject.toml` declares no httpx direct dep.

### Keyring on headless Linux

Linux's keyring backends (GNOME Keyring, KWallet) require a desktop session with dbus. CI runners and SSH sessions typically lack this. The CLI auto-falls back to `credentials.toml` with a warning; `--no-keyring` makes the choice explicit.

### Refresh-token rotation

The CLI rotates the refresh token whenever `/auth/refresh` returns a new one. If you copy `credentials.toml` to another machine after a refresh, the old machine's refresh token is invalid.

### `--token` and shell history (T-216-05)

`geolens login <url> --token <jwt>` is convenient but the JWT lands in shell history. For production CI use, prefer the env-var path (`GEOLENS_TOKEN=<jwt> geolens whoami`) which leaves no flag in history. A `--token-stdin` enhancement is captured for a future phase as the structural fix.

### Commit is not idempotent

Re-running `geolens publish` on a job that has already committed prints `Job <id> was already committed` and exits 1. There is no resume of in-flight commits — each publish starts a new job.

### STAC for vector datasets

STAC export is raster-only in v13.x. Trying `geolens export stac <vector-id>` exits with code 2 and the clear message `STAC export is supported for raster datasets only — got record_type=<...>`. Vector dataset metadata is exposed via `GET /datasets/{id}` and the OGC API Records endpoints.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `geolens --version` shows `0.0.0+dev` | Not installed (running from a source checkout) | `pip install -e cli/` or `pip install geolens-cli` |
| `keyring.errors.NoKeyringError` traceback | Headless Linux without dbus | Use `--no-keyring` or set `GEOLENS_TOKEN` env var |
| `Authentication required. Run \`geolens login\` first.` (exit 3) | Token missing or expired | `geolens login <url>` to refresh credentials |
| `Session expired — run \`geolens login\` again` (exit 3) | Refresh token also expired | Re-login |
| `Job <id> was already committed` (exit 1) | Re-running publish on a job that completed | Each `geolens publish` starts a new job; resume of in-flight commits is not supported |
| `STAC export is supported for raster datasets only` (exit 2) | Trying STAC export on a vector dataset | Use `GET /datasets/{id}` for vector metadata |
| `Manifest apply response had accepted=false` (exit 1) | Backend returned only error results or rejected the apply response | Re-run with `geolens --json apply ...` and inspect `results[*].errors` |
| `Could not read manifest` or schema remediation lines (exit 2) | Manifest path is wrong or the YAML does not satisfy manifest v1 | Run `geolens validate <path>` locally before applying |
| OCCLI-06 violation in CI | A PR added `import httpx` or `import requests` to `cli/geolens_cli/`, or added an httpx/requests dep to `cli/pyproject.toml` | Re-run `make cli-check` locally; the only legitimate path to httpx is via the SDK's `client.get_httpx_client()` |

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Generic command failure |
| 2 | Invalid arguments / misuse (Typer/Click default) |
| 3 | Auth failure (401, expired token, missing credentials) |
| 4 | Network error (timeout, connection refused, DNS) |
| 5 | Server-side error (5xx from backend) |

## References

- [`docs/sdks.md`](sdks.md) — the underlying Python SDK (`geolens`)
- [`docs/install-guide.md`](install-guide.md) — running a GeoLens instance
- [GitHub repository](https://github.com/geolens-io/geolens) — source for the CLI under `cli/`
- [PyPI](https://pypi.org/project/geolens-cli/) — the published package
