"""Python healthchecks on the read-only api and worker images must not write bytecode.

The slim base image ships the standard library without `.pyc` files and the
root filesystem is read-only, so without `-B` every probe tries to create about
sixty uniquely named `__pycache__/*.pyc.<id>` temp files. Each failed attempt
leaves a negative dentry charged to the container's memory cgroup, and at one
probe every 10 seconds that grows the container's working set by about 10 MB
an hour for as long as it runs.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_CALL = re.compile(r"\bpython3?(?P<flags>(?:\s+-\w+)*)\s+-c\b")


def _python_calls(command: str) -> list[list[str]]:
    return [m.group("flags").split() for m in _PYTHON_CALL.finditer(command)]


def _dockerfile_healthchecks() -> dict[str, str]:
    text = (_REPO_ROOT / "Dockerfile").read_text().replace("\\\n", " ")
    checks: dict[str, str] = {}
    stage = ""
    for line in text.splitlines():
        if match := re.match(r"FROM\s+\S+\s+AS\s+(\S+)", line, re.IGNORECASE):
            stage = match.group(1)
        elif line.startswith("HEALTHCHECK"):
            checks[stage] = line
    return checks


def _compose_healthchecks(name: str) -> dict[str, str]:
    services = yaml.safe_load((_REPO_ROOT / name).read_text())["services"]
    checks: dict[str, str] = {}
    for service in ("api", "worker"):
        test = services[service].get("healthcheck", {}).get("test")
        if test:
            checks[service] = " ".join(test) if isinstance(test, list) else test
    return checks


def _assert_no_bytecode_writes(where: str, command: str) -> None:
    calls = _python_calls(command)
    assert calls, f"{where} healthcheck no longer runs python; update this test"
    for flags in calls:
        assert "-B" in flags, f"{where} healthcheck runs python without -B"


def test_image_healthchecks_do_not_write_bytecode():
    checks = _dockerfile_healthchecks()
    assert {"api", "worker"} <= checks.keys()
    for stage in ("api", "worker"):
        _assert_no_bytecode_writes(f"Dockerfile {stage}", checks[stage])


def test_compose_healthchecks_do_not_write_bytecode():
    for name in ("docker-compose.yml", "docker-compose.prod.yml"):
        for service, command in _compose_healthchecks(name).items():
            _assert_no_bytecode_writes(f"{name} {service}", command)
