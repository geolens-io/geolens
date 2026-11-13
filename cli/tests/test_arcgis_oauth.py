"""Browser sign-in to an ArcGIS portal with OAuth (`--client-id`), offline."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest
from keyring.errors import KeyringError

from geolens_cli import arcgis_inventory as inventory
from geolens_cli import auth as _auth
from geolens_cli import config as _config
from geolens_cli import arcgis_migrate_session as session
from geolens_cli import arcgis_oauth as oauth
from geolens_cli import arcgis_portal
from geolens_cli.main import app

from .arcgis_fake import PORTAL, USER, FakePortal, load, portal_routes
from .test_arcgis_inventory_redaction import _expiring

CLIENT_ID = "geolensTestApp01"
ACCOUNT = ("geolens", f"arcgis-oauth:{CLIENT_ID}@{PORTAL}")
CODE = "SENTINEL-code-31c7-not-real"
ACCESS = "SENTINEL-access-0d5e-not-real"
ACCESS_2 = "SENTINEL-access-2-8f1a-not-real"
REFRESH = "SENTINEL-refresh-a64b-not-real"
STORED = "SENTINEL-stored-refresh-5e90-not-real"
ROTATED = "SENTINEL-rotated"
HEADER = arcgis_portal.ESRI_AUTHORIZATION_HEADER.lower()
NOW = 1_800_000_000.0
LIFETIME = 1209599
INVALID_GRANT = {
    "error": {
        "code": 400,
        "error": "invalid_grant",
        "error_description": "Invalid refresh_token",
        "message": "Invalid refresh_token",
        "details": [],
    }
}
INVALIDATED = {
    "error": {
        "code": 498,
        "error": "invalid_grant",
        "error_description": "invalidated refresh_token",
        "message": "invalidated refresh_token",
        "details": [],
    }
}
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Browser:
    """Stands in for the user's browser: after the "sign-in" it follows the
    portal's redirect to the loopback listener with *reply* as the query
    (``state`` copied from the authorize link unless *reply* sets it)."""

    def __init__(self, **reply: str | None) -> None:
        self.reply = {"code": CODE, **reply}
        self.urls: list[str] = []
        self.status: int | None = None
        self._threads: list[threading.Thread] = []

    @property
    def params(self) -> dict[str, str]:
        return dict(parse_qsl(urlsplit(self.urls[-1]).query))

    def __call__(self, url: str) -> bool:
        self.urls.append(url)
        query = {"state": self.params["state"], **self.reply}
        target = (
            self.params["redirect_uri"]
            + "?"
            + urlencode({k: v for k, v in query.items() if v is not None})
        )
        thread = threading.Thread(target=self._follow, args=(target,), daemon=True)
        thread.start()
        self._threads.append(thread)
        return True

    def _follow(self, target: str) -> None:
        try:
            with _DIRECT.open(target, timeout=10) as response:
                self.status = response.status
        except urllib.error.HTTPError as exc:
            self.status = exc.code

    def join(self) -> None:
        for thread in self._threads:
            thread.join(10)


def _never_opened(url: str) -> bool:
    raise AssertionError("the browser must not open")


class TokenEndpoint:
    """``/sharing/rest/oauth2/token``: issues ACCESS and REFRESH for CODE,
    ``ACCESS_2`` onwards for a refresh token in *valid*, and for an exchange
    a new refresh token living *lifetime* seconds that invalidates the old
    one, unless *exchange* gives the reply. An exchange whose redirect URI
    is not *redirect_uri*, when given, is refused."""

    def __init__(
        self,
        valid: tuple[str, ...] = (REFRESH,),
        *,
        exchange: Any = None,
        lifetime: int = LIFETIME,
        redirect_uri: str | None = None,
    ) -> None:
        self.redirect_uri = redirect_uri
        self.valid = set(valid)
        self.invalidated: set[str] = set()
        self.exchange = exchange
        self.lifetime = lifetime
        self.rotated: list[str] = []
        self.grants: list[dict[str, str]] = []
        self.users: dict[str, str] = {}
        self._issued = 0

    def __call__(self, seen) -> Any:
        params = seen.params
        self.grants.append(params)
        assert seen.method == "POST"
        assert HEADER not in seen.headers
        if params["grant_type"] == "authorization_code":
            if params["code"] != CODE:
                return {"error": {"code": 400, "message": "Invalid code"}}
            return {
                "access_token": ACCESS,
                "expires_in": 1800,
                "refresh_token": REFRESH,
                "refresh_token_expires_in": LIFETIME,
                "username": USER,
            }
        token = params["refresh_token"]
        if params["grant_type"] == "exchange_refresh_token":
            if self.exchange:
                return self.exchange
            if self.redirect_uri and params["redirect_uri"] != self.redirect_uri:
                return {"error": {"code": 400, "message": "Invalid redirect_uri"}}
        if token in self.invalidated:
            return INVALIDATED
        if token not in self.valid:
            return INVALID_GRANT
        answer = {
            "access_token": self._access(),
            "expires_in": 1800,
            "username": self.users.get(token, USER),
        }
        if params["grant_type"] == "exchange_refresh_token":
            assert params["redirect_uri"]
            answer["refresh_token"] = self.rotate(token)
            answer["refresh_token_expires_in"] = self.lifetime
        return answer

    def rotate(self, token: str) -> str:
        """What a winning exchange does: *token* is replaced by a new one."""
        self.valid.discard(token)
        self.invalidated.add(token)
        self.rotated.append(f"{ROTATED}-{len(self.rotated) + 1}-not-real")
        self.valid.add(self.rotated[-1])
        return self.rotated[-1]

    def _access(self) -> str:
        self._issued += 1
        return ACCESS_2 if self._issued == 1 else f"{ACCESS_2}-{self._issued}"

    def kinds(self) -> list[str]:
        return [g["grant_type"] for g in self.grants]


def _value(
    token: str,
    age: float = 3600,
    lifetime: float = LIFETIME,
    redirect_uri: str | None = None,
) -> str:
    """A stored sign-in issued *age* seconds before NOW."""
    issued = NOW - age
    return json.dumps(
        {
            "refresh_token": token,
            "issued_at": issued,
            "expires_at": issued + lifetime,
            "redirect_uri": redirect_uri,
        }
    )


@pytest.fixture(autouse=True)
def wall(monkeypatch, tmp_xdg_home) -> list[float]:
    """The wall clock the sign-in reads, at NOW until a test moves it."""
    now = [NOW]
    monkeypatch.setattr(oauth, "_now", lambda: now[0])
    monkeypatch.setattr(oauth, "_LOCK_POLL", 0.01)
    return now


@pytest.fixture
def invoke(runner, monkeypatch, tmp_path, caplog, mock_keyring, tmp_xdg_home):
    """Run `arcgis inventory --client-id` against *portal* with *browser*."""
    for name in ("ARCGIS_TOKEN", "ARCGIS_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(inventory, "_sleep", lambda seconds: None)
    caplog.set_level(logging.DEBUG)

    def run(portal: FakePortal, browser, *args: str):
        monkeypatch.setattr(inventory, "build_opener", lambda: portal)
        monkeypatch.setattr("webbrowser.open", browser)
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
        )
        texts = [result.stdout, result.stderr, caplog.text]
        if out.exists():
            texts += [p.read_text() for p in sorted(out.rglob("*")) if p.is_file()]
        if result.exception is not None and not isinstance(
            result.exception, SystemExit
        ):
            texts.append(repr(result.exception))
        if isinstance(browser, Browser):
            browser.join()
        return result, "\n".join(texts), out

    return run


def _assert_no_secret(text: str, *extra: str) -> None:
    for secret in (CODE, ACCESS, ACCESS_2, REFRESH, STORED, ROTATED, *extra):
        assert secret not in text


def _client(
    portal: FakePortal, redact: arcgis_portal.Redactor
) -> arcgis_portal.PortalClient:
    return arcgis_portal.PortalClient(
        PORTAL, opener=portal, redact=redact, sleep=lambda seconds: None
    )


def test_pkce_pair_is_a_fresh_s256_pair():
    verifier, challenge = oauth.pkce_pair()
    assert re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    assert challenge == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert oauth.pkce_pair()[0] != verifier


def test_browser_sign_in_sends_pkce_and_stores_the_refresh_token(invoke, mock_keyring):
    endpoint = TokenEndpoint()
    portal = FakePortal(portal_routes({"oauth2/token": endpoint}))
    browser = Browser()

    result, texts, out = invoke(portal, browser, "--client-id", CLIENT_ID)

    assert result.exit_code == 0, result.output
    link = browser.params
    assert urlsplit(browser.urls[0]).path == "/sharing/rest/oauth2/authorize"
    assert link["client_id"] == CLIENT_ID
    assert link["response_type"] == "code"
    assert link["code_challenge_method"] == "S256"
    assert re.fullmatch(r"http://127\.0\.0\.1:\d+/callback", link["redirect_uri"])
    assert browser.status == 200
    # The link is printed for a shell with no browser.
    assert browser.urls[0] in result.stderr
    [grant] = endpoint.grants
    assert grant["grant_type"] == "authorization_code"
    assert grant["redirect_uri"] == link["redirect_uri"]
    verifier = grant["code_verifier"]
    digest = hashlib.sha256(verifier.encode()).digest()
    assert (
        link["code_challenge"] == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    )
    assert verifier not in browser.urls[0]
    assert json.loads(mock_keyring[ACCOUNT]) == {
        "refresh_token": REFRESH,
        "issued_at": NOW,
        "expires_at": NOW + LIFETIME,
        "redirect_uri": link["redirect_uri"],
    }
    reads = [s for s in portal.seen if s.path != "oauth2/token"]
    assert reads and all(s.headers.get(HEADER) == f"Bearer {ACCESS}" for s in reads)
    report = json.loads((out / "arcgis-inventory.json").read_text())
    assert report["auth"]["mode"] == "oauth"
    _assert_no_secret(texts, verifier)


def test_a_second_run_signs_in_with_the_stored_refresh_token(invoke, mock_keyring):
    mock_keyring[ACCOUNT] = _value(STORED)
    endpoint = TokenEndpoint(valid=(STORED,))
    portal = FakePortal(portal_routes({"oauth2/token": endpoint}))

    result, texts, _ = invoke(portal, _never_opened, "--client-id", CLIENT_ID)

    assert result.exit_code == 0, result.output
    assert endpoint.kinds() == ["refresh_token"]
    assert endpoint.grants[0]["client_id"] == CLIENT_ID
    assert mock_keyring[ACCOUNT] == _value(STORED)
    reads = [s for s in portal.seen if s.path != "oauth2/token"]
    assert all(s.headers.get(HEADER) == f"Bearer {ACCESS_2}" for s in reads)
    _assert_no_secret(texts)


def test_a_refused_refresh_token_goes_back_to_the_browser(invoke, mock_keyring):
    mock_keyring[ACCOUNT] = _value(STORED)
    endpoint = TokenEndpoint(valid=())
    portal = FakePortal(portal_routes({"oauth2/token": endpoint}))
    browser = Browser()

    result, texts, _ = invoke(portal, browser, "--client-id", CLIENT_ID)

    assert result.exit_code == 0, result.output
    assert endpoint.kinds() == ["refresh_token", "authorization_code"]
    assert len(browser.urls) == 1
    assert json.loads(mock_keyring[ACCOUNT])["refresh_token"] == REFRESH
    _assert_no_secret(texts)


def test_a_token_that_expires_mid_inventory_is_refreshed(invoke, mock_keyring):
    endpoint = TokenEndpoint()
    routes = portal_routes({"oauth2/token": endpoint})
    portal = FakePortal(_expiring(routes, ACCESS, uses=5))

    result, texts, out = invoke(
        portal, Browser(), "--client-id", CLIENT_ID, "--concurrency", "4"
    )

    assert result.exit_code == 0, result.output
    assert endpoint.kinds() == ["authorization_code", "refresh_token"]
    assert endpoint.grants[1]["refresh_token"] == REFRESH
    report = json.loads((out / "arcgis-inventory.json").read_text())
    assert report["complete"] is True
    sent = [s.headers.get(HEADER) for s in portal.seen]
    assert f"Bearer {ACCESS_2}" in sent
    _assert_no_secret(texts)


def test_a_long_migration_renews_the_oauth_token_before_it_lapses(
    mock_keyring, tmp_xdg_home
):
    """The run's GeoLens credential is replaced before the 30-minute OAuth
    token lapses, not on the 60-minute schedule of a password token."""
    mock_keyring[ACCOUNT] = _value(STORED)
    endpoint = TokenEndpoint(valid=(STORED,))
    redact = arcgis_portal.Redactor()
    client = _client(FakePortal({"oauth2/token": endpoint}), redact)
    oauth.sign_in(client, CLIENT_ID, redact, open_browser=_never_opened)
    now = [0.0]
    auth = session.PortalAuth(client, renewable=True, clock=lambda: now[0])

    now[0] = 27 * 60
    assert auth.service_auth().token == ACCESS_2
    now[0] = 29 * 60
    assert auth.service_auth().token == f"{ACCESS_2}-2"
    assert endpoint.kinds() == ["refresh_token", "refresh_token"]
    assert redact(f"{ACCESS_2}-2 {STORED}") == "[REDACTED] [REDACTED]"


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        ({"state": "forged"}, "state"),
        ({"state": None}, "state"),
        (
            {
                "code": None,
                "error": "access_denied",
                "error_description": "User denied",
            },
            "access_denied: User denied",
        ),
    ],
)
def test_a_refused_or_forged_callback_ends_the_sign_in(
    reply, message, mock_keyring, tmp_xdg_home
):
    endpoint = TokenEndpoint()
    redact = arcgis_portal.Redactor()
    client = _client(FakePortal({"oauth2/token": endpoint}), redact)
    browser = Browser(**reply)

    with pytest.raises(arcgis_portal.PortalError) as caught:
        oauth.sign_in(
            client, CLIENT_ID, redact, open_browser=browser, notify=lambda m: None
        )
    browser.join()

    assert caught.value.kind == "auth"
    assert message in str(caught.value)
    assert CODE not in str(caught.value)
    assert browser.status == 400
    assert endpoint.grants == []
    assert client.token is None
    assert ACCOUNT not in mock_keyring


def test_the_sign_in_times_out_and_frees_the_port(
    monkeypatch, mock_keyring, tmp_xdg_home
):
    monkeypatch.setattr(oauth, "SIGN_IN_TIMEOUT", 0.3)
    redact = arcgis_portal.Redactor()
    client = _client(FakePortal({}), redact)
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    opened: list[str] = []

    with pytest.raises(arcgis_portal.PortalError) as caught:
        oauth.sign_in(
            client,
            CLIENT_ID,
            redact,
            redirect_port=port,
            open_browser=opened.append,
            notify=lambda m: None,
        )

    assert caught.value.kind == "auth"
    assert "no sign-in arrived" in str(caught.value)
    assert dict(parse_qsl(urlsplit(opened[0]).query))["redirect_uri"] == (
        f"http://127.0.0.1:{port}/callback"
    )
    with socket.socket() as again:
        again.bind(("127.0.0.1", port))


def test_a_password_refusal_names_the_browser_sign_in(invoke, monkeypatch):
    monkeypatch.setenv("ARCGIS_PASSWORD", "SENTINEL-password-not-real")
    portal = FakePortal(
        portal_routes({"generateToken": load("generate_token_fail.json")})
    )

    result, _, _ = invoke(portal, _never_opened, "--username", USER)

    assert result.exit_code == 3
    assert "--client-id" in result.stderr


def test_client_id_with_another_credential_is_a_usage_error(invoke):
    portal = FakePortal(portal_routes())

    result, _, _ = invoke(
        portal, _never_opened, "--client-id", CLIENT_ID, "--token", "abc"
    )

    assert result.exit_code == 2
    assert "--client-id" in result.stderr
    assert portal.seen == []


@pytest.mark.parametrize(
    "reply",
    [
        (429, {}),
        {"error": {"code": 500, "message": "Internal server error"}},
        {"error": {"code": 503, "message": "Service unavailable"}},
    ],
)
def test_a_transient_failure_keeps_the_saved_sign_in(reply, mock_keyring, tmp_xdg_home):
    mock_keyring[ACCOUNT] = _value(STORED)
    redact = arcgis_portal.Redactor()
    portal = FakePortal({"oauth2/token": reply})
    client = _client(portal, redact)
    opened: list[str] = []

    with pytest.raises(arcgis_portal.PortalError) as caught:
        oauth.sign_in(client, CLIENT_ID, redact, open_browser=opened.append)

    assert caught.value.kind != "auth"
    assert mock_keyring[ACCOUNT] == _value(STORED)
    assert opened == []
    assert len(portal.requests_to("oauth2/token")) == 1


def test_a_browser_command_that_blocks_does_not_stall_the_callback(
    mock_keyring, tmp_xdg_home
):
    redact = arcgis_portal.Redactor()
    client = _client(FakePortal({"oauth2/token": TokenEndpoint()}), redact)
    browser = Browser()
    released = threading.Event()

    def foreground_browser(url: str) -> None:
        browser(url)
        released.wait(10)

    started = time.monotonic()
    try:
        oauth.sign_in(
            client, CLIENT_ID, redact, open_browser=foreground_browser, notify=print
        )
    finally:
        released.set()
    browser.join()

    assert time.monotonic() - started < 4
    assert client.token == ACCESS


def _trickle(prefix: bytes):
    """A browser stand-in that sends *prefix* to the listener, then one more
    byte every 0.1 s for 6 s."""

    def open_browser(url: str) -> None:
        params = dict(parse_qsl(urlsplit(url).query))
        port = urlsplit(params["redirect_uri"]).port
        head = prefix.replace(b"STATE", params["state"].encode())

        def send() -> None:
            with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
                try:
                    sock.sendall(head)
                    for _ in range(60):
                        time.sleep(0.1)
                        sock.sendall(b"x")
                except OSError:
                    return

        threading.Thread(target=send, daemon=True).start()

    return open_browser


@pytest.mark.parametrize(
    "prefix",
    [
        b"GET /callback?code=" + CODE.encode(),
        b"GET /callback?code=" + CODE.encode() + b"&state=STATE HTTP/1.1\r\nX-Slow: ",
    ],
    ids=["request line", "headers"],
)
def test_a_trickled_request_cannot_outlast_the_deadline(
    prefix, monkeypatch, mock_keyring, tmp_xdg_home
):
    monkeypatch.setattr(oauth, "SIGN_IN_TIMEOUT", 1.0)
    redact = arcgis_portal.Redactor()
    endpoint = TokenEndpoint()
    client = _client(FakePortal({"oauth2/token": endpoint}), redact)
    started = time.monotonic()

    with pytest.raises(arcgis_portal.PortalError) as caught:
        oauth.sign_in(
            client, CLIENT_ID, redact, open_browser=_trickle(prefix), notify=print
        )

    assert time.monotonic() - started < 3
    assert "no sign-in arrived" in str(caught.value)
    assert endpoint.grants == []


def _block_file_cleanup(monkeypatch) -> None:
    def refuse(account: str) -> None:
        raise OSError("read-only file system")

    monkeypatch.setattr(_auth, "_clear_credential_section", refuse)


def test_a_stale_file_sign_in_falls_back_to_the_keyring_one(
    monkeypatch, mock_keyring, tmp_xdg_home
):
    _auth._set_credential_field(ACCOUNT[1], "secret", _value(STORED))
    mock_keyring[ACCOUNT] = _value(REFRESH)
    _block_file_cleanup(monkeypatch)
    endpoint = TokenEndpoint(valid=(REFRESH,))
    redact = arcgis_portal.Redactor()
    client = _client(FakePortal({"oauth2/token": endpoint}), redact)
    opened: list[str] = []

    oauth.sign_in(client, CLIENT_ID, redact, open_browser=opened.append, notify=print)

    assert [g["refresh_token"] for g in endpoint.grants] == [STORED, REFRESH]
    assert opened == []
    assert mock_keyring[ACCOUNT] == _value(REFRESH)
    assert client.token == ACCESS_2


def test_a_new_sign_in_replaces_a_file_copy_it_cannot_remove(
    monkeypatch, mock_keyring, tmp_xdg_home
):
    _auth._set_credential_field(ACCOUNT[1], "secret", STORED)
    _block_file_cleanup(monkeypatch)
    redact = arcgis_portal.Redactor()
    client = _client(FakePortal({"oauth2/token": TokenEndpoint(valid=())}), redact)
    browser = Browser()

    oauth.sign_in(client, CLIENT_ID, redact, open_browser=browser, notify=print)
    browser.join()

    saved = [json.loads(v) for _, v in _auth.load_secrets(ACCOUNT[1])]
    assert [v["refresh_token"] for v in saved] == [REFRESH]


def test_arcgis_logout_forgets_the_saved_sign_in(runner, mock_keyring, tmp_xdg_home):
    _auth._set_credential_field(ACCOUNT[1], "secret", STORED)
    mock_keyring[ACCOUNT] = REFRESH
    args = [
        "arcgis",
        "logout",
        "--portal-url",
        PORTAL + "/home",
        "--client-id",
        CLIENT_ID,
    ]

    result = runner.invoke(app, args)

    assert result.exit_code == 0, result.output
    assert "credentials.toml and the OS keyring" in result.stdout
    assert ACCOUNT not in mock_keyring
    assert _auth.load_secrets(ACCOUNT[1]) == []
    _assert_no_secret(result.output)
    again = runner.invoke(app, args)
    assert again.exit_code == 0
    assert "No ArcGIS sign-in was saved" in again.stdout
    assert runner.invoke(app, ["arcgis", "logout"]).exit_code == 2


def _unreadable_keyring(monkeypatch) -> None:
    def locked(*args: object) -> None:
        raise KeyringError("keyring locked")

    monkeypatch.setattr("keyring.get_password", locked)
    monkeypatch.setattr("keyring.delete_password", locked)


@pytest.mark.parametrize("backend", ["keyring", "file"])
def test_arcgis_logout_does_not_claim_success_when_it_cannot_check(
    backend, runner, monkeypatch, mock_keyring, tmp_xdg_home
):
    if backend == "keyring":
        mock_keyring[ACCOUNT] = REFRESH
        _unreadable_keyring(monkeypatch)
        place = "the OS keyring"
    else:
        path = _config.credentials_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not = [toml")
        place = "credentials.toml"
    args = ["arcgis", "logout", "--portal-url", PORTAL, "--client-id", CLIENT_ID]

    result = runner.invoke(app, args)

    assert result.exit_code == 1, result.output
    assert f"{place} could not be read" in result.output
    assert "No ArcGIS sign-in was saved" not in result.output
    _assert_no_secret(result.output)


def test_an_empty_client_id_is_refused_not_ignored(invoke):
    portal = FakePortal(portal_routes())

    result, _, out = invoke(portal, _never_opened, "--client-id", "", "--scope", "org")

    assert result.exit_code == 2, result.output
    assert "--client-id" in result.stderr
    assert portal.seen == []
    assert not out.exists()


def _sign_in_stored(endpoint: TokenEndpoint, client_id: str = CLIENT_ID, **kwargs):
    """Sign in from the stored sign-in, with the browser refused; returns the
    client and the messages shown to the user."""
    redact = arcgis_portal.Redactor()
    client = _client(FakePortal({"oauth2/token": endpoint}), redact)
    shown: list[str] = []
    oauth.sign_in(
        client,
        client_id,
        redact,
        open_browser=_never_opened,
        notify=shown.append,
        **kwargs,
    )
    return client, shown


def _waiting_for_lock(monkeypatch) -> threading.Event:
    """Set once a lock attempt finds the lock held by someone else."""
    waiting = threading.Event()
    try_lock = oauth._try_lock

    def observed(fd: int):
        locked = try_lock(fd)
        if locked is False:
            waiting.set()
        return locked

    monkeypatch.setattr(oauth, "_try_lock", observed)
    return waiting


def _in_thread(call) -> tuple[threading.Thread, list[Any]]:
    outcome: list[Any] = []

    def run() -> None:
        try:
            outcome.append(call())
        except BaseException as exc:  # broad: the test asserts on it
            outcome.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, outcome


@pytest.mark.parametrize(
    ("age", "kinds"),
    [
        (LIFETIME / 2 - 60, ["refresh_token"]),
        (LIFETIME / 2 + 60, ["refresh_token", "exchange_refresh_token"]),
    ],
    ids=["before half", "past half"],
)
def test_a_stored_sign_in_is_exchanged_only_past_half_its_life(
    age, kinds, mock_keyring
):
    mock_keyring[ACCOUNT] = _value(STORED, age=age)
    endpoint = TokenEndpoint(valid=(STORED,))

    _sign_in_stored(endpoint)

    assert endpoint.kinds() == kinds


@pytest.mark.parametrize("lifetime", [LIFETIME, 3 * 86400])
def test_an_exchanged_token_and_its_lifetime_are_stored_before_use(
    lifetime, monkeypatch, mock_keyring
):
    mock_keyring[ACCOUNT] = _value(STORED, age=LIFETIME * 0.6)
    endpoint = TokenEndpoint(valid=(STORED,), lifetime=lifetime)
    stored_when_used: list[dict] = []
    use_token = arcgis_portal.PortalClient.use_token

    def record(self, token, lifetime, renew):
        stored_when_used.append(json.loads(mock_keyring[ACCOUNT]))
        use_token(self, token, lifetime, renew)

    monkeypatch.setattr(arcgis_portal.PortalClient, "use_token", record)

    client, shown = _sign_in_stored(endpoint)

    grant = endpoint.grants[1]
    assert grant["grant_type"] == "exchange_refresh_token"
    assert grant["client_id"] == CLIENT_ID
    assert grant["refresh_token"] == STORED
    assert re.fullmatch(r"http://127\.0\.0\.1:\d+/callback", grant["redirect_uri"])
    [rotated] = endpoint.rotated
    saved = {
        "refresh_token": rotated,
        "issued_at": NOW,
        "expires_at": NOW + lifetime,
        "redirect_uri": grant["redirect_uri"],
    }
    assert stored_when_used == [saved]
    assert json.loads(mock_keyring[ACCOUNT]) == saved
    assert client.token == f"{ACCESS_2}-2"
    assert shown == [f"Signed in to {PORTAL} as {USER}"]


def test_the_exchange_reuses_the_sign_ins_redirect_uri(mock_keyring):
    used = "http://127.0.0.1:54321/callback"
    mock_keyring[ACCOUNT] = _value(STORED, age=LIFETIME, redirect_uri=used)
    endpoint = TokenEndpoint(valid=(STORED,), redirect_uri=used)

    _sign_in_stored(endpoint, redirect_port=8765)

    assert endpoint.grants[1]["redirect_uri"] == used
    [rotated] = endpoint.rotated
    saved = json.loads(mock_keyring[ACCOUNT])
    assert (saved["refresh_token"], saved["redirect_uri"]) == (rotated, used)


def test_without_a_stored_redirect_uri_the_exchange_sends_the_port_given(
    mock_keyring,
):
    mock_keyring[ACCOUNT] = _value(STORED, age=LIFETIME)
    endpoint = TokenEndpoint(valid=(STORED,))

    _sign_in_stored(endpoint, redirect_port=8765)

    assert endpoint.grants[1]["redirect_uri"] == "http://127.0.0.1:8765/callback"


def test_a_sign_in_with_no_recorded_lifetime_is_exchanged(mock_keyring):
    mock_keyring[ACCOUNT] = STORED
    endpoint = TokenEndpoint(valid=(STORED,))

    _sign_in_stored(endpoint)

    assert endpoint.kinds() == ["refresh_token", "exchange_refresh_token"]
    saved = json.loads(mock_keyring[ACCOUNT])
    assert saved["refresh_token"] == endpoint.rotated[0]
    assert (saved["issued_at"], saved["expires_at"]) == (NOW, NOW + LIFETIME)


@pytest.mark.parametrize(
    "reply",
    [
        {
            "error": {
                "code": 400,
                "error": "unsupported_grant_type",
                "message": "Invalid grant_type",
            }
        },
        (500, {}),
        urllib.error.URLError("connection refused"),
    ],
    ids=["refused", "http error", "network error"],
)
def test_a_failed_exchange_keeps_the_refresh_grant(reply, invoke, mock_keyring):
    mock_keyring[ACCOUNT] = _value(STORED, age=LIFETIME * 0.9)
    endpoint = TokenEndpoint(valid=(STORED,), exchange=reply)
    portal = FakePortal(portal_routes({"oauth2/token": endpoint}))

    result, texts, _ = invoke(portal, _never_opened, "--client-id", CLIENT_ID)

    assert result.exit_code == 0, result.output
    assert endpoint.kinds() == ["refresh_token", "exchange_refresh_token"]
    assert json.loads(mock_keyring[ACCOUNT])["refresh_token"] == STORED
    reads = [s for s in portal.seen if s.path != "oauth2/token"]
    assert reads and all(s.headers.get(HEADER) == f"Bearer {ACCESS_2}" for s in reads)
    _assert_no_secret(texts)


def test_an_invalidated_stored_token_signs_in_through_the_browser(invoke, mock_keyring):
    mock_keyring[ACCOUNT] = _value(STORED, age=LIFETIME * 0.9)
    endpoint = TokenEndpoint(valid=())
    endpoint.invalidated.add(STORED)
    portal = FakePortal(portal_routes({"oauth2/token": endpoint}))
    browser = Browser()

    result, texts, _ = invoke(portal, browser, "--client-id", CLIENT_ID)

    assert result.exit_code == 0, result.output
    assert endpoint.kinds() == ["refresh_token", "authorization_code"]
    assert "The saved ArcGIS sign-in was refused" in result.stderr
    assert json.loads(mock_keyring[ACCOUNT])["refresh_token"] == REFRESH
    _assert_no_secret(texts)


def test_a_store_that_takes_no_write_is_not_exchanged(monkeypatch, mock_keyring):
    mock_keyring[ACCOUNT] = _value(STORED, age=LIFETIME)
    endpoint = TokenEndpoint(valid=(STORED,))

    def refuse(account: str, value: str) -> str:
        raise OSError("read-only file system")

    monkeypatch.setattr(_auth, "store_secret", refuse)

    client, shown = _sign_in_stored(endpoint)

    assert endpoint.kinds() == ["refresh_token"]
    assert mock_keyring[ACCOUNT] == _value(STORED, age=LIFETIME)
    assert client.token == ACCESS_2
    assert shown == [f"Signed in to {PORTAL} as {USER}"]


class _FlakyStore:
    """``store_secret`` into *keyring* that fails while ``broken`` is set,
    after its first *good* calls succeed."""

    def __init__(self, keyring: dict, good: int) -> None:
        self.keyring = keyring
        self.good = good
        self.broken = True
        self.calls = 0

    def __call__(self, account: str, value: str) -> str:
        self.calls += 1
        if self.broken and self.calls > self.good:
            raise OSError("keyring busy")
        self.keyring[("geolens", account)] = value
        return "keyring"


def test_an_exchanged_token_that_cannot_be_saved_lasts_only_this_run(
    monkeypatch, mock_keyring, capsys, caplog
):
    caplog.set_level(logging.DEBUG)
    mock_keyring[ACCOUNT] = _value(STORED, age=LIFETIME)
    endpoint = TokenEndpoint(valid=(STORED,))
    store = _FlakyStore(mock_keyring, good=1)
    monkeypatch.setattr(_auth, "store_secret", store)

    client, shown = _sign_in_stored(endpoint)
    assert client.renew_token()
    store.broken = False
    assert client.renew_token()

    [rotated] = endpoint.rotated
    assert [g["refresh_token"] for g in endpoint.grants[2:]] == [rotated, rotated]
    assert store.calls == 2
    assert mock_keyring[ACCOUNT] == _value(STORED, age=LIFETIME)
    assert shown == [f"Signed in to {PORTAL} as {USER}", oauth._UNSAVED]
    assert "no longer works" in oauth._UNSAVED
    assert "browser" in oauth._UNSAVED
    captured = capsys.readouterr()
    _assert_no_secret("\n".join([*shown, captured.out, captured.err, caplog.text]))


@pytest.mark.parametrize("error", [BrokenPipeError(), ValueError("closed file")])
def test_a_warning_that_cannot_be_written_does_not_end_the_sign_in(
    error, monkeypatch, mock_keyring
):
    mock_keyring[ACCOUNT] = _value(STORED, age=LIFETIME)
    endpoint = TokenEndpoint(valid=(STORED,))
    monkeypatch.setattr(_auth, "store_secret", _FlakyStore(mock_keyring, good=1))
    redact = arcgis_portal.Redactor()
    client = _client(FakePortal({"oauth2/token": endpoint}), redact)

    def unwritable(message: str) -> None:
        raise error

    oauth.sign_in(
        client, CLIENT_ID, redact, open_browser=_never_opened, notify=unwritable
    )

    assert client.token == f"{ACCESS_2}-2"


def test_a_stored_sign_in_never_shows_its_token_in_repr():
    saved = oauth._Saved.parse(_value(STORED))

    assert saved.token == STORED
    assert STORED not in repr(saved)


def test_a_run_that_waited_for_another_exchange_uses_the_new_token(
    monkeypatch, mock_keyring
):
    mock_keyring[ACCOUNT] = _value(STORED, age=LIFETIME * 0.9)
    endpoint = TokenEndpoint(valid=(STORED,))
    waiting = _waiting_for_lock(monkeypatch)

    with oauth._exchange_lock(ACCOUNT[1]) as held:
        assert held
        thread, outcome = _in_thread(lambda: _sign_in_stored(endpoint)[0])
        assert waiting.wait(10)
        # The other run exchanges and saves while this one waits.
        rotated = endpoint.rotate(STORED)
        mock_keyring[ACCOUNT] = _value(rotated, age=0)
    thread.join(10)

    [client] = outcome
    assert isinstance(client, arcgis_portal.PortalClient)
    assert endpoint.kinds() == ["refresh_token"]
    assert endpoint.grants[0]["refresh_token"] == rotated
    assert mock_keyring[ACCOUNT] == _value(rotated, age=0)


def test_a_run_without_the_lock_leaves_a_refused_token_for_the_holder(
    monkeypatch, mock_keyring
):
    """The lock holder's save may land between this run's read and a delete;
    a run without the lock deletes nothing."""
    mock_keyring[ACCOUNT] = _value(STORED, age=LIFETIME * 0.9)
    endpoint = TokenEndpoint(valid=(STORED,))
    monkeypatch.setattr(oauth, "_LOCK_WAIT", 0.05)
    monkeypatch.setattr(oauth, "SIGN_IN_TIMEOUT", 0.2)
    delete_secret = _auth.delete_secret
    holder: list[str] = []

    def holder_saves() -> None:
        if len(holder) == 1:
            holder.append("saved")
            mock_keyring[ACCOUNT] = _value(holder[0], age=0)

    def holder_saves_first(account: str, backend: str | None = None) -> None:
        holder_saves()
        delete_secret(account, backend)

    monkeypatch.setattr(_auth, "delete_secret", holder_saves_first)
    redact = arcgis_portal.Redactor()
    client = _client(FakePortal({"oauth2/token": endpoint}), redact)

    with oauth._exchange_lock(ACCOUNT[1]) as held:
        assert held
        holder.append(endpoint.rotate(STORED))
        with pytest.raises(arcgis_portal.PortalError):
            oauth.sign_in(
                client, CLIENT_ID, redact, open_browser=lambda url: None, notify=print
            )
        holder_saves()

    assert mock_keyring[ACCOUNT] == _value(holder[0], age=0)


def test_a_renewal_waits_for_another_runs_exchange_to_be_saved(
    monkeypatch, mock_keyring
):
    mock_keyring[ACCOUNT] = _value(STORED)
    endpoint = TokenEndpoint(valid=(STORED,))
    client, _ = _sign_in_stored(endpoint)
    waiting = _waiting_for_lock(monkeypatch)

    with oauth._exchange_lock(ACCOUNT[1]) as held:
        assert held
        # Another run has exchanged the token and not yet saved the new one.
        rotated = endpoint.rotate(STORED)
        thread, outcome = _in_thread(client.renew_token)
        assert waiting.wait(10)
        mock_keyring[ACCOUNT] = _value(rotated, age=0)
    thread.join(10)

    assert outcome == [True]
    assert endpoint.grants[-1]["refresh_token"] == rotated
    assert client.token == f"{ACCESS_2}-2"


def test_a_renewal_tries_each_stored_token_before_giving_up(monkeypatch, mock_keyring):
    mock_keyring[ACCOUNT] = _value(STORED)
    endpoint = TokenEndpoint(valid=(STORED,))
    client, _ = _sign_in_stored(endpoint)
    rotated = endpoint.rotate(STORED)
    # A stale file copy the other run could not remove is read first.
    _auth._set_credential_field(ACCOUNT[1], "secret", _value(REFRESH))
    mock_keyring[ACCOUNT] = _value(rotated, age=0)

    assert client.renew_token()

    assert [g["refresh_token"] for g in endpoint.grants[1:]] == [
        STORED,
        REFRESH,
        rotated,
    ]
    assert client.token == f"{ACCESS_2}-2"


def test_a_renewal_does_not_adopt_another_users_sign_in(mock_keyring):
    mock_keyring[ACCOUNT] = _value(STORED)
    endpoint = TokenEndpoint(valid=(STORED, REFRESH))
    endpoint.users[REFRESH] = "someone-else"
    client, _ = _sign_in_stored(endpoint)
    signed_in = client.token
    # This run's sign-in is revoked and another user signs in with the same app.
    endpoint.valid.discard(STORED)
    mock_keyring[ACCOUNT] = _value(REFRESH, age=0)

    assert not client.renew_token()

    assert client.token == signed_in
    assert json.loads(mock_keyring[ACCOUNT])["refresh_token"] == REFRESH


def test_a_logout_waits_for_an_exchange_in_flight(
    monkeypatch, mock_keyring, tmp_xdg_home
):
    mock_keyring[ACCOUNT] = _value(STORED)
    waiting = _waiting_for_lock(monkeypatch)

    with oauth._exchange_lock(ACCOUNT[1]) as held:
        assert held
        thread, outcome = _in_thread(lambda: oauth.forget(PORTAL, CLIENT_ID))
        assert waiting.wait(5)
        # The exchange saves its new token while the logout waits.
        mock_keyring[ACCOUNT] = _value(REFRESH, age=0)
    thread.join(10)

    assert outcome == [(["keyring"], [], [])]
    assert ACCOUNT not in mock_keyring


def test_a_logout_that_cannot_get_the_lock_leaves_the_sign_in(
    monkeypatch, mock_keyring, tmp_xdg_home
):
    mock_keyring[ACCOUNT] = _value(STORED)
    monkeypatch.setattr(oauth, "_LOCK_WAIT", 0.2)

    with oauth._exchange_lock(ACCOUNT[1]) as held:
        assert held
        thread, outcome = _in_thread(lambda: oauth.forget(PORTAL, CLIENT_ID))
        thread.join(10)

    assert outcome == [([], ["keyring"], [])]
    assert json.loads(mock_keyring[ACCOUNT])["refresh_token"] == STORED


_HOLD_LOCK = """
import sys, time
from geolens_cli import arcgis_oauth
with arcgis_oauth._exchange_lock(sys.argv[1]) as held:
    print("held" if held else "free", flush=True)
    time.sleep(60)
"""


def test_the_exchange_lock_is_released_when_its_holder_dies(monkeypatch, tmp_xdg_home):
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLD_LOCK, ACCOUNT[1]],
        stdout=subprocess.PIPE,
        text=True,
        env={**os.environ, "XDG_CONFIG_HOME": str(tmp_xdg_home)},
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        monkeypatch.setattr(oauth, "_LOCK_WAIT", 0.2)
        with oauth._exchange_lock(ACCOUNT[1]) as held:
            assert not held
    finally:
        holder.kill()
        holder.wait(10)
        holder.stdout.close()

    with oauth._exchange_lock(ACCOUNT[1]) as held:
        assert held


def test_a_run_that_cannot_get_the_lock_does_not_exchange(monkeypatch, mock_keyring):
    mock_keyring[ACCOUNT] = _value(STORED, age=LIFETIME * 0.9)
    endpoint = TokenEndpoint(valid=(STORED,))
    monkeypatch.setattr(oauth, "_LOCK_WAIT", 0.05)

    with oauth._exchange_lock(ACCOUNT[1]) as held:
        assert held
        client, _ = _sign_in_stored(endpoint)

    assert endpoint.kinds() == ["refresh_token"]
    assert client.token == ACCESS_2
    assert mock_keyring[ACCOUNT] == _value(STORED, age=LIFETIME * 0.9)


def test_the_account_signed_in_is_shown_once_and_never_a_secret(invoke, mock_keyring):
    """A browser sign-in and a reused stored one each print the portal and
    username on stderr only, with no token."""
    portal = FakePortal(portal_routes({"oauth2/token": TokenEndpoint()}))
    result, texts, out = invoke(portal, Browser(), "--client-id", CLIENT_ID)
    assert result.stderr.count(" as " + USER) == 1
    assert "Signed in to " in result.stderr and USER not in result.stdout
    _assert_no_secret(texts)

    mock_keyring[ACCOUNT] = _value(STORED)
    portal = FakePortal(portal_routes({"oauth2/token": TokenEndpoint(valid=(STORED,))}))
    result, _, _ = invoke(portal, _never_opened, "--client-id", CLIENT_ID)
    assert result.stderr.count(" as " + USER) == 1


def test_a_stored_sign_in_whose_reply_has_no_username_shows_no_line(mock_keyring):
    """A reply without a username signs in and prints no account line."""
    mock_keyring[ACCOUNT] = _value(STORED)
    endpoint = TokenEndpoint(valid=(STORED,))

    def no_name(seen):
        answer = endpoint(seen)
        answer.pop("username", None)
        return answer

    redact = arcgis_portal.Redactor()
    client = _client(FakePortal({"oauth2/token": no_name}), redact)
    shown: list[str] = []
    oauth.sign_in(
        client, CLIENT_ID, redact, open_browser=_never_opened, notify=shown.append
    )
    assert not [m for m in shown if m.startswith("Signed in")]
