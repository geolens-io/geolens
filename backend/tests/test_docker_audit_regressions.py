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
DEP_AUDIT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "dep-audit.yml"
BACKEND_DOCKERIGNORE = REPO_ROOT / "backend" / ".dockerignore"
FRONTEND_ENTRYPOINT = REPO_ROOT / "frontend" / "docker-entrypoint.sh"
FRONTEND_NGINX = REPO_ROOT / "frontend" / "nginx.conf"
MAKEFILE = REPO_ROOT / "Makefile"


def _load_compose(path):
    with path.open() as compose_file:
        return yaml.safe_load(compose_file)


def test_test_cov_uses_writable_staging_data_file_and_cleanup(tmp_path):
    target_match = re.search(
        r"(?m)^test-cov:\n(?P<recipe>(?:\t[^\n]*(?:\n|$))+)",
        MAKEFILE.read_text(encoding="utf-8"),
    )
    assert target_match is not None
    recipe = target_match.group("recipe")
    env_prefix, separator, _pytest_args = recipe.partition(" uv run pytest ")

    assert separator, recipe
    coverage_match = re.search(r"\bCOVERAGE_FILE=(\S+)", env_prefix)
    assert coverage_match is not None, recipe
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


def test_docker_audit_matrix_pins_match_dockerfile_from_tags():
    # fix(#1778): dep-audit.yml's own comment says the node/python/nginx
    # pins must be "matched to the Dockerfile FROM tags they mirror (bump
    # together)" because Dependabot bumps the Dockerfile but cannot touch
    # this inline matrix string — the two drifted (node 26.5.0 vs the
    # Dockerfile's 26.7.0+, nginx 1.31.1 vs 1.31.3+) with nothing catching it.
    matrix = yaml.safe_load(DEP_AUDIT_WORKFLOW.read_text())["jobs"]["docker-audit"][
        "strategy"
    ]["matrix"]["include"]
    enforced_images = [entry["image"] for entry in matrix if entry["enforce"] == "1"]
    assert enforced_images

    dockerfile_text = DOCKERFILE.read_text()
    for image in enforced_images:
        assert re.search(
            rf"^FROM {re.escape(image)}(\s|$)", dockerfile_text, re.MULTILINE
        ), f"{image} (dep-audit.yml) has no matching FROM line in Dockerfile"


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


def _backup_stage_text() -> str:
    """The `AS backup` build stage's own text, up to the next `FROM` line
    (or EOF) — scoping COPY-line parsing to just that stage so a similarly
    named script elsewhere in the Dockerfile can't cross-contaminate the
    check.
    """
    text = DOCKERFILE.read_text()
    match = re.search(r"^FROM .* AS backup$", text, re.MULTILINE)
    assert match, "no `AS backup` stage found in Dockerfile"
    rest = text[match.end() :]
    next_from = re.search(r"^FROM ", rest, re.MULTILINE)
    return rest[: next_from.start()] if next_from else rest


def _backup_stage_copy_map() -> dict[str, Path]:
    """Every plain `COPY <src...> <dest>` line in the backup stage,
    resolved to {baked destination path: repo source path}. Mirrors
    Docker's own COPY placement rule: a destination ending in "/" (or
    naming more than one source) places each source under it by basename;
    a single source with an exact destination path is placed there
    verbatim. `COPY --from=...` (pulling from another stage/image, not the
    build context) is deliberately excluded — nothing in this stage uses
    it, and a `--from` copy has no single repo source path to map to.
    """
    baked: dict[str, Path] = {}
    for line in _backup_stage_text().splitlines():
        line = line.strip()
        if not line.startswith("COPY ") or "--from=" in line:
            continue
        parts = line.split()[1:]
        assert len(parts) >= 2, f"unparseable COPY line in backup stage: {line!r}"
        *sources, dest = parts
        if dest.endswith("/") or len(sources) > 1:
            for src in sources:
                baked[dest.rstrip("/") + "/" + Path(src).name] = REPO_ROOT / src
        else:
            baked[dest] = REPO_ROOT / sources[0]
    return baked


def test_backup_stage_bakes_every_script_it_sources():
    """fix(#1798 review round 7, P2): restore.sh sources
    `$SCRIPT_DIR/lib/common.sh` (SCRIPT_DIR=/scripts in this baked
    layout) for get_env_value, but the backup stage's COPY line used to
    bring in only backup-entrypoint.sh and restore.sh — the PUBLISHED
    geolens-backup image's baked restore.sh (no dev bind-mount there to
    mask it) hit "No such file or directory" on that `.` and exited
    immediately. Generic sweep, not a common.sh-specific check: for every
    script the backup stage bakes, every bash `. "$SCRIPT_DIR/<path>"`
    source line in the REAL repo file must resolve to something the same
    stage also bakes at that path.
    """
    baked = _backup_stage_copy_map()
    assert baked, "no COPY destinations found in the backup stage"

    source_line = re.compile(r'^\s*\.\s+"\$SCRIPT_DIR/([^"]+)"')
    checked_any_source_line = False
    for dest, repo_path in baked.items():
        if repo_path.suffix != ".sh" or not repo_path.is_file():
            continue
        script_dir = dest.rsplit("/", 1)[0]
        for line in repo_path.read_text().splitlines():
            match = source_line.match(line)
            if not match:
                continue
            checked_any_source_line = True
            resolved = f"{script_dir}/{match.group(1)}"
            assert resolved in baked, (
                f"{repo_path.relative_to(REPO_ROOT)} (baked at {dest}) sources "
                f"{resolved!r}, which the backup stage never COPYs — the "
                f'baked script will fail with "No such file or directory" '
                f"in the published image"
            )

    assert checked_any_source_line, (
        'no `. "$SCRIPT_DIR/..."` sourcing line found in any baked script — '
        "if restore.sh's sourcing style changed, update source_line's regex "
        "instead of silently passing with nothing checked"
    )
