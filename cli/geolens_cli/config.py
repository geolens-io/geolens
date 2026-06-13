# SPDX-License-Identifier: Apache-2.0
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
    section: dict[str, str] = {"instance": instance}
    if username is not None:
        section["username"] = username
    payload = {"default": section}
    atomic_write_text(config_path(), tomli_w.dumps(payload), mode=0o600, tighten_parent=True)


def atomic_write_text(
    path: Path,
    content: str,
    *,
    mode: int = 0o600,
    tighten_parent: bool = False,
) -> None:
    """Write content to path atomically with the given file mode.

    Per RESEARCH Pattern 4: tempfile in same dir + chmod + os.replace.

    Args:
        path: Destination file path.
        content: Text content to write.
        mode: File permission mode (default 0o600 for secrets).
        tighten_parent: When True, create/chmod the parent directory to 0o700.
            Use this only for SECRET files (e.g. credentials.toml). For
            non-secret outputs (e.g. ``geolens export stac -o file``), leave
            this False so the parent directory's mode is not changed.
            (BUG-014)
    """
    if tighten_parent:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            # On some platforms (Windows) chmod is a no-op; not fatal.
            pass
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
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
    """Canonicalize an instance URL to the single form used for storage AND lookup.

    Performs, in order:
      * strip surrounding whitespace and trailing slashes;
      * reject non-http(s) schemes via ValueError;
      * auto-append the required ``/api`` path prefix when missing (GAP-019),
        idempotently — a URL that already ends in ``/api`` (or has ``/api/``
        somewhere mid-path) is left untouched so existing ``/api``-suffixed
        configs keep resolving.

    Both ``geolens login`` (store side) and ``active_instance()`` (lookup side)
    route through this one function so a trailing-slash or missing-``/api``
    variant resolves to the same canonical key (BUG-033).
    """
    url = url.strip()
    if not url:
        raise ValueError("Instance URL must not be empty")
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Instance URL must use http or https scheme: got {url!r}")
    url = url.rstrip("/")
    if not _has_api_prefix(url):
        url = f"{url}/api"
    return url


def _has_api_prefix(url: str) -> bool:
    """Return True if ``url`` already carries the ``/api`` path prefix.

    Idempotency guard for GAP-019: matches a trailing ``/api`` segment or an
    ``/api/`` segment anywhere in the path so we never double-append.
    """
    from urllib.parse import urlsplit

    path = urlsplit(url).path.rstrip("/")
    if not path:
        return False
    segments = path.split("/")
    return "api" in segments
