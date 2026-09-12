"""Regression tests for production container hardening invariants."""

import json
import os
import re
import subprocess
import sys
import tempfile
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


def test_docker_audit_matrix_is_derived_not_a_second_literal_copy():
    # fix(#1983): dep-audit.yml derives node/python/nginx from the Dockerfile
    # at run time instead of a second literal matrix copy (#1778 drifted,
    # #1975 needed a manual fix) — assert it stays derived, not reverted.
    workflow = yaml.safe_load(DEP_AUDIT_WORKFLOW.read_text())["jobs"]
    docker_audit = workflow["docker-audit"]

    assert docker_audit["needs"] == "resolve-docker-audit-matrix"
    matrix_include = docker_audit["strategy"]["matrix"]["include"]
    assert isinstance(matrix_include, str) and "fromJson(" in matrix_include, (
        "docker-audit's matrix.include must reference the resolved job "
        "output, not a literal list of images — a literal list is exactly "
        "the second copy that drifted behind the Dockerfile in #1778/#1983"
    )


def test_docker_audit_matrix_resolver_pins_match_dockerfile_from_tags():
    # fix(#1983): runs the real resolve-docker-audit-matrix step against the
    # Dockerfile, so a broken grep pattern or renamed stage fails here
    # instead of silently emitting an empty or stale pin in CI.
    steps = yaml.safe_load(DEP_AUDIT_WORKFLOW.read_text())["jobs"][
        "resolve-docker-audit-matrix"
    ]["steps"]
    matrix_step = next(step for step in steps if step.get("id") == "matrix")

    with tempfile.TemporaryDirectory() as tmp_dir:
        output_file = Path(tmp_dir) / "github_output"
        output_file.touch()
        subprocess.run(
            ["bash", "-c", matrix_step["run"]],
            cwd=REPO_ROOT,
            env={**os.environ, "GITHUB_OUTPUT": str(output_file)},
            check=True,
            capture_output=True,
            text=True,
        )
        output_line = next(
            line
            for line in output_file.read_text().splitlines()
            if line.startswith("include=")
        )
        resolved = json.loads(output_line[len("include=") :])

    enforced_images = {entry["image"] for entry in resolved if entry["enforce"] == "1"}
    assert enforced_images

    dockerfile_text = DOCKERFILE.read_text()
    for image in enforced_images:
        assert re.search(
            rf"^FROM {re.escape(image)}(\s|$)", dockerfile_text, re.MULTILINE
        ), (
            f"{image} (resolved by dep-audit.yml) has no matching FROM line in Dockerfile"
        )

    python_image = re.search(
        r"^FROM (python:\S+) AS backend-system$", dockerfile_text, re.MULTILINE
    )
    assert python_image is not None
    report_only = [entry for entry in resolved if entry["enforce"] == "0"]
    assert report_only == [
        {"image": python_image.group(1), "enforce": "0"},
        {"image": "postgis/postgis:18-3.6", "enforce": "0"},
    ]


def test_python_system_audit_builds_and_enforces_patched_stage():
    jobs = yaml.safe_load(DEP_AUDIT_WORKFLOW.read_text())["jobs"]
    steps = jobs["python-system-audit"]["steps"]
    build_step = next(step for step in steps if "run" in step)
    scan_step = next(
        step for step in steps if "aquasecurity/trivy-action" in step.get("uses", "")
    )

    assert "docker build --pull --no-cache" in build_step["run"]
    assert "--target backend-system" in build_step["run"]
    assert "--tag geolens-python-system:audit" in build_step["run"]
    expected_scan_config = {
        "image-ref": "geolens-python-system:audit",
        "severity": "CRITICAL",
        "exit-code": "1",
        "ignore-unfixed": True,
    }
    assert expected_scan_config.items() <= scan_step["with"].items()


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


def test_frontend_streams_request_bodies_outside_the_bounded_tmpfs():
    compose = _load_compose(PROD_COMPOSE)
    frontend = compose["services"]["frontend"]
    nginx = FRONTEND_NGINX.read_text()

    tmpfs_mount = next(
        mount for mount in frontend["tmpfs"] if mount.startswith("/tmp:")
    )
    assert "size=64m" in tmpfs_mount
    assert "frontend_cache:/var/cache/nginx" in frontend["volumes"]
    assert "proxy_http_version 1.1;" in nginx
    assert "proxy_request_buffering off;" in nginx
    assert "client_body_temp_path" not in nginx


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
