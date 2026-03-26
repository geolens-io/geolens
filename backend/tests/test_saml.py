"""SAML SSO unit tests: metadata parsing, replay cache, and schema validation."""

import time

import pytest

# Sample IdP metadata XML for testing
SAMPLE_IDP_METADATA = """<?xml version="1.0"?>
<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata"
    entityID="https://idp.example.com/saml/metadata">
  <IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <KeyDescriptor use="signing">
      <ds:KeyInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
        <ds:X509Data>
          <ds:X509Certificate>MIICpDCCAYwCCQDbase64certdata</ds:X509Certificate>
        </ds:X509Data>
      </ds:KeyInfo>
    </KeyDescriptor>
    <SingleSignOnService
        Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
        Location="https://idp.example.com/saml/sso"/>
  </IDPSSODescriptor>
</EntityDescriptor>"""


class TestMetadataParsing:
    """Test IdP metadata XML parsing."""

    def test_parse_valid_metadata(self):
        from app.auth.saml.metadata import parse_idp_metadata

        result = parse_idp_metadata(SAMPLE_IDP_METADATA)
        assert result["entity_id"] == "https://idp.example.com/saml/metadata"
        assert result["sso_url"] == "https://idp.example.com/saml/sso"
        assert result["certificate"] is not None
        assert "MIICpDCCAYwCCQD" in result["certificate"]

    def test_parse_malformed_xml(self):
        from app.auth.saml.metadata import parse_idp_metadata

        with pytest.raises(ValueError, match="Malformed XML"):
            parse_idp_metadata("<not-xml>")

    def test_parse_missing_entity_id(self):
        from app.auth.saml.metadata import parse_idp_metadata

        xml = SAMPLE_IDP_METADATA.replace(
            'entityID="https://idp.example.com/saml/metadata"', ""
        )
        with pytest.raises(ValueError, match="entityID"):
            parse_idp_metadata(xml)

    def test_parse_missing_sso_url(self):
        from app.auth.saml.metadata import parse_idp_metadata

        # Remove the SingleSignOnService element entirely
        xml = """<?xml version="1.0"?>
<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata"
    entityID="https://idp.example.com/saml/metadata">
  <IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <KeyDescriptor use="signing">
      <ds:KeyInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
        <ds:X509Data>
          <ds:X509Certificate>MIICpDCCAYwCCQDbase64certdata</ds:X509Certificate>
        </ds:X509Data>
      </ds:KeyInfo>
    </KeyDescriptor>
  </IDPSSODescriptor>
</EntityDescriptor>"""
        with pytest.raises(ValueError, match="SSO"):
            parse_idp_metadata(xml)


class TestReplayCache:
    """Test SAML assertion replay cache."""

    def test_new_assertion_accepted(self):
        from app.auth.saml.replay import ReplayCache

        cache = ReplayCache()
        assert cache.check_and_record("id-1") is True

    def test_duplicate_rejected(self):
        from app.auth.saml.replay import ReplayCache

        cache = ReplayCache()
        cache.check_and_record("id-1")
        assert cache.check_and_record("id-1") is False

    def test_different_ids_accepted(self):
        from app.auth.saml.replay import ReplayCache

        cache = ReplayCache()
        assert cache.check_and_record("id-1") is True
        assert cache.check_and_record("id-2") is True

    def test_eviction_after_ttl(self):
        from app.auth.saml.replay import ReplayCache

        cache = ReplayCache(ttl_seconds=0)
        cache.check_and_record("id-1")
        time.sleep(0.01)
        assert cache.check_and_record("id-1") is True


class TestSamlSchemas:
    """Test Pydantic schema extensions for SAML providers."""

    def test_create_saml_provider(self):
        from app.auth.oauth.schemas import OAuthProviderCreate

        provider = OAuthProviderCreate(
            slug="okta-saml",
            display_name="Okta SAML",
            provider_type="saml",
            metadata_xml="<xml>test</xml>",
        )
        assert provider.provider_type == "saml"
        assert provider.client_id is None
        assert provider.client_secret is None
        assert provider.metadata_xml == "<xml>test</xml>"

    def test_create_oidc_provider_still_works(self):
        from app.auth.oauth.schemas import OAuthProviderCreate

        provider = OAuthProviderCreate(
            slug="google",
            display_name="Google",
            provider_type="google",
            client_id="my-client-id",
            client_secret="my-secret",
        )
        assert provider.provider_type == "google"
        assert provider.client_id == "my-client-id"

    def test_provider_response_includes_saml_fields(self):
        from app.auth.oauth.schemas import OAuthProviderResponse

        assert "idp_entity_id" in OAuthProviderResponse.model_fields
        assert "sp_entity_id" in OAuthProviderResponse.model_fields

    def test_update_schema_accepts_metadata_xml(self):
        from app.auth.oauth.schemas import OAuthProviderUpdate

        update = OAuthProviderUpdate(metadata_xml="<new-xml/>")
        assert update.metadata_xml == "<new-xml/>"
