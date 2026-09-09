"""Structural gate for #1946: markers reaching the published OpenAPI surface.

A Pydantic/FastAPI ``description=`` string is a string literal, not a
docstring, so backend/tests/finding_markers.py's comment/docstring walk never
reads it. This gate scans backend/openapi.json directly, the artifact those
descriptions actually reach.
"""

import json

from tests import finding_markers as fm


class TestPublishedSurface:
    """The gate over the real backend/openapi.json."""

    def test_the_real_spec_is_clean(self):
        problems = fm.check_openapi()
        assert not problems, "\n".join(problems)

    def test_scan_reaches_the_real_spec(self):
        spec = json.loads(fm.OPENAPI_PATH.read_text(encoding="utf-8"))
        assert fm.MIN_OPENAPI_DESCRIPTIONS > 0
        assert len(fm._openapi_descriptions(spec)) >= fm.MIN_OPENAPI_DESCRIPTIONS

    def test_collapsed_spec_fails_instead_of_passing_empty(self, tmp_path):
        empty = tmp_path / "openapi.json"
        empty.write_text("{}", encoding="utf-8")
        problems = fm.check_openapi(empty)
        assert problems

    def test_unreadable_spec_is_reported(self, tmp_path):
        bad = tmp_path / "openapi.json"
        bad.write_text("not json", encoding="utf-8")
        problems = fm.check_openapi(bad)
        assert problems

    def test_a_new_marker_fails_the_gate(self, tmp_path):
        spec_path = tmp_path / "openapi.json"
        spec_path.write_text(
            json.dumps({"description": "Bound is PERF-N16."}), encoding="utf-8"
        )
        problems = fm.check_openapi(spec_path)
        assert any("PERF-N16" in problem for problem in problems)


class TestDetector:
    """What the openapi.json scan reads, and what it exempts."""

    def test_a_bare_marker_in_a_description_fails(self):
        hits = fm.scan_openapi({"description": "Maximum rows returned (PERF-N16)."})
        assert [h.markers for h in hits] == [("PERF-N16",)]

    def test_an_issue_anchor_scopes_it(self):
        spec = {"description": "Maximum rows returned (PERF-N16, see #1234)."}
        assert not fm.scan_openapi(spec)

    def test_a_gh_anchor_scopes_itself(self):
        spec = {"description": "Delivered as a cookie instead (GH-1302)."}
        assert not fm.scan_openapi(spec)

    def test_adr_002_is_a_resolvable_citation(self):
        spec = {"description": "One refresh attempt (ADR-002 Decision 4)."}
        assert not fm.scan_openapi(spec)

    def test_shares_technical_vocabulary_with_the_source_scan(self):
        spec = {"description": "Digest as SHA-256, decoded as UTF-8."}
        assert not fm.scan_openapi(spec)

    def test_nested_paths_are_walked(self):
        spec = {
            "paths": {
                "/x": {"get": {"parameters": [{"description": "PERF-N16 bound"}]}}
            }
        }
        hits = fm.scan_openapi(spec)
        assert len(hits) == 1
        assert hits[0].module == "$.paths./x.get.parameters[0].description"

    def test_a_further_anchor_does_not_scope_it(self):
        spec = {"description": "Bound (PERF-N16).\n\nl2\nl3\nl4\nSee #1927."}
        hits = fm.scan_openapi(spec)
        assert [h.markers for h in hits] == [("PERF-N16",)]
