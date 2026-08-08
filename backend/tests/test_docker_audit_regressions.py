"""Regression tests for production container hardening invariants."""

import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)
DOCKERFILE = REPO_ROOT / "Dockerfile"
DEV_COMPOSE = REPO_ROOT / "docker-compose.yml"
PROD_COMPOSE = REPO_ROOT / "docker-compose.prod.yml"
PUBLISH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish.yml"
BACKEND_DOCKERIGNORE = REPO_ROOT / "backend" / ".dockerignore"
FRONTEND_ENTRYPOINT = REPO_ROOT / "frontend" / "docker-entrypoint.sh"
FRONTEND_NGINX = REPO_ROOT / "frontend" / "nginx.conf"
MAKEFILE = REPO_ROOT / "Makefile"


def _load_compose(path):
    with path.open() as compose_file:
        return yaml.safe_load(compose_file)


def test_test_cov_uses_writable_staging_data_file_and_cleanup(tmp_path):
    dry_run = subprocess.run(
        ["make", "--dry-run", "test-cov"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    env_prefix, separator, _pytest_args = dry_run.partition(" uv run pytest ")

    assert separator, dry_run
    coverage_match = re.search(r"\bCOVERAGE_FILE=(\S+)", env_prefix)
    assert coverage_match is not None, dry_run
    container_data_file = Path(coverage_match.group(1))
    assert container_data_file == Path("/app/staging/.coverage")

    smoke_dir = tmp_path / "staging"
    smoke_dir.mkdir()
    smoke_data_file = smoke_dir / container_data_file.name
    probe = tmp_path / "coverage_probe.py"
    probe.write_text("probe_ran = True\n", encoding="utf-8")
    env = {**os.environ, "COVERAGE_FILE": str(smoke_data_file)}

    subprocess.run(
        [sys.executable, "-m", "coverage", "run", str(probe)],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert smoke_data_file.is_file()
    assert not (tmp_path / ".coverage").exists()

    subprocess.run(
        [sys.executable, "-m", "coverage", "erase"],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert not list(smoke_dir.glob(".coverage*"))


def test_every_publish_scan_blocks_on_vulnerabilities():
    text = PUBLISH_WORKFLOW.read_text()

    assert "scan_exit_code" not in text
    assert text.count("exit-code: '1'") == 2


def test_backup_base_is_digest_pinned():
    text = DOCKERFILE.read_text()

    assert re.search(
        r"^FROM postgres:18@sha256:[0-9a-f]{64} AS backup$", text, re.MULTILINE
    )


def test_backend_runtime_does_not_recursively_chown_application_tree():
    text = DOCKERFILE.read_text()

    assert "chown -R appuser:appgroup /app" not in text
    assert "install -d -o appuser -g appgroup" in text


def test_backend_context_excludes_private_key_material():
    patterns = set(BACKEND_DOCKERIGNORE.read_text().splitlines())

    assert {"*.pem", "*.key", "*.crt", "*.p12", "*.pfx"} <= patterns


def test_production_database_init_script_is_read_only():
    services = _load_compose(PROD_COMPOSE)["services"]
    init_mounts = [
        mount for mount in services["db"]["volumes"] if "init-db.sh" in mount
    ]

    assert init_mounts == [
        "./scripts/init-db.sh:/docker-entrypoint-initdb.d/10-init.sh:ro"
    ]


def test_backup_services_override_inherited_postgres_data_volume():
    # chore(#704): postgres 18+ bases declare VOLUME /var/lib/postgresql
    # (PGDATA moved to <major>/docker inside it) — the tmpfs override must
    # target the new path or the anonymous volume comes back.
    for compose_path in (DEV_COMPOSE, PROD_COMPOSE):
        backup = _load_compose(compose_path)["services"]["backup"]
        tmpfs_paths = [mount.split(":", 1)[0] for mount in backup["tmpfs"]]

        assert "/var/lib/postgresql" in tmpfs_paths, compose_path.name


def test_production_frontend_has_only_explicit_writable_mounts():
    compose = _load_compose(PROD_COMPOSE)
    frontend = compose["services"]["frontend"]

    assert frontend["read_only"] is True
    assert any(mount.startswith("/tmp:") for mount in frontend["tmpfs"])
    assert frontend["volumes"] == ["frontend_cache:/var/cache/nginx"]
    assert "frontend_cache" in compose["volumes"]


def test_frontend_runtime_config_is_materialized_in_tmpfs():
    dockerfile = DOCKERFILE.read_text()
    entrypoint = FRONTEND_ENTRYPOINT.read_text()
    nginx = FRONTEND_NGINX.read_text()

    assert "/opt/geolens/html" in dockerfile
    assert "/usr/share/nginx/html" not in dockerfile
    assert "runtime_html=/tmp/geolens-html" in entrypoint
    assert "root /tmp/geolens-html;" in nginx


def test_frontend_image_healthcheck_uses_ipv4_loopback():
    text = DOCKERFILE.read_text()

    assert "--spider http://127.0.0.1:8080/" in text
    assert "--spider http://localhost:8080/" not in text
