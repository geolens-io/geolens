"""Microsoft multitenant SSO correctness (geolens#303).

Azure /common/ and /organizations/ advertise a templated issuer
(https://login.microsoftonline.com/{tenantid}/v2.0) and accept identities from
many tenants. Two things are gated on detecting that case:

1. id_token `iss` is relaxed to required-but-not-value-pinned (authlib's exact
   templated-issuer match otherwise rejects every login).
2. The OAuthAccount subject is prefixed with the tenant id, because Microsoft's
   bare `sub` is not globally unique across tenants — without partitioning, two
   tenants' users sharing a `sub` would collide and the second would be linked
   to the first's local account (cross-tenant takeover).

Tenant-specific Microsoft (fixed issuer) keeps authlib's default pin and the
bare `sub`.
"""

import pytest

from app.modules.auth.oauth.router import _id_token_claims_options
from app.modules.auth.oauth.service import (
    OAuthIssuerError,
    is_azure_multitenant,
    oauth_account_subject,
    verify_azure_multitenant_issuer,
)

_COMMON = (
    "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration"
)
_ORGS = "https://login.microsoftonline.com/organizations/v2.0/.well-known/openid-configuration"
_TENANT = "https://login.microsoftonline.com/9188040d-6c67-4c5b-b112-36a304b66dad/v2.0/.well-known/openid-configuration"


def test_is_azure_multitenant():
    assert is_azure_multitenant("microsoft", _COMMON) is True
    assert is_azure_multitenant("microsoft", _ORGS) is True
    # Tenant-specific and non-Microsoft are NOT multitenant.
    assert is_azure_multitenant("microsoft", _TENANT) is False
    assert is_azure_multitenant("microsoft", None) is False
    assert is_azure_multitenant("google", _COMMON) is False


def test_iss_relaxed_only_for_multitenant():
    for disco in (_COMMON, _ORGS):
        opts = _id_token_claims_options("microsoft", disco)
        assert opts == {"iss": {"essential": True}}, disco
        # Must NOT pin a value/values or the templated-issuer bug regresses.
        assert "value" not in opts["iss"] and "values" not in opts["iss"]
    # Tenant-specific Microsoft and other providers keep authlib's default pin.
    assert _id_token_claims_options("microsoft", _TENANT) is None
    for provider_type in ("google", "github", "oidc", "saml", ""):
        assert _id_token_claims_options(provider_type, _COMMON) is None


def test_subject_partitioned_for_multitenant_only():
    ui = {"sub": "S", "tid": "TENANT-A", "oid": "O"}
    # Multitenant Microsoft -> tenant-prefixed so cross-tenant subs can't collide.
    assert oauth_account_subject("microsoft", _COMMON, ui) == "TENANT-A:S"
    assert oauth_account_subject("microsoft", _ORGS, ui) == "TENANT-A:S"
    # Tenant-specific Microsoft and other providers keep the bare sub.
    assert oauth_account_subject("microsoft", _TENANT, ui) == "S"
    assert oauth_account_subject("google", _COMMON, ui) == "S"
    # Defensive: multitenant token without a tid falls back to bare sub.
    assert oauth_account_subject("microsoft", _COMMON, {"sub": "S"}) == "S"


def test_resolved_issuer_check_for_multitenant():
    good = {"tid": "T", "iss": "https://login.microsoftonline.com/T/v2.0"}
    # Matching iss/tid passes.
    verify_azure_multitenant_issuer("microsoft", _COMMON, good)
    # iss for a different tenant than tid -> rejected.
    with pytest.raises(OAuthIssuerError):
        verify_azure_multitenant_issuer(
            "microsoft",
            _COMMON,
            {"tid": "T", "iss": "https://login.microsoftonline.com/EVIL/v2.0"},
        )
    # Missing tid -> rejected.
    with pytest.raises(OAuthIssuerError):
        verify_azure_multitenant_issuer("microsoft", _COMMON, {"iss": "x"})
    # Non-multitenant providers are not checked (no raise even with junk claims).
    verify_azure_multitenant_issuer("microsoft", _TENANT, {"iss": "x"})
    verify_azure_multitenant_issuer("google", _COMMON, {"iss": "x"})
