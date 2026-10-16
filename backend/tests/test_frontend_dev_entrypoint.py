"""Behavior of the dev frontend entrypoint's lockfile sync."""

import hashlib
import os
import stat
import subprocess

from tests.repo_paths import repo_root

SCRIPT = repo_root(__file__) / "frontend/docker-dev-entrypoint.sh"
STAMP = "node_modules/.package-lock.sha256"


def _run(app, tmp_path, baked=None):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    npm = bin_dir / "npm"
    npm.write_text('#!/bin/sh\necho "$@" >> npm-calls\nmkdir -p node_modules\n')
    npm.chmod(npm.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    env["BAKED_NODE_MODULES"] = str(baked or tmp_path / "no-baked")
    return subprocess.run(
        ["sh", str(SCRIPT), "true"], cwd=app, env=env, check=True, capture_output=True
    )


def _calls(app):
    f = app / "npm-calls"
    return f.read_text().splitlines() if f.exists() else []


def test_reinstalls_when_lockfile_differs_then_stays_quiet(tmp_path):
    app = tmp_path / "app"
    (app / "node_modules" / "stale-pkg").mkdir(parents=True)
    (app / "package-lock.json").write_text('{"v": 2}')
    (app / STAMP).write_text("old-hash\n")

    _run(app, tmp_path)
    assert len(_calls(app)) == 1
    assert not (app / "node_modules" / "stale-pkg").exists()

    _run(app, tmp_path)
    assert len(_calls(app)) == 1


def test_reinstalls_when_stamp_missing(tmp_path):
    app = tmp_path / "app"
    (app / "node_modules").mkdir(parents=True)
    (app / "package-lock.json").write_text("{}")

    _run(app, tmp_path)
    assert len(_calls(app)) == 1


def test_restores_baked_dependencies_without_npm(tmp_path):
    app = tmp_path / "app"
    (app / "node_modules" / "stale-pkg").mkdir(parents=True)
    lock = '{"v": 3}'
    (app / "package-lock.json").write_text(lock)
    (app / STAMP).write_text("old-hash\n")
    baked = tmp_path / "baked"
    (baked / "fresh-pkg").mkdir(parents=True)
    digest = hashlib.sha256(lock.encode()).hexdigest()
    (baked / ".package-lock.sha256").write_text(digest + "\n")

    _run(app, tmp_path, baked)

    assert _calls(app) == []
    assert (app / "node_modules" / "fresh-pkg").is_dir()
    assert not (app / "node_modules" / "stale-pkg").exists()
    _run(app, tmp_path, baked)
    assert _calls(app) == []


def _dev_readiness(url):
    script = repo_root(__file__) / "frontend/scripts/dev-readiness.mjs"
    return subprocess.run(
        ["node", str(script)],
        env={**os.environ, "READINESS_URL": url},
        capture_output=True,
    )


def test_dev_frontend_healthcheck_runs_the_readiness_script():
    import yaml

    compose = yaml.safe_load((repo_root(__file__) / "docker-compose.yml").read_text())
    test = compose["services"]["frontend"]["healthcheck"]["test"]
    assert test == ["CMD", "node", "/app/scripts/dev-readiness.mjs"]
    assert (repo_root(__file__) / "frontend/scripts/dev-readiness.mjs").exists()
    assert (
        repo_root(__file__) / "frontend/src/components/builder/BuilderMap.tsx"
    ).exists()


def _serve_dev_server(stale_dep=None):
    """A stub of Vite's dev server where each optimized dep has its own ?v= hash."""
    import http.server
    import threading

    deps = {
        "/node_modules/.vite/deps/@vis__gl_react-maplibre.js": (
            "aaaa1111",
            "maplibre-gl",
        ),
        "/node_modules/.vite/deps/maplibre-gl.js": ("bbbb2222", None),
    }

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            path, _, query = self.path.partition("?")
            content_type, status, body = "text/javascript", 200, b"export {}"
            if path == "/":
                content_type, body = "text/html", b"<html>"
            elif path.startswith("/src/"):
                body = b'import "/node_modules/.vite/deps/@vis__gl_react-maplibre.js?v=aaaa1111"'
            elif path in deps:
                version, imports = deps[path]
                if query != f"v={version}" or path == stale_dep:
                    status, body = 504, b"Outdated Optimize Dep"
                elif imports:
                    body = (
                        b'import("/node_modules/.vite/deps/maplibre-gl.js?v=bbbb2222")'
                    )
            else:
                status, body = 404, b""
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_dev_readiness_passes_when_each_dep_has_its_own_hash():
    server = _serve_dev_server()
    try:
        result = _dev_readiness(f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
    assert result.returncode == 0, result.stderr


def test_dev_readiness_fails_when_a_builder_dependency_is_stale():
    server = _serve_dev_server(stale_dep="/node_modules/.vite/deps/maplibre-gl.js")
    try:
        result = _dev_readiness(f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
    assert result.returncode == 1
    assert b"504" in result.stderr


def test_dev_readiness_fails_when_the_server_is_down():
    assert _dev_readiness("http://127.0.0.1:1").returncode == 1
