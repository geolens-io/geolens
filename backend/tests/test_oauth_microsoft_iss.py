"""Microsoft multitenant id_token iss validation (geolens#303).

Azure /common/ and /organizations/ advertise a templated issuer
(https://login.microsoftonline.com/{tenantid}/v2.0) but issue tokens with the
resolved per-tenant issuer, so authlib's default exact-match iss check rejects
every multitenant Microsoft login. _id_token_claims_options relaxes iss to
required-but-not-value-pinned for those authorities ONLY — tenant-specific
providers keep authlib's default pin so cross-tenant iss isolation holds.
"""

from app.modules.auth.oauth.router import _id_token_claims_options

_COMMON = (
    "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration"
)
_ORGS = "https://login.microsoftonline.com/organizations/v2.0/.well-known/openid-configuration"
_TENANT = "https://login.microsoftonline.com/9188040d-6c67-4c5b-b112-36a304b66dad/v2.0/.well-known/openid-configuration"


def test_microsoft_multitenant_relaxes_iss_not_pinned():
    for disco in (_COMMON, _ORGS):
        opts = _id_token_claims_options("microsoft", disco)
        assert opts == {"iss": {"essential": True}}, disco
        # Must NOT pin a value/values or the templated-issuer bug regresses.
        assert "value" not in opts["iss"]
        assert "values" not in opts["iss"]


def test_microsoft_tenant_specific_keeps_default():
    # Concrete-tenant discovery has a FIXED issuer authlib should still pin;
    # relaxing it would drop cross-tenant iss isolation.
    assert _id_token_claims_options("microsoft", _TENANT) is None
    # Defensive: no discovery URL => don't relax either.
    assert _id_token_claims_options("microsoft", None) is None


def test_other_providers_keep_authlib_default():
    # None => authlib applies its default iss pin from discovery metadata.
    for provider_type in ("google", "github", "oidc", "saml", ""):
        assert _id_token_claims_options(provider_type, _COMMON) is None
