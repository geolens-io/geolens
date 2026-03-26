"""Dynamic pysaml2 client builder from database provider configuration."""

import os
import tempfile

from saml2 import BINDING_HTTP_POST, BINDING_HTTP_REDIRECT
from saml2.client import Saml2Client
from saml2.config import Config as Saml2Config

from app.auth.oauth.encryption import decrypt_secret
from app.auth.oauth.models import OAuthProvider


def _build_idp_metadata_xml(entity_id: str, sso_url: str, certificate: str) -> str:
    """Generate minimal IdP metadata XML from extracted fields."""
    return f"""<?xml version="1.0"?>
<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata"
    entityID="{entity_id}">
  <IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <KeyDescriptor use="signing">
      <ds:KeyInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
        <ds:X509Data>
          <ds:X509Certificate>{certificate}</ds:X509Certificate>
        </ds:X509Data>
      </ds:KeyInfo>
    </KeyDescriptor>
    <SingleSignOnService
        Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
        Location="{sso_url}"/>
    <SingleSignOnService
        Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
        Location="{sso_url}"/>
  </IDPSSODescriptor>
</EntityDescriptor>"""


def build_saml_client(provider: OAuthProvider, acs_url: str) -> Saml2Client:
    """Build a pysaml2 Saml2Client from the database provider configuration.

    Creates a temporary metadata file for pysaml2 (required by its API),
    loads the config, then cleans up the temp file.
    """
    certificate = decrypt_secret(provider.idp_certificate)

    idp_metadata_xml = _build_idp_metadata_xml(
        entity_id=provider.idp_entity_id,
        sso_url=provider.idp_sso_url,
        certificate=certificate,
    )

    # pysaml2 requires metadata as a file path
    fd, metadata_path = tempfile.mkstemp(suffix=".xml")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(idp_metadata_xml)

        settings = {
            "entityid": provider.sp_entity_id,
            "metadata": {"local": [metadata_path]},
            "service": {
                "sp": {
                    "endpoints": {
                        "assertion_consumer_service": [
                            (acs_url, BINDING_HTTP_POST),
                        ],
                    },
                    "allow_unsolicited": False,
                    "authn_requests_signed": False,
                    "want_assertions_signed": True,
                    "want_response_signed": False,
                },
            },
        }
        config = Saml2Config()
        config.load(settings)
        config.allow_unknown_attributes = True
        return Saml2Client(config=config)
    finally:
        os.unlink(metadata_path)
