---
phase: 216-geolens-cli-mvp
plan: 02
type: execute
wave: 2
depends_on: [01]
files_modified:
  - cli/geolens_cli/config.py
  - cli/geolens_cli/auth.py
  - cli/geolens_cli/main.py
  - cli/tests/test_config.py
  - cli/tests/test_auth_keyring.py
files_read:
  - cli/geolens_cli/output.py
  - cli/geolens_cli/_sdk_helpers.py
  - cli/tests/conftest.py
autonomous: true
requirements:
  - OCCLI-02
must_haves:
  decisions_covered:
    - "D-08: `geolens login <url>` interactive flow validates URL, prompts username/password, POSTs /auth/login, stores access+refresh tokens in keyring; updates config.toml (no tokens)"
    - "D-09: `--token <jwt>` flag for non-interactive login (skips prompt; pairs with --no-keyring for headless)"
    - "D-10: `--api-key <key>` alternate auth mode stored under keyring account `<url>:api_key`"
    - "D-11: `--no-keyring` fallback writes ~/.config/geolens/credentials.toml mode 0600, parent dir 0700"
    - "D-12: `keyring` library as hard dep; users on headless machines use --no-keyring (no extra backend deps)"
    - "D-13: Refresh-token retry once on 401; if refresh fails, exit code 3 (auth)"
    - "D-14: Single profile for MVP (one `[default]` table)"
    - "D-29: `rich` for human output; --json suppresses formatting; respect NO_COLOR"
    - "D-30: `--json` global flag toggles machine-readable output across all commands"
    - "D-31: `-v`/`--verbose` adds structlog debug; `-q`/`--quiet` suppresses non-error output"
    - "D-32: Exit codes 0/1/2/3/4/5 (success/generic/misuse/auth/network/server)"
    - "D-33: Backend `{detail}` error responses rendered as `Error: <detail>` to stderr; full traceback only with --verbose"
    - "D-34: Config + credentials under XDG_CONFIG_HOME/geolens/ (config.toml without secrets, credentials.toml with mode 0600)"
    - "D-35: Auth precedence — CLI flag > GEOLENS_TOKEN env var > credentials.toml > keyring"
    - "D-36: `--instance <url>` flag overrides active instance for single command invocation"
    - "D-44: Phase 217 SAML compatibility — CLI's auth flow is username/password; SAML users paste JWT via `geolens login --token`"
  truths:
    - "`geolens login <url>` prompts for username/password (or accepts --token / --api-key) and stores credentials in the OS keyring under service `geolens`"
    - "`--no-keyring` writes credentials to `~/.config/geolens/credentials.toml` with mode 0600 and parent dir mode 0700"
    - "When the keyring is unavailable (NoKeyringError / KeyringLocked), the CLI auto-falls back to the credentials.toml file with a printed warning (unless --no-keyring is explicit)"
    - "`geolens logout` deletes both keyring entries (token, refresh) AND the credentials.toml entry for the active instance"
    - "`geolens whoami` calls GET /auth/me via the SDK and prints the current user's email + instance"
    - "Config (instance URL, username) lives in `~/.config/geolens/config.toml` (XDG-compliant via platformdirs); tokens NEVER appear in config.toml"
    - "Auth precedence: CLI flag > GEOLENS_TOKEN env var > credentials.toml > keyring (D-35)"
    - "On 401 from the SDK, if a refresh token is stored, CLI calls POST /auth/refresh once and retries; if refresh fails, prints session-expired message and exits with EXIT_AUTH (3)"
    - "AppState.sdk() lazy-constructs a GeolensClient with the active instance's bearer_token OR api_key (not both)"
  artifacts:
    - path: cli/geolens_cli/config.py
      provides: "AppConfig dataclass; XDG path resolution via platformdirs; load_config / write_default_instance / atomic_write_text helpers"
      contains: "platformdirs"
    - path: cli/geolens_cli/auth.py
      provides: "BearerToken / ApiKey discriminator types; store_bearer_token / store_api_key / store_refresh_token / load_bearer_token / load_api_key / load_refresh_token / delete_credentials; SDK client construction lazy-injected via AppState.sdk()"
      contains: "keyring.set_password"
    - path: cli/geolens_cli/main.py
      provides: "real `login` / `logout` / `whoami` command bodies replacing Plan 01 stubs; AppState.sdk() lazy property"
    - path: cli/tests/test_config.py
      provides: "TOML round-trip + 0600 mode + atomic-write semantics + XDG path resolution"
    - path: cli/tests/test_auth_keyring.py
      provides: "keyring set/get/delete; --no-keyring file fallback; NoKeyringError auto-fallback; precedence rules"
  key_links:
    - from: "cli/geolens_cli/auth.py"
      to: "keyring (service='geolens', account=instance_url)"
      via: "keyring.set_password / get_password / delete_password"
      pattern: "keyring\\.(set|get|delete)_password"
    - from: "cli/geolens_cli/main.py login"
      to: "geolens_sdk.api.auth.login_auth_login_post"
      via: "GeolensClient(base_url=instance) → call_sdk(login_auth_login_post.sync_detailed, ...)"
      pattern: "login_auth_login_post"
    - from: "cli/geolens_cli/main.py whoami"
      to: "geolens_sdk.api.auth.me_auth_me_get"
      via: "AppState.sdk() → me_auth_me_get.sync_detailed"
      pattern: "me_auth_me_get"
    - from: "cli/geolens_cli/auth.py refresh path"
      to: "geolens_sdk.api.auth.refresh_auth_refresh_post"
      via: "401 handler → refresh_auth_refresh_post.sync_detailed → retry once"
      pattern: "refresh_auth_refresh_post"
---

<objective>
Build the credential layer + the three auth commands (`login`, `logout`, `whoami`) on top of Plan 01's scaffold. After this plan: a user can run `geolens login https://geolens.example.com`, type credentials, and see the token persist across CLI invocations via keyring (or `credentials.toml` with `--no-keyring`); `geolens whoami` proves the round-trip.

Purpose: Closes OCCLI-02 — keyring-with-fallback credential storage; XDG config; refresh-token retry; the bridge from `AppState` to a constructed `GeolensClient` that downstream plans (publish, export-stac) consume. Implements decisions D-08 through D-14, D-29, D-32, D-33, D-34, D-35, D-36, D-44.

Output: Working `login`/`logout`/`whoami` commands; `config.py` with XDG resolution and atomic write; `auth.py` with keyring + file fallback + refresh-retry; AppState.sdk() lazy property; unit tests for both modules.
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
@.planning/phases/216-geolens-cli-mvp/216-01-scaffold-cli-package-PLAN.md
@sdks/python/geolens_sdk/auth.py
@sdks/python/geolens_sdk/__init__.py

<interfaces>
<!-- Public surface from sdks/python/geolens_sdk that this plan consumes -->

From geolens_sdk.api.auth — endpoint binders the login/logout/whoami commands call:
```python
# Login: POST /auth/login (body: {username, password}) → TokenResponse
from geolens_sdk.api.auth import login_auth_login_post
# Returns: Response[Union[TokenResponse, HTTPValidationError]]
# 200 OK shape (TokenResponse): {access_token: str, refresh_token: str | None, token_type: str}

# Whoami: GET /auth/me → UserResponse
from geolens_sdk.api.auth import me_auth_me_get
# Returns: Response[Union[UserResponse, ProblemDetail]]
# 200 OK shape (UserResponse): {id, email, full_name, role, ...}

# Refresh: POST /auth/refresh (body: {refresh_token}) → TokenResponse
from geolens_sdk.api.auth import refresh_auth_refresh_post
```

From geolens_sdk.models — request/response shapes:
```python
from geolens_sdk.models.body_login_auth_login_post import BodyLoginAuthLoginPost
# BodyLoginAuthLoginPost(username: str, password: str)
```

From geolens_sdk:
```python
from geolens_sdk import GeolensClient
GeolensClient(base_url=instance)                       # anonymous (used by login)
GeolensClient(base_url=instance, bearer_token="<jwt>") # bearer mode
GeolensClient(base_url=instance, api_key="<key>")      # api-key mode
# .client property returns the underlying AuthenticatedClient/Client
# Raises ValueError if both bearer_token and api_key passed.
```

From cli/geolens_cli/_sdk_helpers.py (Plan 01):
```python
unwrap(resp, *, expected: int = 200) -> T   # parses or exits with EXIT_AUTH/EXIT_SERVER/EXIT_GENERIC
call_sdk(fn, **kwargs) -> Response          # maps httpx errors to EXIT_NETWORK
EXIT_OK=0, EXIT_GENERIC=1, EXIT_USAGE=2, EXIT_AUTH=3, EXIT_NETWORK=4, EXIT_SERVER=5
```

From cli/geolens_cli/output.py (Plan 01):
```python
class Formatter:
    success(msg), error(msg), info(msg), debug(msg), json(payload), is_tty
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Implement config.py — XDG paths, AppConfig, atomic TOML I/O</name>
  <files>cli/geolens_cli/config.py, cli/tests/test_config.py</files>
  <read_first>
    - .planning/phases/216-geolens-cli-mvp/216-RESEARCH.md (Pattern 4 lines 369-393 — atomic_write_text verbatim; Pitfall 8 — platformdirs usage; Standard Stack — version pins)
    - .planning/phases/216-geolens-cli-mvp/216-PATTERNS.md (§`cli/geolens_cli/config.py` — atomic write + idempotency precedent from sync_sdk_versions.py)
    - .planning/phases/216-geolens-cli-mvp/216-CONTEXT.md (D-11, D-34, D-35 — config.toml schema, XDG layout, env-var precedence)
    - scripts/sync_sdk_versions.py (lines 50-62 — file-replace + idempotency precedent)
    - sdks/python/geolens_sdk/auth.py (lines 1-13 — "Hand-maintained — NOT regenerated" docstring marker)
  </read_first>
  <behavior>
    - `AppConfig.load()` reads `~/.config/geolens/config.toml` (XDG-resolved); returns `AppConfig(instance=None, username=None)` when missing
    - `write_default_instance(instance: str, username: str | None)` writes `[default]\ninstance = "..."\nusername = "..."` (no token, no api_key — D-11 forbids tokens in config.toml)
    - `atomic_write_text(path, content, mode=0o600)` creates parent dir at 0o700, writes via mkstemp+chmod+os.replace
    - `credentials_path()` returns the XDG-resolved path to `credentials.toml`
    - `config_path()` returns the XDG-resolved path to `config.toml`
    - `get_instance_from_env() -> str | None` returns `os.environ.get("GEOLENS_INSTANCE")`
    - `get_token_from_env() -> str | None` returns `os.environ.get("GEOLENS_TOKEN")`
    - All paths obey `XDG_CONFIG_HOME` (verified via tmp_xdg_home fixture)
  </behavior>
  <action>
    Create `cli/geolens_cli/config.py` (per RESEARCH Pattern 4 + PATTERNS.md):
    ```python
    """XDG-compliant config + atomic TOML I/O for the GeoLens CLI.

    Hand-maintained — NOT regenerated. config.toml stores the active instance
    URL and username; credentials.toml stores tokens (only when --no-keyring
    is set or the keyring is unavailable). Per CONTEXT.md D-11, tokens NEVER
    appear in config.toml.
    """
    from __future__ import annotations

    import os
    import tempfile
    import tomllib
    from dataclasses import dataclass
    from pathlib import Path
    from typing import Optional

    import tomli_w
    from platformdirs import user_config_dir

    APP_NAME = "geolens"


    def _config_dir() -> Path:
        # platformdirs honors XDG_CONFIG_HOME on Linux, AppData on Windows.
        # appauthor=False so the path is ~/.config/geolens (not ~/.config/geolens/geolens).
        return Path(user_config_dir(APP_NAME, appauthor=False))


    def config_path() -> Path:
        return _config_dir() / "config.toml"


    def credentials_path() -> Path:
        return _config_dir() / "credentials.toml"


    @dataclass
    class AppConfig:
        instance: Optional[str] = None
        username: Optional[str] = None

        @classmethod
        def load(cls) -> "AppConfig":
            path = config_path()
            if not path.is_file():
                return cls()
            try:
                data = tomllib.loads(path.read_text())
            except tomllib.TOMLDecodeError:
                return cls()
            default = data.get("default", {})
            return cls(
                instance=default.get("instance"),
                username=default.get("username"),
            )


    def load_config() -> AppConfig:
        return AppConfig.load()


    def write_default_instance(instance: str, username: Optional[str]) -> None:
        """Write the active instance URL + username to config.toml.

        Does NOT write tokens (D-11). Tokens go to keyring or credentials.toml.
        """
        section = {"instance": instance}
        if username is not None:
            section["username"] = username
        payload = {"default": section}
        atomic_write_text(config_path(), tomli_w.dumps(payload), mode=0o600)


    def atomic_write_text(path: Path, content: str, *, mode: int = 0o600) -> None:
        """Write content to path atomically with the given file mode.

        Per RESEARCH Pattern 4: tempfile in same dir + chmod + os.replace. Parent
        directory is created at 0o700 if missing. On any failure the tempfile is
        removed before the exception propagates.
        """
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Tighten parent dir mode in case it pre-existed at a different mode.
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            # On some platforms (Windows) chmod is a no-op; not fatal.
            pass
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            os.write(fd, content.encode("utf-8"))
            os.close(fd)
            os.chmod(tmp_path, mode)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


    def get_instance_from_env() -> Optional[str]:
        return os.environ.get("GEOLENS_INSTANCE")


    def get_token_from_env() -> Optional[str]:
        return os.environ.get("GEOLENS_TOKEN")


    def normalize_instance_url(url: str) -> str:
        """Strip trailing slash; reject non-http(s) schemes via ValueError."""
        url = url.strip()
        if not url:
            raise ValueError("Instance URL must not be empty")
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"Instance URL must use http or https scheme: got {url!r}")
        return url.rstrip("/")
    ```

    Create `cli/tests/test_config.py`:
    ```python
    """Config module — XDG paths, TOML round-trip, atomic write, mode 0600."""
    from __future__ import annotations

    import os
    import stat

    import pytest
    import tomllib

    from geolens_cli.config import (
        AppConfig,
        atomic_write_text,
        config_path,
        credentials_path,
        get_instance_from_env,
        get_token_from_env,
        load_config,
        normalize_instance_url,
        write_default_instance,
    )


    class TestXdgPaths:
        def test_config_path_under_xdg_home(self, tmp_xdg_home) -> None:
            assert config_path() == tmp_xdg_home / "geolens" / "config.toml"

        def test_credentials_path_under_xdg_home(self, tmp_xdg_home) -> None:
            assert credentials_path() == tmp_xdg_home / "geolens" / "credentials.toml"


    class TestConfigRoundTrip:
        def test_load_when_missing_returns_empty(self, tmp_xdg_home) -> None:
            cfg = load_config()
            assert cfg.instance is None
            assert cfg.username is None

        def test_write_then_load_roundtrip(self, tmp_xdg_home) -> None:
            write_default_instance("https://x.example.com", username="alice")
            cfg = load_config()
            assert cfg.instance == "https://x.example.com"
            assert cfg.username == "alice"

        def test_write_omits_username_when_none(self, tmp_xdg_home) -> None:
            write_default_instance("https://x.example.com", username=None)
            data = tomllib.loads(config_path().read_text())
            assert data["default"]["instance"] == "https://x.example.com"
            assert "username" not in data["default"]

        def test_config_toml_never_contains_token(self, tmp_xdg_home) -> None:
            """D-11: tokens never appear in config.toml."""
            write_default_instance("https://x.example.com", username="alice")
            text = config_path().read_text()
            assert "token" not in text.lower()
            assert "api_key" not in text.lower()


    @pytest.mark.skipif(os.name == "nt", reason="POSIX file modes only")
    class TestFileModes:
        def test_credentials_file_mode_0600(self, tmp_xdg_home) -> None:
            atomic_write_text(credentials_path(), "x = 1\n", mode=0o600)
            actual_mode = stat.S_IMODE(credentials_path().stat().st_mode)
            assert actual_mode == 0o600, f"got {oct(actual_mode)}"

        def test_parent_dir_mode_0700(self, tmp_xdg_home) -> None:
            atomic_write_text(credentials_path(), "x = 1\n", mode=0o600)
            actual_mode = stat.S_IMODE(credentials_path().parent.stat().st_mode)
            assert actual_mode == 0o700, f"got {oct(actual_mode)}"


    class TestEnvOverrides:
        def test_get_instance_from_env(self, monkeypatch) -> None:
            monkeypatch.setenv("GEOLENS_INSTANCE", "https://from-env.example.com")
            assert get_instance_from_env() == "https://from-env.example.com"

        def test_get_token_from_env(self, monkeypatch) -> None:
            monkeypatch.setenv("GEOLENS_TOKEN", "abc.def.ghi")
            assert get_token_from_env() == "abc.def.ghi"

        def test_env_unset_returns_none(self, monkeypatch) -> None:
            monkeypatch.delenv("GEOLENS_INSTANCE", raising=False)
            monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
            assert get_instance_from_env() is None
            assert get_token_from_env() is None


    class TestNormalizeInstanceUrl:
        def test_strips_trailing_slash(self) -> None:
            assert normalize_instance_url("https://x.example.com/") == "https://x.example.com"

        def test_strips_whitespace(self) -> None:
            assert normalize_instance_url("  https://x.example.com  ") == "https://x.example.com"

        def test_rejects_empty(self) -> None:
            with pytest.raises(ValueError, match="must not be empty"):
                normalize_instance_url("")

        def test_rejects_non_http_scheme(self) -> None:
            with pytest.raises(ValueError, match="http or https"):
                normalize_instance_url("ftp://x.example.com")
    ```
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv pip install -e . --quiet 2>/dev/null; uv run pytest tests/test_config.py -v 2>&1 | tail -30</automated>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run python -c "from geolens_cli.config import AppConfig, atomic_write_text, normalize_instance_url, config_path, credentials_path, load_config, write_default_instance; print('OK')"</automated>
    <automated>! grep -rE '^(import|from) (httpx|requests)' /Users/ishiland/Code/geolens/cli/geolens_cli/config.py</automated>
  </verify>
  <acceptance_criteria>
    - cli/geolens_cli/config.py uses `from platformdirs import user_config_dir` (NOT `os.path.expanduser`)
    - cli/geolens_cli/config.py defines `AppConfig` dataclass with `instance: Optional[str]`, `username: Optional[str]` fields
    - cli/geolens_cli/config.py exports `atomic_write_text`, `config_path`, `credentials_path`, `load_config`, `write_default_instance`, `get_instance_from_env`, `get_token_from_env`, `normalize_instance_url`
    - `atomic_write_text` uses `tempfile.mkstemp` + `os.chmod` + `os.replace` (POSIX atomic rename)
    - `cd cli && uv run pytest tests/test_config.py -v` exits 0 with all tests passing (≥ 12 tests; 2 skipped on Windows due to POSIX mode markers)
    - test_config.py asserts mode 0o600 on credentials.toml AND mode 0o700 on parent dir (D-11)
    - test_config.py asserts `"token" not in config.toml` and `"api_key" not in config.toml` (D-11)
    - Zero `import httpx` or `import requests` lines in config.py
  </acceptance_criteria>
  <done>config.py exposes AppConfig + atomic TOML I/O + XDG path resolution + env-var helpers + URL normalization. test_config.py covers 12+ behaviors. Plan 02 Task 2 (auth.py) and Plan 04/05 (publish/export) can call into these helpers.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Implement auth.py — keyring + file fallback + refresh-retry</name>
  <files>cli/geolens_cli/auth.py, cli/tests/test_auth_keyring.py</files>
  <read_first>
    - .planning/phases/216-geolens-cli-mvp/216-RESEARCH.md (Pattern 5 lines 401-421 verbatim; Pitfall 4 — NoKeyringError + KeyringLocked subclass of KeyringError; Pitfall 7 (refresh-retry context); Assumption A5 — verify KeyringError is parent of both)
    - .planning/phases/216-geolens-cli-mvp/216-PATTERNS.md (§`cli/geolens_cli/auth.py` — sibling pattern from sdks/python/geolens_sdk/auth.py)
    - .planning/phases/216-geolens-cli-mvp/216-CONTEXT.md (D-08 through D-14 — the full auth flow; D-44 — SAML overlay does not require CLI changes)
    - sdks/python/geolens_sdk/auth.py (lines 1-71 — module docstring style + ValueError-on-both gate)
    - cli/geolens_cli/config.py (Task 1 — atomic_write_text, credentials_path, config_path, get_token_from_env)
  </read_first>
  <behavior>
    - `BearerToken(value: str)` and `ApiKey(value: str)` are simple dataclasses (discriminator types)
    - `store_bearer_token(instance, token, *, no_keyring=False) -> str` returns "keyring" or "file" depending on which backend was used
    - `store_api_key(instance, api_key, *, no_keyring=False) -> str` same shape
    - `store_refresh_token(instance, refresh, *, no_keyring=False) -> str` same shape
    - `load_bearer_token(instance) -> BearerToken | None` checks GEOLENS_TOKEN env first (per D-35), then keyring service=`geolens` account=`<instance>`, then credentials.toml `[<instance>].bearer_token`
    - `load_api_key(instance) -> ApiKey | None` checks keyring account=`<instance>:api_key`, then credentials.toml `[<instance>].api_key`
    - `load_refresh_token(instance) -> str | None` checks keyring account=`<instance>:refresh`, then credentials.toml `[<instance>].refresh_token`
    - `delete_credentials(instance) -> None` removes ALL three keyring entries AND the credentials.toml `[<instance>]` table; missing entries are silently ignored
    - On `keyring.errors.KeyringError` (parent of NoKeyringError + KeyringLocked per A5), auto-fall back to file with a structlog warning unless `no_keyring=True` was explicit
    - `try_refresh(instance) -> str | None` calls `refresh_auth_refresh_post.sync_detailed`; returns new access_token on success (also rotates the stored refresh_token if response includes one); returns None on failure
  </behavior>
  <action>
    Create `cli/geolens_cli/auth.py` (per RESEARCH Pattern 5 + Pitfall 4 + PATTERNS.md analog):
    ```python
    """Credential storage — OS keyring with credentials.toml fallback.

    Hand-maintained — NOT regenerated. Mirrors sdks/python/geolens_sdk/auth.py's
    "configure exactly one" discipline for BearerToken vs ApiKey.

    Backend storage precedence (matches CONTEXT.md D-35):
        CLI flag (handled in main.py)
        > GEOLENS_TOKEN env var
        > credentials.toml
        > OS keyring

    Storage backends:
        Default: OS keyring via `keyring` (service="geolens", account=<instance_url>)
        Fallback: ~/.config/geolens/credentials.toml (mode 0600)
    """
    from __future__ import annotations

    from dataclasses import dataclass
    from typing import Optional

    import keyring
    import structlog
    import tomli_w
    import tomllib
    from keyring.errors import KeyringError

    from . import config as _config

    log = structlog.get_logger()
    SERVICE = "geolens"


    @dataclass(frozen=True)
    class BearerToken:
        value: str


    @dataclass(frozen=True)
    class ApiKey:
        value: str


    # ---------- Internal helpers ----------

    def _keyring_account_token(instance: str) -> str:
        return instance


    def _keyring_account_refresh(instance: str) -> str:
        return f"{instance}:refresh"


    def _keyring_account_api_key(instance: str) -> str:
        return f"{instance}:api_key"


    def _read_credentials_file() -> dict:
        path = _config.credentials_path()
        if not path.is_file():
            return {}
        try:
            return tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError:
            return {}


    def _write_credentials_file(data: dict) -> None:
        _config.atomic_write_text(
            _config.credentials_path(),
            tomli_w.dumps(data),
            mode=0o600,
        )


    def _set_credential_field(instance: str, field: str, value: str) -> None:
        data = _read_credentials_file()
        data.setdefault(instance, {})[field] = value
        _write_credentials_file(data)


    def _clear_credential_section(instance: str) -> None:
        data = _read_credentials_file()
        data.pop(instance, None)
        if data:
            _write_credentials_file(data)
        else:
            # Empty -> remove the file entirely so `geolens logout` leaves no trace.
            path = _config.credentials_path()
            if path.exists():
                path.unlink()


    # ---------- Store ----------

    def store_bearer_token(instance: str, token: str, *, no_keyring: bool = False) -> str:
        """Store the access token. Returns 'keyring' or 'file'."""
        if not no_keyring:
            try:
                keyring.set_password(SERVICE, _keyring_account_token(instance), token)
                return "keyring"
            except KeyringError as exc:
                log.warning("keyring_unavailable_falling_back_to_file", error=str(exc))
        _set_credential_field(instance, "bearer_token", token)
        return "file"


    def store_api_key(instance: str, api_key: str, *, no_keyring: bool = False) -> str:
        """Store an API key. Returns 'keyring' or 'file'."""
        if not no_keyring:
            try:
                keyring.set_password(SERVICE, _keyring_account_api_key(instance), api_key)
                return "keyring"
            except KeyringError as exc:
                log.warning("keyring_unavailable_falling_back_to_file", error=str(exc))
        _set_credential_field(instance, "api_key", api_key)
        return "file"


    def store_refresh_token(instance: str, refresh: str, *, no_keyring: bool = False) -> str:
        if not no_keyring:
            try:
                keyring.set_password(SERVICE, _keyring_account_refresh(instance), refresh)
                return "keyring"
            except KeyringError as exc:
                log.warning("keyring_unavailable_falling_back_to_file", error=str(exc))
        _set_credential_field(instance, "refresh_token", refresh)
        return "file"


    # ---------- Load ----------

    def load_bearer_token(instance: str) -> Optional[BearerToken]:
        """Return the active bearer token per the D-35 precedence."""
        env_token = _config.get_token_from_env()
        if env_token:
            return BearerToken(env_token)
        # credentials.toml > keyring (file is explicit; keyring is fallback)
        data = _read_credentials_file().get(instance, {})
        token = data.get("bearer_token")
        if token:
            return BearerToken(token)
        try:
            kr_token = keyring.get_password(SERVICE, _keyring_account_token(instance))
        except KeyringError:
            return None
        return BearerToken(kr_token) if kr_token else None


    def load_api_key(instance: str) -> Optional[ApiKey]:
        data = _read_credentials_file().get(instance, {})
        key = data.get("api_key")
        if key:
            return ApiKey(key)
        try:
            kr_key = keyring.get_password(SERVICE, _keyring_account_api_key(instance))
        except KeyringError:
            return None
        return ApiKey(kr_key) if kr_key else None


    def load_refresh_token(instance: str) -> Optional[str]:
        data = _read_credentials_file().get(instance, {})
        refresh = data.get("refresh_token")
        if refresh:
            return refresh
        try:
            return keyring.get_password(SERVICE, _keyring_account_refresh(instance))
        except KeyringError:
            return None


    # ---------- Delete ----------

    def delete_credentials(instance: str) -> None:
        """Remove all three keyring entries AND the credentials.toml section.

        Missing entries are silently ignored — logout is idempotent.
        """
        for account in (
            _keyring_account_token(instance),
            _keyring_account_refresh(instance),
            _keyring_account_api_key(instance),
        ):
            try:
                keyring.delete_password(SERVICE, account)
            except (KeyringError, Exception):
                # PasswordDeleteError is a sibling of KeyringError in older keyring
                # versions; swallow both.
                pass
        _clear_credential_section(instance)


    # ---------- Refresh ----------

    def try_refresh(instance: str) -> Optional[str]:
        """Attempt a single refresh; return new access token or None on failure.

        Per CONTEXT D-13, this is called once on a 401. If it fails, the caller
        prints "Session expired" and exits with EXIT_AUTH (3).
        """
        refresh = load_refresh_token(instance)
        if not refresh:
            return None
        from geolens_sdk import GeolensClient
        from geolens_sdk.api.auth import refresh_auth_refresh_post
        from geolens_sdk.models.refresh_token_request import RefreshTokenRequest

        try:
            sdk = GeolensClient(base_url=instance)
            body = RefreshTokenRequest(refresh_token=refresh)
            resp = refresh_auth_refresh_post.sync_detailed(client=sdk.client, body=body)
        except Exception as exc:  # network or unexpected SDK error
            log.warning("refresh_failed", error=str(exc))
            return None
        if int(resp.status_code) != 200:
            return None
        parsed = resp.parsed
        if parsed is None or not getattr(parsed, "access_token", None):
            return None
        new_access = parsed.access_token
        store_bearer_token(instance, new_access, no_keyring=False)
        new_refresh = getattr(parsed, "refresh_token", None)
        if new_refresh:
            store_refresh_token(instance, new_refresh, no_keyring=False)
        return new_access
    ```

    Note on `RefreshTokenRequest`: the executor MUST verify the actual model name in `sdks/python/geolens_sdk/models/`. The OpenAPI snapshot's refresh body class may be named `RefreshRequest`, `BodyRefreshAuthRefreshPost`, or similar. Read `sdks/python/geolens_sdk/api/auth/refresh_auth_refresh_post.py` to confirm the body parameter type, and adjust the import accordingly. If the endpoint takes the refresh token as a query/header parameter rather than a body, drop the body construction and pass the parameter the SDK signature requires.

    Create `cli/tests/test_auth_keyring.py`:
    ```python
    """Auth module — keyring + file fallback + refresh-retry."""
    from __future__ import annotations

    import os
    import stat

    import pytest

    from geolens_cli import auth as _auth
    from geolens_cli import config as _config


    INSTANCE = "https://test.example.com"


    class TestKeyringStore:
        def test_store_bearer_uses_keyring(self, tmp_xdg_home, mock_keyring) -> None:
            backend = _auth.store_bearer_token(INSTANCE, "tok-1")
            assert backend == "keyring"
            assert mock_keyring[("geolens", INSTANCE)] == "tok-1"

        def test_store_api_key_uses_keyring(self, tmp_xdg_home, mock_keyring) -> None:
            backend = _auth.store_api_key(INSTANCE, "key-1")
            assert backend == "keyring"
            assert mock_keyring[("geolens", f"{INSTANCE}:api_key")] == "key-1"

        def test_store_refresh_uses_keyring(self, tmp_xdg_home, mock_keyring) -> None:
            backend = _auth.store_refresh_token(INSTANCE, "ref-1")
            assert backend == "keyring"
            assert mock_keyring[("geolens", f"{INSTANCE}:refresh")] == "ref-1"

        def test_load_bearer_from_keyring(self, tmp_xdg_home, mock_keyring) -> None:
            mock_keyring[("geolens", INSTANCE)] = "tok-2"
            tok = _auth.load_bearer_token(INSTANCE)
            assert tok is not None
            assert tok.value == "tok-2"

        def test_load_returns_none_when_missing(self, tmp_xdg_home, mock_keyring) -> None:
            assert _auth.load_bearer_token(INSTANCE) is None
            assert _auth.load_api_key(INSTANCE) is None
            assert _auth.load_refresh_token(INSTANCE) is None


    class TestNoKeyringFallback:
        def test_store_bearer_no_keyring_writes_file(self, tmp_xdg_home, mock_keyring) -> None:
            backend = _auth.store_bearer_token(INSTANCE, "tok-3", no_keyring=True)
            assert backend == "file"
            # Token should NOT be in keyring
            assert ("geolens", INSTANCE) not in mock_keyring
            # File should contain the token
            text = _config.credentials_path().read_text()
            assert "tok-3" in text

        @pytest.mark.skipif(os.name == "nt", reason="POSIX file modes only")
        def test_credentials_file_mode_0600(self, tmp_xdg_home, mock_keyring) -> None:
            _auth.store_bearer_token(INSTANCE, "tok-4", no_keyring=True)
            actual_mode = stat.S_IMODE(_config.credentials_path().stat().st_mode)
            assert actual_mode == 0o600

        def test_load_bearer_from_file(self, tmp_xdg_home, mock_keyring) -> None:
            _auth.store_bearer_token(INSTANCE, "tok-5", no_keyring=True)
            tok = _auth.load_bearer_token(INSTANCE)
            assert tok is not None
            assert tok.value == "tok-5"


    class TestKeyringErrorAutoFallback:
        def test_keyring_error_falls_back_to_file(self, tmp_xdg_home, monkeypatch) -> None:
            from keyring.errors import NoKeyringError

            def explode(*args, **kwargs):
                raise NoKeyringError("no backend")

            monkeypatch.setattr("keyring.set_password", explode)
            backend = _auth.store_bearer_token(INSTANCE, "tok-6")
            assert backend == "file"
            text = _config.credentials_path().read_text()
            assert "tok-6" in text


    class TestEnvOverride:
        def test_env_token_takes_precedence(self, tmp_xdg_home, mock_keyring, monkeypatch) -> None:
            mock_keyring[("geolens", INSTANCE)] = "tok-from-keyring"
            monkeypatch.setenv("GEOLENS_TOKEN", "tok-from-env")
            tok = _auth.load_bearer_token(INSTANCE)
            assert tok is not None
            assert tok.value == "tok-from-env"


    class TestDeleteCredentials:
        def test_delete_clears_keyring_and_file(self, tmp_xdg_home, mock_keyring) -> None:
            _auth.store_bearer_token(INSTANCE, "tok", no_keyring=False)
            _auth.store_refresh_token(INSTANCE, "ref", no_keyring=False)
            _auth.store_api_key(INSTANCE, "key", no_keyring=True)  # this one in file
            _auth.delete_credentials(INSTANCE)
            # Keyring entries gone
            assert ("geolens", INSTANCE) not in mock_keyring
            assert ("geolens", f"{INSTANCE}:refresh") not in mock_keyring
            # File entry gone
            assert _auth.load_api_key(INSTANCE) is None

        def test_delete_idempotent_when_nothing_stored(self, tmp_xdg_home, mock_keyring) -> None:
            _auth.delete_credentials(INSTANCE)  # should not raise
    ```
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run pytest tests/test_auth_keyring.py -v 2>&1 | tail -30</automated>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run python -c "from geolens_cli.auth import BearerToken, ApiKey, store_bearer_token, store_api_key, store_refresh_token, load_bearer_token, load_api_key, load_refresh_token, delete_credentials, try_refresh, SERVICE; assert SERVICE=='geolens'; print('OK')"</automated>
    <automated>! grep -rE '^(import|from) (httpx|requests)' /Users/ishiland/Code/geolens/cli/geolens_cli/auth.py</automated>
  </verify>
  <acceptance_criteria>
    - cli/geolens_cli/auth.py defines `SERVICE = "geolens"`
    - cli/geolens_cli/auth.py defines `BearerToken` and `ApiKey` frozen dataclasses with `value: str`
    - cli/geolens_cli/auth.py exports `store_bearer_token`, `store_api_key`, `store_refresh_token`, `load_bearer_token`, `load_api_key`, `load_refresh_token`, `delete_credentials`, `try_refresh`
    - All store/load/delete functions accept the `instance` parameter and use keyring service `geolens` with account `<instance>` (token), `<instance>:refresh` (refresh), `<instance>:api_key` (api key)
    - `KeyringError` (parent class) is caught (not just NoKeyringError) — verified by reading auth.py for `from keyring.errors import KeyringError`
    - `load_bearer_token` checks `GEOLENS_TOKEN` env first (D-35 precedence)
    - `cd cli && uv run pytest tests/test_auth_keyring.py -v` exits 0 with all tests passing (≥ 12 tests)
    - test_auth_keyring asserts the auto-fallback path triggers on `NoKeyringError`
    - test_auth_keyring asserts credentials.toml mode is 0600 on POSIX
    - Zero `import httpx` or `import requests` lines in auth.py
  </acceptance_criteria>
  <done>auth.py exposes the full credential lifecycle: store, load (with env > file > keyring precedence), delete, and refresh-retry. Test coverage proves keyring is the default, file is the fallback, KeyringError auto-falls back, and `delete_credentials` clears both backends.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Wire login / logout / whoami commands + AppState.sdk() lazy property</name>
  <files>cli/geolens_cli/main.py</files>
  <read_first>
    - cli/geolens_cli/main.py (Plan 01 — current scaffolding with stub commands; AppState dataclass shape)
    - cli/geolens_cli/auth.py (Task 2 — store/load/delete/try_refresh API)
    - cli/geolens_cli/config.py (Task 1 — load_config, write_default_instance, normalize_instance_url, get_instance_from_env, get_token_from_env)
    - cli/geolens_cli/_sdk_helpers.py (Plan 01 — unwrap, call_sdk, EXIT_*)
    - .planning/phases/216-geolens-cli-mvp/216-RESEARCH.md (Example A lines 666-722 verbatim — login flow; Open Question 3 — whoami calls /auth/me always)
    - .planning/phases/216-geolens-cli-mvp/216-CONTEXT.md (D-08 step-by-step login; D-09 --token; D-10 --api-key; D-13 refresh-retry; D-14 single profile MVP; D-44 SAML uses --token paste-flow)
    - sdks/python/geolens_sdk/api/auth/login_auth_login_post.py (verify the function signature, body model name, and 200 response shape)
    - sdks/python/geolens_sdk/api/auth/me_auth_me_get.py (verify the function signature)
  </read_first>
  <behavior>
    - `geolens login <url>` (no flags): prompt for username + password (hidden), POST to /auth/login, store access + refresh tokens in keyring, write config.toml, print success
    - `geolens login <url> --token <jwt>`: skip prompt, store the JWT directly
    - `geolens login <url> --api-key <key>`: skip prompt, store the API key
    - `geolens login <url> --no-keyring`: same flows but write to credentials.toml instead of keyring
    - `--token` and `--api-key` are mutually exclusive (raises typer.BadParameter / EXIT_USAGE)
    - `geolens logout`: deletes credentials for the active instance (config.instance) — both keyring AND credentials.toml entries
    - `geolens whoami`: calls /auth/me via SDK; prints `username (instance)`; on 401 with stored refresh token, retries once; on second 401 prints "Session expired" + exits EXIT_AUTH (3)
    - `AppState.sdk()` lazy-constructs a `GeolensClient` for the active instance using the highest-precedence credential available (CLI flag > env > file > keyring per D-35)
    - `AppState.sdk()` raises `typer.BadParameter` when no instance is configured (with message instructing the user to run `geolens login`)
  </behavior>
  <action>
    Modify `cli/geolens_cli/main.py` — replace the Plan 01 stub command bodies for `login`, `logout`, `whoami` with real implementations and add the `AppState.sdk()` lazy property. The `scan`, `publish`, `export stac` stubs remain unchanged in this plan (they are filled by Plans 03/04/05). Keep the existing imports + `_version_callback` + `@app.callback()` block intact.

    Update the imports at the top of main.py to add:
    ```python
    import getpass
    from . import auth as _auth, config as _config
    from ._sdk_helpers import EXIT_AUTH, call_sdk, unwrap
    ```

    Extend the `AppState` dataclass with the `sdk()` lazy method (replacing the Plan 01 placeholder). The new AppState block should look like:
    ```python
    @dataclass
    class AppState:
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
            from geolens_sdk import GeolensClient
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
    ```

    Update `@app.callback()` to load config and pass it into AppState:
    ```python
    @app.callback()
    def root(...) -> None:
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
    ```

    Replace the `login` stub body with the real implementation per RESEARCH Example A:
    ```python
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
        from geolens_sdk import GeolensClient
        from geolens_sdk.api.auth import login_auth_login_post
        from geolens_sdk.models.body_login_auth_login_post import BodyLoginAuthLoginPost

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
    ```

    Replace the `logout` stub body:
    ```python
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
    ```

    Replace the `whoami` stub body. Per Open Question 3 (RESEARCH lines 962-965): always call /auth/me; on network error fall back to cached username with a warning. Implement refresh-retry per D-13:
    ```python
    @app.command()
    def whoami(ctx: typer.Context) -> None:
        """Print the current user/instance (calls /auth/me; refresh-retries once on 401)."""
        state: AppState = ctx.obj
        instance = state.active_instance()
        if not instance:
            state.output.error("No active instance. Run `geolens login <url>` first.")
            raise typer.Exit(EXIT_AUTH)

        from geolens_sdk.api.auth import me_auth_me_get

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
    ```

    Note for the executor: read `sdks/python/geolens_sdk/api/auth/login_auth_login_post.py` and `me_auth_me_get.py` to confirm the exact body class name (e.g., `BodyLoginAuthLoginPost`) and the response model name (e.g., `TokenResponse`, `UserResponse`). If a name differs, update the import accordingly. The CLI accesses fields via `getattr(...)` to be resilient to OpenAPI field renames during regeneration.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run python -c "from geolens_cli.main import app, AppState; import inspect; src = inspect.getsource(AppState); assert 'def sdk' in src; assert 'def active_instance' in src; print('OK')"</automated>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run pytest tests/test_version.py tests/test_output.py tests/test_config.py tests/test_auth_keyring.py -v 2>&1 | tail -10</automated>
    <automated>! grep -rE '^(import|from) (httpx|requests)' /Users/ishiland/Code/geolens/cli/geolens_cli/main.py</automated>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run python -c "
from typer.testing import CliRunner
from geolens_cli.main import app
runner = CliRunner()
# No instance configured → whoami must exit with EXIT_AUTH (3)
import os
os.environ.pop('GEOLENS_INSTANCE', None)
os.environ.pop('GEOLENS_TOKEN', None)
import tempfile, pathlib
with tempfile.TemporaryDirectory() as td:
    os.environ['XDG_CONFIG_HOME'] = td
    result = runner.invoke(app, ['whoami'])
    assert result.exit_code == 3, f'got {result.exit_code}: {result.output}'
print('OK')
"</automated>
    <automated>cd /Users/ishiland/Code/geolens/cli && uv run python -c "
from typer.testing import CliRunner
from geolens_cli.main import app
runner = CliRunner()
# --token and --api-key together must exit 2
result = runner.invoke(app, ['login', 'https://x.example.com', '--token', 'abc', '--api-key', 'xyz', '--no-keyring'])
assert result.exit_code == 2, f'got {result.exit_code}: {result.output}'
print('OK')
"</automated>
  </verify>
  <acceptance_criteria>
    - cli/geolens_cli/main.py `AppState` has `sdk()` method that imports GeolensClient lazily and uses load_bearer_token / load_api_key with the active_instance
    - cli/geolens_cli/main.py `AppState` has `active_instance()` method honoring D-35 precedence (instance_override > env > config)
    - `@app.callback()` calls `_config.load_config()` and passes it into AppState
    - `login` command imports `getpass`, prompts username + password (in interactive mode), POSTs via `login_auth_login_post.sync_detailed`, calls `unwrap(resp, expected=200)`, calls `store_bearer_token` and (if present) `store_refresh_token`, calls `write_default_instance`
    - `login --token` skips prompt and calls only `store_bearer_token`
    - `login --api-key` skips prompt and calls only `store_api_key`
    - `login` returns EXIT_USAGE (2) when both `--token` and `--api-key` are passed
    - `logout` calls `delete_credentials(active_instance)` and unlinks `config_path()`
    - `whoami` calls `me_auth_me_get.sync_detailed`; on 401 calls `try_refresh`; on second 401 exits EXIT_AUTH (3)
    - Programmatic test (no real backend): `geolens whoami` with no instance configured exits with code 3 (EXIT_AUTH) — verified by automated script
    - Programmatic test: `geolens login <url> --token A --api-key B` exits with code 2 (EXIT_USAGE) — verified by automated script
    - Zero `import httpx` or `import requests` lines in main.py
  </acceptance_criteria>
  <done>The three auth commands work end-to-end against the SDK. `geolens login`/`logout`/`whoami` no longer raise "not yet implemented". AppState.sdk() is the bridge Plans 04 (publish) and 05 (export stac) consume to get an authenticated GeolensClient.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| User shell → CLI process | Username/password typed at the prompt; `--token`/`--api-key` flags may also carry secrets |
| CLI process → keyring | Tokens written via `keyring.set_password` (OS-native: Keychain on macOS, Credential Manager on Windows, Secret Service / KWallet on Linux) |
| CLI process → credentials.toml | Tokens written to disk under XDG_CONFIG_HOME with mode 0600 (parent dir 0700) |
| CLI process → backend | HTTPS to `<instance>/auth/login`, `/auth/me`, `/auth/refresh` — all via the geolens-sdk httpx client (TLS by SDK default) |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-216-01 | Information Disclosure | credentials.toml on disk | mitigate | atomic_write_text enforces mode 0600; parent dir mode 0700; tomllib-decoded so no log lines emit token strings; structlog warning on fallback says "keyring_unavailable_falling_back_to_file" without including the token value (per D-11). Verified by test_auth_keyring `test_credentials_file_mode_0600` and `test_config.py::test_config_toml_never_contains_token`. |
| T-216-01 | Information Disclosure | keyring service "geolens" | mitigate | OS-native primitive; per-instance accounts (`<instance>` for token, `<instance>:refresh` for refresh, `<instance>:api_key` for API key). No token strings logged anywhere in auth.py. |
| T-216-02 | Spoofing / Replay | Stolen access token replayed against the API | mitigate | Refresh-token retry on 401 happens ONCE; second 401 exits EXIT_AUTH (3) and prompts re-login. Refresh is rotated on use (the new refresh token replaces the stored one). The CLI never silently re-issues without an explicit `try_refresh` call. |
| T-216-02 | Spoofing | Forged login response | accept | The SDK validates HTTP responses against the OpenAPI schema; backend issues JWTs signed with `JWT_SECRET_KEY`. Verifying signatures client-side is a server-side responsibility (the JWT lives on the client purely as an opaque bearer token). |
| T-216-05 | Information Disclosure | `--token <jwt>` flag in shell history | accept-mitigated | CONTEXT.md D-09 explicitly exposes `--token` for MVP (paste-token flow for SAML/OAuth). Plan 06 docs/cli.md MUST recommend a `--token-stdin` follow-up and warn about shell history. The MVP risk is acknowledged, low-impact (rotatable JWT), and called out in user docs. |

**Not Applicable in this plan:**
- T-216-03 (file-content spoof): Not applicable — auth/config flow does not handle uploaded files; `scan` (Plan 03) and `publish` (Plan 04) own extension/MIME concerns. The server is the security boundary for content validation.
- T-216-04 (HTTP bypass): Not applicable to direct mitigation — this plan adds `config.py` and `auth.py`, both of which use only the SDK (`geolens_sdk.api.auth.*`) and `keyring`. Acceptance criteria assert zero `^(import|from) (httpx|requests)` lines in those files; the global CI grep gate that closes T-216-04 ships in Plan 06.
</threat_model>

<verification>
Phase-level checks for this plan:
- `cd cli && uv run pytest tests/test_config.py tests/test_auth_keyring.py -v` exits 0 with all tests passing (≥ 24 tests; some skipped on Windows)
- `cd cli && uv run pytest -v` (full unit slice) exits 0
- `geolens login <url> --token A --api-key B` exits with code 2 (EXIT_USAGE)
- `geolens whoami` with no config exits with code 3 (EXIT_AUTH)
- credentials.toml mode 0600 verified on POSIX
- `grep -rE '^(import|from) (httpx|requests)' cli/geolens_cli/{config,auth,main}.py` returns zero matches (OCCLI-06 holding)
</verification>

<success_criteria>
- OCCLI-02 closed: keyring-by-default + `--no-keyring` file fallback + auto-fallback on KeyringError + refresh-token retry + XDG-compliant config + token-never-in-config.toml all verified by tests
- AppState.sdk() lazy property exposes the authenticated GeolensClient to Plans 04 and 05
- `geolens login` / `logout` / `whoami` work against a real backend (UAT verified in Plan 06's round-trip)
- Zero new direct httpx/requests imports introduced
</success_criteria>

<output>
After completion, create `.planning/phases/216-geolens-cli-mvp/216-02-SUMMARY.md` capturing: files created/modified, OCCLI-02 evidence (test counts + file mode + keyring service name), the AppState.sdk() public surface that Plans 04/05 consume, and any deviations from RESEARCH (e.g., if `RefreshTokenRequest` model name was different, document the actual name used).
</output>
