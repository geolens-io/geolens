"""Static-analysis tests for Phase 272 docker-compose.yml hardening.

Pins every invariant added by Plans 272-02, 272-03, 272-04 (security_opt,
cap_drop, cap_add, read_only, tmpfs, healthchecks, port bindings, restart
policy). The original ``resource limits`` invariant was removed (see the
INF-01 note below) after commit 90919990 deleted the deploy.resources blocks.
Static analysis only — no docker daemon required.
"""

import pytest
import yaml

from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"


@pytest.fixture(scope="module")
def compose():
    """Parse docker-compose.yml once per test module."""
    with COMPOSE_PATH.open() as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def services(compose):
    return compose["services"]


# ---------------------------------------------------------------------------
# INF-01: deploy.resources.limits — INTENTIONALLY REMOVED
# ---------------------------------------------------------------------------
#
# Commit 90919990 ("refactor(compose): remove deploy.resources caps and VPS
# budget framing") deliberately deleted all 10 deploy.resources blocks:
# GeoLens does not target a specific hardware envelope, and production
# deployments via k8s/ECS set limits at the orchestrator level. The
# TestInf01ResourceLimits class that pinned those limits was removed to match
# that product decision — re-adding a resource-limits invariant here would
# contradict the documented direction.


# ---------------------------------------------------------------------------
# INF-02: security_opt no-new-privileges
# ---------------------------------------------------------------------------


class TestInf02SecurityOpt:
    """api, worker, migrate (and existing db, titiler, frontend) declare no-new-privileges:true."""

    @pytest.mark.parametrize(
        "service", ["api", "worker", "migrate", "db", "titiler", "frontend"]
    )
    def test_service_has_no_new_privileges(self, services, service):
        sec_opts = services[service].get("security_opt", [])
        assert "no-new-privileges:true" in sec_opts, (
            f"{service} missing 'no-new-privileges:true' in security_opt"
        )


# ---------------------------------------------------------------------------
# INF-03: cap_drop ALL on stateless services
# ---------------------------------------------------------------------------


class TestInf03CapDrop:
    """api, worker, frontend, titiler, migrate declare cap_drop: [ALL]."""

    @pytest.mark.parametrize(
        "service", ["api", "worker", "frontend", "titiler", "migrate"]
    )
    def test_service_drops_all_caps(self, services, service):
        cap_drop = services[service].get("cap_drop", [])
        assert "ALL" in cap_drop, f"{service} missing cap_drop: [ALL]"

    @pytest.mark.parametrize("service", ["api", "worker", "migrate"])
    def test_setpriv_services_have_required_cap_add(self, services, service):
        """api/worker/migrate need CAP_SETUID/SETGID/CHOWN/DAC_OVERRIDE/FOWNER for entrypoint setpriv + chown."""
        cap_add = set(services[service].get("cap_add", []))
        required = {"CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID"}
        missing = required - cap_add
        assert not missing, f"{service} cap_add missing required caps: {missing}"

    @pytest.mark.parametrize("service", ["titiler", "frontend"])
    def test_pure_stateless_services_have_no_cap_add(self, services, service):
        """titiler and frontend need no privileges; cap_add should be empty or absent."""
        cap_add = services[service].get("cap_add", []) or []
        assert not cap_add, (
            f"{service} should have empty cap_add (got {cap_add}); "
            f"only setpriv-based services need cap_add"
        )


# ---------------------------------------------------------------------------
# INF-04: healthchecks
# ---------------------------------------------------------------------------


class TestInf04Healthchecks:
    """frontend (dev) and backup gain healthchecks. Existing services keep theirs."""

    @pytest.mark.parametrize(
        "service",
        ["db", "api", "worker", "titiler", "frontend", "backup", "minio", "valkey"],
    )
    def test_service_has_healthcheck(self, services, service):
        hc = services[service].get("healthcheck")
        assert hc, f"{service} missing healthcheck"
        assert "test" in hc, f"{service} healthcheck missing 'test' field"


# ---------------------------------------------------------------------------
# INF-05: cloud-dev port bindings to 127.0.0.1
# ---------------------------------------------------------------------------


class TestInf05PortBindings:
    """minio + valkey ports bind to 127.0.0.1 only."""

    @pytest.mark.parametrize("service,expected_count", [("minio", 2), ("valkey", 1)])
    def test_cloud_dev_ports_bind_loopback(self, services, service, expected_count):
        ports = services[service].get("ports", [])
        assert len(ports) == expected_count, (
            f"{service} expected {expected_count} ports"
        )
        for p in ports:
            assert p.startswith("127.0.0.1:"), (
                f"{service} port {p!r} should bind to 127.0.0.1"
            )

    def test_db_port_binds_loopback(self, services):
        """Pre-existing 127.0.0.1 binding for db must remain."""
        for p in services["db"].get("ports", []):
            assert p.startswith("127.0.0.1:"), f"db port {p!r} should bind to 127.0.0.1"


# ---------------------------------------------------------------------------
# INF-07: read_only filesystems with tmpfs mounts
# ---------------------------------------------------------------------------


class TestInf07ReadOnlyFilesystem:
    """api, worker, titiler, migrate run with read_only: true + tmpfs."""

    @pytest.mark.parametrize("service", ["api", "worker", "titiler", "migrate"])
    def test_service_is_read_only(self, services, service):
        assert services[service].get("read_only") is True, (
            f"{service} missing read_only: true"
        )

    @pytest.mark.parametrize("service", ["api", "worker", "titiler", "migrate"])
    def test_service_has_tmpfs(self, services, service):
        tmpfs = services[service].get("tmpfs", [])
        assert tmpfs, f"{service} missing tmpfs mounts (required with read_only)"
        # /tmp is the universal must-have for stateless services
        tmpfs_paths = [t.split(":", 1)[0] for t in tmpfs]
        assert "/tmp" in tmpfs_paths, f"{service} tmpfs missing /tmp"

    def test_frontend_dev_is_NOT_read_only(self, services):
        """Vite is incompatible with read_only — explicit non-application."""
        assert not services["frontend"].get("read_only"), (
            "frontend (dev) must NOT be read_only — Vite writes HMR cache to /tmp/.vite"
        )


# ---------------------------------------------------------------------------
# INF-08: UVICORN_* env plumbing
# ---------------------------------------------------------------------------


class TestInf08UvicornEnv:
    """api command and environment block reference UVICORN_WORKERS / UVICORN_TIMEOUT_*."""

    def test_api_command_references_uvicorn_workers(self, services):
        cmd = services["api"].get("command", "")
        assert "UVICORN_WORKERS" in cmd, (
            f"api command missing UVICORN_WORKERS env interpolation: {cmd!r}"
        )

    def test_api_environment_declares_uvicorn_vars(self):
        """Compose source text must declare all three UVICORN_* env vars."""
        text = COMPOSE_PATH.read_text()
        for var in (
            "UVICORN_WORKERS",
            "UVICORN_TIMEOUT_KEEP_ALIVE",
            "UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN",
        ):
            assert var in text, f"docker-compose.yml missing {var}"


# ---------------------------------------------------------------------------
# INF-13: migrate restart: "no"
# ---------------------------------------------------------------------------


class TestInf13MigrateRestart:
    def test_migrate_restart_explicit_no(self, services):
        assert services["migrate"].get("restart") == "no", (
            "migrate must have explicit restart: 'no' (one-shot policy)"
        )


# ---------------------------------------------------------------------------
# GAP-021: every host-file bind mount on db is read-only
# ---------------------------------------------------------------------------


class TestGap021DbBindMountsReadOnly:
    """The db service must not bind-mount any host file/dir writable.

    A compromised db container (postgres initdb runs as root) must not be able
    to rewrite a host file the repo treats as trusted shell+SQL. Named volumes
    (e.g. pgdata) are container-managed state and are exempt.
    """

    def test_init_db_script_mount_is_read_only(self, services):
        mounts = services["db"].get("volumes", [])
        init = [m for m in mounts if "init-db.sh" in m]
        assert init, "db service no longer mounts scripts/init-db.sh"
        for m in init:
            assert m.endswith(":ro"), (
                f"init-db.sh bind mount must be :ro (defense-in-depth): {m!r}"
            )

    def test_all_db_host_bind_mounts_are_read_only(self, services):
        mounts = services["db"].get("volumes", [])
        for m in mounts:
            # Host bind mounts start with ./ or / ; named volumes (pgdata) do not.
            if m.startswith("./") or m.startswith("/"):
                assert m.endswith(":ro"), f"db host bind mount must be :ro: {m!r}"


# ---------------------------------------------------------------------------
# GAP-022: shared-staging contract — UPLOAD_STAGING_DIR is pinned, not a knob
# ---------------------------------------------------------------------------


class TestGap022SharedStagingContract:
    """api, worker, titiler share one /app/staging volume; the path is fixed.

    Setting UPLOAD_STAGING_DIR would desync the app's path from the unchanged
    mount target and silently break fan-out ingest + raster tiling, so the env
    var is pinned to the literal /app/staging (no "${UPLOAD_STAGING_DIR:-...}"
    interpolation) on every service that declares it.
    """

    STAGING_SERVICES = ["api", "worker", "titiler"]

    def test_staging_volume_mount_target_is_fixed(self, services):
        for svc in self.STAGING_SERVICES:
            mounts = services[svc].get("volumes", [])
            staging = [m for m in mounts if "upload_staging" in m]
            assert staging == ["upload_staging:/app/staging"], (
                f"{svc} must mount the shared upload_staging volume at the fixed "
                f"/app/staging (got {staging!r})"
            )

    def test_upload_staging_dir_env_is_pinned_not_interpolated(self):
        """No service may expose UPLOAD_STAGING_DIR as a ${...} override.

        Check the parsed env values (not raw text, which carries explanatory
        comments): every declared value must be the literal /app/staging.
        """
        with COMPOSE_PATH.open() as f:
            parsed = yaml.safe_load(f)
        for svc, cfg in parsed["services"].items():
            env = cfg.get("environment", {}) or {}
            if "UPLOAD_STAGING_DIR" in env:
                val = env["UPLOAD_STAGING_DIR"]
                assert val == "/app/staging", (
                    f"{svc} UPLOAD_STAGING_DIR must be pinned to /app/staging, "
                    f"not an operator-tunable override (got {val!r})"
                )

    def test_compose_declares_upload_staging_pinned(self, services):
        for svc in ("api", "worker"):
            env = services[svc].get("environment", {})
            assert env.get("UPLOAD_STAGING_DIR") == "/app/staging", (
                f"{svc} UPLOAD_STAGING_DIR must be pinned to /app/staging "
                f"(got {env.get('UPLOAD_STAGING_DIR')!r})"
            )
