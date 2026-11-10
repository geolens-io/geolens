"""The bundled database gets a /dev/shm large enough for parallel queries.

Docker's 64 MB default made parallel queries fail with "could not resize
shared memory segment" under 12 concurrent dashboard users; 512 MB stopped it.
The tmpfs is charged to the container's memory cgroup, so it has to fit inside
the memory cap next to shared_buffers.
"""

from __future__ import annotations

import re

import pytest
import yaml

from tests.repo_paths import repo_root

ROOT = repo_root(__file__)
_UNITS = {"k": 1 << 10, "m": 1 << 20, "g": 1 << 30}


def _default_bytes(value: str) -> float:
    match = re.fullmatch(r"\$\{\w+:-([\d.]+)([kmg])\}", value)
    assert match, f"expected an env-overridable default, got {value!r}"
    return float(match[1]) * _UNITS[match[2]]


def _shared_buffers_bytes() -> int:
    conf = (ROOT / "db/postgresql.conf").read_text(encoding="utf-8")
    match = re.search(r"^shared_buffers\s*=\s*(\d+)MB", conf, re.MULTILINE)
    assert match
    return int(match[1]) << 20


@pytest.mark.parametrize(
    "compose_file", ["docker-compose.yml", "docker-compose.prod.yml"]
)
def test_db_shm_fits_parallel_queries_inside_the_memory_cap(compose_file):
    compose = yaml.safe_load((ROOT / compose_file).read_text(encoding="utf-8"))
    db = compose["services"]["db"]
    shm = _default_bytes(db["shm_size"])
    assert shm >= 512 << 20
    assert shm + _shared_buffers_bytes() < _default_bytes(db["mem_limit"])
