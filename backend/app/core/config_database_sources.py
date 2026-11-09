"""Database connections the operator configures in DATABASE_SOURCES.

Each value ends up in a generated freetds.conf section or the ODBC connection
string GDAL builds, so the validators refuse the characters either format
treats as syntax. Error messages name the connection and the field, never the
value, because the value can be a password.
"""

import ipaddress
import json
import re
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import NoDecode

_CONNECTION_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$")
_HOST_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
# `;` `{` `}` `=` delimit ODBC attributes, `#` and `;` start INI comments, and a
# line break would start a new freetds.conf line.
_ODBC_INI_SYNTAX = frozenset(";{}=#")


def _has_control_character(value: str) -> bool:
    return any(ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F for ch in value)


def _is_printable_ascii(value: str) -> bool:
    return all(0x20 <= ord(ch) <= 0x7E for ch in value)


def _is_host(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        pass
    if len(value) > 253:
        return False
    return all(_HOST_LABEL_RE.match(label) for label in value.split("."))


class DatabaseConnection(BaseModel):
    """One SQL Server the operator lets GeoLens read."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    engine: Literal["sqlserver"]
    host: str = Field(min_length=1)
    port: int = Field(default=1433, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    password: SecretStr
    encrypt: bool = True
    trust_server_certificate: bool = False
    ca_file: str | None = None

    @field_validator("host")
    @classmethod
    def _check_host(cls, v: str) -> str:
        if not _is_host(v):
            raise ValueError("must be a hostname or an IP address")
        return v

    @field_validator("database")
    @classmethod
    def _check_database(cls, v: str) -> str:
        if _has_control_character(v) or _ODBC_INI_SYNTAX.intersection(v):
            raise ValueError("may not contain ; { } = # or control characters")
        return v

    @field_validator("username")
    @classmethod
    def _check_username(cls, v: str) -> str:
        if not _is_printable_ascii(v) or _ODBC_INI_SYNTAX.intersection(v):
            raise ValueError("must be printable ASCII and may not contain ; { } = or #")
        return v

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: SecretStr) -> SecretStr:
        # GDAL appends `;PWD=<password>` to the ODBC string unquoted, and
        # FreeTDS 1.3 fails to sign in with a non-ASCII password.
        secret = v.get_secret_value()
        if not secret:
            raise ValueError("may not be empty")
        if not _is_printable_ascii(secret) or ";" in secret or secret[0] == "{":
            raise ValueError(
                "must be printable ASCII, may not contain ; and may not start with {"
            )
        return v

    @field_validator("ca_file", mode="before")
    @classmethod
    def _blank_ca_file_to_none(cls, v: object) -> object:
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @field_validator("ca_file")
    @classmethod
    def _check_ca_file(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.startswith("/"):
            raise ValueError("must be an absolute path")
        if _has_control_character(v) or {";", "#"}.intersection(v):
            raise ValueError("may not contain ; # or control characters")
        return v

    @model_validator(mode="after")
    def _check_tls(self) -> "DatabaseConnection":
        if self.trust_server_certificate and self.ca_file is not None:
            raise ValueError(
                "ca_file and trust_server_certificate=true contradict each other; "
                "set one"
            )
        return self


def _connection_error(label: str, exc: ValidationError) -> ValueError:
    problems = []
    for error in exc.errors(include_input=False, include_url=False):
        field = ".".join(str(part) for part in error["loc"])
        message = str(error["msg"]).removeprefix("Value error, ")
        problems.append(f"{field}: {message}" if field else message)
    return ValueError(f"DATABASE_SOURCES {label}: " + "; ".join(problems))


class DatabaseSourcesSettings(BaseModel):
    # JSON object of connection name -> connection. Decoded here rather than by
    # pydantic-settings so a blank value means off and a parse error can't
    # quote the password.
    database_sources: Annotated[dict[str, DatabaseConnection], NoDecode] = Field(
        default_factory=dict
    )

    @field_validator("database_sources", mode="before")
    @classmethod
    def parse_database_sources_to_default(cls, v: object) -> object:
        if isinstance(v, str):
            if v.strip() == "":
                return {}
            try:
                v = json.loads(v)
            except ValueError:
                raise ValueError("DATABASE_SOURCES is not valid JSON") from None
        if not isinstance(v, dict):
            raise ValueError("DATABASE_SOURCES must be a JSON object of connections")
        connections: dict[str, DatabaseConnection] = {}
        for position, (name, value) in enumerate(v.items(), start=1):
            if not isinstance(name, str) or not _CONNECTION_NAME_RE.match(name):
                raise ValueError(
                    f"DATABASE_SOURCES connection #{position} needs a name of "
                    "lowercase letters, digits, - and _ (at most 64)"
                )
            if isinstance(value, DatabaseConnection):
                connections[name] = value
                continue
            try:
                connections[name] = DatabaseConnection.model_validate(value)
            except ValidationError as exc:
                raise _connection_error(f"connection {name!r}", exc) from None
        return connections

    @model_validator(mode="after")
    def refuse_database_sources_when_multi_tenant(self) -> "DatabaseSourcesSettings":
        # The connections are global to the process, so no tenant could be
        # kept to its own.
        if self.database_sources and (
            getattr(self, "geolens_tenancy_mode", None) == "multi_tenant"
        ):
            raise ValueError(
                "DATABASE_SOURCES is not available in multi_tenant mode; leave it empty"
            )
        return self
