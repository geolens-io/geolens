"""The prod compose file's bundled cache is a supported, bounded service."""

import yaml

from tests.repo_paths import repo_root


def _valkey():
    path = repo_root(__file__) / "docker-compose.prod.yml"
    return yaml.safe_load(path.read_text())["services"]["valkey"]


def test_cache_profile_selects_valkey_without_minio():
    assert "cache" in _valkey()["profiles"]


def test_valkey_restarts_and_is_memory_limited():
    svc = _valkey()
    assert svc["restart"] == "unless-stopped"
    assert svc["mem_limit"] == "${VALKEY_MEM_LIMIT:-256m}"


def test_valkey_is_not_published_on_the_host():
    assert "ports" not in _valkey()


def test_valkey_keeps_credentials_off_disk_and_evicts_below_the_cap():
    svc = _valkey()
    cmd = svc["command"]
    assert cmd[cmd.index("--save") + 1] == ""
    assert cmd[cmd.index("--appendonly") + 1] == "no"
    assert "--maxmemory" in cmd
    assert cmd[cmd.index("--maxmemory-policy") + 1] == "volatile-ttl"
    assert not any("/data" in str(v) for v in svc.get("volumes", []))
