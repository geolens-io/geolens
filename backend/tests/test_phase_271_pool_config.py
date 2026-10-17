"""Static-analysis tests for the database pool configuration."""

import re

from tests.repo_paths import repo_root

_REPO_ROOT = repo_root(__file__)
_CONFIG_PY = _REPO_ROOT / "backend" / "app" / "core" / "config.py"
_ENV_EXAMPLE = _REPO_ROOT / ".env.example"
_DOCKER_COMPOSE = _REPO_ROOT / "docker-compose.yml"


def test_config_py_db_max_overflow_default_is_3():
    """Lower db_max_overflow from 5 to 3."""
    text = _CONFIG_PY.read_text()
    assert re.search(
        r"db_max_overflow\s*:\s*int\s*=\s*(?:3\b|Field\(\s*default\s*=\s*3\b)",
        text,
    ), "Expected db_max_overflow to default to 3 in backend/app/core/config.py"


def test_env_example_db_max_overflow_documents_3():
    text = _ENV_EXAMPLE.read_text()
    # Allow either commented or active form, with optional whitespace.
    assert re.search(
        r"^\s*#?\s*DB_MAX_OVERFLOW\s*=\s*3\b",
        text,
        re.MULTILINE,
    ), "Expected `DB_MAX_OVERFLOW=3` (commented or active) in .env.example"


def test_docker_compose_db_max_overflow_fallback_is_3():
    text = _DOCKER_COMPOSE.read_text()
    assert "DB_MAX_OVERFLOW:-3" in text, (
        "Expected `${DB_MAX_OVERFLOW:-3}` in docker-compose.yml — fallback must match config.py default."
    )
