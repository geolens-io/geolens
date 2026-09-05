"""fix(#579): GDAL /vsis3/ AWS_* derivation from the app's S3_* settings, and
fix(#1828): the schema-import clamp both vector subprocess envs carry."""

import os
import pathlib
import re
from types import SimpleNamespace

from pydantic import SecretStr

from app.core.runtime.gdal_env import configure_gdal_s3_env, derive_gdal_s3_env


def _s3_settings(**overrides):
    base = dict(
        storage_provider="s3",
        s3_endpoint=None,
        s3_access_key_id="test-access-key",
        s3_secret_access_key=SecretStr("test-secret-key"),
        s3_region="us-east-1",
        s3_allow_http=False,
        s3_addressing_style="auto",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_non_s3_provider_derives_nothing():
    assert derive_gdal_s3_env(_s3_settings(storage_provider="local")) == {}
    assert derive_gdal_s3_env(_s3_settings(storage_provider="azure")) == {}


def test_aws_proper_gets_creds_and_region_only():
    derived = derive_gdal_s3_env(_s3_settings())
    assert derived == {
        "AWS_ACCESS_KEY_ID": "test-access-key",
        "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        "AWS_DEFAULT_REGION": "us-east-1",
    }


def test_minio_style_endpoint_derives_full_trio():
    derived = derive_gdal_s3_env(
        _s3_settings(s3_endpoint="http://minio:9000", s3_addressing_style="path")
    )
    assert derived["AWS_S3_ENDPOINT"] == "minio:9000"
    assert derived["AWS_HTTPS"] == "NO"
    assert derived["AWS_VIRTUAL_HOSTING"] == "FALSE"


def test_https_endpoint_leaves_https_default():
    derived = derive_gdal_s3_env(
        _s3_settings(s3_endpoint="https://account.r2.cloudflarestorage.com")
    )
    assert derived["AWS_S3_ENDPOINT"] == "account.r2.cloudflarestorage.com"
    assert "AWS_HTTPS" not in derived
    assert "AWS_VIRTUAL_HOSTING" not in derived


def test_endpoint_path_suffix_and_schemeless_form_reduce_to_host():
    assert (
        derive_gdal_s3_env(_s3_settings(s3_endpoint="http://minio:9000/"))[
            "AWS_S3_ENDPOINT"
        ]
        == "minio:9000"
    )
    schemeless = derive_gdal_s3_env(_s3_settings(s3_endpoint="minio:9000"))
    assert schemeless["AWS_S3_ENDPOINT"] == "minio:9000"
    assert "AWS_HTTPS" not in schemeless


def test_schemeless_endpoint_honors_allow_http():
    # Mirrors S3StorageProvider: scheme-less + S3_ALLOW_HTTP -> http endpoint.
    derived = derive_gdal_s3_env(
        _s3_settings(s3_endpoint="minio:9000", s3_allow_http=True)
    )
    assert derived["AWS_HTTPS"] == "NO"
    # An explicit https scheme wins over allow_http, as in the provider.
    explicit = derive_gdal_s3_env(
        _s3_settings(s3_endpoint="https://minio:9000", s3_allow_http=True)
    )
    assert "AWS_HTTPS" not in explicit


def test_empty_region_omits_default_region():
    assert "AWS_DEFAULT_REGION" not in derive_gdal_s3_env(_s3_settings(s3_region=""))


def test_configure_sets_missing_and_never_clobbers(monkeypatch):
    for key in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_DEFAULT_REGION",
        "AWS_S3_ENDPOINT",
        "AWS_HTTPS",
        "AWS_VIRTUAL_HOSTING",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AWS_S3_ENDPOINT", "operator-override:9000")

    import os

    configure_gdal_s3_env(
        _s3_settings(s3_endpoint="http://minio:9000", s3_addressing_style="path")
    )
    assert os.environ["AWS_S3_ENDPOINT"] == "operator-override:9000"
    assert os.environ["AWS_ACCESS_KEY_ID"] == "test-access-key"
    assert os.environ["AWS_HTTPS"] == "NO"
    assert os.environ["AWS_VIRTUAL_HOSTING"] == "FALSE"


_SCHEMA_FETCH_KEYS = ("GML_USE_SCHEMA_IMPORT", "GML_DOWNLOAD_SCHEMA")

# The three shapes an assignment of a key can take in Python source: a dict
# entry or `KEY=value` pair, an `os.environ[...] = ...` store, and a
# `setenv("KEY", value)` call.
_ASSIGNMENT_SHAPES = (
    r'["\']?\]?\s*[:=]\s*["\']([^"\']*)["\']',
    r'["\']\s*,\s*["\']([^"\']*)["\']',
)
_ASSIGNMENTS = [
    (key, re.compile(key + shape))
    for key in _SCHEMA_FETCH_KEYS
    for shape in _ASSIGNMENT_SHAPES
]


def _assigned_values(line: str) -> list[tuple[str, str]]:
    return [
        (key, m.group(1))
        for key, pattern in _ASSIGNMENTS
        for m in pattern.finditer(line)
    ]


class TestSchemaFetchesStayOffByValue:
    """fix(#1828): `GML_USE_SCHEMA_IMPORT` and `GML_DOWNLOAD_SCHEMA` are NO in
    both GDAL vector envs.

    The GML driver reads both from the process env. At YES the first fetches
    every `xs:import` location of a schema and the second fetches the schema a
    GetFeature response points at, each with the credential header attached.
    A value rather than an absence, so an operator's env cannot flip either.
    """

    def test_both_envs_pin_both_keys_to_no(self) -> None:
        from app.platform.gdal_env import gdal_service_safe_env, gdal_vector_safe_env

        for env in (gdal_vector_safe_env(), gdal_service_safe_env()):
            for key in _SCHEMA_FETCH_KEYS:
                assert env[key] == "NO", key

    def test_a_process_env_value_cannot_flip_either(self, monkeypatch) -> None:
        from app.platform.gdal_env import gdal_service_safe_env, gdal_vector_safe_env

        for key in _SCHEMA_FETCH_KEYS:
            monkeypatch.setenv(key, "YES")

        for env in (gdal_vector_safe_env(), gdal_service_safe_env()):
            for key in _SCHEMA_FETCH_KEYS:
                assert env[key] == "NO", key
        assert all(os.environ[key] == "YES" for key in _SCHEMA_FETCH_KEYS)

    def test_the_grep_sees_every_assignment_shape(self) -> None:
        """Positive control for the tree walk below, for both keys."""
        for key in _SCHEMA_FETCH_KEYS:
            assert _assigned_values(f'{{"{key}": "YES"}}') == [(key, "YES")]
            assert _assigned_values(f'env["{key}"] = "YES"') == [(key, "YES")]
            assert _assigned_values(f"{key}='YES'") == [(key, "YES")]
            assert _assigned_values(f'setenv("{key}", "YES")') == [(key, "YES")]
            assert _assigned_values(f"once {key} is YES anywhere") == []

    def test_nothing_under_backend_app_sets_either_to_anything_else(self) -> None:
        app_root = pathlib.Path(__file__).resolve().parents[1] / "app"
        assignments: dict[str, list[tuple[str, str]]] = {}
        for path in sorted(app_root.rglob("*.py")):
            for line in path.read_text(encoding="utf-8").splitlines():
                values = _assigned_values(line)
                if values:
                    rel = path.relative_to(app_root).as_posix()
                    assignments.setdefault(rel, []).extend(values)

        # The pins themselves are found, so an empty answer elsewhere means
        # absence rather than a blind walk.
        assert sorted(assignments.get("platform/gdal_env.py", [])) == sorted(
            (key, "NO") for key in _SCHEMA_FETCH_KEYS
        ), assignments
        for rel, values in assignments.items():
            assert all(value == "NO" for _key, value in values), (rel, values)
