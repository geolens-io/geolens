"""SSO-06: Microsoft multitenant id_token iss validation.

Azure /common/ and /organizations/ advertise a templated issuer
(https://login.microsoftonline.com/{tenantid}/v2.0) but issue tokens with the
resolved per-tenant issuer, so authlib's default exact-match iss check rejects
every Microsoft login. _id_token_claims_options relaxes iss to
required-but-not-value-pinned for Microsoft only.
"""

from app.modules.auth.oauth.router import _id_token_claims_options


def test_microsoft_relaxes_iss_to_required_not_pinned():
    opts = _id_token_claims_options("microsoft")
    assert opts == {"iss": {"essential": True}}
    # Must NOT pin a value/values or the templated-issuer bug regresses.
    assert "value" not in opts["iss"]
    assert "values" not in opts["iss"]


def test_other_providers_keep_authlib_default():
    # None => authlib applies its default iss pin from discovery metadata.
    for provider_type in ("google", "github", "oidc", "saml", ""):
        assert _id_token_claims_options(provider_type) is None
