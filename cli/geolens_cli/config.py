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
