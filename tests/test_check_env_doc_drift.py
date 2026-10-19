from __future__ import annotations

import importlib.util
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_env_doc_drift.py"

SETTINGS_SOURCE = textwrap.dedent(
    """
    from pydantic import BaseModel, Field, field_validator


    class Settings(BaseModel):
        jwt_secret_key: str
        postgres_host: str = "localhost"
        log_level: str = "INFO"
        banner_text: str = ""
        log_json: bool = False
        db_pool_size: int = Field(default=10, ge=1)
        redis_url: str | None = None
        environment: str | None = None
        computed: str = DEFAULT_FROM_ELSEWHERE

        @field_validator("redis_url", mode="before")
        @classmethod
        def empty_str_to_none(cls, v):
            return None if v == "" else v
    """
)

COMPLETE_ENV = """\
      JWT_SECRET_KEY: ${JWT_SECRET_KEY}
      POSTGRES_HOST: db
      LOG_LEVEL: "${LOG_LEVEL:-INFO}"
      BANNER_TEXT:
      LOG_JSON: "${LOG_JSON:-false}"
      DB_POOL_SIZE: "${DB_POOL_SIZE:-10}"
      REDIS_URL:
      ENVIRONMENT:
      COMPUTED:
"""


def load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_env_doc_drift", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ComposeSettingsGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = load_gate()
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        self.dir = Path(tempdir.name)
        settings = self.dir / "config.py"
        settings.write_text(SETTINGS_SOURCE)
        classes = ((settings, "Settings"),)
        self.fields = self.gate.settings_field_defaults(classes)
        self.blank = self.gate.blank_normalized_fields(classes)
        patcher = mock.patch.multiple(
            self.gate,
            COMPOSE_SPECIFIC_DEFAULTS={"POSTGRES_HOST": "Compose network host"},
            SETTINGS_NOT_IN_COMPOSE={},
            SERVICE_SETTINGS_EXCLUSIONS={"api": {}, "worker": {}},
            MIGRATE_SETTINGS_ANCHORS=(),
            MIGRATE_SETTINGS={"JWT_SECRET_KEY": "r"},
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def errors(
        self,
        env: str,
        *,
        anchors: str = "",
        extra: str = "",
        worker_env: str = COMPLETE_ENV,
        migrate_env: str = "      JWT_SECRET_KEY: ${JWT_SECRET_KEY}\n",
    ) -> list[str]:
        """Gate errors for a file whose api receives ``env``."""
        compose = self.dir / "compose.yml"
        compose.write_text(
            anchors
            + "services:\n  api:\n    image: x\n    environment:\n"
            + env
            + "  worker:\n    image: x\n    environment:\n"
            + worker_env
            + "  migrate:\n    image: x\n    environment:\n"
            + migrate_env
            + extra
        )
        return self.gate.compose_settings_errors((compose,), self.fields, self.blank)

    def test_reads_literal_defaults_from_settings(self) -> None:
        self.assertEqual(self.fields["DB_POOL_SIZE"], 10)
        self.assertIs(self.fields["JWT_SECRET_KEY"], self.gate._REQUIRED)
        self.assertIs(self.fields["COMPUTED"], self.gate._NOT_LITERAL)
        self.assertEqual(self.blank, {"REDIS_URL"})

    def test_complete_environment_passes(self) -> None:
        self.assertEqual(self.errors(COMPLETE_ENV), [])

    def test_settings_field_without_a_compose_entry_fails(self) -> None:
        env = COMPLETE_ENV.replace('      LOG_LEVEL: "${LOG_LEVEL:-INFO}"\n', "")
        self.assertEqual(self.errors(env), ["compose.yml:api never receives LOG_LEVEL"])

    def test_field_another_service_receives_still_fails_for_the_api(self) -> None:
        env = COMPLETE_ENV.replace("      REDIS_URL:\n", "")
        self.assertEqual(self.errors(env), ["compose.yml:api never receives REDIS_URL"])

    def test_field_missing_from_the_worker_fails(self) -> None:
        worker_env = COMPLETE_ENV.replace("      REDIS_URL:\n", "")
        self.assertEqual(
            self.errors(COMPLETE_ENV, worker_env=worker_env),
            ["compose.yml:worker never receives REDIS_URL"],
        )

    def test_service_exclusion_allows_absence_and_flags_staleness(self) -> None:
        env = COMPLETE_ENV.replace("      REDIS_URL:\n", "")
        exclusions = {"api": {"REDIS_URL": "r"}, "worker": {"REDIS_URL": "r"}}
        with mock.patch.dict(self.gate.SERVICE_SETTINGS_EXCLUSIONS, exclusions):
            errors = self.errors(env)
        self.assertEqual(
            errors,
            [
                "compose.yml:worker receives REDIS_URL, which "
                "SERVICE_SETTINGS_EXCLUSIONS excludes for it"
            ],
        )

    def test_migrate_needs_its_anchor_fields_and_listed_fields(self) -> None:
        anchors = (
            'x-db: &db-env\n  LOG_LEVEL: "${LOG_LEVEL:-INFO}"\n  NOT_A_FIELD: x\n\n'
        )
        with mock.patch.object(self.gate, "MIGRATE_SETTINGS_ANCHORS", ("db-env",)):
            self.assertEqual(
                self.errors(COMPLETE_ENV, anchors=anchors),
                ["compose.yml:migrate never receives LOG_LEVEL"],
            )
            merged = "      <<: *db-env\n      JWT_SECRET_KEY: ${JWT_SECRET_KEY}\n"
            self.assertEqual(
                self.errors(COMPLETE_ENV, anchors=anchors, migrate_env=merged), []
            )
        with mock.patch.object(self.gate, "MIGRATE_SETTINGS_ANCHORS", ("gone",)):
            self.assertEqual(
                self.errors(COMPLETE_ENV),
                ["compose.yml: anchor &gone for migrate is missing"],
            )

    def test_excluded_field_may_be_absent(self) -> None:
        env = COMPLETE_ENV.replace('      LOG_LEVEL: "${LOG_LEVEL:-INFO}"\n', "")
        with mock.patch.dict(self.gate.SETTINGS_NOT_IN_COMPOSE, {"LOG_LEVEL": "r"}):
            self.assertEqual(self.errors(env), [])

    def test_empty_default_that_repeats_settings_must_be_bare(self) -> None:
        for key in ("REDIS_URL", "BANNER_TEXT"):
            with self.subTest(key=key):
                env = COMPLETE_ENV.replace(
                    f"      {key}:\n", f'      {key}: "${{{key}:-}}"\n'
                )
                (error,) = self.errors(env)
                self.assertIn(f"write it bare as `{key}:`", error)

    def test_empty_default_without_blank_normalization_must_be_listed(self) -> None:
        env = COMPLETE_ENV.replace(
            "      ENVIRONMENT:\n", '      ENVIRONMENT: "${ENVIRONMENT:-}"\n'
        )
        (error,) = self.errors(env)
        self.assertIn("an empty value is not the Settings default None", error)

    def test_bare_entry_hides_a_compose_specific_default(self) -> None:
        env = COMPLETE_ENV.replace(
            "      POSTGRES_HOST: db\n", "      POSTGRES_HOST:\n"
        )
        (bare_error,) = self.errors(env)
        self.assertIn("api POSTGRES_HOST is bare", bare_error)
        bare_error, _, stale_error = self.errors(env, worker_env=env)
        self.assertIn("lists POSTGRES_HOST, which no Settings service", stale_error)

    def test_bare_entry_drops_the_empty_value_default(self) -> None:
        for key, old in (
            ("LOG_LEVEL", '"${LOG_LEVEL:-INFO}"'),
            ("LOG_JSON", '"${LOG_JSON:-false}"'),
            ("DB_POOL_SIZE", '"${DB_POOL_SIZE:-10}"'),
        ):
            with self.subTest(key=key):
                env = COMPLETE_ENV.replace(f"      {key}: {old}\n", f"      {key}:\n")
                (error,) = self.errors(env)
                self.assertIn(f"api {key} is bare, so an empty host value", error)

    def test_bare_entry_without_a_settings_field_fails(self) -> None:
        (error,) = self.errors(COMPLETE_ENV + "      UVICORN_MAX_REQUESTS:\n")
        self.assertIn("UVICORN_MAX_REQUESTS is bare but is no Settings field", error)

    def test_explicit_default_that_differs_from_settings_fails(self) -> None:
        cases = {
            "LOG_LEVEL": '"${LOG_LEVEL:-DEBUG}"',
            "LOG_JSON": '"${LOG_JSON:-true}"',
            "DB_POOL_SIZE": '"${DB_POOL_SIZE:-11}"',
            "COMPUTED": '"${COMPUTED:-x}"',
        }
        for key, value in cases.items():
            with self.subTest(key=key):
                env = "".join(
                    f"      {key}: {value}\n"
                    if line.startswith(f"      {key}:")
                    else line
                    for line in COMPLETE_ENV.splitlines(keepends=True)
                )
                (error,) = self.errors(env)
                self.assertIn(f"api {key} = ", error)

    def test_bool_default_accepts_pydantic_spellings(self) -> None:
        env = COMPLETE_ENV.replace("${LOG_JSON:-false}", "${LOG_JSON:-False}")
        self.assertEqual(self.errors(env), [])

    def test_unlisted_container_specific_value_fails(self) -> None:
        with mock.patch.dict(self.gate.COMPOSE_SPECIFIC_DEFAULTS, clear=True):
            errors = self.errors(COMPLETE_ENV)
        self.assertEqual(len(errors), 2)
        for service, error in zip(("api", "worker"), errors):
            self.assertIn(
                f"{service} POSTGRES_HOST = 'db' is not the Settings default", error
            )

    def test_stale_compose_specific_entry_fails(self) -> None:
        with mock.patch.dict(
            self.gate.COMPOSE_SPECIFIC_DEFAULTS, {"api:LOG_JSON": "r"}
        ):
            errors = self.errors(
                COMPLETE_ENV.replace(
                    '      LOG_JSON: "${LOG_JSON:-false}"\n', "      LOG_JSON:\n"
                )
            )
        self.assertEqual(
            errors,
            [
                "compose.yml:api LOG_JSON is bare, which drops the Compose-specific "
                "value COMPOSE_SPECIFIC_DEFAULTS lists for it",
                "COMPOSE_SPECIFIC_DEFAULTS lists api:LOG_JSON, which no Settings "
                "service sets explicitly any more",
            ],
        )

    def test_service_entry_overrides_a_merged_anchor(self) -> None:
        anchors = "x-shared: &shared\n  REDIS_URL:\n\n"
        env = COMPLETE_ENV.replace("      REDIS_URL:\n", "      <<: *shared\n")
        self.assertEqual(self.errors(env, anchors=anchors), [])
        overridden = env + '      REDIS_URL: "${REDIS_URL:-}"\n'
        (error,) = self.errors(overridden, anchors=anchors)
        self.assertIn("write it bare as `REDIS_URL:`", error)

    def test_other_services_are_not_settings_consumers(self) -> None:
        extra = '  titiler:\n    image: y\n    environment:\n      S3_ENDPOINT: "${S3_ENDPOINT:-}"\n      TITILER_WORKERS:\n'
        self.assertEqual(self.errors(COMPLETE_ENV, extra=extra), [])


class RepositoryGateTest(unittest.TestCase):
    def test_repository_compose_files_pass(self) -> None:
        gate = load_gate()
        errors = gate.compose_settings_errors(
            gate.COMPOSE_FILES,
            gate.settings_field_defaults(),
            gate.blank_normalized_fields(),
        )
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
