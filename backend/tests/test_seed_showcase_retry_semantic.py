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
    def __init__(
        self, ai: dict, source: str | None, openai: bool, backfill_status: int
    ):
        self.ai = ai
        self.source = source
        self.openai = openai
        self.backfill_status = backfill_status
        self.sent: list[tuple[str, str, dict | None]] = []

    def _resp(self, payload, status=200):
        def raise_for_status():
            if status >= 400:
                raise httpx.HTTPStatusError(
                    "bad",
                    request=httpx.Request("POST", "http://x"),
                    response=httpx.Response(status),
                )

        return SimpleNamespace(
            status_code=status, raise_for_status=raise_for_status, json=lambda: payload
        )

    def get(self, url, **_kw):
        self.sent.append(("GET", url, None))
        if url.endswith("/api/admin/ai-status/"):
            return self._resp(self.ai)
        if url.endswith("/api/settings/api-key-status/"):
            return self._resp(
                {"anthropic_configured": True, "openai_configured": self.openai}
            )
        items = (
            []
            if self.source is None
            else [{"key": "semantic_search_enabled", "source": self.source}]
        )
        return self._resp({"tabs": {"ai": items}})

    def put(self, url, **kw):
        self.sent.append(("PUT", url, kw["json"]))
        return self._resp({})

    def post(self, url, **_kw):
        self.sent.append(("POST", url, None))
        return self._resp({"job_id": "job-1"}, self.backfill_status)


READY = {"enabled": True, "configured": False, "semantic_search_enabled": False}


def _api(
    ai: dict,
    source: str | None = "default",
    openai: bool = True,
    backfill_status: int = 200,
    job: dict | None = None,
    source_after_poll: str | None = None,
):
    polled: list[str] = []
    client = FakeClient(ai, source, openai, backfill_status)

    def poll(job_id, timeout=300):
        polled.append(job_id)
        if source_after_poll is not None:
            client.source = source_after_poll
        return job or {}

    api = SimpleNamespace(base="http://x", h={}, client=client, poll=poll)
    return api, polled


def _writes(api) -> list:
    return [m for m in api.client.sent if m[0] != "GET"]


BACKFILL = ("POST", "http://x/api/admin/backfill-embeddings/", None)
ENABLE = (
    "PUT",
    "http://x/api/settings/",
    {"settings": {"semantic_search_enabled": True}},
)


def test_embedding_key_without_a_chat_provider_backfills_then_enables():
    api, polled = _api(READY)
    seeder.enable_semantic_search(api)
    assert _writes(api) == [BACKFILL, ENABLE]
    assert polled == ["job-1"]


def test_anthropic_only_stack_changes_nothing(capsys):
    api, polled = _api({**READY, "configured": True}, openai=False)
    seeder.enable_semantic_search(api)
    assert _writes(api) == [] and polled == []
    assert "stays off" in capsys.readouterr().out


def test_ai_disabled_changes_nothing():
    api, _ = _api({**READY, "enabled": False})
    seeder.enable_semantic_search(api)
    assert _writes(api) == []


def test_failed_backfill_leaves_the_setting_off_and_a_rerun_submits_again():
    api, _ = _api(READY, backfill_status=503)
    with pytest.raises(httpx.HTTPStatusError):
        seeder.enable_semantic_search(api)
    assert _writes(api) == [BACKFILL]
    rerun, polled = _api(READY)
    seeder.enable_semantic_search(rerun)
    assert _writes(rerun) == [BACKFILL, ENABLE] and polled == ["job-1"]


def test_backfill_already_running_is_not_a_failure_and_changes_no_setting():
    api, polled = _api(READY, backfill_status=409)
    seeder.enable_semantic_search(api)
    assert _writes(api) == [BACKFILL] and polled == []


def test_partial_backfill_does_not_enable_search(capsys):
    api, _ = _api(READY, job={"rows_failed": 3})
    seeder.enable_semantic_search(api)
    assert _writes(api) == [BACKFILL]
    assert "3 record(s) failed" in capsys.readouterr().out


def test_an_override_saved_during_the_backfill_is_not_overwritten():
    api, _ = _api(READY, source_after_poll="overridden")
    seeder.enable_semantic_search(api)
    assert _writes(api) == [BACKFILL]


def test_setting_on_without_embeddings_backfills_without_touching_the_setting():
    api, polled = _api(
        {**READY, "semantic_search_enabled": True, "has_embeddings": False}
    )
    seeder.enable_semantic_search(api)
    assert _writes(api) == [BACKFILL] and polled == ["job-1"]


@pytest.mark.parametrize(
    ("ai", "source"),
    [
        ({**READY, "semantic_search_enabled": True, "has_embeddings": True}, "default"),
        (READY, "overridden"),
        (READY, "env_only"),
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
