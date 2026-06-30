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

    def write_config(self, config: dict[str, object]) -> tuple[Path, tempfile.TemporaryDirectory[str]]:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        path = Path(tempdir.name) / "deployed_surface_gate.json"
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        return path, tempdir

    def minimal_config(self, **page_overrides: object) -> dict[str, object]:
        page = {
            "id": "fixture_page",
            "url": "https://example.test/",
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

    def load_config(self, config: dict[str, object]):
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
        self.assertEqual("https://example.test/final", failure.url)
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

        self.assertIn("marketing_home", pages)
        self.assertIn("docs_install", pages)
        self.assertIn("docs_backups", pages)
        self.assertIn("docs_cloud_deployment", pages)
        self.assertIn("docs_provider_notes", pages)
        self.assertIn("curl_installer", {item.id for item in pages["marketing_home"].required})
        self.assertIn("ogc_api_collections_url", {item.id for item in pages["marketing_home"].required})
        self.assertIn("stale_geolens_yml", {item.id for item in pages["marketing_home"].forbidden})
        self.assertIn("stale_backup_profile", {item.id for item in pages["docs_install"].forbidden})
        self.assertIn("backups_default_on", {item.id for item in pages["docs_backups"].required})
        self.assertIn("provider_title", {item.id for item in pages["docs_cloud_deployment"].required})


if __name__ == "__main__":
    unittest.main()
