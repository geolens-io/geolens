"""The api image's default command and its uvicorn request limit."""

import json
import os
import re
import subprocess

import pytest

from tests.repo_paths import repo_root

DOCKERFILE = repo_root(__file__) / "Dockerfile"


def _api_cmd() -> list[str]:
    stage = DOCKERFILE.read_text().split(" AS api\n", 1)[1].split("\nFROM ", 1)[0]
    return json.loads(re.search(r"^CMD (\[.*\])$", stage, re.M).group(1))


def _uv_args(tmp_path, env: dict[str, str]) -> list[str]:
    stub = tmp_path / "uv"
    stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    stub.chmod(0o755)
    result = subprocess.run(
        _api_cmd(),
        env={"PATH": f"{tmp_path}:{os.environ['PATH']}", **env},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.split()


@pytest.mark.parametrize(
    ("env", "limited"),
    [
        ({"UVICORN_WORKERS": "2", "UVICORN_MAX_REQUESTS": "10000"}, True),
        ({"UVICORN_WORKERS": "1", "UVICORN_MAX_REQUESTS": "10000"}, False),
        ({"UVICORN_MAX_REQUESTS": "10000"}, False),
        ({"UVICORN_WORKERS": "2"}, False),
    ],
)
def test_request_limit_needs_a_second_worker(tmp_path, env, limited):
    """A lone worker that reaches the limit exits and stops the container."""
    args = _uv_args(tmp_path, env)
    assert args[:4] == ["run", "--no-dev", "uvicorn", "app.api.main:app"]
    assert ("--limit-max-requests" in args) is limited
    if limited:
        assert args[args.index("--limit-max-requests") + 1] == "10000"
