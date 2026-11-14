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


def test_short_session_key_is_refused_by_name_without_the_value():
    short = "short-" + secrets.token_hex(4)
    with pytest.raises(ValidationError) as exc:
        _settings(session_secret_key=short)
    msg = exc.value.errors()[0]["msg"]
    assert "SESSION_SECRET_KEY" in msg
    assert short not in msg


def test_session_key_equal_to_jwt_secret_is_refused():
    with pytest.raises(ValidationError) as exc:
        _settings(session_secret_key=JWT)
    msg = exc.value.errors()[0]["msg"]
    assert "SESSION_SECRET_KEY must not be the same value as JWT_SECRET_KEY" in msg
    assert JWT not in msg


def test_session_key_equal_to_tile_key_is_refused():
    shared = _key()
    with pytest.raises(ValidationError) as exc:
        _settings(tile_signing_secret=shared, session_secret_key=shared)
    msg = exc.value.errors()[0]["msg"]
    assert "SESSION_SECRET_KEY must not be the same value as TILE_SIGNING_SECRET" in msg
    assert shared not in msg


@pytest.mark.parametrize("tile", ["tiny-key", JWT])
def test_existing_tile_key_still_boots(tile):
    """A short tile key or one equal to the JWT secret is not refused."""
    assert _settings(tile_signing_secret=tile).tile_signing_secret


def test_loader_error_text_names_the_variable_and_hides_values(monkeypatch, capsys):
    """The settings loader's fatal output names SESSION_SECRET_KEY, no values."""
    from app.core import config as cfg

    bad = "bad-" + secrets.token_hex(4)
    for k, v in BASE_ENV.items():
        if v is not None:
            monkeypatch.setenv(k.upper(), v)
    monkeypatch.setenv("SESSION_SECRET_KEY", bad)
    with pytest.raises(SystemExit):
        cfg._create_settings()
    err = capsys.readouterr().err
    assert "SESSION_SECRET_KEY" in err
    assert bad not in err
    assert JWT not in err


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


def _ns(**kw):
    base = {
        "is_production": True,
        "tile_signing_secret": None,
        "session_secret_key": None,
        "jwt_secret_key": SecretStr(JWT),
    }
    return SimpleNamespace(**{**base, **kw})


def _events(settings_obj):
    log = MagicMock()
    main_module._warn_on_weak_signing_keys(settings_obj, log)
    return [c.args[0] for c in log.warning.call_args_list], log


def test_unset_session_key_warns_in_production_only():
    assert _events(_ns())[0] == ["session_secret_key_unset"]
    assert _events(_ns(session_secret_key=SecretStr(_key())))[0] == []
    assert _events(_ns(is_production=False))[0] == []


@pytest.mark.parametrize("tile", ["tiny-key", JWT])
def test_weak_existing_tile_key_warns_without_the_value(tile):
    events, log = _events(
        _ns(tile_signing_secret=SecretStr(tile), session_secret_key=SecretStr(_key()))
    )
    assert "tile_signing_secret_weak" in events
    assert tile not in log.warning.call_args.kwargs["message"]
