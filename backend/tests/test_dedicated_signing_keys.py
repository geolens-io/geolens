"""TILE_SIGNING_SECRET and SESSION_SECRET_KEY validation, selection and warnings.

Every key is generated inside the test; none is printed.
"""

import secrets
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr, ValidationError
from starlette.applications import Starlette
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.api import main as main_module
from app.core.config import Settings

JWT = "j" * 40
BASE_ENV = {
    "postgres_password": "testpass",
    "jwt_secret_key": JWT,
    "geolens_admin_username": "admin",
    "geolens_admin_password": "adminpass",
    "aws_role_arn": None,
    "aws_web_identity_token_file": None,
    "aws_container_credentials_full_uri": None,
    "aws_container_credentials_relative_uri": None,
}


def _settings(**overrides) -> Settings:
    return Settings(**{**BASE_ENV, **overrides})


def _key() -> str:
    return secrets.token_hex(32)


@pytest.mark.parametrize("field", ["tile_signing_secret", "session_secret_key"])
def test_unset_and_empty_keys_are_allowed(field):
    """Unset and empty-string both mean no dedicated key."""
    assert getattr(_settings(), field) is None
    assert getattr(_settings(**{field: ""}), field) is None


def test_distinct_long_keys_are_accepted():
    s = _settings(tile_signing_secret=_key(), session_secret_key=_key())
    assert s.tile_signing_secret and s.session_secret_key


@pytest.mark.parametrize(
    ("field", "name"),
    [
        ("tile_signing_secret", "TILE_SIGNING_SECRET"),
        ("session_secret_key", "SESSION_SECRET_KEY"),
    ],
)
def test_short_key_is_refused_by_name_without_the_value(field, name):
    short = "short-" + secrets.token_hex(4)
    with pytest.raises(ValidationError) as exc:
        _settings(**{field: short})
    msg = exc.value.errors()[0]["msg"]
    assert name in msg
    assert short not in msg


@pytest.mark.parametrize(
    ("field", "name"),
    [
        ("tile_signing_secret", "TILE_SIGNING_SECRET"),
        ("session_secret_key", "SESSION_SECRET_KEY"),
    ],
)
def test_key_equal_to_jwt_secret_is_refused(field, name):
    with pytest.raises(ValidationError) as exc:
        _settings(**{field: JWT})
    msg = exc.value.errors()[0]["msg"]
    assert f"{name} must not be the same value as JWT_SECRET_KEY" in msg
    assert JWT not in msg


def test_keys_equal_to_each_other_are_refused():
    shared = _key()
    with pytest.raises(ValidationError) as exc:
        _settings(tile_signing_secret=shared, session_secret_key=shared)
    msg = exc.value.errors()[0]["msg"]
    assert "SESSION_SECRET_KEY must not be the same value as" in msg
    assert shared not in msg


def _app(secret: str) -> Starlette:
    async def read(request):
        return JSONResponse(dict(request.session))

    async def write(request):
        request.session["user"] = "alice"
        return JSONResponse({})

    app = Starlette(routes=[Route("/read", read), Route("/write", write)])
    app.add_middleware(SessionMiddleware, secret_key=secret)
    return app


def test_unset_key_keeps_the_jwt_secret_so_old_cookies_still_load():
    """A cookie minted under the JWT secret loads when no dedicated key is set."""
    s = _settings()
    assert main_module._session_secret(s) == JWT
    writer = TestClient(_app(JWT))
    writer.get("/write")
    reader = TestClient(_app(main_module._session_secret(s)))
    reader.cookies.update(writer.cookies)
    assert reader.get("/read").json() == {"user": "alice"}


def test_dedicated_key_rejects_a_cookie_signed_under_the_jwt_secret():
    s = _settings(session_secret_key=_key())
    writer = TestClient(_app(JWT))
    writer.get("/write")
    reader = TestClient(_app(main_module._session_secret(s)))
    reader.cookies.update(writer.cookies)
    assert reader.get("/read").json() == {}


def test_warning_names_each_unset_key_in_production_only():
    log = MagicMock()
    both_unset = SimpleNamespace(
        is_production=True, tile_signing_secret=None, session_secret_key=None
    )
    main_module._warn_if_dedicated_keys_unset(both_unset, log)
    assert log.warning.call_count == 2

    log = MagicMock()
    one_set = SimpleNamespace(
        is_production=True,
        tile_signing_secret=SecretStr(_key()),
        session_secret_key=None,
    )
    main_module._warn_if_dedicated_keys_unset(one_set, log)
    assert log.warning.call_count == 1
    assert "SESSION_SECRET_KEY" in log.warning.call_args.kwargs["message"]

    log = MagicMock()
    dev = SimpleNamespace(
        is_production=False, tile_signing_secret=None, session_secret_key=None
    )
    main_module._warn_if_dedicated_keys_unset(dev, log)
    log.warning.assert_not_called()
