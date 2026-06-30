from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_deployed_surface.py"
CONFIG = ROOT / "scripts" / "deployed_surface_gate.json"


def load_scanner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_deployed_surface", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DeployedSurfaceGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.scanner = load_scanner()

    def write_config(self, config: object) -> tuple[Path, tempfile.TemporaryDirectory[str]]:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        path = Path(tempdir.name) / "deployed_surface_gate.json"
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        return path, tempdir

    def write_raw_config(self, text: str) -> Path:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        path = Path(tempdir.name) / "deployed_surface_gate.json"
        path.write_text(text, encoding="utf-8")
        return path

    def minimal_config(self, **page_overrides: object) -> dict[str, object]:
        page = {
            "id": "fixture_page",
            "url": "https://getgeolens.com/fixture/",
            "required": [
                {
                    "id": "required_copy",
                    "pattern": "required\\s+copy",
                    "flags": "i",
                    "reason": "Required copy should be present.",
                }
            ],
            "forbidden": [
                {
                    "id": "stale_copy",
                    "pattern": "stale\\s+copy",
                    "flags": "i",
                    "reason": "Stale copy should be absent.",
                }
            ],
        }
        page.update(page_overrides)
        return {"timeout_seconds": 3, "max_bytes": 4096, "pages": [page]}

    def load_config(self, config: object):
        path, _tempdir = self.write_config(config)
        return self.scanner.load_config(path)

    def scan_fixture(self, text: str, config: dict[str, object] | None = None):
        gate_config = self.load_config(config or self.minimal_config())

        def fetch(url: str, _timeout_seconds: float, _max_bytes: int):
            return self.scanner.PageFetch(url=f"{url}final", text=text)

        return self.scanner.scan_pages(gate_config, fetch=fetch)

    def test_forbidden_term_reports_page_url_match_and_excerpt(self) -> None:
        result = self.scan_fixture("Required copy is here. This has stale copy in deployed HTML.")

        self.assertEqual([], result.errors)
        self.assertEqual(1, len(result.failures))
        failure = result.failures[0]
        self.assertEqual("fixture_page", failure.page_id)
        self.assertEqual("https://getgeolens.com/fixture/final", failure.url)
        self.assertEqual("stale_copy", failure.assertion_id)
        self.assertEqual("forbidden", failure.kind)
        self.assertEqual("stale copy", failure.match)
        self.assertIn("deployed HTML", failure.excerpt)

    def test_missing_required_term_reports_assertion_failure(self) -> None:
        result = self.scan_fixture("No expected installer text here.")

        self.assertEqual([], result.errors)
        self.assertEqual(1, len(result.failures))
        failure = result.failures[0]
        self.assertEqual("required", failure.kind)
        self.assertEqual("required_copy", failure.assertion_id)
        self.assertEqual("", failure.match)
        self.assertIn("missing pattern", failure.excerpt)

    def test_successful_fixture_passes_without_failures(self) -> None:
        result = self.scan_fixture("<main>Required    copy is present.</main>")

        self.assertEqual(1, result.pages_scanned)
        self.assertEqual([], result.errors)
        self.assertEqual([], result.failures)

    def test_html_entities_and_whitespace_are_normalized(self) -> None:
        config = self.minimal_config(
            required=[
                {
                    "id": "backup_link",
                    "pattern": "Backups\\s+&\\s+Restore",
                    "flags": "i",
                    "reason": "Backup link should be present.",
                }
            ],
            forbidden=[],
        )

        result = self.scan_fixture("<a>Backups&nbsp;&amp;&nbsp;Restore</a>", config)

        self.assertEqual([], result.errors)
        self.assertEqual([], result.failures)

    def test_script_and_style_text_do_not_satisfy_required_or_forbidden_assertions(self) -> None:
        result = self.scan_fixture(
            "<script>required copy stale copy</script>"
            "<style>.x::before { content: 'required copy stale copy'; }</style>"
            "<main>Required copy is visible.</main>"
        )

        self.assertEqual([], result.errors)
        self.assertEqual([], result.failures)

    def test_required_copy_inside_script_is_ignored(self) -> None:
        result = self.scan_fixture("<script>required copy</script><main>Visible shell only.</main>")

        self.assertEqual([], result.errors)
        self.assertEqual(1, len(result.failures))
        self.assertEqual("required", result.failures[0].kind)
        self.assertEqual("required_copy", result.failures[0].assertion_id)

    def test_fetch_errors_are_reported_without_assertion_failures(self) -> None:
        gate_config = self.load_config(self.minimal_config())

        def fetch(_url: str, _timeout_seconds: float, _max_bytes: int):
            raise OSError("network unavailable")

        result = self.scanner.scan_pages(gate_config, fetch=fetch)

        self.assertEqual(0, result.pages_scanned)
        self.assertTrue(any("network unavailable" in error for error in result.errors))
        self.assertEqual([], result.failures)

    def test_invalid_config_rejects_missing_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "url"):
            self.load_config(self.minimal_config(url=""))

    def test_invalid_config_rejects_non_https_and_disallowed_urls(self) -> None:
        for bad_url in (
            "http://getgeolens.com/",
            "file:///etc/passwd",
            "https://example.test/",
            "https://docs.getgeolens.com:444/",
            "https://user:pass@getgeolens.com/",
        ):
            with self.subTest(bad_url=bad_url):
                with self.assertRaisesRegex(ValueError, "allowed deployed host|default HTTPS port|credentials"):
                    self.load_config(self.minimal_config(url=bad_url))

    def test_redirect_handler_rejects_disallowed_redirect_target(self) -> None:
        handler = self.scanner.DeployedRedirectHandler()
        request = self.scanner.Request("https://getgeolens.com/")

        with self.assertRaisesRegex(ValueError, "allowed deployed host"):
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {"Location": "https://example.test/"},
                "https://example.test/",
            )

    def test_malformed_config_shapes_fail_cleanly(self) -> None:
        malformed_configs = [
            (["not", "an", "object"], "must be an object"),
            ({"timeout_seconds": 3, "max_bytes": 4096, "pages": "bad"}, "pages must be a list"),
            ({"timeout_seconds": 3, "max_bytes": 4096, "pages": ["bad"]}, "pages\\[0\\] must be an object"),
            (self.minimal_config(required="bad"), "fixture_page.required must be a list"),
            (
                self.minimal_config(required=["bad"]),
                "fixture_page.required\\[0\\] must be an object",
            ),
            (
                {"timeout_seconds": "3", "max_bytes": 4096, "pages": []},
                "timeout_seconds must be a positive number",
            ),
            (
                {"timeout_seconds": float("inf"), "max_bytes": 4096, "pages": []},
                "unsupported JSON constant: Infinity",
            ),
            (
                {"timeout_seconds": 3, "max_bytes": "4096", "pages": []},
                "max_bytes must be a positive integer",
            ),
            (
                {"timeout_seconds": 3, "max_bytes": 4096, "pages": [], "unexpected": True},
                "unknown field\\(s\\): unexpected",
            ),
            (self.minimal_config(forbiddem=[]), "unknown field\\(s\\): forbiddem"),
            (self.minimal_config(id=123), "pages\\[0\\].id must be a string"),
            (self.minimal_config(url=123), "fixture_page.url must be a string"),
            (
                self.minimal_config(
                    required=[
                        {
                            "id": "required",
                            "pattern": "required",
                            "reason": "Required.",
                            "extra": True,
                        }
                    ]
                ),
                "fixture_page.required\\[0\\] unknown field\\(s\\): extra",
            ),
            (
                self.minimal_config(required=[{"id": 123, "pattern": "required", "reason": "Required."}]),
                "fixture_page.required\\[0\\].id must be a string",
            ),
            (
                self.minimal_config(required=[{"id": "required", "pattern": 123, "reason": "Required."}]),
                "fixture_page.required\\[0\\].pattern must be a string",
            ),
            (
                self.minimal_config(required=[{"id": "required", "pattern": "required", "reason": 123}]),
                "fixture_page.required\\[0\\].reason must be a string",
            ),
            (
                self.minimal_config(
                    required=[
                        {
                            "id": "required",
                            "pattern": "required",
                            "reason": "Required.",
                            "flags": 123,
                        }
                    ]
                ),
                "fixture_page.required\\[0\\].flags must be a string",
            ),
        ]

        for config, message in malformed_configs:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    self.load_config(config)

    def test_nonstandard_json_constants_fail_cleanly(self) -> None:
        path = self.write_raw_config('{"timeout_seconds": NaN, "max_bytes": 4096, "pages": []}')

        with self.assertRaisesRegex(ValueError, "unsupported JSON constant: NaN"):
            self.scanner.load_config(path)

    def test_invalid_config_rejects_duplicate_assertion_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate assertion id"):
            self.load_config(
                self.minimal_config(
                    required=[
                        {
                            "id": "same_id",
                            "pattern": "required",
                            "reason": "Required.",
                        }
                    ],
                    forbidden=[
                        {
                            "id": "same_id",
                            "pattern": "forbidden",
                            "reason": "Forbidden.",
                        }
                    ],
                )
            )

    def test_invalid_config_rejects_unsupported_regex_flags(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported regex flag"):
            self.load_config(
                self.minimal_config(
                    required=[
                        {
                            "id": "bad_flags",
                            "pattern": "required",
                            "flags": "m",
                            "reason": "Required.",
                        }
                    ]
                )
            )

    def test_invalid_config_rejects_empty_patterns(self) -> None:
        with self.assertRaisesRegex(ValueError, "pattern"):
            self.load_config(
                self.minimal_config(
                    required=[
                        {
                            "id": "empty_pattern",
                            "pattern": "",
                            "reason": "Required.",
                        }
                    ]
                )
            )

    def test_default_config_covers_marketing_and_docs_requirements(self) -> None:
        config = self.scanner.load_config(CONFIG)
        pages = {page.id: page for page in config.pages}

        expected = {
            "marketing_home": {
                "url": "https://getgeolens.com/",
                "required": [
                    ("curl_installer", "curl\\s+-fsSL\\s+https://getgeolens\\.com/install\\.sh\\s+\\|\\s+sh", "i"),
                    ("ogc_api_collections_url", "http://localhost:8080/api/collections", "i"),
                ],
                "forbidden": [
                    ("stale_geolens_yml", "\\bgeolens\\.yml\\b", "i"),
                    ("raw_ogc_collections_url", "localhost:8001/collections", "i"),
                    (
                        "ogc_compliant_claim",
                        "\\bOGC[- ]API[- ](?:Compliant|compliance)\\b|\\bOGC[- ](?:Compliant|compliance)\\b",
                        "i",
                    ),
                ],
            },
            "docs_install": {
                "url": "https://docs.getgeolens.com/guides/quickstart/install/",
                "required": [
                    ("curl_installer", "curl\\s+-fsSL\\s+https://getgeolens\\.com/install\\.sh\\s+\\|\\s+sh", "i"),
                    (
                        "reverse_proxy_ogc_api",
                        "OGC\\s+API\\s+clients\\s+should\\s+connect\\s+through\\s+the\\s+reverse-proxy\\s+path\\s+at\\s+http://localhost:8080/api/",
                        "i",
                    ),
                    ("backup_guide_link", "Backups\\s+&\\s+Restore", "i"),
                    ("provider_guide_link", "Self-host\\s+on\\s+AWS,\\s+GCP,\\s+or\\s+DigitalOcean", "i"),
                    ("provider_notes_link", "Self-hosted\\s+Provider\\s+Notes", "i"),
                ],
                "forbidden": [
                    ("stale_strategy_label", "Get\\s+Enterprise\\s+Only\\s+Tabs", "i"),
                    ("stale_edition_label", "\\bEdition\\s+Info\\b", "i"),
                    ("stale_backup_profile", "\\bbackup[- ]profile\\b|--profile\\s+backup", "i"),
                    ("hosted_cloud_wording", "\\bhosted[- ]Cloud\\b", "i"),
                    ("saas_wording", "\\bSaaS\\b", "i"),
                ],
            },
            "docs_backups": {
                "url": "https://docs.getgeolens.com/guides/admin/backups/",
                "required": [
                    ("backups_title", "Backups\\s+&\\s+Restore", "i"),
                    ("backups_default_on", "Automated\\s+backups\\s+are\\s+on\\s+by\\s+default", "i"),
                    ("backup_service", "\\bbackup\\s+service\\b", "i"),
                    ("backup_s3_enabled", "\\bBACKUP_S3_ENABLED\\b", ""),
                ],
                "forbidden": [
                    ("stale_backup_profile", "\\bbackup[- ]profile\\b|--profile\\s+backup", "i"),
                    ("hosted_cloud_wording", "\\bhosted[- ]Cloud\\b", "i"),
                    ("saas_wording", "\\bSaaS\\b", "i"),
                ],
            },
            "docs_cloud_deployment": {
                "url": "https://docs.getgeolens.com/guides/quickstart/cloud-deployment/",
                "required": [
                    ("provider_title", "Self-host\\s+on\\s+AWS,\\s+GCP,\\s+or\\s+DigitalOcean", "i"),
                    ("managed_database", "\\bmanaged\\s+database\\b", "i"),
                    ("object_storage", "\\bobject\\s+storage\\b", "i"),
                    ("docker_compose_comparison", "\\bDocker\\s+Compose\\b", "i"),
                ],
                "forbidden": [
                    ("hosted_cloud_wording", "\\bhosted[- ]Cloud\\b", "i"),
                    ("saas_wording", "\\bSaaS\\b", "i"),
                ],
            },
            "docs_provider_notes": {
                "url": "https://docs.getgeolens.com/guides/admin/cloud/",
                "required": [("provider_notes_title", "Self-hosted\\s+Provider\\s+Notes", "i")],
                "forbidden": [
                    ("hosted_cloud_wording", "\\bhosted[- ]Cloud\\b", "i"),
                    ("saas_wording", "\\bSaaS\\b", "i"),
                ],
            },
        }

        self.assertEqual(set(expected), set(pages))
        for page_id, page_expected in expected.items():
            with self.subTest(page=page_id):
                page = pages[page_id]
                self.assertEqual(page_expected["url"], page.url)
                self.assertEqual(page_expected["required"], [(item.id, item.pattern, item.flags) for item in page.required])
                self.assertEqual(
                    page_expected["forbidden"],
                    [(item.id, item.pattern, item.flags) for item in page.forbidden],
                )

    def test_default_config_fixture_pages_pass_offline(self) -> None:
        config = self.scanner.load_config(CONFIG)
        fixtures = {
            "marketing_home": (
                "curl -fsSL https://getgeolens.com/install.sh | sh "
                "OGC API at http://localhost:8080/api/collections"
            ),
            "docs_install": (
                "curl -fsSL https://getgeolens.com/install.sh | sh "
                "OGC API clients should connect through the reverse-proxy path at http://localhost:8080/api/ "
                "Backups & Restore Self-host on AWS, GCP, or DigitalOcean Self-hosted Provider Notes"
            ),
            "docs_backups": (
                "Backups & Restore Automated backups are on by default. "
                "The backup service uses BACKUP_S3_ENABLED for off-site upload."
            ),
            "docs_cloud_deployment": (
                "Self-host on AWS, GCP, or DigitalOcean with managed database, object storage, "
                "and Docker Compose comparison notes."
            ),
            "docs_provider_notes": "Self-hosted Provider Notes",
        }

        for page in config.pages:
            with self.subTest(page=page.id):
                failures = self.scanner.scan_page_text(page, fixtures[page.id])
                self.assertEqual([], failures)

    def test_default_config_rejects_representative_forbidden_strings_offline(self) -> None:
        config = self.scanner.load_config(CONFIG)
        pages = {page.id: page for page in config.pages}
        cases = [
            (
                "marketing_home",
                "curl -fsSL https://getgeolens.com/install.sh | sh "
                "http://localhost:8080/api/collections geolens.yml",
                "stale_geolens_yml",
            ),
            (
                "docs_install",
                "curl -fsSL https://getgeolens.com/install.sh | sh "
                "OGC API clients should connect through the reverse-proxy path at http://localhost:8080/api/ "
                "Backups & Restore Self-host on AWS, GCP, or DigitalOcean Self-hosted Provider Notes "
                "Get Enterprise Only Tabs",
                "stale_strategy_label",
            ),
            (
                "docs_backups",
                "Backups & Restore Automated backups are on by default. "
                "The backup service uses BACKUP_S3_ENABLED. Run --profile backup.",
                "stale_backup_profile",
            ),
        ]

        for page_id, text, expected_assertion in cases:
            with self.subTest(page=page_id):
                failures = self.scanner.scan_page_text(pages[page_id], text)
                self.assertIn(expected_assertion, {failure.assertion_id for failure in failures})


if __name__ == "__main__":
    unittest.main()
