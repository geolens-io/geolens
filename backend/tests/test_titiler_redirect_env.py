"""Static checks for TiTiler GDAL redirect hardening."""

import yaml

from tests.repo_paths import repo_root

_REPO_ROOT = repo_root(__file__)


def _compose_service_env(filename: str, service: str) -> dict:
    body = yaml.safe_load((_REPO_ROOT / filename).read_text(encoding="utf-8"))
    return body["services"][service]["environment"]


def test_titiler_disables_gdal_http_redirects_in_dev_compose() -> None:
    env = _compose_service_env("docker-compose.yml", "titiler")
    assert env["GDAL_HTTP_FOLLOWLOCATION"] == "NO"


def test_titiler_disables_gdal_http_redirects_in_prod_compose() -> None:
    env = _compose_service_env("docker-compose.prod.yml", "titiler")
    assert env["GDAL_HTTP_FOLLOWLOCATION"] == "NO"
