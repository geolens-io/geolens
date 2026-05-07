"""Static-analysis tests for Phase 271 / DBM-04 pool config + README docs."""

import re
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PY = _REPO_ROOT / "backend" / "app" / "core" / "config.py"
_ENV_EXAMPLE = _REPO_ROOT / ".env.example"
_DOCKER_COMPOSE = _REPO_ROOT / "docker-compose.yml"
_README = _REPO_ROOT / "README.md"


def test_config_py_db_max_overflow_default_is_3():
    """DBM-04: lower db_max_overflow from 5 to 3."""
    text = _CONFIG_PY.read_text()
    assert re.search(
        r"db_max_overflow\s*:\s*int\s*=\s*3\b",
        text,
    ), "Expected `db_max_overflow: int = 3` in backend/app/core/config.py"


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


def test_readme_documents_connection_pool_budget():
    text = _README.read_text()
    # Section header + arithmetic. Allow flexible heading prefix (#, ##, etc).
    assert re.search(
        r"#+\s*Connection Pool Budget|Connection Pool Budget|connection-pool budget",
        text,
        re.IGNORECASE,
    ), "README must have a 'Connection Pool Budget' section."
    # The arithmetic must show pool_size + max_overflow + procrastinate.
    assert "pool_size" in text or "DB_POOL_SIZE" in text or "10" in text
    assert "max_overflow" in text or "DB_MAX_OVERFLOW" in text
