"""`geolens arcgis inventory` never lets the ArcGIS token or password out."""

from __future__ import annotations

import http.server
import json
import logging
import threading
from collections.abc import Iterator

import pytest

from geolens_cli import arcgis_inventory as inventory
from geolens_cli.main import app

from .arcgis_fake import (
    B1,
    C1,
    PORTAL,
    USER,
    FakePortal,
    item_data_path,
    load,
    portal_routes,
)

SECRET_TOKEN = "SENTINEL-token-7f3a9c-not-real"
SECRET_PASSWORD = "SENTINEL-password-b81e-not-real"
MINTED_TOKEN = "SENTINEL-minted-token-44d2-not-real"
SECRETS = (SECRET_TOKEN, SECRET_PASSWORD, MINTED_TOKEN)
HEADER = inventory.ESRI_AUTHORIZATION_HEADER.lower()


@pytest.fixture
def invoke(runner, monkeypatch, tmp_path, caplog):
    """Run the command with --verbose and --output-dir; return every output text."""
    for name in ("ARCGIS_TOKEN", "ARCGIS_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(inventory, "_sleep", lambda seconds: None)
    caplog.set_level(logging.DEBUG)

    def run(portal: FakePortal, *args: str, stdin: str | None = None, env=None):
        monkeypatch.setattr(inventory, "build_opener", lambda: portal)
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "--verbose",
                "arcgis",
                "inventory",
                "--portal-url",
                PORTAL,
                "--output-dir",
                str(out),
                *args,
            ],
            input=stdin,
            env=env,
        )
        texts = [result.stdout, result.stderr, caplog.text]
        texts += (
            [p.read_text() for p in sorted(out.rglob("*")) if p.is_file()]
            if out.exists()
            else []
        )
        if result.exception is not None and not isinstance(
            result.exception, SystemExit
        ):
            texts.append(repr(result.exception))
        return result, "\n".join(texts)

    return run


def _assert_no_secret(text: str) -> None:
    for secret in SECRETS:
        assert secret not in text


def _assert_token_only_in_header(portal: FakePortal, token: str) -> None:
    for seen in portal.seen:
        assert token not in seen.url
        if seen.path != "generateToken":
            assert seen.headers.get(HEADER) == f"Bearer {token}"


def test_success_path_keeps_the_token_in_the_header(invoke):
    """A clean run sends the token only as X-Esri-Authorization and prints none of it."""
    portal = FakePortal(portal_routes())
    result, texts = invoke(portal, "--token", SECRET_TOKEN)
    assert result.exit_code == 0, result.output
    _assert_no_secret(texts)
    _assert_token_only_in_header(portal, SECRET_TOKEN)
    assert all(SECRET_TOKEN not in seen.body for seen in portal.seen)


def test_token_from_env_and_stdin(invoke):
    """ARCGIS_TOKEN and --token-stdin feed the same header."""
    portal = FakePortal(portal_routes())
    result, texts = invoke(portal, env={"ARCGIS_TOKEN": SECRET_TOKEN})
    assert result.exit_code == 0, result.output
    _assert_token_only_in_header(portal, SECRET_TOKEN)
    portal = FakePortal(portal_routes())
    result, more = invoke(portal, "--token-stdin", stdin=SECRET_TOKEN + "\n")
    assert result.exit_code == 0, result.output
    _assert_token_only_in_header(portal, SECRET_TOKEN)
    _assert_no_secret(texts + more)


def test_portal_echoing_the_token_in_a_498_is_redacted(invoke):
    """A portal error message that quotes the token is printed without it."""
    echo = {"error": {"code": 498, "message": f"Invalid token {SECRET_TOKEN}"}}
    portal = FakePortal(portal_routes({"portals/self": echo}))
    result, texts = invoke(portal, "--token", SECRET_TOKEN)
    assert result.exit_code == 3
    assert "Invalid token [REDACTED]" in result.stderr
    _assert_no_secret(texts)


def test_mid_run_498_echo_is_redacted_in_the_partial_report(invoke):
    """The abort reason saved in the partial report is redacted too."""
    echo = {"error": {"code": 498, "message": f"token={SECRET_TOKEN} expired"}}
    portal = FakePortal(portal_routes({item_data_path(B1): echo}))
    result, texts = invoke(portal, "--token", SECRET_TOKEN)
    assert result.exit_code == 3
    assert "[REDACTED]" in texts
    _assert_no_secret(texts)


def test_item_error_echo_is_redacted_in_the_error_row(invoke):
    """An item-level error quoting the token lands in errors[] redacted."""
    echo = {"error": {"code": 403, "message": f"No access with {SECRET_TOKEN}"}}
    portal = FakePortal(portal_routes({item_data_path(C1): echo}))
    result, texts = invoke(portal, "--token", SECRET_TOKEN)
    assert result.exit_code == 0, result.output
    assert "No access with [REDACTED]" in texts
    _assert_no_secret(texts)


def test_network_error_quoting_the_token_is_redacted(invoke):
    """A transport error whose text holds the token is redacted."""
    import urllib.error

    error = urllib.error.URLError(f"proxy refused {SECRET_TOKEN}")
    portal = FakePortal(portal_routes({"portals/self": error}))
    result, texts = invoke(portal, "--token", SECRET_TOKEN)
    assert result.exit_code == 4
    _assert_no_secret(texts)


def test_unexpected_exception_text_is_redacted(invoke):
    """Even a bug's exception message can't print the token."""
    portal = FakePortal(
        portal_routes({"portals/self": RuntimeError(f"boom {SECRET_TOKEN}")})
    )
    result, texts = invoke(portal, "--token", SECRET_TOKEN)
    assert result.exit_code == 1
    assert "boom [REDACTED]" in result.stderr
    _assert_no_secret(texts)


def test_generate_token_sends_the_password_once_in_a_post_body(invoke, tmp_path):
    """--username posts the password to generateToken only, then uses the minted token as a header."""
    minted = {**load("generate_token_ok.json"), "token": MINTED_TOKEN}
    portal = FakePortal(portal_routes({"generateToken": minted}))
    result, texts = invoke(
        portal, "--username", USER, env={"ARCGIS_PASSWORD": SECRET_PASSWORD}
    )
    assert result.exit_code == 0, result.output
    _assert_no_secret(texts)
    sign_in = portal.requests_to("generateToken")
    assert len(sign_in) == 1
    assert sign_in[0].method == "POST"
    assert sign_in[0].params["password"] == SECRET_PASSWORD
    assert sign_in[0].params["client"] == "referer"
    assert sign_in[0].params["expiration"] == "60"
    assert SECRET_PASSWORD not in sign_in[0].url
    others = [s for s in portal.seen if s.path != "generateToken"]
    assert others and all(SECRET_PASSWORD not in s.url + s.body for s in others)
    _assert_token_only_in_header(portal, MINTED_TOKEN)
    report = json.loads((tmp_path / "out" / "arcgis-inventory.json").read_text())
    assert report["auth"] == {"mode": "generateToken", "user": USER}


def test_password_from_stdin(invoke):
    """--password-stdin reads the password without a prompt."""
    minted = {**load("generate_token_ok.json"), "token": MINTED_TOKEN}
    portal = FakePortal(portal_routes({"generateToken": minted}))
    result, texts = invoke(
        portal, "--username", USER, "--password-stdin", stdin=SECRET_PASSWORD + "\n"
    )
    assert result.exit_code == 0, result.output
    assert portal.requests_to("generateToken")[0].params["password"] == SECRET_PASSWORD
    _assert_no_secret(texts)


def test_failed_sign_in_is_not_retried_and_not_echoed(invoke):
    """A refused generateToken exits 3 after one attempt, without the password."""
    fail = load("generate_token_fail.json")
    fail["error"]["details"].append(f"password {SECRET_PASSWORD} rejected")
    portal = FakePortal(portal_routes({"generateToken": [(503, {}), fail]}))
    result, texts = invoke(
        portal, "--username", USER, env={"ARCGIS_PASSWORD": SECRET_PASSWORD}
    )
    assert result.exit_code == 5
    assert len(portal.requests_to("generateToken")) == 1
    portal = FakePortal(portal_routes({"generateToken": fail}))
    result, more = invoke(
        portal, "--username", USER, env={"ARCGIS_PASSWORD": SECRET_PASSWORD}
    )
    assert result.exit_code == 3
    assert len(portal.seen) == 1
    assert "SAML" in result.stderr
    _assert_no_secret(texts + more)


def test_token_with_control_characters_is_refused_unechoed(invoke):
    """A token that could split a header is refused without printing it."""
    bad = SECRET_TOKEN + "\r\nX-Injected: 1"
    portal = FakePortal(portal_routes())
    result, texts = invoke(portal, env={"ARCGIS_TOKEN": bad})
    assert result.exit_code == 2
    assert portal.seen == []
    _assert_no_secret(texts)


def test_pre_10_5_1_portal_gets_the_token_in_a_post_body_never_the_url(invoke):
    """A 499 despite the header switches to a POST form field, not a query string."""
    required = {"error": {"code": 499, "message": "Token Required"}}

    def self_info(seen):
        if seen.method == "GET":
            return required
        return load("portal_self.json")

    portal = FakePortal(portal_routes({"portals/self": self_info}))
    result, texts = invoke(portal, "--token", SECRET_TOKEN)
    assert result.exit_code == 0, result.output
    _assert_no_secret(texts)
    assert all(SECRET_TOKEN not in s.url for s in portal.seen)
    later = portal.seen[1:]
    assert later and all(
        s.method == "POST" and s.params["token"] == SECRET_TOKEN for s in later
    )


def test_stored_service_tokens_are_stripped_from_urls(invoke):
    """Tokens saved inside item or layer URLs never reach the report."""
    portal = FakePortal(portal_routes())
    result, texts = invoke(portal, "--token", SECRET_TOKEN, "--scope", "org")
    assert result.exit_code == 0, result.output
    assert "stored-in-item-url-not-a-real-token" not in texts
    assert "stored-in-web-map-not-a-real-token" not in texts
    assert "https://gis.example.gov/arcgis/rest/services/Roads/FeatureServer" in texts


class _RedirectingPortal(http.server.BaseHTTPRequestHandler):
    hits: list[tuple[str, dict[str, str]]] = []

    def do_GET(self) -> None:  # noqa: N802
        type(self).hits.append((self.path, dict(self.headers)))
        self.send_response(302)
        self.send_header("Location", "/elsewhere/sharing/rest/portals/self?f=json")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args: object) -> None:
        return None


@pytest.fixture
def redirecting_portal() -> Iterator[str]:
    _RedirectingPortal.hits = []
    server = http.server.HTTPServer(("127.0.0.1", 0), _RedirectingPortal)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/portal"
    finally:
        server.shutdown()
        server.server_close()


def test_redirects_are_refused_with_the_real_opener(
    runner, monkeypatch, redirecting_portal
):
    """The shipped opener never follows a redirect, so the header can't travel."""
    monkeypatch.delenv("ARCGIS_TOKEN", raising=False)
    monkeypatch.setenv("NO_PROXY", "*")
    result = runner.invoke(
        app,
        [
            "arcgis",
            "inventory",
            "--portal-url",
            redirecting_portal,
            "--allow-insecure-http",
            "--token",
            SECRET_TOKEN,
        ],
    )
    assert result.exit_code == 2
    assert "redirect" in result.stderr
    assert [path.split("?")[0] for path, _ in _RedirectingPortal.hits] == [
        "/portal/sharing/rest/portals/self"
    ]
    _assert_no_secret(result.stdout + result.stderr)


def _referer_enforcing(routes: dict) -> dict:
    """Routes that answer 498 unless the Referer matches the token's binding."""

    def guard(reply):
        def handler(seen):
            if seen.headers.get("referer") != PORTAL:
                return {"error": {"code": 498, "message": "Invalid token."}}
            return reply(seen) if callable(reply) else reply

        return handler

    return {
        path: reply if path == "generateToken" else guard(reply)
        for path, reply in routes.items()
    }


def test_generated_token_is_used_with_the_referer_it_was_bound_to(invoke):
    """A portal enforcing the referer binding accepts every request after sign-in."""
    minted = {**load("generate_token_ok.json"), "token": MINTED_TOKEN}
    portal = FakePortal(_referer_enforcing(portal_routes({"generateToken": minted})))
    result, texts = invoke(
        portal, "--username", USER, env={"ARCGIS_PASSWORD": SECRET_PASSWORD}
    )
    assert result.exit_code == 0, result.output
    assert portal.requests_to("generateToken")[0].params["referer"] == PORTAL
    assert all(
        s.headers.get("referer") == PORTAL
        for s in portal.seen
        if s.path != "generateToken"
    )
    _assert_no_secret(texts)


def test_generated_token_fallback_post_carries_the_referer(invoke):
    """The pre-10.5.1 form-field fallback keeps the Referer for a generated token."""
    minted = {**load("generate_token_ok.json"), "token": MINTED_TOKEN}

    def self_info(seen):
        if seen.method == "GET":
            return {"error": {"code": 499, "message": "Token Required"}}
        return load("portal_self.json")

    routes = _referer_enforcing(
        portal_routes({"generateToken": minted, "portals/self": self_info})
    )
    portal = FakePortal(routes)
    result, _ = invoke(
        portal, "--username", USER, env={"ARCGIS_PASSWORD": SECRET_PASSWORD}
    )
    assert result.exit_code == 0, result.output
    posts = [s for s in portal.seen if s.method == "POST" and s.path != "generateToken"]
    assert posts and all(s.headers.get("referer") == PORTAL for s in posts)


def test_supplied_token_sends_no_referer(invoke):
    """A token the user brings is sent without a Referer, as before."""
    portal = FakePortal(portal_routes())
    result, _ = invoke(portal, "--token", SECRET_TOKEN)
    assert result.exit_code == 0, result.output
    assert all("referer" not in s.headers for s in portal.seen)


def test_token_crossing_the_message_cut_is_redacted(invoke):
    """A token straddling the 500-character message limit leaves no prefix behind."""
    echo = {"error": {"code": 498, "message": "a" * 490 + SECRET_TOKEN}}
    portal = FakePortal(portal_routes({"portals/self": echo}))
    result, texts = invoke(portal, "--token", SECRET_TOKEN)
    assert result.exit_code == 3
    assert SECRET_TOKEN[:10] not in texts
    _assert_no_secret(texts)


def test_password_crossing_the_message_cut_is_redacted(invoke):
    """A password echoed across the message limit by a failed sign-in leaves no prefix behind."""
    fail = load("generate_token_fail.json")
    fail["error"]["details"] = ["b" * 464 + SECRET_PASSWORD]
    portal = FakePortal(portal_routes({"generateToken": fail}))
    result, texts = invoke(
        portal, "--username", USER, env={"ARCGIS_PASSWORD": SECRET_PASSWORD}
    )
    assert result.exit_code == 3
    assert SECRET_PASSWORD[:10] not in texts
    _assert_no_secret(texts)
