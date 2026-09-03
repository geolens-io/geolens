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
        # Injected by the runtime, never set by a host operator: EKS IRSA and
        # Pod Identity write the web-identity pair into the pod, and the
        # ECS/EKS container credential providers write the other two. The
        # Settings fields exist only so has_ambient_aws_credentials can read
        # them the documented way instead of through os.environ. Putting them
        # in .env.example would invite operators to set by hand what a platform
        # is supposed to supply, and a hand-set AWS_ROLE_ARN resolves nothing.
        "AWS_ROLE_ARN",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
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
APP_RUNTIME_KEYS = frozenset(
    {
        "LANDING_FIRST",
        "BANNER_ENABLED",
        "BANNER_TEXT",
        "BANNER_COLOR",
        "TITILER_BASE_URL",
    }
)
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

# fix(#950): operator docs prescribed `scripts/prepare-tenant-rls.py`, a script
# that never existed in any repo — the multi-tenant restore recipe was
# unrunnable as written and nothing caught it. Every `scripts/<file>` path a
# doc tells an operator to run must resolve to a real file.
SCRIPT_DOC_FILES = (
    "RUNBOOK.md",
    "README.md",
    # The translations carry the same operator-facing install/upgrade commands
    # (codex review on #950's PR), so a path mistyped only in a translation is
    # exactly as broken for the reader who follows it.
    "README.de.md",
    "README.es.md",
    "README.fr.md",
    "UPGRADING.md",
    "EDITIONS.md",
    "SUPPORT.md",
    ".env.example",
    ".env.test.example",
)
# Nested path components and any extension are both in scope (codex review on
# #950's PR): RUNBOOK references scripts/tests/test-backup-restore-roundtrip.sh
# and README references scripts/README.md, and a pattern restricted to
# single-component .py/.sh/.mjs/.sql paths silently skipped both. A trailing
# extension is still required so that prose like "the scripts/ directory" and
# bare directory names do not get resolved as files.
#
# The optional `./` prefix is the executable form operator commands actually
# use (`./scripts/restore.sh`), so it must match; the lookbehind then runs
# against the character before that prefix, which keeps a URL path such as
# https://example.test/scripts/foo.py from being resolved repo-relative.
SCRIPT_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])(?:\./)?scripts/((?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_-]+"
    r"(?:\.[A-Za-z0-9_-]+)+)\b"
)


def unresolvable_doc_script_refs() -> list[str]:
    """Return doc-referenced scripts/ paths that do not exist in the repo."""
    errors: list[str] = []
    for name in SCRIPT_DOC_FILES:
        doc = REPO_ROOT / name
        if not doc.is_file():
            continue
        for lineno, line in enumerate(doc.read_text().splitlines(), start=1):
            for rel in SCRIPT_REF_RE.findall(line):
                if not (REPO_ROOT / "scripts" / rel).is_file():
                    errors.append(f"{name}:{lineno} references scripts/{rel}")
    return sorted(set(errors))


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
        # fix(#582): (?<!\$) skips $$-escaped references — Compose passes those
        # through as literal ${...} for in-container shells (e.g. the titiler
        # command wrapper), so they are not host inputs.
        keys.update(re.findall(r"(?<!\$)\$\{([A-Z][A-Z0-9_]*)", text))
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
    titiler_s3_mappings = (
        'AWS_ACCESS_KEY_ID: "${TITILER_S3_ACCESS_KEY_ID:-${S3_ACCESS_KEY_ID:-}}"',
        'AWS_SECRET_ACCESS_KEY: "${TITILER_S3_SECRET_ACCESS_KEY:-${S3_SECRET_ACCESS_KEY:-}}"',
    )

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
        for mapping in titiler_s3_mappings:
            if mapping not in text:
                errors.append(
                    f"{path.name}: Titiler must prefer its dedicated S3 credential "
                    f"with the shared-credential compatibility fallback: {mapping}"
                )
    return errors


# fix(#1778 codex r1): DB_* Settings fields that are deliberately not passed to
# the containers. Empty on purpose -- every entry here is a documented knob an
# operator can set and the app will never see, so each one needs a reason.
DB_KNOBS_NOT_PASSED_TO_CONTAINERS: frozenset[str] = frozenset()


def db_knobs_absent_from_services(
    compose_files: tuple[Path, ...],
    documented: set[str],
    settings_keys: set[str],
) -> list[str]:
    """Documented DB_* knobs that never reach the api or worker container.

    fix(#1778 codex r1): the gate had no way to catch this. A new Settings
    field documented in `.env.example` satisfied the two checks that already
    existed -- it is documented, and it has a consumer (the Settings field
    itself) -- while neither manifest listed it and neither uses `env_file`,
    so the container never received it and the documented default was the only
    value anyone could ever get. `DB_STATEMENT_TIMEOUT_SECONDS` shipped exactly
    that way.

    Scoped to the `DB_` prefix rather than to every Settings field: the whole
    group is pool and query behaviour that an operator tunes per deployment,
    they all belong on the same `x-db-ssl-env` anchor, and a prefix rule is one
    a reviewer can check by eye. Widening it further would need an allowlist
    entry for every key a service legitimately does not take.
    """
    candidates = {
        key
        for key in documented & settings_keys
        if key.startswith("DB_") and key not in DB_KNOBS_NOT_PASSED_TO_CONTAINERS
    }
    errors: list[str] = []
    for path in compose_files:
        service_keys = _service_environment_keys(path.read_text())
        for service in ("api", "worker"):
            missing = sorted(candidates - service_keys.get(service, set()))
            if missing:
                errors.append(
                    f"{path.name}:{service} never receives {', '.join(missing)}"
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

    inert_db_knobs = db_knobs_absent_from_services(
        COMPOSE_FILES, documented, settings_keys
    )
    if inert_db_knobs:
        failures.append(
            ("documented DB_* knobs that no container receives", inert_db_knobs)
        )

    phantom_scripts = unresolvable_doc_script_refs()
    if phantom_scripts:
        failures.append(
            ("doc-referenced scripts/ paths that do not exist", phantom_scripts)
        )

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
