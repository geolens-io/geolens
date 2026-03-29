"""Parse IdP metadata XML to extract entity ID, SSO URL, and signing certificate."""

from defusedxml import ElementTree

SAML_NS = "urn:oasis:names:tc:SAML:2.0:metadata"
DS_NS = "http://www.w3.org/2000/09/xmldsig#"


def parse_idp_metadata(xml_string: str) -> dict:
    """Parse IdP metadata XML, returning entity_id, sso_url, and certificate.

    Raises ValueError on malformed XML or missing required fields.
    """
    try:
        root = ElementTree.fromstring(xml_string)
    except Exception as exc:
        raise ValueError(f"Malformed XML: {exc}") from exc

    entity_id = root.attrib.get("entityID")
    if not entity_id:
        raise ValueError("Missing entityID attribute on EntityDescriptor")

    # Find SSO URL with HTTP-Redirect binding
    sso_elem = root.find(
        f".//{{{SAML_NS}}}SingleSignOnService"
        f"[@Binding='urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect']"
    )
    if sso_elem is None:
        raise ValueError(
            "Missing SingleSignOnService with HTTP-Redirect binding (SSO URL)"
        )
    sso_url = sso_elem.attrib.get("Location")
    if not sso_url:
        raise ValueError(
            "SingleSignOnService element missing Location attribute (SSO URL)"
        )

    # Find signing certificate
    cert_elem = root.find(f".//{{{DS_NS}}}X509Certificate")
    if cert_elem is None or not cert_elem.text:
        raise ValueError("Missing X509Certificate in IdP metadata")
    certificate = cert_elem.text.strip()

    return {
        "entity_id": entity_id,
        "sso_url": sso_url,
        "certificate": certificate,
    }
