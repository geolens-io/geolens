"""DATABASE_SOURCES: parsing, validation and the multi-tenant refusal."""

import json
import secrets

import pytest
from pydantic import ValidationError

from tests.test_config import _make_settings

PASSWORD = secrets.token_hex(16)


def _connection(**overrides):
    return {
        "engine": "sqlserver",
        "host": "gis-sql.corp.example",
        "database": "GIS",
        "username": "geolens_reader",
        "password": PASSWORD,
        **overrides,
    }


def _errors(sources) -> list[str]:
    raw = sources if isinstance(sources, str) else json.dumps(sources)
    with pytest.raises(ValidationError) as caught:
        _make_settings(database_sources=raw)
    return [error["msg"] for error in caught.value.errors()]


def test_blank_means_no_connections():
    assert _make_settings(database_sources="").database_sources == {}
    assert _make_settings(database_sources="  ").database_sources == {}
    assert _make_settings().database_sources == {}


def test_env_json_is_parsed_into_named_connections(monkeypatch):
    monkeypatch.setenv("DATABASE_SOURCES", json.dumps({"gis": _connection(port=14330)}))
    connection = _make_settings().database_sources["gis"]
    assert connection.host == "gis-sql.corp.example"
    assert connection.port == 14330
    assert connection.password.get_secret_value() == PASSWORD
    assert connection.encrypt is True
    assert connection.trust_server_certificate is False
    assert connection.ca_file is None
    assert PASSWORD not in repr(connection)


def test_password_may_hold_characters_freetds_accepts():
    password = "a=b}c 'd\" e "
    connection = _make_settings(
        database_sources=json.dumps({"gis": _connection(password=password)})
    ).database_sources["gis"]
    assert connection.password.get_secret_value() == password


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("host", "sql;evil"),
        ("host", "sql\nport = 1"),
        ("host", "sql#x"),
        ("host", "sql server"),
        ("host", "-sql"),
        ("host", "fe80::1%eth0\nhost = evil\nencryption = off\n[unused]"),
        ("host", "fe80::1%eth0"),
        ("host", ".".join(["a" * 49] * 5)),
        ("database", "GIS;Server=evil"),
        ("database", "GIS{x}"),
        ("database", "GIS\nhost = evil"),
        ("database", "GIS#x"),
        ("username", "reader;PWD=x"),
        ("username", "reader="),
        ("username", "réader"),
        ("username", "reader\t"),
        ("password", "abc;def"),
        ("password", "{abc"),
        ("password", "pässword"),
        ("password", "abc\ndef"),
        ("password", ""),
        ("ca_file", "relative/ca.pem"),
        ("ca_file", "/certs/ca.pem\nhost = evil"),
        ("ca_file", "/certs/ca.pem;x"),
        ("ca_file", "/" + "a" * 244 + "ca file ="),
        ("ca_file", "/" + "é" * 100),
        ("port", 0),
        ("port", 70000),
    ],
)
def test_metacharacters_are_refused_without_echoing_the_value(field, value):
    messages = _errors({"gis": _connection(**{field: value})})
    assert len(messages) == 1
    assert "'gis'" in messages[0]
    assert field in messages[0]
    if isinstance(value, str) and value:
        assert value not in messages[0]
    assert PASSWORD not in messages[0]


def test_unknown_keys_are_refused():
    messages = _errors({"gis": _connection(trust_cert=True)})
    assert "trust_cert" in messages[0]
    assert PASSWORD not in messages[0]


def test_other_engines_are_refused():
    messages = _errors({"gis": _connection(engine="postgresql")})
    assert "engine" in messages[0]
    assert PASSWORD not in messages[0]


def test_missing_fields_name_the_connection():
    connection = _connection()
    del connection["host"]
    messages = _errors({"gis": connection})
    assert "'gis'" in messages[0] and "host" in messages[0]


@pytest.mark.parametrize("name", ["GIS", "gis sql", "gis;x", "-gis", "g" * 65, ""])
def test_non_slug_names_are_refused_without_echoing_them(name):
    messages = _errors({name: _connection()})
    assert "connection #1" in messages[0]
    if name:
        assert name not in messages[0]


def test_a_ca_file_and_the_trust_opt_out_contradict():
    messages = _errors(
        {"gis": _connection(ca_file="/certs/ca.pem", trust_server_certificate=True)}
    )
    assert "ca_file" in messages[0]


def test_broken_json_does_not_quote_the_value():
    raw = '{"gis": {"password": "' + PASSWORD + '"'
    messages = _errors(raw)
    assert messages and all(PASSWORD not in m for m in messages)


def test_a_non_object_is_refused():
    assert "JSON object" in _errors("[1, 2]")[0]


def test_multi_tenant_refuses_any_connection():
    with pytest.raises(ValidationError) as caught:
        _make_settings(
            geolens_tenancy_mode="multi_tenant",
            database_sources=json.dumps({"gis": _connection()}),
        )
    messages = [error["msg"] for error in caught.value.errors()]
    assert any("multi_tenant" in m and "DATABASE_SOURCES" in m for m in messages)
    assert all(PASSWORD not in m for m in messages)


def test_multi_tenant_boots_with_none():
    settings = _make_settings(geolens_tenancy_mode="multi_tenant", database_sources="")
    assert settings.database_sources == {}
