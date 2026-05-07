"""Static-analysis tests for Phase 272 Dockerfile + frontend image hardening.

Pins INF-06 (multi-stage), INF-09 (BuildKit cache mounts), INF-10 (frontend/Dockerfile
deletion), INF-14 (nginx mime), INF-15 (python pin cross-comments), INF-16 (USER node).
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"
FRONTEND_DOCKERFILE_DEV = REPO_ROOT / "frontend" / "Dockerfile.dev"
FRONTEND_DOCKERFILE_LEGACY = REPO_ROOT / "frontend" / "Dockerfile"
FRONTEND_NGINX_CONF = REPO_ROOT / "frontend" / "nginx.conf"
PYPROJECT = REPO_ROOT / "backend" / "pyproject.toml"


# ---------------------------------------------------------------------------
# INF-06: True multi-stage Dockerfile
# ---------------------------------------------------------------------------


class TestInf06MultiStage:
    def test_dockerfile_has_builder_stage(self):
        text = DOCKERFILE.read_text()
        assert re.search(r"^FROM\s+\S+\s+AS\s+backend-builder\s*$", text, re.M), (
            "Dockerfile must declare a `FROM ... AS backend-builder` stage"
        )

    def test_dockerfile_has_runtime_stage(self):
        text = DOCKERFILE.read_text()
        assert re.search(r"^FROM\s+\S+\s+AS\s+backend-base\s*$", text, re.M), (
            "Dockerfile must declare a `FROM ... AS backend-base` runtime stage"
        )

    def test_runtime_copies_venv_from_builder(self):
        text = DOCKERFILE.read_text()
        assert "COPY --from=backend-builder" in text, (
            "Runtime stage must copy /app from backend-builder, not rebuild"
        )

    def test_uv_kept_in_runtime_with_explanatory_comment(self):
        """INF-06 disposition: uv is intentionally kept in runtime; comment must explain."""
        text = DOCKERFILE.read_text()
        # Two COPY --from=ghcr.io/astral-sh/uv lines (one per stage)
        copy_count = text.count("COPY --from=ghcr.io/astral-sh/uv")
        assert copy_count >= 2, (
            f"Expected uv copied into both builder and runtime stages "
            f"(got {copy_count} COPY lines)"
        )
        # Comment naming the constraint
        assert "enterprise" in text.lower() and "overlay" in text.lower(), (
            "Dockerfile runtime should comment on the enterprise overlay constraint "
            "(why uv is kept in runtime). Per 272-RESEARCH-NOTES.md §INF-06."
        )


# ---------------------------------------------------------------------------
# INF-09: BuildKit npm cache mounts
# ---------------------------------------------------------------------------


class TestInf09BuildkitNpmCache:
    def test_root_dockerfile_frontend_uses_cache_mount(self):
        text = DOCKERFILE.read_text()
        # Frontend stage starts with "FROM node:... AS frontend-build"
        # and should have RUN --mount=type=cache for npm
        assert re.search(
            r"RUN\s+--mount=type=cache,target=/root/\.npm\s+.*npm ci",
            text,
            re.S,
        ), "Root Dockerfile frontend stage missing BuildKit npm cache mount"

    def test_dockerfile_dev_uses_cache_mount(self):
        text = FRONTEND_DOCKERFILE_DEV.read_text()
        assert "--mount=type=cache,target=/root/.npm" in text, (
            "frontend/Dockerfile.dev missing BuildKit npm cache mount"
        )

    def test_dockerfile_dev_has_syntax_directive(self):
        text = FRONTEND_DOCKERFILE_DEV.read_text()
        # First non-blank line must be the syntax directive
        first = next(line for line in text.splitlines() if line.strip())
        assert first.strip() == "# syntax=docker/dockerfile:1", (
            "frontend/Dockerfile.dev must start with `# syntax=docker/dockerfile:1` "
            "for BuildKit features"
        )


# ---------------------------------------------------------------------------
# INF-10: frontend/Dockerfile deleted
# ---------------------------------------------------------------------------


class TestInf10FrontendDockerfileDeleted:
    def test_legacy_frontend_dockerfile_does_not_exist(self):
        assert not FRONTEND_DOCKERFILE_LEGACY.exists(), (
            "frontend/Dockerfile must be deleted (drift target — no current consumer; "
            "see 272-PATTERNS.md §10)"
        )


# ---------------------------------------------------------------------------
# INF-14: nginx mime types
# ---------------------------------------------------------------------------


class TestInf14NginxMime:
    def test_nginx_conf_has_default_type(self):
        text = FRONTEND_NGINX_CONF.read_text()
        assert "default_type application/octet-stream" in text, (
            "nginx.conf server block must declare `default_type application/octet-stream`"
        )

    def test_nginx_conf_includes_mime_types(self):
        text = FRONTEND_NGINX_CONF.read_text()
        assert "include /etc/nginx/mime.types" in text, (
            "nginx.conf server block must `include /etc/nginx/mime.types`"
        )


# ---------------------------------------------------------------------------
# INF-15: Python pin cross-comments
# ---------------------------------------------------------------------------


class TestInf15PythonPinReconciliation:
    def test_dockerfile_pins_python_3_14_3(self):
        text = DOCKERFILE.read_text()
        assert "python:3.14.3-slim" in text, "Dockerfile must pin python:3.14.3-slim"

    def test_pyproject_requires_python_at_least_3_13(self):
        text = PYPROJECT.read_text()
        assert re.search(r'requires-python\s*=\s*">=3\.13"', text), (
            "backend/pyproject.toml must specify requires-python = '>=3.13'"
        )

    def test_pyproject_has_cross_comment(self):
        """A comment near requires-python referencing the Docker pin / INF-15."""
        text = PYPROJECT.read_text()
        # Find the requires-python line and check the preceding lines for a comment block
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if "requires-python" in line and "=" in line:
                # Look at preceding 5 lines for a comment about Dockerfile / 3.14.3 / INF-15
                preceding = "\n".join(lines[max(0, i - 5) : i])
                assert any(
                    kw in preceding for kw in ("3.14.3-slim", "Dockerfile", "INF-15")
                ), (
                    f"backend/pyproject.toml requires-python at line {i + 1} "
                    f"missing cross-comment about Docker pin (3.14.3-slim or INF-15)"
                )
                return
        raise AssertionError("requires-python line not found in pyproject.toml")


# ---------------------------------------------------------------------------
# INF-16: Vite non-root user
# ---------------------------------------------------------------------------


class TestInf16ViteNonRoot:
    def test_dockerfile_dev_has_user_node(self):
        text = FRONTEND_DOCKERFILE_DEV.read_text()
        # Find the USER node directive — must come BEFORE EXPOSE / CMD
        assert re.search(r"^USER node\s*$", text, re.M), (
            "frontend/Dockerfile.dev must declare `USER node` for non-root runtime"
        )

    def test_dockerfile_dev_user_node_before_cmd(self):
        text = FRONTEND_DOCKERFILE_DEV.read_text()
        # Find the first USER node directive (skipping comments)
        user_match = re.search(r"^USER node\s*$", text, re.M)
        cmd_match = re.search(r"^CMD\s+", text, re.M)
        assert user_match, "USER node directive missing"
        assert cmd_match, "CMD directive missing"
        assert user_match.start() < cmd_match.start(), (
            "USER node must appear before CMD (USER affects subsequent layers/runtime)"
        )

    def test_copy_uses_chown_node(self):
        """COPY directives use --chown=node:node so non-root user can read source files."""
        text = FRONTEND_DOCKERFILE_DEV.read_text()
        # At least the source-copy line should use --chown=node:node
        assert "--chown=node:node" in text, (
            "frontend/Dockerfile.dev COPY must use --chown=node:node "
            "for USER node to read mounted source"
        )
