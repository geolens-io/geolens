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
        except Exception:
            # PasswordDeleteError + KeyringError + missing entries all swallowed.
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
    from geolens_sdk.models.refresh_request import RefreshRequest

    try:
        sdk = GeolensClient(base_url=instance)
        body = RefreshRequest(refresh_token=refresh)
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
