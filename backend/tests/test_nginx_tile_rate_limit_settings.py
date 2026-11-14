"""The edge tile rate limits render from validated environment settings."""

import re
import shutil
import subprocess

import pytest

from tests.repo_paths import repo_root

ROOT = repo_root(__file__)
ENTRYPOINT = (ROOT / "frontend" / "docker-entrypoint.sh").read_text()
NGINX_CONF = ROOT / "frontend" / "nginx.conf"
VARS = (
    "TILE_RASTER_RATE_PER_MINUTE",
    "TILE_RASTER_BURST",
    "TILE_VECTOR_RATE_PER_MINUTE",
    "TILE_VECTOR_BURST",
    "TILE_VECTOR_DELAY",
)
needs_envsubst = pytest.mark.skipif(
    shutil.which("envsubst") is None, reason="envsubst not installed"
)
SHELLS = [s for s in ("sh", "dash", "bash") if shutil.which(s)]
_SECTION = "tile_limit() {"
_SECTION_END = "\nexport API_UPSTREAM"
_ENVSUBST_ALLOWLIST = " ".join(f"${v}" for v in VARS)


def _render(shell, env, subst=True):
    section = ENTRYPOINT.split(_SECTION, 1)[1].split(_SECTION_END, 1)[0]
    script = "set -e\n" + _SECTION + section + f"\nexport {' '.join(VARS)}\n"
    if subst:
        script += f"envsubst '{_ENVSUBST_ALLOWLIST}' < {NGINX_CONF}"
    return subprocess.run(
        [shell, "-c", script],
        env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", **env},
        capture_output=True,
        text=True,
    )


def _limit_lines(conf):
    return [
        line.strip()
        for line in conf.splitlines()
        if re.match(r"\s*limit_req(_zone)?\s", line)
        and not line.lstrip().startswith("#")
        and "limit_req_status" not in line
    ]


DEFAULT_LINES = [
    "limit_req_zone $binary_remote_addr zone=raster_anon:10m rate=600r/m;",
    "limit_req_zone $geolens_vector_limit_key zone=vector_anon:10m rate=5400r/m;",
    "limit_req zone=raster_anon burst=200 nodelay;",
    "limit_req zone=raster_anon burst=200 nodelay;",
    "limit_req zone=vector_anon burst=720 delay=120;",
]


@pytest.mark.parametrize("shell", SHELLS)
@needs_envsubst
def test_defaults_render_the_historical_limits(shell):
    result = _render(shell, {})
    assert result.returncode == 0, result.stderr
    assert _limit_lines(result.stdout) == DEFAULT_LINES
    assert "${TILE_" not in result.stdout


@pytest.mark.parametrize("shell", SHELLS)
@needs_envsubst
def test_empty_values_take_the_defaults(shell):
    env = {name: "" for name in VARS if name != "TILE_VECTOR_DELAY"}
    result = _render(shell, env)
    assert result.returncode == 0, result.stderr
    assert _limit_lines(result.stdout) == DEFAULT_LINES


@pytest.mark.parametrize("shell", SHELLS)
@needs_envsubst
def test_overrides_land_in_every_directive(shell):
    result = _render(
        shell,
        {
            "TILE_RASTER_RATE_PER_MINUTE": "1200",
            "TILE_RASTER_BURST": "300",
            "TILE_VECTOR_RATE_PER_MINUTE": "9000",
            "TILE_VECTOR_BURST": "900",
        },
    )
    assert result.returncode == 0, result.stderr
    assert _limit_lines(result.stdout) == [
        "limit_req_zone $binary_remote_addr zone=raster_anon:10m rate=1200r/m;",
        "limit_req_zone $geolens_vector_limit_key zone=vector_anon:10m rate=9000r/m;",
        "limit_req zone=raster_anon burst=300 nodelay;",
        "limit_req zone=raster_anon burst=300 nodelay;",
        "limit_req zone=vector_anon burst=900 delay=120;",
    ]


@pytest.mark.parametrize("shell", SHELLS)
@needs_envsubst
def test_vector_delay_never_exceeds_the_burst(shell):
    low = _render(shell, {"TILE_VECTOR_BURST": "50"})
    assert "zone=vector_anon burst=50 delay=50;" in low.stdout
    edge = _render(shell, {"TILE_VECTOR_BURST": "120"})
    assert "zone=vector_anon burst=120 delay=120;" in edge.stdout


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("name", VARS[:4])
@pytest.mark.parametrize(
    "value",
    ["0", "-5", "abc", "600;", "600 nodelay", "1.5", "007", "1000001", "99999999999"],
)
def test_invalid_values_are_refused_and_named(shell, name, value):
    result = _render(shell, {name: value}, subst=False)
    assert result.returncode != 0
    assert name in result.stderr
    assert "1 to 1000000" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("shell", SHELLS)
@needs_envsubst
def test_upper_bound_is_accepted(shell):
    result = _render(shell, {"TILE_RASTER_BURST": "1000000"})
    assert result.returncode == 0, result.stderr
    assert "burst=1000000 nodelay;" in result.stdout


def test_entrypoint_allowlists_the_tile_variables():
    allowlist = re.search(
        r"envsubst '([^']*)' \\\n\s*< /opt/geolens/default", ENTRYPOINT
    )
    assert allowlist is not None
    for name in VARS:
        assert f"${name}" in allowlist[1]
