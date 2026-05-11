"""Static-analysis tests for Phase 272 .dockerignore polish.

Pins INF-11 (db/.dockerignore alignment) + INF-12 (root .dockerignore comment header).
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_DOCKERIGNORE = REPO_ROOT / ".dockerignore"
DB_DOCKERIGNORE = REPO_ROOT / "db" / ".dockerignore"


# ---------------------------------------------------------------------------
# INF-12: Root .dockerignore comment header
# ---------------------------------------------------------------------------


class TestInf12RootDockerignoreHeader:
    def test_first_line_is_comment(self):
        text = ROOT_DOCKERIGNORE.read_text()
        first_line = text.splitlines()[0]
        assert first_line.startswith("#"), (
            "root .dockerignore line 1 must be a comment introducing the file"
        )

    def test_contains_default_deny_explanation(self):
        text = ROOT_DOCKERIGNORE.read_text()
        assert "default-deny" in text, (
            "root .dockerignore comment header must explain the default-deny pattern"
        )

    def test_negate_include_pattern_preserved(self):
        """The functional behavior — `**` + `!path/` pattern — must remain."""
        text = ROOT_DOCKERIGNORE.read_text()
        assert "**" in text, "root .dockerignore must retain `**` exclude pattern"
        assert "!backend/" in text, "root .dockerignore must retain `!backend/` include"
        assert "!frontend/" in text, (
            "root .dockerignore must retain `!frontend/` include"
        )


# ---------------------------------------------------------------------------
# INF-11: db/.dockerignore alignment
# ---------------------------------------------------------------------------


class TestInf11DbDockerignoreAlignment:
    def test_ignores_git(self):
        text = DB_DOCKERIGNORE.read_text()
        assert ".git" in text, "db/.dockerignore must ignore .git"

    def test_ignores_env_files(self):
        text = DB_DOCKERIGNORE.read_text()
        # Two patterns: .env and .env.*
        assert ".env" in text, "db/.dockerignore must ignore .env"
        assert ".env.*" in text, "db/.dockerignore must ignore .env.*"

    def test_ignores_markdown(self):
        text = DB_DOCKERIGNORE.read_text()
        assert "*.md" in text, "db/.dockerignore must ignore *.md"

    def test_ignores_ds_store(self):
        text = DB_DOCKERIGNORE.read_text()
        assert ".DS_Store" in text, "db/.dockerignore must ignore .DS_Store"

    def test_file_size_grew(self):
        """Pre-Phase 272 the file was 10 bytes (just .git\\n*.md). After, ~250+ bytes."""
        size = DB_DOCKERIGNORE.stat().st_size
        assert size > 100, (
            f"db/.dockerignore is {size} bytes; expected >100 after Phase 272 alignment"
        )
