"""fix(#1548 review r8): PUBLIC_APP_URL has ONE shape rule, and both sides obey it.

The setting is environment-backed, so it never passes through the
persistent-setting validator and arrives as whatever string the operator typed.
Two consumers read it — this backend, which compares it against the origin an
embed shell presents, and the frontend, which APPENDS ``/m/<token>`` to it —
and until this round each had learned about a different set of invalid shapes:

* the backend accepted ``ftp://maps.example.com``, whose normalization prepends
  ``https://`` and yields the plausible non-loopback origin ``https://ftp:``, so
  ``assert_domain_lock_is_enforceable`` read the deployment as configured and
  issued a domain lock that no embed shell could ever satisfy — the original bug
  of this PR, returning through the very check added to prevent it;
* the frontend accepted ``https://maps.example.com?tenant=a``, so appending a
  path put it inside the query string.

Two independent validators for one setting is the arrangement that produced
both. The implementations cannot be shared across the language boundary, so the
SPEC is: ``frontend/src/lib/__tests__/public-app-url-shape.cases.json`` is the
single statement of the rule, and this file runs it against the Python half.
The TypeScript half runs the same table in
``frontend/src/lib/__tests__/public-urls.test.ts``.

The rule: an absolute HTTP(S) URL, with a host, no query or fragment, and no
path naming the ``/api`` base.

SHAPE, and one classification on top of it. Whether a shape-valid value is
TRUSTED in context is a separate question — a loopback origin is shape-valid but
untrusted when the caller is somewhere else — which is why loopback entries sit
under ``valid`` in the fixture, and the decision itself lives in
``assert_domain_lock_is_enforceable``. fix(#1555): WHICH origins are loopback is
back here, though, because it is not each side's private opinion either. It was
an enumerated set of three spellings on both sides, and ``127.0.0.2`` — loopback
to every operating system, and to the frontend's `loopback-default` state once
it was fixed there — has to mean the same thing in both halves or the UI and the
API disagree about which deployments are misconfigured.

fix(#1555) also puts the setting's OTHER door under the same rule: an admin PUT
goes through ``validate_public_app_url``, which held the ``/api`` clause the
environment path lacked while lacking every host-spelling clause the environment
path had. Both are asserted here, against the same values.
"""

import json
from pathlib import Path

import pytest

from app.core.public_urls import is_usable_public_origin

_CASES_PATH = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "lib"
    / "__tests__"
    / "public-app-url-shape.cases.json"
)


def _spec() -> dict:
    if not _CASES_PATH.is_file():
        pytest.skip("frontend tree not present in this checkout")
    return json.loads(_CASES_PATH.read_text(encoding="utf-8"))


def test_the_shared_case_table_has_cases_on_both_sides():
    """A fixture that quietly emptied would make every case below vacuous."""
    spec = _spec()
    assert spec["valid"], "no valid cases"
    assert spec["invalid"], "no invalid cases"


def test_every_shape_the_spec_calls_valid_is_accepted():
    spec = _spec()
    rejected = [v for v in spec["valid"] if not is_usable_public_origin(v)]
    assert not rejected, (
        "is_usable_public_origin rejects values the shared spec calls usable. "
        "Either the rule changed on one side only, or the fixture is wrong:\n"
        + "\n".join(f"  {v!r}" for v in rejected)
    )


def test_every_shape_the_spec_calls_invalid_is_refused():
    spec = _spec()
    accepted = [v for v in spec["invalid"] if is_usable_public_origin(v)]
    assert not accepted, (
        "is_usable_public_origin accepts values the shared spec calls unusable. "
        "The frontend refuses these, so the two halves have drifted:\n"
        + "\n".join(f"  {v!r}" for v in accepted)
    )


def test_every_canonical_origin_matches_the_browsers_spelling():
    """fix(#1548 review r9): same place is not the same STRING.

    A browser serializes the shell's Origin with an IDNA ASCII host, lowercased,
    no userinfo and the default port dropped. The configured value is compared
    against that string, so a Unicode hostname stored as typed was issued a lock
    and then missed on every request. Both sides canonicalize now — the frontend
    through ``new URL(x).origin``, this side through ``_normalize_origin`` — and
    the fixture is the one statement of what they must agree on.
    """
    from app.modules.embed_tokens.schemas import _normalize_origin

    spec = _spec()
    assert spec["canonical_origin"], "no canonicalization cases"
    wrong = {
        raw: (_normalize_origin(raw), expected)
        for raw, expected in spec["canonical_origin"].items()
        if _normalize_origin(raw) != expected
    }
    assert not wrong, (
        "_normalize_origin disagrees with the shared canonical spelling, so a "
        "configured origin and the browser's Origin header would not match:\n"
        + "\n".join(f"  {r!r}: got {g!r}, want {w!r}" for r, (g, w) in wrong.items())
    )


def test_canonicalization_is_idempotent():
    """A canonical value must survive a second pass unchanged.

    Not decoration: the value is normalized when stored AND when compared, so a
    non-idempotent rule would match on the first request and miss afterwards.
    """
    from app.modules.embed_tokens.schemas import _normalize_origin

    for expected in set(_spec()["canonical_origin"].values()):
        assert _normalize_origin(expected) == expected, expected


def test_the_loopback_table_has_cases_on_both_sides():
    spec = _spec()
    assert spec["loopback"], "no loopback cases"
    assert spec["not_loopback"], "no routable cases"


def test_every_origin_the_spec_calls_loopback_is_read_as_loopback():
    """fix(#1555): loopback is a range, and both sides have to agree on it.

    The consumer is asserted, not the helper: ``_is_localhost_origin`` is what
    ``assert_domain_lock_is_enforceable`` asks, and reading ``127.0.0.2`` as a
    routable public origin is what let it issue a lock recipients resolve to
    their own machine.
    """
    from app.modules.embed_tokens.service import _is_localhost_origin

    missed = [v for v in _spec()["loopback"] if not _is_localhost_origin(v)]
    assert not missed, (
        "these reach only the machine the browser runs on, and the frontend "
        "classifies them as loopback-default, so a domain lock offered from "
        "them could never be satisfied:\n" + "\n".join(f"  {v!r}" for v in missed)
    )


def test_no_origin_the_spec_calls_routable_is_read_as_loopback():
    """The counterfactual: the range must not swallow its neighbours.

    Without this, ``return True`` passes the test above. ``126.255.255.255`` and
    ``128.0.0.1`` sit either side of ``127.0.0.0/8``, and ``mylocalhost.example``
    ends in the same letters as the one hostname that is special.
    """
    from app.modules.embed_tokens.service import _is_localhost_origin

    wrong = [v for v in _spec()["not_loopback"] if _is_localhost_origin(v)]
    assert not wrong, (
        "these are ordinary public origins; treating them as loopback would "
        "refuse a domain lock on a correctly configured deployment:\n"
        + "\n".join(f"  {v!r}" for v in wrong)
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "configured",
    [
        "ftp://maps.example.com",
        "mailto:ops@example.com",
        "file:///etc/hosts",
        "not-a-url",
        # fix(#1555): an API base is not an app URL, and this door never
        # applied the clause the persisted one had.
        "https://maps.example.com/api",
    ],
)
async def test_a_non_http_setting_cannot_authorize_a_domain_lock(
    monkeypatch, configured
):
    """The finding itself, end to end through the gate.

    Not merely "the predicate returns False": what matters is that the lock is
    REFUSED, because the failure was a plausible-looking pseudo-origin
    convincing the gate that the deployment was configured. Each value below
    normalizes to a non-loopback string — ``ftp://maps.example.com`` becomes
    ``https://ftp:`` — which is precisely why the loopback test could not catch
    them.
    """
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.modules.embed_tokens import service as embed_service

    async def _fake_get_configured_public_app_url(db, **kwargs):
        return configured

    monkeypatch.setattr(
        embed_service,
        "get_configured_public_app_url",
        _fake_get_configured_public_app_url,
    )
    monkeypatch.setattr(embed_service, "is_enterprise", lambda: True)

    request = MagicMock()
    request.headers = {"origin": "https://maps.example.com"}
    request.client = SimpleNamespace(host="172.18.0.5")
    request.state = SimpleNamespace()

    with pytest.raises(embed_service.DomainLockNotEnforceableError) as exc:
        await embed_service.assert_domain_lock_is_enforceable(
            AsyncMock(), request, ["https://customer.example.com"]
        )
    message = str(exc.value)
    assert "PUBLIC_APP_URL" in message
    assert "nothing usable" in message, (
        "an unusable setting must resolve to no self-origin at all, not to a "
        "pseudo-origin the operator will not recognize"
    )


@pytest.mark.anyio
async def test_a_loopback_setting_outside_127_0_0_1_cannot_authorize_a_domain_lock(
    monkeypatch,
):
    """fix(#1555): the finding, end to end through the gate.

    ``http://127.0.0.2:8080`` is a perfectly well-formed origin — it passes the
    whole shape rule, which is why the previous check let it through. It is also
    an address every recipient of the embed resolves to their OWN machine, so a
    domain lock issued here has exactly the failure the refusal exists to
    prevent: the shell never loads, and the operator hears nothing until they
    ask a customer why the map is empty.

    Asserted through the gate rather than the predicate, because "does this
    deployment know a public origin" is the question the predicate is asked, and
    a version of it that returns the right boolean while the gate goes on to
    permit the lock would be no fix at all.
    """
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.modules.embed_tokens import service as embed_service

    async def _configured(db, **kwargs):
        return "http://127.0.0.2:8080"

    monkeypatch.setattr(embed_service, "get_configured_public_app_url", _configured)
    monkeypatch.setattr(embed_service, "is_enterprise", lambda: True)

    request = MagicMock()
    request.headers = {"origin": "https://maps.example.com"}
    request.client = SimpleNamespace(host="172.18.0.5")
    request.state = SimpleNamespace()

    with pytest.raises(embed_service.DomainLockNotEnforceableError) as exc:
        await embed_service.assert_domain_lock_is_enforceable(
            AsyncMock(), request, ["https://customer.example.com"]
        )
    message = str(exc.value)
    assert "http://127.0.0.2:8080" in message, (
        "the refusal must name the value the operator has to change"
    )
    assert "PUBLIC_APP_URL" in message


@pytest.mark.anyio
@pytest.mark.parametrize(
    "configured", ["https://maps.example.com", "http://126.255.255.255"]
)
async def test_a_deployment_on_a_routable_host_still_gets_its_domain_lock(
    monkeypatch, configured
):
    """The counterfactual for the test above.

    A loopback rule that widened far enough to catch a correctly configured
    deployment would trade a silent failure for a loud one on a healthy
    install. ``126.255.255.255`` is one address below the loopback block.
    """
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.modules.embed_tokens import service as embed_service

    async def _configured(db, **kwargs):
        return configured

    monkeypatch.setattr(embed_service, "get_configured_public_app_url", _configured)
    monkeypatch.setattr(embed_service, "is_enterprise", lambda: True)

    request = MagicMock()
    request.headers = {"origin": "https://maps.example.com"}
    request.client = SimpleNamespace(host="172.18.0.5")
    request.state = SimpleNamespace()

    await embed_service.assert_domain_lock_is_enforceable(
        AsyncMock(), request, ["https://customer.example.com"]
    )


@pytest.mark.parametrize(
    "configured",
    [
        "https://maps.example.com/api",
        "https://maps.example.com/api/",
        "https://example.com/geolens/api",
        "https://192.168.1",
        # fix(#1555 review): resolve to the API base in a browser, and were
        # left alone by urlsplit, so both doors used to take them.
        "https://maps.example.com/api/.",
        "https://maps.example.com/api/./",
        "https://maps.example.com/foo/../api/.",
    ],
)
def test_both_entry_points_of_the_setting_refuse_the_same_values(configured):
    """fix(#1555): one rule, wherever ``public_app_url`` enters.

    The setting has two doors — the environment, read by
    ``is_usable_public_origin``, and the admin API, validated by
    ``validate_public_app_url`` — and each used to hold half the rule. The
    ``/api`` clause lived only on the persisted side, so an environment value
    naming the API base was accepted and built ``/api/api/maps/...`` links; the
    host-spelling clauses lived only on the environment side, so the admin form
    accepted ``https://192.168.1`` and every reader then ignored it, which is
    the same as the form doing nothing.
    """
    from app.core.public_urls import is_usable_public_origin
    from app.modules.settings.schemas import validate_public_app_url

    assert not is_usable_public_origin(configured)
    with pytest.raises(ValueError):
        validate_public_app_url(configured)


@pytest.mark.parametrize(
    "configured",
    [
        "https://maps.example.com",
        "https://example.com/geolens",
        "https://xn--ls8h.example",
    ],
)
def test_both_entry_points_accept_a_value_a_viewer_could_reach(configured):
    """The counterfactual: neither door may refuse a working configuration.

    ``/geolens`` is a sub-path deployment and ``xn--ls8h`` is an ACE label all
    four engines accept identically — a rule that rejected either would cost an
    operator a setting that works today.

    fix(#1555 review r4): ACE labels are otherwise absent from this file, and
    that is the finding rather than an omission. Chromium and WebKit accept
    every ``xn--`` label without decoding it, Firefox applies the full URL
    Standard and refuses most of them, and Node agrees with neither, so no
    refusal can be right for all of them. See ``canonical_host_error`` and the
    fixture's ``_ace_note`` for the measurements.
    """
    from app.core.public_urls import is_usable_public_origin
    from app.modules.settings.schemas import validate_public_app_url

    assert is_usable_public_origin(configured)
    assert validate_public_app_url(configured) == configured


@pytest.mark.parametrize(
    ("path", "browser_resolves_to", "is_api_base"),
    [
        # The three that were live: urlsplit leaves them, browsers resolve them.
        ("/api/.", "/api/", True),
        ("/api/./", "/api/", True),
        ("/foo/../api/.", "/api/", True),
        # Percent-encoded dot segments. UNREACHABLE end to end — every candidate
        # containing '%' is refused several clauses earlier, on both sides —
        # which is exactly why they are asserted HERE, against the classifier
        # itself. Through the front door these cases would pass on the percent
        # rule and say nothing about this code.
        ("/api/%2e", "/api/", True),
        ("/api/%2E/", "/api/", True),
        ("/api/.%2e", "/", False),
        ("/api/%2e%2e", "/", False),
        # Dot segments that resolve AWAY from the API base. The counterfactual:
        # a normalizer that simply looked for '/api' anywhere would refuse a
        # deployment that is not on the API base at all.
        ("/api/..", "/", False),
        ("/apiary/.", "/apiary/", False),
        ("/geolens/./x", "/geolens/x", False),
        ("/a/./b/../api", "/a/api", True),
        # Unchanged by normalization, so the ordinary answers must not move.
        ("/api", "/api", True),
        ("/apiary", "/apiary", False),
        ("/geolens", "/geolens", False),
        ("", "", False),
    ],
)
def test_the_api_path_rule_reads_the_path_a_browser_resolves(
    path, browser_resolves_to, is_api_base
):
    """fix(#1555 review): ``urlsplit`` is not a URL parser's normalizer.

    ``expected`` is what ``new URL('https://x' + path).pathname`` returns,
    measured in Node rather than reasoned about, with one deliberate exception:
    a path-less URL, where a browser supplies ``/`` and this function leaves the
    empty string alone. Supplying a default path is not resolving dot segments,
    and the classification is the same either way.
    """
    from app.core.public_urls import _remove_dot_segments, is_api_base_path

    assert _remove_dot_segments(path) == browser_resolves_to
    assert is_api_base_path(path) is is_api_base
