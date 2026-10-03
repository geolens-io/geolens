"""The showcase seeder retries transient downloads and enables semantic search."""

from __future__ import annotations

import importlib.util
from types import SimpleNamespace

import httpx
import pytest

from tests.repo_paths import repo_root

SCRIPT_PATH = repo_root(__file__) / "scripts" / "seed-showcase.py"


def _load_seeder():
    spec = importlib.util.spec_from_file_location("seed_showcase_retry", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seeder = _load_seeder()


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(seeder.time, "sleep", lambda _s: None)


def _response(status: int = 200, body: bytes = b"ok") -> httpx.Response:
    return httpx.Response(
        status, content=body, request=httpx.Request("GET", "https://x")
    )


def _scripted_get(monkeypatch, outcomes: list) -> list:
    calls: list = []

    def fake_get(url, **_kw):
        calls.append(url)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(seeder.httpx, "get", fake_get)
    return calls


def test_fetch_retries_a_timeout_then_succeeds(monkeypatch):
    calls = _scripted_get(
        monkeypatch,
        [httpx.ConnectTimeout("slow"), httpx.ConnectError("down"), _response()],
    )
    assert seeder.fetch("https://x") == b"ok"
    assert len(calls) == 3


def test_fetch_gives_up_after_the_last_attempt(monkeypatch):
    calls = _scripted_get(
        monkeypatch, [httpx.ReadTimeout("slow")] * seeder.FETCH_ATTEMPTS
    )
    with pytest.raises(httpx.ReadTimeout):
        seeder.fetch("https://x")
    assert len(calls) == seeder.FETCH_ATTEMPTS


def test_fetch_does_not_retry_an_http_error_status(monkeypatch):
    calls = _scripted_get(monkeypatch, [_response(404), _response()])
    with pytest.raises(httpx.HTTPStatusError):
        seeder.fetch("https://x")
    assert len(calls) == 1


class FakeClient:
    def __init__(self, ai: dict, source: str | None):
        self.ai = ai
        self.source = source
        self.sent: list[tuple[str, str, dict | None]] = []

    def _ok(self, payload):
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)

    def get(self, url, **_kw):
        self.sent.append(("GET", url, None))
        if url.endswith("/api/admin/ai-status/"):
            return self._ok(self.ai)
        items = (
            []
            if self.source is None
            else [{"key": "semantic_search_enabled", "source": self.source}]
        )
        return self._ok({"tabs": {"ai": items}})

    def put(self, url, **kw):
        self.sent.append(("PUT", url, kw["json"]))
        return self._ok({})

    def post(self, url, **_kw):
        self.sent.append(("POST", url, None))
        return self._ok({"job_id": "job-1"})


def _api(ai: dict, source: str | None = "default"):
    polled: list[str] = []
    api = SimpleNamespace(
        base="http://x",
        h={},
        client=FakeClient(ai, source),
        poll=lambda job_id, timeout=300: polled.append(job_id),
    )
    return api, polled


def _writes(api) -> list:
    return [m for m in api.client.sent if m[0] != "GET"]


def test_semantic_enabled_and_backfilled_when_configured_and_unset():
    api, polled = _api({"configured": True, "semantic_search_enabled": False})
    seeder.enable_semantic_search(api)
    assert _writes(api) == [
        (
            "PUT",
            "http://x/api/settings/",
            {"settings": {"semantic_search_enabled": True}},
        ),
        ("POST", "http://x/api/admin/backfill-embeddings/", None),
    ]
    assert polled == ["job-1"]


def test_semantic_stays_off_without_a_provider(capsys):
    api, polled = _api({"configured": False, "semantic_search_enabled": False})
    seeder.enable_semantic_search(api)
    assert _writes(api) == [] and polled == []
    assert "stays off" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("ai", "source"),
    [
        ({"configured": True, "semantic_search_enabled": True}, "default"),
        ({"configured": True, "semantic_search_enabled": False}, "overridden"),
        ({"configured": True, "semantic_search_enabled": False}, "env_only"),
    ],
)
def test_semantic_left_alone_when_already_set(ai, source):
    api, polled = _api(ai, source)
    seeder.enable_semantic_search(api)
    assert _writes(api) == [] and polled == []


def _main_with_failed_builder(monkeypatch, argv: list[str], builder=None):
    calls = {"semantic": 0}

    class FakeApi:
        @classmethod
        def login(cls, *_a):
            return cls()

    def boom(api, force=False, force_pinned=False):
        raise RuntimeError("upstream down")

    for name in (
        "enrich_showcase_metadata",
        "apply_globe_projection",
        "apply_showcase_styling",
    ):
        monkeypatch.setattr(seeder, name, lambda _api: [])
    monkeypatch.setattr(seeder, "_rename_map_if_needed", lambda *_a: None)
    monkeypatch.setattr(seeder, "refresh_sentinel2_scenes", lambda _api: None)
    monkeypatch.setattr(seeder, "_backfill_thumbnails", lambda *_a: None)
    monkeypatch.setattr(seeder, "_print_pinned_summary", lambda *_a: None)
    monkeypatch.setattr(
        seeder,
        "enable_semantic_search",
        lambda _api: calls.__setitem__("semantic", calls["semantic"] + 1),
    )
    monkeypatch.setattr(seeder, "Api", FakeApi)
    monkeypatch.setattr(seeder, "build_meteorites", builder or boom)
    monkeypatch.setattr(seeder, "run_maintenance_mode", lambda *_a: None)
    monkeypatch.setattr("sys.argv", ["seed", "--password", "p", *argv])
    return seeder.main(), calls


def test_a_failed_builder_prints_its_rerun_line(monkeypatch, capsys):
    rc, calls = _main_with_failed_builder(monkeypatch, ["--only", "meteorites"])
    assert rc == 1
    assert "--only meteorites" in capsys.readouterr().err
    assert calls["semantic"] == 0


def test_main_runs_the_semantic_step_unless_no_semantic(monkeypatch):
    def run(argv):
        rc, calls = _main_with_failed_builder(
            monkeypatch,
            ["--only", "meteorites", *argv],
            builder=lambda api, force=False, force_pinned=False: "map-id",
        )
        assert rc == 0
        return calls["semantic"]

    assert run([]) == 1
    assert run(["--no-semantic"]) == 0
