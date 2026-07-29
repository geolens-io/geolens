"""fix(#836): unit tests for the centralized allowed_email_domains HTTP gate.

The fetch-check-break-glass-403 block was pasted at four HTTP endpoints
(login, refresh, register, admin-create); enforce_email_domain_gate is that
block, once. No DB: the persistent-config read and the capability check are
monkeypatched at their sources.
"""

import pytest
from fastapi import HTTPException

import app.modules.auth.domain_policy as domain_policy
from app.modules.auth.domain_policy import (
    EMAIL_DOMAIN_FORBIDDEN_DETAIL,
    enforce_email_domain_gate,
)


class _Sentinel:
    """Stands in for the AsyncSession / User the patched callables ignore."""


def _patch_domains(monkeypatch: pytest.MonkeyPatch, domains: list[str]) -> None:
    async def _get_uncached(db):
        return domains

    monkeypatch.setattr(
        domain_policy.ALLOWED_EMAIL_DOMAINS, "get_uncached", _get_uncached
    )


def _patch_break_glass(monkeypatch: pytest.MonkeyPatch, has_capability: bool) -> None:
    import app.modules.auth.permissions as permissions

    async def _user_has_capability(db, user, capability):
        return has_capability

    monkeypatch.setattr(permissions, "user_has_capability", _user_has_capability)


@pytest.mark.anyio
async def test_null_email_is_permitted(monkeypatch: pytest.MonkeyPatch) -> None:
    """No address to gate on — preserves no-email registration paths (DOMAIN-02)."""
    _patch_domains(monkeypatch, ["example.com"])
    await enforce_email_domain_gate(_Sentinel(), None)
    await enforce_email_domain_gate(_Sentinel(), "")


@pytest.mark.anyio
async def test_allowed_domain_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_domains(monkeypatch, ["example.com"])
    await enforce_email_domain_gate(_Sentinel(), "user@example.com")


@pytest.mark.anyio
async def test_empty_allowlist_permits_any_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unconfigured allowlist means no enforcement (is_email_allowed contract)."""
    _patch_domains(monkeypatch, [])
    await enforce_email_domain_gate(_Sentinel(), "anyone@anywhere.test")


@pytest.mark.anyio
async def test_disallowed_domain_raises_403(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_domains(monkeypatch, ["example.com"])
    with pytest.raises(HTTPException) as exc_info:
        await enforce_email_domain_gate(_Sentinel(), "user@evil.test")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == EMAIL_DOMAIN_FORBIDDEN_DETAIL


@pytest.mark.anyio
async def test_break_glass_user_with_manage_settings_is_exempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_domains(monkeypatch, ["example.com"])
    _patch_break_glass(monkeypatch, True)
    await enforce_email_domain_gate(
        _Sentinel(), "user@evil.test", break_glass_user=_Sentinel()
    )


@pytest.mark.anyio
async def test_break_glass_user_without_capability_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_domains(monkeypatch, ["example.com"])
    _patch_break_glass(monkeypatch, False)
    with pytest.raises(HTTPException) as exc_info:
        await enforce_email_domain_gate(
            _Sentinel(), "user@evil.test", break_glass_user=_Sentinel()
        )
    assert exc_info.value.status_code == 403


@pytest.mark.anyio
async def test_no_break_glass_path_for_signup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Register passes no user — a new identity has no principal to exempt."""
    _patch_domains(monkeypatch, ["example.com"])
    _patch_break_glass(monkeypatch, True)  # must NOT be consulted
    with pytest.raises(HTTPException):
        await enforce_email_domain_gate(_Sentinel(), "user@evil.test")
