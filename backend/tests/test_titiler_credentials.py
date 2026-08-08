"""Security contract for TiTiler object-store credentials (#1191).

TiTiler only reads managed rasters. Its container must prefer a distinct,
prefix-scoped credential without also carrying the API/worker credential in a
second environment variable. A shared-credential fallback keeps upgrades
compatible until operators provision the dedicated principal.
"""

from __future__ import annotations

import os
import subprocess

import pytest
import yaml

from tests.repo_paths import repo_root

_REPO_ROOT = repo_root(__file__)
_COMPOSE_FILES = ("docker-compose.yml", "docker-compose.prod.yml")
_EXPECTED_MAPPINGS = {
    "AWS_ACCESS_KEY_ID": ("${TITILER_S3_ACCESS_KEY_ID:-${S3_ACCESS_KEY_ID:-}}"),
    "AWS_SECRET_ACCESS_KEY": (
        "${TITILER_S3_SECRET_ACCESS_KEY:-${S3_SECRET_ACCESS_KEY:-}}"
    ),
}
_EXPECTED_PRESENCE_FLAGS = {
    "TITILER_S3_ACCESS_KEY_ID_SET": "${TITILER_S3_ACCESS_KEY_ID:+1}",
    "TITILER_S3_SECRET_ACCESS_KEY_SET": "${TITILER_S3_SECRET_ACCESS_KEY:+1}",
}


@pytest.mark.parametrize("filename", _COMPOSE_FILES)
def test_titiler_prefers_dedicated_s3_credentials(filename: str) -> None:
    body = yaml.safe_load((_REPO_ROOT / filename).read_text(encoding="utf-8"))
    env = body["services"]["titiler"]["environment"]

    for aws_key, expected in _EXPECTED_MAPPINGS.items():
        assert env.get(aws_key) == expected, (
            f"{filename}: {aws_key} must prefer the dedicated TITILER_S3_* "
            "input and retain only the shared-credential upgrade fallback"
        )

    assert "S3_ACCESS_KEY_ID" not in env
    assert "S3_SECRET_ACCESS_KEY" not in env
    assert "TITILER_S3_ACCESS_KEY_ID" not in env
    assert "TITILER_S3_SECRET_ACCESS_KEY" not in env


@pytest.mark.parametrize("filename", _COMPOSE_FILES)
def test_titiler_rejects_a_partial_dedicated_credential_pair(filename: str) -> None:
    body = yaml.safe_load((_REPO_ROOT / filename).read_text(encoding="utf-8"))
    titiler = body["services"]["titiler"]
    env = titiler["environment"]

    for flag, expected in _EXPECTED_PRESENCE_FLAGS.items():
        assert env.get(flag) == expected

    # Compose reduces $$ to $ before the command reaches /bin/sh. Simulate that
    # boundary and prove a partial rollout exits before the final uvicorn exec.
    command = titiler["command"][2].replace("$$", "$")
    result = subprocess.run(
        ["/bin/sh", "-ec", command],
        env={
            "PATH": os.environ["PATH"],
            "TITILER_S3_ACCESS_KEY_ID_SET": "1",
            "TITILER_S3_SECRET_ACCESS_KEY_SET": "",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "dedicated S3 access key and secret must be set together" in result.stderr


def test_env_example_documents_the_dedicated_pair() -> None:
    text = (_REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "# TITILER_S3_ACCESS_KEY_ID=<read-only-key-id>" in text
    assert "# TITILER_S3_SECRET_ACCESS_KEY=<read-only-secret>" in text
