"""The database healthchecks must not report healthy during first-boot init.

The postgres entrypoint runs init scripts against a temporary server that
listens only on the Unix socket, then stops it and starts the real server. A
socket-only ``pg_isready`` passes against that temporary server, so a caller
that waits for healthy can connect just as it shuts down. Probing over TCP
skips that window.
"""

from __future__ import annotations

import shlex

import pytest
import yaml

from tests.repo_paths import repo_root

ROOT = repo_root(__file__)


@pytest.mark.parametrize(
    "compose_file",
    [
        "docker-compose.yml",
        "docker-compose.prod.yml",
        "scripts/tests/ci-restore-db.compose.yml",
    ],
)
def test_db_healthcheck_probes_over_tcp(compose_file):
    compose = yaml.safe_load((ROOT / compose_file).read_text(encoding="utf-8"))
    test = compose["services"]["db"]["healthcheck"]["test"]
    assert test[0] == "CMD-SHELL"
    args = shlex.split(test[1])
    assert args[0] == "pg_isready"
    assert "-h" in args, f"{compose_file}: pg_isready without -h probes the socket"
    assert args[args.index("-h") + 1] == "127.0.0.1"
