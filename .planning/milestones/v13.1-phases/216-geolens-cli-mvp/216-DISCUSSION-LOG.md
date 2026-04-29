# Phase 216: geolens-cli-mvp - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-27
**Phase:** 216-geolens-cli-mvp
**Mode:** auto (Claude judgment — no AskUserQuestion calls; recommended defaults selected for every gray area)
**Areas discussed:** Package layout & distribution, CLI framework, Authentication & credential storage, Scan command, Publish command, Export STAC command, Output / errors / exit codes, Configuration & XDG, Testing, CI / publish, Documentation

---

## Package layout & distribution

| Option | Description | Selected |
|--------|-------------|----------|
| Top-level `cli/` directory (sibling to `sdks/`) | Self-contained Apache-2.0 package, atomic commits with backend + SDK, single source of truth | ✓ |
| Co-locate inside `sdks/python/` | Reuse SDK package, single PyPI artifact | |
| Separate `geolens-cli` git repo | Clean repo isolation, independent release cadence | |

**Selection rationale:** Mirrors Phase 215 D-04. Atomic commits coupling backend route changes with CLI regeneration; no cross-repo synchronization burden.

---

## CLI framework

| Option | Description | Selected |
|--------|-------------|----------|
| Typer | Type-hint-driven, modern, integrates with rich, FastAPI-ecosystem-idiomatic | ✓ |
| Click | More conservative, more boilerplate, broad adoption | |
| argparse (stdlib) | No new dependency, verbose for nested subcommands | |

**Selection rationale:** Typer's type-hint ergonomics match the project's Python style; auto-generated `--help`; clean nested sub-app support for `geolens export stac`.

---

## Authentication & credential storage

| Option | Description | Selected |
|--------|-------------|----------|
| Keyring with `--no-keyring` file fallback | Native OS integration with documented headless escape hatch | ✓ |
| File-only credential storage | Simpler, no keyring dependency, works headless out of the box | |
| Environment-variables-only | CI-friendly, but no interactive flow | |

**Login flow selected:** Username/password prompt → `POST /auth/login` via SDK → store JWT in keyring under service `geolens`, account `<instance_url>`. `--token` flag for non-interactive paste; `--api-key` flag for API-key auth; `--no-keyring` for headless. Refresh-token retry once on 401.

**Single-vs-multi-profile:** Single `[default]` profile for MVP. Multi-profile deferred.

---

## Scan command

| Option | Description | Selected |
|--------|-------------|----------|
| Extension-based detection only | Simple, fast, server re-validates on upload | ✓ |
| Magic-byte verification client-side via puremagic | Mirrors backend validation precisely | |
| Both: extension first, magic-byte for ambiguous cases | Belt-and-suspenders | |

**Selection rationale:** KISS for MVP. The backend uses `puremagic` to validate at upload time, so client-side magic-byte adds zero security and a meaningful dep. Extension allowlist subset of server allowlist (`backend/app/processing/ingest/validation.py`).

**Walk semantics:** Recursive by default; `--max-depth N` flag; symlink-loop detection; hidden files skipped.

**Output:** Human-readable `rich` table by default; `--json` flag for machine-readable. Shapefile siblings grouped under the `.shp`.

---

## Publish command

| Option | Description | Selected |
|--------|-------------|----------|
| 3-step ingest flow via SDK (upload → preview → commit) | Matches existing backend pipeline; zero new server work | ✓ |
| Direct-to-S3 presigned upload | Better for >100MB files; SDK already exposes the endpoints | |
| Synchronous single-shot upload | Simplest, but loses progress UX | |

**Selection rationale:** MVP uses the streamed multipart endpoint. Presigned-S3 path captured in Deferred Ideas; can land in a future phase when large-file workflows surface.

**Progress UX:** `rich.progress.Progress` 4-stage bar; degrades cleanly when stdout is not a TTY.

**Optional flags:** `--name`, `--description`, `--tags`, `--collection`, `--wait/--no-wait`. All optional with sane defaults.

---

## Export STAC command

| Option | Description | Selected |
|--------|-------------|----------|
| Pass-through `GET /stac/items/{id}` via SDK | Backend already emits STAC 1.1; CLI is a thin wrapper | ✓ |
| Construct STAC client-side | Adds pystac dep; duplicates server logic | |
| Wrap multiple endpoints into a richer client-side document | Out of MVP scope | |

**Selection rationale:** Backend produces conformant STAC 1.1; CLI is a formatting layer. Vector/collection guard returns exit code 2 with a clear message ("STAC export is supported for raster datasets only").

**Output:** Pretty-printed JSON to stdout by default; `-o FILE` for atomic file write; `--compact` for jq pipelines.

---

## Output / errors / exit codes

| Option | Description | Selected |
|--------|-------------|----------|
| `rich` for human + `--json` for machine | Best UX with clean machine-readable escape hatch | ✓ |
| Plain text only | Smaller dep tree | |
| Always JSON | CI-friendly but bad interactive UX | |

**Exit codes selected:** 0 success, 1 generic, 2 misuse (Click default), 3 auth, 4 network, 5 server.

**Verbose / quiet:** `-v` adds `structlog` debug; `-q` suppresses non-error output.

---

## Configuration & XDG

| Option | Description | Selected |
|--------|-------------|----------|
| XDG-compliant `~/.config/geolens/` | Matches aws-cli, gcloud, gh, kubectl muscle memory | ✓ |
| Platform-native (macOS Application Support, Windows AppData) | Per-OS correct but inconsistent across the user's machines | |
| Hardcoded `~/.geolens/` | Simpler but non-XDG | |

**Files:** `config.toml` (instance URL, default profile, username — no secrets), `credentials.toml` (used only with `--no-keyring`, mode 0600). `GEOLENS_INSTANCE` and `GEOLENS_TOKEN` env vars override config-file values.

---

## Testing

| Option | Description | Selected |
|--------|-------------|----------|
| Round-trip integration test (mirrors Phase 215-04) + unit tests | End-to-end coverage with fast feedback loop | ✓ |
| Unit tests only | Faster to write, less coverage | |
| Full Docker Compose round-trip in CI | Most realistic, slowest | |

**Selection rationale:** Phase 215 set the in-process ASGI pattern via `httpx.ASGITransport`; reuse it for `backend/tests/test_cli_round_trip.py`. Typer's `CliRunner` + monkeypatched keyring for unit tests.

---

## CI / publish

| Option | Description | Selected |
|--------|-------------|----------|
| Manual-trigger `publish-cli.yml` (mirrors `publish-sdks.yml`) | Same v13.1 default as Phase 215 D-16 | ✓ |
| Auto-publish on tag push | Faster releases, riskier during early adoption | |
| Auto-publish on every merge | Most aggressive, highest risk | |

**Selection rationale:** Same risk model as the SDKs. First publish is a user action. Future tightening to "publish-on-tag" once the CLI is stable.

**Drift gate:** No new gate needed. The existing `make sdks-check` already catches version skew because `scripts/sync_sdk_versions.py` (extended in this phase) writes `cli/pyproject.toml`'s version field.

---

## Documentation

| Option | Description | Selected |
|--------|-------------|----------|
| `docs/cli.md` (full user docs) + `cli/README.md` (PyPI-facing) | Mirrors `docs/sdks.md` + `sdks/python/README.md` pattern from Phase 215 | ✓ |
| `cli/README.md` only | Less to maintain, no project-side surface | |
| Generated docs site | Future polish; out of MVP | |

---

## Claude's Discretion

The following were left to the planner per CONTEXT.md "Claude's Discretion":

- **Commit decomposition** — likely 5-6 plans (scaffold, auth+config, scan, publish, export-stac, round-trip+CI+docs).
- **`pydantic` vs `dataclasses`** for config schemas.
- **`tomllib` (3.11+) vs `tomli` (3.10 backport)** — tied to Python-floor decision.
- **`rich` vs lighter formatters** if dep weight matters.
- **Whether to expose `--install-completion`** — Typer freebie, ship if cheap.

---

## Deferred Ideas

Captured for future phases (full list in `216-CONTEXT.md` under `<deferred>`):

- OAuth/OIDC interactive login from the CLI (device-code or localhost-callback flow).
- SAML CLI flow (Phase 217 ships server-side only; CLI gets `--token` workaround).
- Multi-profile config (`[staging]`, `[prod]`).
- Presigned-upload path for >100MB files.
- `geolens.yaml` declarative manifest spec (P2 from audit / OCSDK-05).
- Bulk publish, watch mode, schema-editor commands, collection-management standalone commands, RBAC commands.
- Plugin system, client-side STAC validation, CSV-with-lat/lon publish.
- `geolens dataset list/get`, `geolens config show/set`.
- Shell autocompletion bootstrap (`--install-completion`).
- `geolens --version` showing both CLI and backend versions.
- `--type vector|raster` override on publish.
