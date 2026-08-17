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

The rule: an absolute HTTP(S) URL, with a host, and no query or fragment.

SHAPE ONLY. Whether a shape-valid value is TRUSTED in context is a separate
question — a loopback origin is shape-valid but untrusted when the caller is
somewhere else — which is why loopback entries sit under ``valid`` in the
fixture. That second question lives in ``assert_domain_lock_is_enforceable``.
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


@pytest.mark.anyio
@pytest.mark.parametrize(
    "configured",
    [
        "ftp://maps.example.com",
        "mailto:ops@example.com",
        "file:///etc/hosts",
        "not-a-url",
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

    async def _fake_get_public_app_url(db, **kwargs):
        return configured

    monkeypatch.setattr(embed_service, "get_public_app_url", _fake_get_public_app_url)
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
