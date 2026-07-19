"""fix(#579): GDAL /vsis3/ AWS_* derivation from the app's S3_* settings."""

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
