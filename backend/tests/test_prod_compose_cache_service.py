"""The prod compose file's bundled cache is a supported, bounded service."""

import subprocess

import pytest
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


def _stub(bin_dir, name, body):
    path = bin_dir / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def _start_valkey(tmp_path, password):
    """Run the service command with a stub valkey-server that records its input."""
    cmd = _valkey()["command"]
    assert cmd[:2] == ["/bin/sh", "-c"]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(
        bin_dir,
        "valkey-server",
        f'printf "%s\\n" "$@" > {tmp_path}/argv\ncat > {tmp_path}/stdin\n',
    )
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin"}
    if password is not None:
        env["VALKEY_PASSWORD"] = password
    # Compose turns $$ into a literal $ before the shell sees the script.
    script = cmd[2].replace("$$", "$")
    result = subprocess.run(
        ["/bin/sh", "-c", script, *cmd[3:]],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, cmd[4:]


def test_valkey_requires_the_password_when_one_is_set(tmp_path):
    result, args = _start_valkey(tmp_path, "s3cret-Value_1.~")
    assert result.returncode == 0, result.stderr
    argv = (tmp_path / "argv").read_text().splitlines()
    assert argv == [*args[1:], "-"]
    assert (tmp_path / "stdin").read_text() == "requirepass s3cret-Value_1.~\n"
    assert not any("s3cret" in a for a in argv)


@pytest.mark.parametrize("password", [None, ""])
def test_valkey_without_a_password_starts_as_before(tmp_path, password):
    result, args = _start_valkey(tmp_path, password)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "argv").read_text().splitlines() == args[1:]
    assert (tmp_path / "stdin").read_text() == ""


@pytest.mark.parametrize("password", ["two words", "a\nrequirepass b", 'q"uote'])
def test_valkey_refuses_a_password_that_could_add_config(tmp_path, password):
    result, _ = _start_valkey(tmp_path, password)
    assert result.returncode != 0
    assert "VALKEY_PASSWORD" in result.stderr
    assert not (tmp_path / "argv").exists()


def _healthcheck(tmp_path, password, reply):
    test = _valkey()["healthcheck"]["test"]
    assert test[0] == "CMD-SHELL"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(
        bin_dir,
        "valkey-cli",
        f'printf "%s" "${{REDISCLI_AUTH-unset}}" > {tmp_path}/auth\n'
        f'printf "%s\\n" "$@" > {tmp_path}/argv\necho "$STUB_REPLY"\n',
    )
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "STUB_REPLY": reply}
    if password is not None:
        env["VALKEY_PASSWORD"] = password
    result = subprocess.run(
        ["/bin/sh", "-c", test[1].replace("$$", "$")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, (tmp_path / "auth").read_text()


def test_healthcheck_authenticates_without_putting_the_password_on_argv(tmp_path):
    code, auth = _healthcheck(tmp_path, "s3cret", "PONG")
    assert code == 0
    assert auth == "s3cret"
    assert "s3cret" not in (tmp_path / "argv").read_text()


def test_healthcheck_fails_on_a_noauth_reply(tmp_path):
    code, _ = _healthcheck(tmp_path, "s3cret", "NOAUTH Authentication required.")
    assert code != 0


def test_healthcheck_without_a_password_sends_no_auth(tmp_path):
    code, auth = _healthcheck(tmp_path, None, "PONG")
    assert code == 0
    assert auth == "unset"


def test_valkey_password_is_parse_safe_and_reaches_the_container():
    assert _valkey()["environment"]["VALKEY_PASSWORD"] == "${VALKEY_PASSWORD:-}"
