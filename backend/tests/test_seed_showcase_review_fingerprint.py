"""The seeder accepts review reasons only for the service conversions it prints."""

from __future__ import annotations

import importlib.util
from types import SimpleNamespace

import pytest

from tests.repo_paths import repo_root

SCRIPT_PATH = repo_root(__file__) / "scripts" / "seed-showcase.py"


def _load_seeder():
    spec = importlib.util.spec_from_file_location("seed_showcase_review", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seeder = _load_seeder()


class _Client:
    """Records the commit body and answers the preview with a fixed payload."""

    def __init__(self, preview: dict):
        self.preview = preview
        self.commit_bodies: list[dict] = []

    def post(self, url, **kw):
        if url.endswith("/commit"):
            self.commit_bodies.append(kw["json"])
            payload = {}
        elif url.endswith("/preview"):
            payload = self.preview
        else:
            payload = {"job_id": "job-1"}
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)


def _api(preview: dict):
    api = seeder.Api.__new__(seeder.Api)
    api.base = "http://x"
    api.h = {}
    api.client = _Client(preview)
    api.poll = lambda *_a, **_k: {}
    return api


def test_reupload_geojson_leaves_reviewable_replacements_held():
    api = _api({"review_fingerprint": "fp-1"})
    api.reupload_geojson("ds-1", "a.geojson", b"{}")
    assert api.client.commit_bodies == [{}]


@pytest.mark.parametrize(
    ("staged_extra", "expected"),
    [
        ({"review_fingerprint": "fp-2"}, {"review_fingerprint": "fp-2"}),
        ({}, {}),
    ],
)
def test_convert_to_service_echoes_the_preview_fingerprint(
    monkeypatch, staged_extra, expected
):
    api = _api({})
    api.dataset_origin = lambda _id: "file"
    api.service_reupload_preview = lambda _id, _body: {
        "job_id": "job-2",
        "schema_diff": {},
        **staged_extra,
    }
    monkeypatch.setattr(seeder, "service_binding_body", lambda *_a: {})
    monkeypatch.setattr(seeder, "_print_schema_diff", lambda _d: None)
    assert seeder.convert_to_service(api, "ds-2", "http://svc", "label") is True
    assert api.client.commit_bodies == [expected]
