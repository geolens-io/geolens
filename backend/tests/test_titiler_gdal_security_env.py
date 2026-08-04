"""fix(#1192, #1193): pin the titiler service's GDAL security env and worker knob.

Two invariants, both learned from settings that read as decisions and were not.

#1192 — the VRT rawband controls must be set EXPLICITLY, because their defaults
are version-dependent and a base-image bump would otherwise move them silently.
The stronger half is ``test_allowed_source_is_a_value_gdal_accepts``: the value
that shipped here for months, ``NETWORK_OR_LOCAL``, is not one of GDAL's four
accepted forms. GDAL fell through to its absolute-path branch and refused every
VRTRawRasterBand source, so the effective policy was deny-all while the inline
comment claimed "allow VRT bands to reference remote (S3) sources". Measured
2026-08-04 in ghcr.io/developmentseed/titiler 2.0.5 and 2.2.1, both
rasterio 1.5.0 / GDAL 3.12.1::

    Invalid value for GDAL_VRT_RAWRASTERBAND_ALLOWED_SOURCE.
    'NETWORK_OR_LOCAL' is not an absolute path

The membership check below defaults RESTRICTIVE on purpose — an unrecognised
token fails rather than passing — because that is the direction in which this
class of mistake is loud. A test that only asserted "the key is present" would
have passed against the broken value.

#1193 — the worker count is env-tunable, and the memory cap it must be raised
with stays env-tunable too. ``GDAL_CACHEMAX`` is per process, so N workers
multiply the block-cache ceiling; raising workers against a pinned memory limit
reaches OOMKill sooner (#678).

Static analysis only — no docker daemon required.
"""

import pytest
import yaml

from tests.repo_paths import repo_root

_REPO_ROOT = repo_root(__file__)
_COMPOSE_FILES = ("docker-compose.yml", "docker-compose.prod.yml")

# https://gdal.org/en/stable/drivers/raster/vrt.html (GDAL >= 3.12). The fourth
# accepted form is an absolute path, handled separately below.
_ALLOWED_SOURCE_TOKENS = frozenset(
    {"SIBLING_OR_CHILD_OF_VRT_PATH", "ONLY_REMOTE", "ALL"}
)


def _titiler_service(filename: str) -> dict:
    body = yaml.safe_load((_REPO_ROOT / filename).read_text(encoding="utf-8"))
    return body["services"]["titiler"]


def _titiler_env(filename: str) -> dict:
    return _titiler_service(filename)["environment"]


def _titiler_command(filename: str) -> str:
    command = _titiler_service(filename)["command"]
    return command if isinstance(command, str) else "\n".join(command)


@pytest.mark.parametrize("filename", _COMPOSE_FILES)
def test_vrt_rawband_controls_are_pinned_explicitly(filename: str) -> None:
    """Both GDAL >= 3.12 rawband options are set, not inherited (#1192)."""
    env = _titiler_env(filename)
    for key in (
        "GDAL_VRT_ENABLE_RAWRASTERBAND",
        "GDAL_VRT_RAWRASTERBAND_ALLOWED_SOURCE",
    ):
        assert key in env, (
            f"{filename}: titiler must pin {key} explicitly — its GDAL default is "
            "version-dependent, so a base-image bump can relax it silently (#1192)"
        )


@pytest.mark.parametrize("filename", _COMPOSE_FILES)
def test_allowed_source_is_a_value_gdal_accepts(filename: str) -> None:
    """An unrecognised token is refused by GDAL, not treated as permissive (#1192)."""
    value = _titiler_env(filename)["GDAL_VRT_RAWRASTERBAND_ALLOWED_SOURCE"]
    accepted = value in _ALLOWED_SOURCE_TOKENS or value.startswith("/")
    assert accepted, (
        f"{filename}: GDAL_VRT_RAWRASTERBAND_ALLOWED_SOURCE={value!r} is not one of "
        f"{sorted(_ALLOWED_SOURCE_TOKENS)} nor an absolute path. GDAL parses an "
        "unrecognised token as a bogus absolute path and refuses every "
        "VRTRawRasterBand source, so the setting will not mean what its comment "
        "says (#1192)"
    )


@pytest.mark.parametrize("filename", _COMPOSE_FILES)
def test_enable_rawrasterband_is_yes_or_no(filename: str) -> None:
    """The enable switch is a YES/NO option; anything else is a typo (#1192)."""
    value = _titiler_env(filename)["GDAL_VRT_ENABLE_RAWRASTERBAND"]
    assert value in ("YES", "NO"), (
        f"{filename}: GDAL_VRT_ENABLE_RAWRASTERBAND={value!r} — GDAL accepts only "
        "YES or NO (#1192)"
    )


@pytest.mark.parametrize("filename", _COMPOSE_FILES)
def test_header_file_kvp_toggle_is_not_set_prematurely(filename: str) -> None:
    """CPL_VSIL_CURL_HEADER_FILE_KVP_ENABLED needs GDAL >= 3.13.2 (#1192).

    The image installs rasterio from PyPI wheels, so the wheel gates the GDAL
    version rather than the titiler tag — titiler 2.0.5 and 2.2.1 both ship
    GDAL 3.12.1 (measured 2026-08-04). Setting it now would be inert and would
    read as a control we do not have, which is exactly the #937 mistake. Delete
    this test in the commit that adds the key, once a wheel bump crosses 3.13.2.
    """
    assert "CPL_VSIL_CURL_HEADER_FILE_KVP_ENABLED" not in _titiler_env(filename), (
        f"{filename}: CPL_VSIL_CURL_HEADER_FILE_KVP_ENABLED requires GDAL >= 3.13.2. "
        "Confirm rasterio.__gdal_version__ in the pinned image before adding it, and "
        "drop this test in the same commit (#1192)"
    )


@pytest.mark.parametrize("filename", _COMPOSE_FILES)
def test_titiler_worker_count_is_env_tunable(filename: str) -> None:
    """The worker count comes from TITILER_WORKERS, defaulting to 1 (#1193)."""
    command = _titiler_command(filename)
    assert "--workers $${TITILER_WORKERS:-1}" in command, (
        f"{filename}: titiler must take its worker count from TITILER_WORKERS with a "
        f"default of 1, mirroring UVICORN_WORKERS: {command!r}"
    )
    env = _titiler_env(filename)
    assert env.get("TITILER_WORKERS") == "${TITILER_WORKERS:-1}", (
        f"{filename}: the command wrapper reads TITILER_WORKERS from the container "
        "environment, so the service must pass it through from the host"
    )


@pytest.mark.parametrize("filename", _COMPOSE_FILES)
def test_titiler_memory_cap_stays_tunable_alongside_workers(filename: str) -> None:
    """More workers need more memory, so the cap must move with them (#1193, #678)."""
    mem_limit = _titiler_service(filename)["mem_limit"]
    assert "${TITILER_MEM_LIMIT" in mem_limit, (
        f"{filename}: TITILER_MEM_LIMIT must stay env-overridable — GDAL_CACHEMAX is "
        "per process, so raising TITILER_WORKERS against a pinned memory limit "
        f"reaches OOMKill sooner (#678): {mem_limit!r}"
    )
