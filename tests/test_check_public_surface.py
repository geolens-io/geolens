from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_public_surface.py"
CONFIG = ROOT / "scripts" / "public_surface_gate.json"


def load_scanner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_public_surface", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PublicSurfaceGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.scanner = load_scanner()

    def write_config(self, repo: Path, **overrides: object) -> Path:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        config.update(overrides)
        path = repo / "public_surface_gate.json"
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        return path

    def make_repo(self, files: dict[str, str], **config_overrides: object) -> tuple[Path, Path, tempfile.TemporaryDirectory[str]]:
        tempdir = tempfile.TemporaryDirectory()
        repo = Path(tempdir.name)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        for rel_path, content in files.items():
            path = repo / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        config_path = self.write_config(repo, **config_overrides)
        subprocess.run(["git", "add", *files.keys()], cwd=repo, check=True)
        return repo, config_path, tempdir

    def scan(self, files: dict[str, str], **config_overrides: object):
        repo, config_path, tempdir = self.make_repo(files, **config_overrides)
        self.addCleanup(tempdir.cleanup)
        return self.scanner.scan_repository(repo, config_path)

    def test_forbidden_enterprise_term_reports_pattern_and_location(self) -> None:
        result = self.scan({"README.md": "Public Enterprise launch copy.\n"})

        self.assertEqual([], result.errors)
        self.assertEqual(1, len(result.violations))
        violation = result.violations[0]
        self.assertEqual("README.md", violation.path)
        self.assertEqual(1, violation.line)
        self.assertEqual("enterprise_word", violation.pattern_id)
        self.assertEqual("Enterprise", violation.match)

    def test_stale_compose_filename_and_raw_ogc_url_fail(self) -> None:
        result = self.scan(
            {
                "README.md": (
                    "Start with geolens.yml.\n"
                    "Then browse http://localhost:8001/collections.\n"
                )
            }
        )

        self.assertEqual([], result.errors)
        self.assertEqual(
            ["raw_ogc_collections_url", "stale_geolens_yml"],
            sorted(v.pattern_id for v in result.violations),
        )

    def test_weak_admin_default_matches_variants_not_admin_paths(self) -> None:
        result = self.scan(
            {
                "README.md": (
                    "Do not tell users to use admin slash admin.\n"
                    "Do not document `admin` / `admin` credentials.\n"
                    "Do not document admin:admin credentials.\n"
                    "Do not document --username admin --password admin commands.\n"
                    "Do not document --password=admin commands.\n"
                    "Do not document --password=\"admin\" commands.\n"
                    "Do not document GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin installs.\n"
                    "Do not document GEOLENS_ADMIN_PASSWORD=\"admin\" installs.\n"
                    "| `--password` | `admin` | Admin password |\n"
                    "| GEOLENS_ADMIN_PASSWORD | admin |\n"
                ),
                "frontend/src/pages/admin/AdminSharedMapsPage.tsx": "export const path = true;\n",
            },
            include_globs=["*.md", "frontend/src/**/*.tsx"],
        )

        self.assertEqual([], result.errors)
        self.assertEqual(
            [
                "weak_admin_default",
                "weak_admin_default",
                "weak_admin_default",
                "weak_admin_default",
                "weak_admin_default",
                "weak_admin_default",
                "weak_admin_default",
                "weak_admin_default",
                "weak_admin_default",
                "weak_admin_default",
            ],
            [v.pattern_id for v in result.violations],
        )

    def test_commercial_overlay_and_ogc_compliant_variants_fail(self) -> None:
        result = self.scan(
            {
                "README.md": (
                    "Do not discuss commercial overlays.\n"
                    "Do not claim this is OGC-compliant.\n"
                )
            }
        )

        self.assertEqual([], result.errors)
        self.assertEqual(
            ["commercial_overlay_wording", "ogc_compliant_claim"],
            sorted(v.pattern_id for v in result.violations),
        )

    def test_tenancy_and_cloud_edition_variants_fail(self) -> None:
        result = self.scan(
            {
                "README.md": (
                    "Do not discuss multitenant launch copy.\n"
                    "Do not discuss cloud-edition launch copy.\n"
                )
            }
        )

        self.assertEqual([], result.errors)
        self.assertEqual(
            ["cloud_edition_wording", "multi_tenant_wording"],
            sorted(v.pattern_id for v in result.violations),
        )

    def test_recursive_double_star_globs_match_nested_public_docs(self) -> None:
        result = self.scan(
            {
                "backend/app/standards/dcat/README.md": "Public Enterprise launch copy.\n",
                "examples/manifests/first-catalog/README.md": "SaaS launch copy.\n",
            }
        )

        self.assertEqual([], result.errors)
        self.assertEqual(
            [
                ("backend/app/standards/dcat/README.md", "enterprise_word"),
                ("examples/manifests/first-catalog/README.md", "saas_wording"),
            ],
            [(violation.path, violation.pattern_id) for violation in result.violations],
        )

    def test_exact_allowlist_suppresses_observed_hit(self) -> None:
        result = self.scan(
            {"README.md": "Enterprise appears only in a safe technical fixture.\n"},
            allowlist=[
                {
                    "id": "safe-fixture-enterprise",
                    "path": "README.md",
                    "pattern_id": "enterprise_word",
                    "match": "Enterprise",
                    "reason": "Test fixture demonstrates exact-match allowlisting.",
                }
            ],
        )

        self.assertEqual([], result.errors)
        self.assertEqual([], result.violations)

    def test_allowlist_entry_suppresses_only_one_identical_hit(self) -> None:
        result = self.scan(
            {"README.md": "Enterprise appears here. Enterprise appears again.\n"},
            allowlist=[
                {
                    "id": "safe-fixture-enterprise",
                    "path": "README.md",
                    "pattern_id": "enterprise_word",
                    "match": "Enterprise",
                    "reason": "Test fixture demonstrates exact-match allowlisting.",
                }
            ],
        )

        self.assertEqual([], result.errors)
        self.assertEqual(1, len(result.violations))
        self.assertEqual("enterprise_word", result.violations[0].pattern_id)

    def test_stale_allowlist_entry_fails(self) -> None:
        result = self.scan(
            {"README.md": "No launch-sensitive language here.\n"},
            allowlist=[
                {
                    "id": "stale-enterprise",
                    "path": "README.md",
                    "pattern_id": "enterprise_word",
                    "match": "Enterprise",
                    "reason": "This should fail once the exact hit disappears.",
                }
            ],
        )

        self.assertTrue(any("stale allowlist" in error for error in result.errors))
        self.assertEqual([], result.violations)

    def test_wildcard_and_pattern_only_allowlists_fail(self) -> None:
        result = self.scan(
            {"README.md": "Enterprise appears here.\n"},
            allowlist=[
                {
                    "id": "wildcard-path",
                    "path": "*.md",
                    "pattern_id": "enterprise_word",
                    "match": "Enterprise",
                    "reason": "Wildcards must not be accepted.",
                },
                {
                    "id": "pattern-only",
                    "pattern_id": "enterprise_word",
                    "reason": "Missing path and match must fail.",
                },
            ],
        )

        self.assertTrue(any("wildcard" in error for error in result.errors))
        self.assertTrue(any("missing required field" in error for error in result.errors))

    def test_cloud_optimized_geotiff_is_safe_technical_wording(self) -> None:
        result = self.scan({"README.md": "Raster ingest supports Cloud-Optimized GeoTIFF files.\n"})

        self.assertEqual([], result.errors)
        self.assertEqual([], result.violations)

    def test_default_candidate_list_includes_frontend_docs_and_excludes_agents(self) -> None:
        config = self.scanner.load_config(CONFIG)
        files = self.scanner.collect_candidate_files(ROOT, config)

        self.assertIn("frontend/docs/i18n.md", files)
        self.assertIn("backend/app/standards/dcat/README.md", files)
        self.assertIn("examples/manifests/first-catalog/README.md", files)
        self.assertNotIn("AGENTS.md", files)
        self.assertIn("AGENTS.md", config.exclude_rationales)
        self.assertIn("local execution guidance", config.exclude_rationales["AGENTS.md"])


if __name__ == "__main__":
    unittest.main()
