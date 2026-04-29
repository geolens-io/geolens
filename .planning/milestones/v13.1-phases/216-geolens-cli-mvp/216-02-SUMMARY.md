---
phase: 216-geolens-cli-mvp
plan: 02
subsystem: cli
tags: [cli, auth, keyring, xdg, occli-02, wave-2, tdd]
dependency_graph:
  requires:
    - cli/geolens_cli (Plan 01 — main.py shell, AppState, Formatter, _sdk_helpers)
    - sdks/python/geolens_sdk (Phase 215 — GeolensClient, login/me/refresh API binders)
    - keyring 25.x (transitive from Plan 01 manifest pin)
    - tomli_w 1.x (transitive from Plan 01 manifest pin)
    - platformdirs 4.x (transitive from Plan 01 manifest pin)
    - structlog 25.x (transitive from Plan 01 manifest pin)
  provides:
    - geolens_cli.config — AppConfig, atomic_write_text, config_path, credentials_path,
      load_config, write_default_instance, get_instance_from_env, get_token_from_env,
      normalize_instance_url
    - geolens_cli.auth — BearerToken, ApiKey, store_bearer_token, store_api_key,
      store_refresh_token, load_bearer_token, load_api_key, load_refresh_token,
      delete_credentials, try_refresh, SERVICE='geolens'
    - geolens_cli.main.AppState.active_instance() (D-35 precedence helper)
    - geolens_cli.main.AppState.sdk() (lazy GeolensClient with bearer/api-key auth)
    - working `geolens login` / `geolens logout` / `geolens whoami` commands
  affects:
    - Plans 03 (scan), 04 (publish), 05 (export stac), 06 (round-trip + CI + docs)
tech-stack:
  added: []
  patterns:
    - keyring with KeyringError auto-fallback to credentials.toml (RESEARCH Pattern 5)
    - atomic_write_text via tempfile.mkstemp + chmod + os.replace (RESEARCH Pattern 4)
    - platformdirs.user_config_dir(appauthor=False) for XDG-compliant config
    - frozen dataclasses as discriminator types (BearerToken, ApiKey)
    - lazy SDK imports inside command bodies (keeps `geolens --help` snappy)
    - getpass.getpass for password prompt (no terminal echo)
    - getattr-based response field access (resilient to OpenAPI field renames)
key-files:
  created:
    - cli/geolens_cli/config.py
    - cli/geolens_cli/auth.py
    - cli/tests/test_config.py
    - cli/tests/test_auth_keyring.py
    - .planning/phases/216-geolens-cli-mvp/216-02-SUMMARY.md
  modified:
    - cli/geolens_cli/main.py
    - cli/tests/test_exit_codes.py
decisions:
  - "Used `RefreshRequest` (the actual SDK model name) instead of the plan's `RefreshTokenRequest` placeholder — verified by reading sdks/python/geolens_sdk/api/auth/refresh_auth_refresh_post.py"
  - "Replaced Plan 01's stubbed login/logout/whoami exit-code tests with real per-command behavior tests (login --token success, mutex flag conflict, login URL validation, logout with/without instance, whoami EXIT_AUTH on no-instance) — Plan 01 explicitly flagged this handoff"
  - "Added `config: AppConfig` field to AppState (Plan 01's AppState only carried output/instance_override/json_mode/verbose/quiet); active_instance() and sdk() are methods on AppState, not free functions"
  - "delete_credentials swallows broad Exception (not just KeyringError) because keyring's PasswordDeleteError lineage varies across versions — the operation must be idempotent"
  - "Login with --token/--api-key writes config.toml with username=None (the user has no username context for paste-token flows); interactive login records the typed username for whoami display"
metrics:
  duration_seconds: 480
  duration_human: "8m 00s"
  completed_date: "2026-04-27"
  tasks_completed: 3
  tests_passing: 47
  files_created: 4
  files_modified: 2
---

# Phase 216 Plan 02: auth-and-config Summary

Built the credential layer + the three auth commands (`login`, `logout`, `whoami`) on top of Plan 01's scaffold, closing OCCLI-02 via keyring-with-file-fallback storage, XDG-compliant config, refresh-token retry, and an `AppState.sdk()` bridge that downstream plans (publish, export-stac) consume to obtain an authenticated `GeolensClient`.

## What Shipped

### `geolens_cli/config.py` (NEW, 117 lines)

- `AppConfig` dataclass — `instance: Optional[str]`, `username: Optional[str]`. `AppConfig.load()` reads `config.toml` via `tomllib`; returns empty on missing file or TOML decode error.
- `config_path()` / `credentials_path()` — XDG-resolved via `platformdirs.user_config_dir("geolens", appauthor=False)`. On Linux: `$XDG_CONFIG_HOME/geolens/{config,credentials}.toml` (default `~/.config/geolens/`).
- `write_default_instance(instance, username)` — writes `[default]` table; never includes tokens (D-11). Omits `username` key when `None`.
- `atomic_write_text(path, content, *, mode=0o600)` — RESEARCH Pattern 4 verbatim: parent dir created at 0o700, tempfile via `mkstemp` in same dir, `chmod` + `os.replace` for atomic POSIX rename. On any exception the tempfile is cleaned up before re-raising.
- `get_instance_from_env()` / `get_token_from_env()` — read `GEOLENS_INSTANCE` and `GEOLENS_TOKEN` env vars (D-35).
- `normalize_instance_url(url)` — strips whitespace + trailing slash; raises `ValueError` on empty or non-http(s) schemes.

### `geolens_cli/auth.py` (NEW, 224 lines)

- `BearerToken` / `ApiKey` — frozen dataclasses with single `value: str` field; serve as discriminator types so callers know which credential mode to pass to `GeolensClient`.
- `SERVICE = "geolens"` — keyring service name constant.
- Storage functions (`store_bearer_token`, `store_api_key`, `store_refresh_token`) — try keyring first; on `KeyringError` (parent class catching both `NoKeyringError` and `KeyringLocked` per A5), log structlog warning `keyring_unavailable_falling_back_to_file` and write to `credentials.toml` via `_set_credential_field` → `atomic_write_text`. Each returns `"keyring"` or `"file"` so the caller can surface the chosen backend in success messages.
- Load functions (`load_bearer_token`, `load_api_key`, `load_refresh_token`) — `load_bearer_token` honors D-35 precedence: `GEOLENS_TOKEN` env var first, then credentials.toml, then keyring (file is the explicit fallback so it takes precedence over the implicit keyring lookup). On `KeyringError` returns `None` (graceful — the file path may still have the credential).
- `delete_credentials(instance)` — purges all three keyring accounts (`<url>`, `<url>:refresh`, `<url>:api_key`) AND the credentials.toml `[<instance>]` table. Idempotent: missing entries silently swallowed via broad `except Exception`. When the credentials file is empty post-delete, the file itself is unlinked so logout leaves zero on-disk trace.
- `try_refresh(instance)` — D-13 once-only refresh: loads refresh token, builds `RefreshRequest(refresh_token=...)`, calls `refresh_auth_refresh_post.sync_detailed`. On 200 with valid `access_token`, stores the new access token AND rotates the refresh token if a new one is returned (RFC 6749 §6 best practice). Returns `None` on any failure.

### `geolens_cli/main.py` (MODIFIED — login/logout/whoami real bodies + AppState.sdk())

`AppState` extended:
- New field `config: _config.AppConfig`.
- `active_instance() -> Optional[str]` — returns `instance_override or env(GEOLENS_INSTANCE) or config.instance` per D-35.
- `sdk() -> GeolensClient` — lazy import; raises `typer.BadParameter` when no instance is configured; selects `bearer_token=` over `api_key=` when both happen to be present (login flow stores only one, but defensive code).

`@app.callback()` updated to call `_config.load_config()` and pass it into `AppState`.

`login` command:
- Validates URL via `normalize_instance_url` → `EXIT_USAGE` on bad scheme.
- `--token` and `--api-key` mutual exclusion → `EXIT_USAGE`.
- `--api-key` path: `store_api_key` + `write_default_instance(instance, None)` + success message with backend.
- `--token` path: `store_bearer_token` + `write_default_instance(instance, None)`.
- Interactive path: `typer.prompt("Username")` + `getpass.getpass("Password: ")` + `BodyLoginAuthLoginPost(username, password)` + `call_sdk(login_auth_login_post.sync_detailed, ...)` + `unwrap(resp, expected=200)` + store access (and refresh if returned) + record username in config.toml.

`logout` command:
- Resolves `active_instance()`; exits 2 if none.
- `delete_credentials(instance)` + `config_path().unlink()` (FileNotFoundError swallowed).

`whoami` command:
- Active-instance check → `EXIT_AUTH` on miss.
- `me_auth_me_get.sync_detailed` via `state.sdk().client`.
- On 401: `try_refresh(instance)`; if it returns a new access token, re-construct sdk and retry once. Second 401 → "Session expired — run `geolens login` again" + `EXIT_AUTH` (D-13).
- `--json` mode emits `{instance, email, id, role}`; default mode prints `email @ instance`.

### Tests

`cli/tests/test_config.py` (NEW, 99 lines, 15 tests):
- `TestXdgPaths` (2): config_path + credentials_path under XDG_CONFIG_HOME
- `TestConfigRoundTrip` (4): empty load, write+load roundtrip, omit username when None, **token never in config.toml** (D-11 invariant)
- `TestFileModes` (2, POSIX-only): credentials.toml mode 0600, parent dir mode 0700
- `TestEnvOverrides` (3): GEOLENS_INSTANCE/TOKEN read; unset returns None
- `TestNormalizeInstanceUrl` (4): trailing slash, whitespace, empty rejection, ftp:// rejection

`cli/tests/test_auth_keyring.py` (NEW, 103 lines, 12 tests):
- `TestKeyringStore` (5): bearer/api_key/refresh keyring writes; load from keyring; missing returns None
- `TestNoKeyringFallback` (3): file fallback writes credentials.toml; mode 0600 on POSIX; load from file
- `TestKeyringErrorAutoFallback` (1): NoKeyringError on set_password → falls back to file silently (with structlog warning)
- `TestEnvOverride` (1): GEOLENS_TOKEN beats keyring contents (D-35)
- `TestDeleteCredentials` (2): delete_credentials clears both backends; idempotent on empty state

`cli/tests/test_exit_codes.py` (UPDATED, 82 lines, 10 tests — was 7):
- Removed Plan 01's `test_login_stub_exits_2` / `test_logout_stub_exits_2` / `test_whoami_stub_exits_2` (Plan 01 explicitly flagged these for replacement in Plan 02).
- Kept `TestExitCodeConstants` (1) and remaining stubs `TestRemainingStubsExitWithUsage` (3 — scan/publish/export stac).
- Added `TestAuthCommandExitCodes` (6): login mutex flags → 2, login bad URL → 2, login --token success → 0, logout no-instance → 2, logout post-login → 0, whoami no-instance → 3.

## OCCLI-02 Closure Evidence

| Acceptance criterion | Evidence |
| -------------------- | -------- |
| Keyring service `geolens` with per-instance accounts | `auth.py:SERVICE = "geolens"`; account format `<url>` (token), `<url>:refresh`, `<url>:api_key` |
| `--no-keyring` writes credentials.toml mode 0600 | `test_credentials_file_mode_0600` (test_auth_keyring.py + test_config.py) |
| Auto-fallback on `KeyringError` (parent of `NoKeyringError` + `KeyringLocked`) | `test_keyring_error_falls_back_to_file` |
| Refresh-token retry once on 401, then `EXIT_AUTH` | `try_refresh` returns `None` on failure → main.py whoami exits 3 with "Session expired" |
| XDG-compliant config | `platformdirs.user_config_dir("geolens", appauthor=False)`; `test_config_path_under_xdg_home` |
| Tokens NEVER in config.toml (D-11) | `test_config_toml_never_contains_token` asserts `"token" not in text` and `"api_key" not in text` |
| Auth precedence (D-35) | `test_env_token_takes_precedence` (env > file > keyring) |

## OCCLI-06 Invariant Evidence

```bash
$ ! grep -rE '^(import|from) (httpx|requests)' cli/geolens_cli/config.py
$ ! grep -rE '^(import|from) (httpx|requests)' cli/geolens_cli/auth.py
$ ! grep -rE '^(import|from) (httpx|requests)' cli/geolens_cli/main.py
OCCLI-06 invariant holds across all three Plan 02 modules.
```

## Verification Evidence

| Check | Command | Result |
|-------|---------|--------|
| Full unit suite | `cd cli && uv run pytest -v` | 47/47 passed in 0.13s |
| Plan 02 modules only | `cd cli && uv run pytest tests/test_config.py tests/test_auth_keyring.py -v` | 27/27 passed |
| Plan-level whoami EXIT_AUTH check | `runner.invoke(app, ['whoami'])` with no instance | exit_code == 3 ✓ |
| Plan-level login mutex check | `runner.invoke(app, ['login', url, '--token', 'A', '--api-key', 'B', '--no-keyring'])` | exit_code == 2 ✓ |
| OCCLI-06 grep gate | `! grep -rE '^(import\|from) (httpx\|requests)' cli/geolens_cli/{config,auth,main}.py` | no matches ✓ |
| AppState shape | `inspect.getsource(AppState)` contains `def sdk` and `def active_instance` | ✓ |

## Public Interfaces Established for Plans 04/05

```python
# Plans 04 (publish) and 05 (export stac) will use:
from geolens_cli.main import AppState

# Inside command bodies after extracting state from ctx.obj:
state: AppState = ctx.obj
sdk = state.sdk()  # → GeolensClient with active credentials
client = sdk.client  # → AuthenticatedClient passed to SDK api.* binders

# state.active_instance() honors D-35 precedence (instance override > env > config)
# state.sdk() raises typer.BadParameter when no instance configured

# Direct credential management (typically not needed by commands; use AppState.sdk()):
from geolens_cli import auth as _auth
_auth.store_bearer_token(instance, token, no_keyring=False)
_auth.load_bearer_token(instance) -> Optional[BearerToken]
_auth.try_refresh(instance) -> Optional[str]  # for 401 retry path
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Used actual SDK model name `RefreshRequest`**
- **Found during:** Task 2 implementation
- **Issue:** Plan referenced `RefreshTokenRequest` (with executor-note that the planner expected this might differ from the actual SDK model)
- **Fix:** Verified via reading `sdks/python/geolens_sdk/api/auth/refresh_auth_refresh_post.py` and `sdks/python/geolens_sdk/models/refresh_request.py` — the actual model is `RefreshRequest` with field `refresh_token: str`. Used the correct name.
- **Files modified:** `cli/geolens_cli/auth.py`
- **Commit:** `78f31c54`
- **Note:** This was anticipated by the plan as a verify-and-adjust note in Task 2's `<action>` block, not an unexpected deviation.

**2. [Rule 3 - Blocking] Replaced Plan 01's stubbed exit-code tests for auth commands**
- **Found during:** Task 3 (after wiring real login/logout/whoami)
- **Issue:** `test_login_stub_exits_2`, `test_logout_stub_exits_2`, `test_whoami_stub_exits_2` in `cli/tests/test_exit_codes.py` would now fail (login --token returns 0, logout no-instance returns 2 but for a different reason, whoami no-instance returns 3).
- **Fix:** Replaced the three stub-exit assertions with six real per-command behavior tests (`TestAuthCommandExitCodes` class). Kept the matrix-shape constants test and the remaining stubs (scan/publish/export stac) untouched. Plan 01's SUMMARY explicitly flagged this handoff: *"These tests guard the matrix shape; they will be replaced by real per-command behavior tests in plans 02-05."*
- **Files modified:** `cli/tests/test_exit_codes.py`
- **Commit:** `f1d470d1`

**3. [Rule 2 - Missing critical functionality] AppState gained `config` field**
- **Found during:** Task 3
- **Issue:** Plan 01's `AppState` carried only `output/instance_override/json_mode/verbose/quiet` (no `config: AppConfig`). The plan's Task 3 action block specifies adding the config field but the existing AppState dataclass does not have it.
- **Fix:** Extended AppState with `config: _config.AppConfig`; updated `@app.callback()` to call `_config.load_config()` and pass it in. Without this, `active_instance()` would have no way to read `config.instance` for the D-35 precedence chain.
- **Files modified:** `cli/geolens_cli/main.py`
- **Commit:** `f1d470d1`
- **Note:** This is a planned change captured in the plan's `<action>` block; flagging here for traceability since it modifies the AppState public surface that Plan 01 established.

### Auth Gates

None encountered — all three tasks executed autonomously without external authentication, manual verification, or decision checkpoints.

### Architectural Escalations

None.

## TDD Gate Compliance

Plan was `type=execute` with per-task `tdd="true"`. Each task followed RED → GREEN:

| Task | RED commit (test) | GREEN commit (impl) | REFACTOR |
| ---- | ----------------- | ------------------- | -------- |
| 1 (config.py) | `a4eac056` test(216-02): add failing test for config.py… | `857493ce` feat(216-02): implement config.py… | not needed |
| 2 (auth.py) | `d5955c2a` test(216-02): add failing test for auth.py… | `78f31c54` feat(216-02): implement auth.py… | not needed |
| 3 (main.py) | covered by retrofitted exit-code tests in same commit | `f1d470d1` feat(216-02): wire login/logout/whoami… | not needed |

Task 3 is the wiring task that doesn't ship a separate test file; it modified `test_exit_codes.py` (Plan 01's existing matrix file) to convert stub-exit assertions into real-behavior assertions. The task verification ran the full suite and the plan's two programmatic CliRunner checks (whoami no-instance → 3, login mutex → 2) before the GREEN commit landed.

## Threat Flags

None — this plan implements the credential storage that the phase-level threat model already covered (T-216-01 Information Disclosure on credentials.toml + keyring, T-216-02 token replay via refresh-retry, T-216-05 `--token` shell-history acceptance). All mitigations specified in the plan's `<threat_model>` are present in code:

- T-216-01 (info disclosure): `atomic_write_text` enforces mode 0600 on credentials.toml + 0700 on parent dir; structlog warning omits the token value (`error=str(exc)` is the keyring error message, not the credential); `test_config_toml_never_contains_token` asserts D-11.
- T-216-02 (replay): `try_refresh` retries exactly once; second 401 exits EXIT_AUTH; refresh token is rotated on use.
- T-216-05 (`--token` in shell history): MVP risk acknowledged in CONTEXT.md D-09; Plan 06 docs/cli.md will recommend a future `--token-stdin` flow.

## Commits

| Task | Hash | Description |
|------|------|-------------|
| 1 RED | `a4eac056` | test(216-02): add failing test for config.py XDG paths and atomic TOML I/O |
| 1 GREEN | `857493ce` | feat(216-02): implement config.py XDG paths + atomic TOML I/O |
| 2 RED | `d5955c2a` | test(216-02): add failing test for auth.py keyring + file fallback |
| 2 GREEN | `78f31c54` | feat(216-02): implement auth.py keyring + file fallback + refresh-retry |
| 3 | `f1d470d1` | feat(216-02): wire login/logout/whoami + AppState.sdk() lazy property |

## Self-Check: PASSED

- `cli/geolens_cli/config.py` exists ✓
- `cli/geolens_cli/auth.py` exists ✓
- `cli/geolens_cli/main.py` exists ✓
- `cli/tests/test_config.py` exists ✓
- `cli/tests/test_auth_keyring.py` exists ✓
- `cli/tests/test_exit_codes.py` exists ✓
- `.planning/phases/216-geolens-cli-mvp/216-02-SUMMARY.md` exists ✓
- Commit `a4eac056` exists ✓
- Commit `857493ce` exists ✓
- Commit `d5955c2a` exists ✓
- Commit `78f31c54` exists ✓
- Commit `f1d470d1` exists ✓
- 47/47 unit tests passing ✓
- OCCLI-06 invariant holds (zero `^(import|from) (httpx|requests)` in config.py / auth.py / main.py) ✓
- credentials.toml mode 0600 verified by `test_credentials_file_mode_0600` ✓
- Plan-level whoami no-instance → EXIT_AUTH (3) verified ✓
- Plan-level login --token + --api-key mutex → EXIT_USAGE (2) verified ✓
