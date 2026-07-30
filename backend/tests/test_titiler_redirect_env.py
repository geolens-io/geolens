"""fix(#937): TiTiler must not claim redirect protection it does not have.

This file used to assert that both compose files set
``GDAL_HTTP_FOLLOWLOCATION=NO`` on the titiler service. That variable is not
a GDAL configuration option and never blocked a redirect (measured on GDAL
3.10.3 and 3.12.1; absent from cpl_known_config_options.h). The regression
that matters now is the opposite one: nobody may reintroduce the key, because
it reads as a security control and does nothing. The real GDAL-side constraint
TiTiler has is the ``CPL_VSIL_CURL_ALLOWED_EXTENSIONS`` allow-list, pinned
here so it cannot silently disappear.
"""

import yaml

from tests.repo_paths import repo_root

_REPO_ROOT = repo_root(__file__)


def _compose_service_env(filename: str, service: str) -> dict:
    body = yaml.safe_load((_REPO_ROOT / filename).read_text(encoding="utf-8"))
    return body["services"][service]["environment"]


def test_dev_compose_does_not_reintroduce_followlocation() -> None:
    env = _compose_service_env("docker-compose.yml", "titiler")
    assert "GDAL_HTTP_FOLLOWLOCATION" not in env, (
        "GDAL_HTTP_FOLLOWLOCATION is not a GDAL option and provides no redirect "
        "protection (#937); do not reintroduce it"
    )


def test_prod_compose_does_not_reintroduce_followlocation() -> None:
    env = _compose_service_env("docker-compose.prod.yml", "titiler")
    assert "GDAL_HTTP_FOLLOWLOCATION" not in env, (
        "GDAL_HTTP_FOLLOWLOCATION is not a GDAL option and provides no redirect "
        "protection (#937); do not reintroduce it"
    )


def test_titiler_keeps_the_real_vsicurl_allowlist() -> None:
    for filename in ("docker-compose.yml", "docker-compose.prod.yml"):
        env = _compose_service_env(filename, "titiler")
        assert env.get("CPL_VSIL_CURL_ALLOWED_EXTENSIONS") == ".tif,.tiff,.cog,.vrt", (
            f"{filename}: the /vsicurl extension allow-list is TiTiler's real "
            "GDAL-side fetch constraint and must stay pinned"
        )
