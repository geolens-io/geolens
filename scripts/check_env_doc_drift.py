"""Environment-contract drift gate.

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
# Settings inherits these fields; they need documenting all the same.
AI_SETTINGS_PY = REPO_ROOT / "backend" / "app" / "core" / "config_ai.py"
AUTH_SETTINGS_PY = REPO_ROOT / "backend" / "app" / "core" / "auth_settings.py"
SETTINGS_CLASSES = (
    (SETTINGS_PY, "Settings"),
    (AUTH_SETTINGS_PY, "AuthSettings"),
    (AI_SETTINGS_PY, "ClaudeSettings"),
    (AI_SETTINGS_PY, "OpenAISettings"),
)
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
        "REMOTE_RASTER_RELAY_BASE_URL",
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

# Every `scripts/<file>` path a doc tells an operator to run must resolve to a
# real file, or the recipe is unrunnable as written.
SCRIPT_DOC_FILES = (
    "RUNBOOK.md",
    "README.md",
    # The translations carry the same operator-facing install/upgrade commands,
    # so a path mistyped only in a translation breaks the reader who follows it.
    "README.de.md",
    "README.es.md",
    "README.fr.md",
    "UPGRADING.md",
    "EDITIONS.md",
    "SUPPORT.md",
    ".env.example",
    ".env.test.example",
)
# Nested path components and any extension are both in scope, for example
# scripts/tests/test-backup-restore-roundtrip.sh and scripts/README.md. A trailing
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


def settings_field_keys(settings_py: Path, class_name: str = "Settings") -> set[str]:
    """Return environment names represented by the fields of ``class_name``."""
    return set(settings_field_defaults(((settings_py, class_name),)))


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
        # (?<!\$) skips $$-escaped references — Compose passes those
        # through as literal ${...} for in-container shells (e.g. the titiler
        # command wrapper), so they are not host inputs.
        keys.update(re.findall(r"(?<!\$)\$\{([A-Z][A-Z0-9_]*)", text))
    return keys


def _environment_value(rest: str) -> str | None:
    """Return a mapping entry's raw value, or None for a bare `KEY:`."""
    rest = _without_yaml_comment(rest).strip()
    if not rest:
        return None
    if len(rest) >= 2 and rest[0] == rest[-1] and rest[0] in "\"'":
        return rest[1:-1]
    return rest


def _anchor_environment(text: str) -> dict[str, dict[str, str | None]]:
    """Parse top-level YAML environment anchors used by the Compose files."""
    lines = text.splitlines()
    anchors: dict[str, dict[str, str | None]] = {}
    for index, line in enumerate(lines):
        match = re.match(r"^x-[^:]+:\s*&([a-z0-9-]+)\s*$", line)
        if not match:
            continue
        entries: dict[str, str | None] = {}
        for child in lines[index + 1 :]:
            if child and not child.startswith((" ", "\t", "#")):
                break
            key_match = re.match(r"^  ([A-Z][A-Z0-9_]*):(.*)$", child)
            if key_match:
                entries[key_match.group(1)] = _environment_value(key_match.group(2))
        anchors[match.group(1)] = entries
    return anchors


def _service_environment_keys(text: str) -> dict[str, set[str]]:
    """Resolve the environment variable names each service receives."""
    return {
        service: set(entries) for service, entries in _service_environment(text).items()
    }


def _service_environment(text: str) -> dict[str, dict[str, str | None]]:
    """Resolve the small YAML subset used by service environment mappings.

    Merged anchors come first and a service's own entries override them, as a
    YAML merge key does.
    """
    lines = text.splitlines()
    anchors = _anchor_environment(text)
    services: dict[str, dict[str, str | None]] = {}
    merged: dict[str, dict[str, str | None]] = {}
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
            services.setdefault(service, {})
            merged.setdefault(service, {})
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

        direct = re.match(r"^      ([A-Z][A-Z0-9_]*):(.*)$", line)
        if direct:
            services[service][direct.group(1)] = _environment_value(direct.group(2))
        for alias in re.findall(r"\*([a-z0-9-]+)", line):
            merged[service].update(anchors.get(alias, {}))

    return {name: {**merged[name], **entries} for name, entries in services.items()}


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


# DB_* Settings fields that are deliberately not passed to
# the containers. Empty on purpose -- every entry here is a documented knob an
# operator can set and the app will never see, so each one needs a reason.
DB_KNOBS_NOT_PASSED_TO_CONTAINERS: frozenset[str] = frozenset()


def db_knobs_absent_from_services(
    compose_files: tuple[Path, ...],
    documented: set[str],
    settings_keys: set[str],
) -> list[str]:
    """Documented DB_* knobs that never reach the api or worker container.

    The gate had no way to catch this. A new Settings
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


# The services that load Settings. Other services take their own variables.
SETTINGS_SERVICES = ("api", "worker", "migrate")

# Settings fields no Compose service lists, each with its reason.
SETTINGS_NOT_IN_COMPOSE: dict[str, str] = {
    "POSTGRES_DB_TEST": "test database name; only the host test suite reads it",
    "AWS_ROLE_ARN": "the platform injects it (EKS IRSA / Pod Identity)",
    "AWS_WEB_IDENTITY_TOKEN_FILE": "the platform injects it (EKS IRSA / Pod Identity)",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI": "the platform injects it (ECS/EKS)",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": "the platform injects it (ECS/EKS)",
}

# Entries whose Compose value deliberately differs from the Settings default,
# so they must stay explicit. A key applies to every Settings service; a
# `service:KEY` entry applies to that service only.
COMPOSE_SPECIFIC_DEFAULTS: dict[str, str] = {
    "POSTGRES_HOST": "the db service's hostname on the Compose network",
    "POSTGRES_PORT": "the db container port; DB_PORT is only the host binding",
    "POSTGRES_USER": "runtime role, falling back to the bootstrap user",
    "POSTGRES_PASSWORD": "runtime role password, falling back to the bootstrap one",
    "POSTGRES_DB": "always taken from .env, which the db service also reads",
    "UPLOAD_STAGING_DIR": "pinned to the shared upload_staging mount target",
    "PUBLIC_APP_URL": "the bundled frontend's localhost:8080 entry point",
    "PUBLIC_API_URL": "the bundled frontend's localhost:8080/api proxy",
    "api:UVICORN_WORKERS": "prod runs 2 workers; dev keeps 1 for --reload",
    "migrate:GEOLENS_RUNTIME_DB_ROLE": "migrate runs as the privileged identity",
    "migrate:GEOLENS_MIGRATION_DB_ROLE": "derived from the runtime role setting",
    "migrate:EMBEDDING_DIMS": "an unset dimension must stay empty for migration 0012",
    # Wiring tests in backend/tests pin these four to the `${KEY:-}` form.
    "SECRET_ENCRYPTION_KEY": "pinned by test_secret_encryption_key_1871.py",
    "SECRET_ENCRYPTION_KEY_PREVIOUS": "pinned by test_secret_encryption_key_1871.py",
    "S3_PUBLIC_ENDPOINT": "pinned by test_config.py",
    "DATABASE_URL_OVERRIDE": "pinned by test_entrypoint_migration_toggle.py; "
    "migrate prefers MIGRATION_DATABASE_URL_OVERRIDE",
    # The Anthropic and OpenAI SDKs read these names from the process
    # environment when the app passes None, and an empty value and an unset
    # one take different paths there.
    "OPENAI_API_KEY": "read by the OpenAI SDK from the environment",
    "ANTHROPIC_FOUNDRY_API_KEY": "read by the Anthropic SDK from the environment",
    "ANTHROPIC_FOUNDRY_RESOURCE": "read by the Anthropic SDK from the environment",
    "ANTHROPIC_VERTEX_PROJECT_ID": "read by the Anthropic SDK from the environment",
    "CLOUD_ML_REGION": "read by the Anthropic SDK from the environment",
}

_REQUIRED = object()
_NOT_LITERAL = object()
_SAME_KEY_DEFAULT_RE = re.compile(r"^\$\{([A-Z][A-Z0-9_]*):-([^${}]*)\}$")
_TRUE = frozenset({"1", "true", "yes", "on", "t", "y"})
_FALSE = frozenset({"0", "false", "no", "off", "f", "n"})


def settings_field_defaults(
    classes: tuple[tuple[Path, str], ...] = SETTINGS_CLASSES,
) -> dict[str, object]:
    """Return each field's literal default by environment name.

    The default is `_REQUIRED` for a field without one and `_NOT_LITERAL` when
    it is computed.
    """
    fields: dict[str, object] = {}
    for path, class_name in classes:
        for item in _class_body(path, class_name):
            if not isinstance(item, ast.AnnAssign) or not isinstance(
                item.target, ast.Name
            ):
                continue
            if item.target.id == "model_config":
                continue
            value = item.value
            if isinstance(value, ast.Call) and getattr(value.func, "id", "") == "Field":
                default_kw = [k.value for k in value.keywords if k.arg == "default"]
                value = default_kw[0] if default_kw else (value.args or [None])[0]
            if value is None:
                default: object = _REQUIRED
            else:
                try:
                    default = ast.literal_eval(value)
                except ValueError:
                    default = _NOT_LITERAL
            fields[item.target.id.upper()] = default
    return fields


def blank_normalized_fields(
    classes: tuple[tuple[Path, str], ...] = SETTINGS_CLASSES,
) -> set[str]:
    """Fields whose before-validator turns a blank string into the default.

    Recognized by name: a `mode="before"` field_validator whose function ends
    in `_to_none` or `_to_default`.
    """
    keys: set[str] = set()
    for path, class_name in classes:
        for item in _class_body(path, class_name):
            if not isinstance(item, ast.FunctionDef):
                continue
            if not item.name.endswith(("_to_none", "_to_default")):
                continue
            for decorator in item.decorator_list:
                if not (
                    isinstance(decorator, ast.Call)
                    and getattr(decorator.func, "id", "") == "field_validator"
                    and any(
                        k.arg == "mode" and getattr(k.value, "value", "") == "before"
                        for k in decorator.keywords
                    )
                ):
                    continue
                keys.update(
                    arg.value.upper()
                    for arg in decorator.args
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                )
    return keys


def _class_body(path: Path, class_name: str) -> list[ast.stmt]:
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node.body
    raise ValueError(f"{class_name} class not found in {path}")


def _parses_to_default(raw: str, default: object) -> bool:
    """Whether a non-empty Compose default equals the literal Settings default."""
    if isinstance(default, bool):
        return raw.strip().lower() in (_TRUE if default else _FALSE)
    if isinstance(default, int):
        try:
            return int(raw) == default
        except ValueError:
            return False
    return isinstance(default, str) and raw == default


def _compose_specific(service: str, key: str) -> bool:
    return key in COMPOSE_SPECIFIC_DEFAULTS or (
        f"{service}:{key}" in COMPOSE_SPECIFIC_DEFAULTS
    )


def compose_settings_errors(
    compose_files: tuple[Path, ...],
    fields: dict[str, object],
    blank_normalized: set[str],
) -> list[str]:
    """Check how the Settings services receive each Settings field.

    Every field needs an entry in each file unless SETTINGS_NOT_IN_COMPOSE
    excuses it. A bare `KEY:` passes the host value through and otherwise
    leaves the Settings default in charge, so it is the form for any entry
    whose Compose default would only repeat that default for both an unset
    and an empty host value. Bare is wrong for a key without a Settings
    field, for one listed in COMPOSE_SPECIFIC_DEFAULTS, and for one whose
    `${KEY:-default}` also turns an empty host value into the default,
    because each would drop a value Compose supplies. Every other explicit
    value must equal the Settings default or be listed with its reason.
    """
    errors: list[str] = []
    explicit_seen: set[str] = set()
    for path in compose_files:
        environments = _service_environment(path.read_text())
        received: set[str] = set()
        for service in SETTINGS_SERVICES:
            for key, raw in environments.get(service, {}).items():
                received.add(key)
                where = f"{path.name}:{service} {key}"
                if raw is None:
                    if key not in fields:
                        errors.append(
                            f"{where} is bare but is no Settings field, so "
                            "nothing supplies a value when the host leaves it unset"
                        )
                    elif _compose_specific(service, key):
                        errors.append(
                            f"{where} is bare, which drops the Compose-specific "
                            "value COMPOSE_SPECIFIC_DEFAULTS lists for it"
                        )
                    elif fields[key] not in (None, "", _REQUIRED, _NOT_LITERAL) and (
                        key not in blank_normalized
                    ):
                        errors.append(
                            f"{where} is bare, so an empty host value reaches "
                            f"Settings as '' instead of {fields[key]!r}; keep "
                            f"the `${{{key}:-...}}` default"
                        )
                    continue
                if key not in fields:
                    continue
                if _compose_specific(service, key):
                    explicit_seen.update({key, f"{service}:{key}"})
                    continue
                default = fields[key]
                if default is _REQUIRED and raw == f"${{{key}}}":
                    continue
                match = _SAME_KEY_DEFAULT_RE.match(raw)
                if not match or match.group(1) != key:
                    errors.append(
                        f"{where} = {raw!r} is not the Settings default; list it "
                        "in COMPOSE_SPECIFIC_DEFAULTS with a reason"
                    )
                    continue
                compose_default = match.group(2)
                if compose_default == "":
                    if default == "" or key in blank_normalized:
                        errors.append(
                            f"{where} = {raw!r} repeats the Settings default; "
                            f"write it bare as `{key}:`"
                        )
                    else:
                        errors.append(
                            f"{where} = {raw!r}: an empty value is not the "
                            f"Settings default {default!r}; list it in "
                            "COMPOSE_SPECIFIC_DEFAULTS with a reason"
                        )
                elif default is _NOT_LITERAL or not _parses_to_default(
                    compose_default, default
                ):
                    errors.append(
                        f"{where} = {raw!r} differs from the Settings default "
                        f"{'(computed)' if default is _NOT_LITERAL else repr(default)}; "
                        "align them or list it in COMPOSE_SPECIFIC_DEFAULTS"
                    )
        missing = sorted(set(fields) - received - set(SETTINGS_NOT_IN_COMPOSE))
        if missing:
            errors.append(
                f"{path.name}: no Settings service receives {', '.join(missing)}"
            )
    for entry in sorted(set(COMPOSE_SPECIFIC_DEFAULTS) - explicit_seen):
        errors.append(
            f"COMPOSE_SPECIFIC_DEFAULTS lists {entry}, which no Settings service "
            "sets explicitly any more"
        )
    for key in sorted(set(SETTINGS_NOT_IN_COMPOSE) - set(fields)):
        errors.append(
            f"SETTINGS_NOT_IN_COMPOSE lists {key}, which is no Settings field"
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
    required_files = (
        INSTALL_SH,
        ENV_EXAMPLE,
        SETTINGS_PY,
        AI_SETTINGS_PY,
        AUTH_SETTINGS_PY,
        *COMPOSE_FILES,
    )
    missing_files = [path for path in required_files if not path.is_file()]
    if missing_files:
        for path in missing_files:
            print(f"error: {path} not found", file=sys.stderr)
        return 2

    written = keys_written_by_installer(INSTALL_SH)
    documented = keys_documented_in_example(ENV_EXAMPLE)
    settings_keys = set().union(
        *(settings_field_keys(path, name) for path, name in SETTINGS_CLASSES)
    )
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

    settings_errors = compose_settings_errors(
        COMPOSE_FILES, settings_field_defaults(), blank_normalized_fields()
    )
    if settings_errors:
        failures.append(("Settings fields Compose passes wrongly", settings_errors))

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
