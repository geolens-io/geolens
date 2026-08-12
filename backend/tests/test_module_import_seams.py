"""What a module drags in when you import it.

Seams whose cost is invisible at the call site, because an import that is too
expensive still returns the right object. Each is asserted in a fresh
interpreter: inside the pytest process every module is already loaded, so a
``sys.modules`` check here would pass no matter where anything lived.

- The shared rate limiter lived in ``app.modules.auth.router``, so the ten
  modules that decorate routes with it executed 28 auth route registrations
  and that router's transitive imports to get a ``Limiter`` instance. It now
  lives in ``app.platform.ratelimit``, which the platform layering guard
  already forbids from importing ``app.modules.*`` at all.
- ``auth.dependencies`` imported ``catalog.authorization`` for a role lookup
  that reads only auth-owned tables, which made the two highest-fan-in modules
  in the backend mutually dependent. The query lives in ``auth.permissions``
  now, and catalog re-exports it.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _app_modules_loaded_by(import_statement: str, out_path: Path) -> set[str]:
    """The ``app.*`` modules a fresh interpreter loads for *import_statement*.

    The child writes to a file rather than stdout: importing app code
    configures structlog and emits startup log lines, which would sit in the
    middle of anything printed.
    """
    script = textwrap.dedent(f"""
        import json, sys
        {import_statement}
        with open({str(out_path)!r}, "w") as fh:
            json.dump(sorted(m for m in sys.modules if m.startswith("app.")), fh)
    """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            f"`{import_statement}` failed in a fresh interpreter "
            f"(rc={result.returncode}):\n{result.stderr}"
        )
    return set(json.loads(out_path.read_text()))


def test_rate_limiter_home_imports_no_product_module(tmp_path: Path):
    """Importing the limiter must not register anyone's routes."""
    loaded = _app_modules_loaded_by(
        "import app.platform.ratelimit", tmp_path / "ratelimit.json"
    )

    assert "app.modules.auth.router" not in loaded, (
        "importing the rate limiter executes the auth router's route "
        "registrations again — the coupling this module was split out to end"
    )
    assert not {m for m in loaded if m.startswith("app.modules.")}, (
        "app.platform.ratelimit reached a product module: "
        f"{sorted(m for m in loaded if m.startswith('app.modules.'))}"
    )


def test_auth_dependencies_imports_no_catalog_module(tmp_path: Path):
    """Auth must not import catalog to resolve a user's roles."""
    loaded = _app_modules_loaded_by(
        "import app.modules.auth.dependencies", tmp_path / "dependencies.json"
    )

    assert not {m for m in loaded if m.startswith("app.modules.catalog")}, (
        "app.modules.auth.dependencies imported catalog: "
        f"{sorted(m for m in loaded if m.startswith('app.modules.catalog'))}. "
        "get_user_roles lives in app.modules.auth.permissions."
    )


async def test_catalog_authorization_delegates_role_lookup_to_auth(monkeypatch):
    """The catalog entry point is a re-export, never a second implementation.

    Its ~40 callers still import ``get_user_roles`` from here, so the name has
    to stay; what must not come back is the query behind it.
    """
    from app.modules.catalog import authorization

    delegate = AsyncMock(return_value={"editor"})
    monkeypatch.setattr(authorization, "_get_user_roles", delegate)

    session, user = object(), object()
    assert await authorization.get_user_roles(session, user) == {"editor"}
    delegate.assert_awaited_once_with(session, user)
