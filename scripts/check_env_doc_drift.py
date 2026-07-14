"""Environment-contract drift gate (DOC-01).

Keep the operator-facing Settings, Compose, installer, and `.env.example`
surfaces aligned. The gate is intentionally standard-library only so it can run
before project dependencies are installed.

"Documented" means the key appears in `.env.example` either as an active
assignment (`KEY=`) or as a commented example/placeholder (`# KEY=`). Commented
keys count because several keys ship commented-out on purpose (cloud-dev MinIO
creds, the prebuilt-deploy GEOLENS_VERSION/COMPOSE_FILE knobs) — they are
documented, just not active in the default-profile install path.

Usage:
    python scripts/check_env_doc_drift.py
Exit code 0 = no drift; 1 = one or more contract violations.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
SETTINGS_PY = REPO_ROOT / "backend" / "app" / "core" / "config.py"
COMPOSE_FILES = (
    REPO_ROOT / "docker-compose.yml",
    REPO_ROOT / "docker-compose.prod.yml",
)

# Settings that are deliberately container/test internals rather than host
# operator knobs. Every other Settings field must be documented.
SETTINGS_DOC_ALLOWLIST: frozenset[str] = frozenset(
    {
        # Compose owns the container-network endpoint. Operators use DB_PORT for
        # the host binding instead.
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        # Test database name is documented in .env.test.example.
        "POSTGRES_DB_TEST",
        # Shared-volume invariant: Compose pins this to /app/staging.
        "UPLOAD_STAGING_DIR",
    }
)

EDITION_KEYS = frozenset(
    {
        "GEOLENS_EDITION",
        "GEOLENS_TENANCY_MODE",
        "GEOLENS_LICENSE_ENFORCE",
        "GEOLENS_LICENSE_KEY",
        "GEOLENS_LICENSE_FILE",
        "GEOLENS_LICENSE_AUDIENCE",
    }
)
NOTIFICATION_KEYS = frozenset(
    {
        "NOTIFICATIONS_ENABLED",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM_ADDRESS",
        "SMTP_USE_TLS",
        "NOTIFICATION_WEBHOOK_URL",
        "NOTIFICATION_WEBHOOK_SECRET",
        "NOTIFY_ON_SIGNUP",
        "NOTIFY_ON_INGEST_COMPLETE",
        "NOTIFY_ON_INGEST_FAILED",
        "NOTIFY_ON_HEALTH_ALERT",
        "NOTIFICATION_ADMIN_EMAIL",
    }
)
APP_RUNTIME_KEYS = frozenset({"LANDING_FIRST", "DEMO_MODE", "TITILER_BASE_URL"})
AZURE_APP_KEYS = frozenset(
    {
        "AZURE_STORAGE_CONTAINER",
        "AZURE_STORAGE_CONNECTION_STRING",
        "AZURE_STORAGE_ACCOUNT_URL",
        "AZURE_STORAGE_ACCOUNT_KEY",
    }
)
AZURE_TITILER_KEYS = frozenset(
    {
        "AZURE_STORAGE_CONNECTION_STRING",
        "AZURE_STORAGE_ACCOUNT",
        "AZURE_STORAGE_ACCESS_KEY",
    }
)

# Matches `update_env_value <KEY> ...` — the canonical write path install.sh
# uses to persist a value into .env.
WRITE_RE = re.compile(r"^\s*update_env_value\s+([A-Z][A-Z0-9_]*)\b")


def keys_written_by_installer(install_sh: Path) -> set[str]:
    """Return the set of env keys install.sh persists via update_env_value."""
    keys: set[str] = set()
    for line in install_sh.read_text().splitlines():
        m = WRITE_RE.match(line)
        if m:
            keys.add(m.group(1))
    return keys


def keys_documented_in_example(env_example: Path) -> set[str]:
    """Return keys documented in .env.example (active `KEY=` or commented `# KEY=`)."""
    keys: set[str] = set()
    # Active assignment at line start.
    active = re.compile(r"^([A-Z][A-Z0-9_]*)=")
    # Commented example/placeholder: `# KEY=` (any leading-hash + whitespace).
    commented = re.compile(r"^#\s*([A-Z][A-Z0-9_]*)=")
    for line in env_example.read_text().splitlines():
        m = active.match(line) or commented.match(line)
        if m:
            keys.add(m.group(1))
    return keys


def settings_field_keys(settings_py: Path) -> set[str]:
    """Return environment names represented by Settings fields."""
    tree = ast.parse(settings_py.read_text())
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            return {
                item.target.id.upper()
                for item in node.body
                if isinstance(item, ast.AnnAssign)
                and isinstance(item.target, ast.Name)
                and item.target.id != "model_config"
            }
    raise ValueError(f"Settings class not found in {settings_py}")


def _without_yaml_comment(line: str) -> str:
    """Drop a trailing YAML comment without disturbing URL fragments."""
    return re.sub(r"\s+#.*$", "", line)


def compose_host_keys(compose_files: tuple[Path, ...]) -> set[str]:
    """Return host variables interpolated by Compose (comments excluded)."""
    keys: set[str] = set()
    for path in compose_files:
        text = "\n".join(
            _without_yaml_comment(line)
            for line in path.read_text().splitlines()
            if not line.lstrip().startswith("#")
        )
        keys.update(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", text))
    return keys


def _anchor_environment_keys(text: str) -> dict[str, set[str]]:
    """Parse top-level YAML environment anchors used by the Compose files."""
    lines = text.splitlines()
    anchors: dict[str, set[str]] = {}
    for index, line in enumerate(lines):
        match = re.match(r"^x-[^:]+:\s*&([a-z0-9-]+)\s*$", line)
        if not match:
            continue
        name = match.group(1)
        keys: set[str] = set()
        for child in lines[index + 1 :]:
            if child and not child.startswith((" ", "\t", "#")):
                break
            key_match = re.match(r"^  ([A-Z][A-Z0-9_]*):", child)
            if key_match:
                keys.add(key_match.group(1))
        anchors[name] = keys
    return anchors


def _service_environment_keys(text: str) -> dict[str, set[str]]:
    """Resolve the small YAML subset used by service environment mappings."""
    lines = text.splitlines()
    anchors = _anchor_environment_keys(text)
    services: dict[str, set[str]] = {}
    in_services = False
    service: str | None = None
    in_environment = False

    for line in lines:
        if line == "services:":
            in_services = True
            service = None
            in_environment = False
            continue
        if not in_services:
            continue
        if line and not line.startswith((" ", "#")):
            break

        service_match = re.match(r"^  ([a-z0-9_-]+):\s*$", line)
        if service_match:
            service = service_match.group(1)
            services.setdefault(service, set())
            in_environment = False
            continue
        if service is None:
            continue
        if re.match(r"^    environment:\s*$", line):
            in_environment = True
            continue
        if in_environment and line.strip() and len(line) - len(line.lstrip()) <= 4:
            in_environment = False
        if not in_environment:
            continue

        direct = re.match(r"^      ([A-Z][A-Z0-9_]*):", line)
        if direct:
            services[service].add(direct.group(1))
        for alias in re.findall(r"\*([a-z0-9-]+)", line):
            services[service].update(anchors.get(alias, set()))

    return services


def compose_contract_errors(compose_files: tuple[Path, ...]) -> list[str]:
    """Check capability groups reach every backend service that consumes them."""
    required = {
        "migrate": EDITION_KEYS,
        "api": EDITION_KEYS | NOTIFICATION_KEYS | APP_RUNTIME_KEYS | AZURE_APP_KEYS,
        "worker": EDITION_KEYS | NOTIFICATION_KEYS | AZURE_APP_KEYS,
        "titiler": AZURE_TITILER_KEYS,
    }
    errors: list[str] = []
    canonical_key_mapping = 'AZURE_STORAGE_ACCESS_KEY: "${AZURE_STORAGE_ACCOUNT_KEY:-}"'

    for path in compose_files:
        text = path.read_text()
        service_keys = _service_environment_keys(text)
        for service, expected in required.items():
            missing = sorted(expected - service_keys.get(service, set()))
            if missing:
                errors.append(f"{path.name}:{service} missing {', '.join(missing)}")
        if canonical_key_mapping not in text:
            errors.append(
                f"{path.name}: Titiler must map AZURE_STORAGE_ACCOUNT_KEY "
                "to AZURE_STORAGE_ACCESS_KEY"
            )
    return errors


def raw_environment_keys() -> set[str]:
    """Find non-Settings env reads needed to identify stale example entries."""
    keys: set[str] = set()
    roots = (
        REPO_ROOT / "backend" / "app",
        REPO_ROOT / "backend" / "alembic",
        REPO_ROOT / "cli",
        REPO_ROOT / "frontend",
        REPO_ROOT / "scripts",
        REPO_ROOT / "tests",
    )
    suffixes = {".py", ".sh", ".ts", ".tsx", ".js", ".mjs"}
    patterns = (
        re.compile(r"os\.(?:getenv|environ\.get)\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]"),
        re.compile(r"process\.env\.([A-Z][A-Z0-9_]*)"),
        re.compile(r"import\.meta\.env\.([A-Z][A-Z0-9_]*)"),
        re.compile(r"\$\{([A-Z][A-Z0-9_]*)"),
    )
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            if any(part in {"node_modules", ".venv", "dist"} for part in path.parts):
                continue
            try:
                text = path.read_text()
            except UnicodeDecodeError:
                continue
            for pattern in patterns:
                keys.update(pattern.findall(text))
    return keys


def main() -> int:
    required_files = (INSTALL_SH, ENV_EXAMPLE, SETTINGS_PY, *COMPOSE_FILES)
    missing_files = [path for path in required_files if not path.is_file()]
    if missing_files:
        for path in missing_files:
            print(f"error: {path} not found", file=sys.stderr)
        return 2

    written = keys_written_by_installer(INSTALL_SH)
    documented = keys_documented_in_example(ENV_EXAMPLE)
    settings_keys = settings_field_keys(SETTINGS_PY)
    compose_keys = compose_host_keys(COMPOSE_FILES)
    raw_keys = raw_environment_keys()

    failures: list[tuple[str, list[str]]] = []
    installer_missing = sorted(written - documented)
    if installer_missing:
        failures.append(
            ("installer-written keys absent from .env.example", installer_missing)
        )

    settings_missing = sorted(settings_keys - documented - SETTINGS_DOC_ALLOWLIST)
    if settings_missing:
        failures.append(
            (
                "operator-facing Settings fields absent from .env.example",
                settings_missing,
            )
        )

    compose_missing = sorted(compose_keys - documented)
    if compose_missing:
        failures.append(
            ("Compose host inputs absent from .env.example", compose_missing)
        )

    referenced = written | settings_keys | compose_keys | raw_keys
    stale_example = sorted(documented - referenced)
    if stale_example:
        failures.append(
            ("documented env keys with no runtime/tool consumer", stale_example)
        )

    contract_errors = compose_contract_errors(COMPOSE_FILES)
    if contract_errors:
        failures.append(("Compose service capability contract drift", contract_errors))

    if failures:
        print("environment contract drift detected:", file=sys.stderr)
        for label, items in failures:
            print(f"\n{label}:", file=sys.stderr)
            for item in items:
                print(f"  - {item}", file=sys.stderr)
        return 1

    print(
        "env-doc-check OK: "
        f"{len(documented)} documented key(s), "
        f"{len(settings_keys)} Settings field(s), "
        f"{len(compose_keys)} Compose input(s), and "
        f"{len(written)} installer-written key(s) are aligned."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
