"""One-shot fixture generator for SAML response fixtures.

Run with::

    cd backend && uv run python tests/fixtures/saml/generate_fixtures.py

(or, when running outside a uv sync that includes pysaml2, inside the API
docker container with the enterprise overlay installed -- see Phase 217
RESEARCH.md S10.)

Produces 5 base64-encoded SAMLResponse XML fixtures used by tests in
``backend/tests/test_saml_overlay.py``. Re-run only when the fixture cert
rotates or new fixtures are needed.

Outputs
-------
- ``idp_response_signed.xml.b64``    -- happy path (signed assertion, valid times)
- ``idp_response_expired.xml.b64``   -- NotOnOrAfter set in 2020 (definitively past)
- ``idp_response_xsw.xml.b64``       -- XML Signature Wrapping attack payload
- ``idp_response_unsigned.xml.b64``  -- assertion without signature
- ``idp_response_replay.xml.b64``    -- byte-identical copy of signed (for replay
                                       cache test; same assertion.id)

Constants
---------
The SP entityID, ACS URL, NameID format, and attributes are FIXED so tests
can hard-code them. If you change anything here, update the test
expectations in ``backend/tests/test_saml_overlay.py`` accordingly.
"""

from __future__ import annotations

import base64
import os
import re
import shutil
from pathlib import Path

# These imports require pysaml2 to be installed (enterprise overlay).
from saml2 import BINDING_HTTP_POST, saml  # noqa: F401  (saml re-exported below)
from saml2.config import IdPConfig
from saml2.saml import NAMEID_FORMAT_PERSISTENT, NameID
from saml2.server import Server


HERE = Path(__file__).parent.resolve()
CERT_PEM = HERE / "idp_cert.pem"
KEY_PEM = HERE / "idp_key.pem"

# Fixed constants -- must match values asserted in tests/test_saml_overlay.py
IDP_ENTITY_ID = "https://fixture-idp.geolens.test/idp"
SP_ENTITY_ID = "https://geolens.test/auth/saml/fixture"
ACS_URL = "https://geolens.test/auth/saml/fixture/acs"
NAMEID = "user@example.com"
USER_ATTRS = {
    "email": ["user@example.com"],
    "displayName": ["Test User"],
    "groups": ["editors"],
}


_SP_METADATA_TEMPLATE = """<?xml version="1.0"?>
<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata"
                  entityID="{sp_entity_id}">
  <SPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol"
                   AuthnRequestsSigned="false" WantAssertionsSigned="true">
    <NameIDFormat>urn:oasis:names:tc:SAML:2.0:nameid-format:persistent</NameIDFormat>
    <AssertionConsumerService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
                              Location="{acs_url}"
                              index="0"/>
  </SPSSODescriptor>
</EntityDescriptor>
"""


def _write_sp_metadata(tmpdir: Path) -> Path:
    """Emit a minimal SP metadata XML so the IdP server can resolve sp_entity_id."""
    sp_meta = tmpdir / "sp_metadata.xml"
    sp_meta.write_text(
        _SP_METADATA_TEMPLATE.format(sp_entity_id=SP_ENTITY_ID, acs_url=ACS_URL)
    )
    return sp_meta


def _xmlsec_binary() -> str:
    """Locate xmlsec1 (Linux: /usr/bin/xmlsec1; macOS Homebrew: /opt/homebrew/bin/xmlsec1)."""
    for candidate in (
        "/usr/bin/xmlsec1",
        "/opt/homebrew/bin/xmlsec1",
        "/usr/local/bin/xmlsec1",
    ):
        if os.path.exists(candidate):
            return candidate
    # Fall back to PATH lookup
    return "xmlsec1"


def _make_server(sp_metadata_path: Path) -> Server:
    """Construct a pysaml2 Server (IdP simulator) loaded with the fixture cert/key."""
    config = IdPConfig()
    config.load(
        {
            "entityid": IDP_ENTITY_ID,
            "service": {
                "idp": {
                    "name": "Fixture IdP",
                    "endpoints": {
                        "single_sign_on_service": [
                            (f"{IDP_ENTITY_ID}/sso", BINDING_HTTP_POST),
                        ],
                    },
                    "policy": {
                        "default": {
                            "lifetime": {"minutes": 15},
                            "attribute_restrictions": None,  # allow all
                            "name_form": "urn:oasis:names:tc:SAML:2.0:attrname-format:basic",
                            "fail_on_missing_requested": False,
                        },
                    },
                    "subject_data": "/tmp/fixture_subject_data.db",
                    "want_authn_requests_signed": False,
                },
            },
            "key_file": str(KEY_PEM),
            "cert_file": str(CERT_PEM),
            "metadata": {"local": [str(sp_metadata_path)]},
            "xmlsec_binary": _xmlsec_binary(),
            "valid_for": 24,
            "organization": {
                "name": "Fixture IdP",
                "display_name": "Fixture IdP",
                "url": IDP_ENTITY_ID,
            },
        }
    )
    return Server(config=config)


def _b64(xml_bytes: bytes | str) -> bytes:
    """Base64-encode the SAMLResponse XML, returning bytes for write-binary."""
    if isinstance(xml_bytes, str):
        xml_bytes = xml_bytes.encode("utf-8")
    # The pysaml2 HTTP-POST flow base64-encodes the SAMLResponse XML element.
    return base64.b64encode(xml_bytes)


def _build_signed_response_xml(server: Server) -> str:
    """Build a signed SAMLResponse XML targeting our fixture SP."""
    # pysaml2's create_authn_response signs the assertion when sign_assertion=True.
    # We bypass the SP-metadata requirement by passing the SP entityID via
    # the ``sp_entity_id`` arg and supplying explicit destination + audience.
    name_id = NameID(
        format=NAMEID_FORMAT_PERSISTENT,
        sp_name_qualifier=SP_ENTITY_ID,
        text=NAMEID,
    )
    response = server.create_authn_response(
        identity=USER_ATTRS,
        in_response_to="id-fixture-request-001",
        destination=ACS_URL,
        sp_entity_id=SP_ENTITY_ID,
        name_id=name_id,
        sign_assertion=True,
        sign_response=False,
        userid=NAMEID,
        authn={
            "class_ref": "urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport",
            "authn_auth": IDP_ENTITY_ID,
        },
    )
    # create_authn_response returns a string of the SAMLResponse XML element.
    if isinstance(response, bytes):
        response = response.decode("utf-8")
    return response


def _build_unsigned_response_xml(server: Server) -> str:
    name_id = NameID(
        format=NAMEID_FORMAT_PERSISTENT,
        sp_name_qualifier=SP_ENTITY_ID,
        text=NAMEID,
    )
    response = server.create_authn_response(
        identity=USER_ATTRS,
        in_response_to="id-fixture-request-002",
        destination=ACS_URL,
        sp_entity_id=SP_ENTITY_ID,
        name_id=name_id,
        sign_assertion=False,
        sign_response=False,
        userid=NAMEID,
    )
    # When sign_assertion=False, pysaml2 returns the saml2.samlp.Response model
    # object instead of a serialized XML string. Serialize it explicitly.
    if isinstance(response, bytes):
        return response.decode("utf-8")
    if isinstance(response, str):
        return response
    return str(response)


def _force_expired(xml_str: str) -> str:
    """Rewrite NotOnOrAfter / NotBefore / IssueInstant to dates in 2020.

    This is a textual transform applied AFTER signing. By design it INVALIDATES
    the assertion signature (xmlsec1 will reject it). Tests treat the expired
    fixture as a negative payload that the SP-side validator should reject;
    they should not assert that the rejection reason is specifically 'expired'
    versus 'signature mismatch' -- both are correct rejections.

    The plan's intent (per RESEARCH S10) is: we have an expired-LOOKING
    fixture that our pipeline rejects. pysaml2's parse_authn_request_response
    will raise (signature error or expiry error) and the SP-side test asserts
    rejection. If a test needs to specifically verify the expiry code path
    (independent of signature), it should either (a) use a separately-signed
    expired assertion built by re-signing after time-rewrite, or (b) call
    pysaml2 with want_assertions_signed=False on the test config.
    """
    # Set all SAML datetime attributes to 2020-01-01T00:00:00Z (-/+ a few sec)
    past = "2020-01-01T00:00:00Z"
    past_after = "2020-01-01T00:05:00Z"
    out = re.sub(r'IssueInstant="[^"]+"', f'IssueInstant="{past}"', xml_str)
    out = re.sub(r'NotBefore="[^"]+"', f'NotBefore="{past}"', out)
    out = re.sub(r'NotOnOrAfter="[^"]+"', f'NotOnOrAfter="{past_after}"', out)
    return out


def _build_xsw_attack_xml(signed_xml: str) -> str:
    """Build an XML Signature Wrapping (XSW) attack payload.

    Wraps the legitimate signed assertion inside an attacker-injected
    <saml:Advice> element while injecting an EVIL assertion as the primary
    Assertion. A naive parser that picks the first Assertion sees the EVIL
    one but a signature-aware parser like pysaml2 7.5.4 with xmlsec1 should
    detect the wrapping and raise SignatureError (per RESEARCH Pitfall 2).

    This fixture is the negative test payload -- Plan 02's
    test_saml_acs_rejects_xsw_attack asserts pysaml2 rejects it.
    """
    # Find the legitimate <ns:Assertion ...>...</ns:Assertion> block.
    # pysaml2 typically emits namespaced prefixes like ns1:Assertion or
    # saml:Assertion depending on serialization. Match any prefix.
    m = re.search(
        r"(<([A-Za-z][\w-]*:)?Assertion\b[^>]*>.*?</(?:\2)?Assertion>)",
        signed_xml,
        re.DOTALL,
    )
    if not m:
        raise RuntimeError("Cannot locate <Assertion> element in signed response")
    legit_assertion = m.group(1)
    # m.group(2) captures the namespace prefix (e.g. 'ns1:' or '' for default
    # ns); kept for diagnostic clarity in the regex but not consumed downstream.

    # Build an evil assertion that swaps subject/email/groups for an admin user.
    # Note: this evil assertion is UNSIGNED. The XSW attack relies on the
    # validator accepting the assertion in front and being fooled by the
    # signature wrapped in <Advice>.
    evil_subject = "attacker@evil.test"
    evil_assertion = (
        '<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
        'ID="id-evil-attacker" IssueInstant="2026-04-29T00:00:00Z" Version="2.0">'
        f"<saml:Issuer>{IDP_ENTITY_ID}</saml:Issuer>"
        f"<saml:Subject><saml:NameID>{evil_subject}</saml:NameID></saml:Subject>"
        '<saml:Conditions NotBefore="2026-04-29T00:00:00Z" '
        'NotOnOrAfter="2099-01-01T00:00:00Z">'
        f"<saml:AudienceRestriction><saml:Audience>{SP_ENTITY_ID}</saml:Audience>"
        "</saml:AudienceRestriction></saml:Conditions>"
        "<saml:AttributeStatement>"
        '<saml:Attribute Name="email">'
        f"<saml:AttributeValue>{evil_subject}</saml:AttributeValue></saml:Attribute>"
        '<saml:Attribute Name="groups">'
        "<saml:AttributeValue>admins</saml:AttributeValue></saml:Attribute>"
        "</saml:AttributeStatement>"
        '<saml:AuthnStatement AuthnInstant="2026-04-29T00:00:00Z">'
        "<saml:AuthnContext><saml:AuthnContextClassRef>"
        "urn:oasis:names:tc:SAML:2.0:ac:classes:Password"
        "</saml:AuthnContextClassRef></saml:AuthnContext>"
        "</saml:AuthnStatement>"
        # Wrap the legitimate signed assertion inside <Advice> so the
        # signature still validates against the original assertion ID, but
        # the parser ideally sees the evil assertion at the top level.
        f"<saml:Advice>{legit_assertion}</saml:Advice>"
        "</saml:Assertion>"
    )

    # Replace the legitimate assertion in the response with the evil one
    # (which contains the legit one wrapped in Advice).
    return signed_xml.replace(legit_assertion, evil_assertion, 1)


def main(output_dir: Path | None = None) -> None:
    if not CERT_PEM.exists() or not KEY_PEM.exists():
        raise SystemExit(
            f"Missing fixture cert/key: {CERT_PEM}, {KEY_PEM}. "
            "Generate with: openssl req -x509 -newkey rsa:2048 "
            f"-keyout {KEY_PEM.name} -out {CERT_PEM.name} -days 36500 -nodes "
            '-subj "/CN=fixture-idp.geolens.test"'
        )

    target = output_dir if output_dir is not None else HERE
    target.mkdir(parents=True, exist_ok=True)

    import tempfile

    tmpdir = Path(tempfile.mkdtemp(prefix="saml_fixture_gen_"))
    sp_meta = _write_sp_metadata(tmpdir)
    server = _make_server(sp_meta)

    # 1. Signed (happy path)
    signed_xml = _build_signed_response_xml(server)
    signed_b64 = _b64(signed_xml)
    (target / "idp_response_signed.xml.b64").write_bytes(signed_b64)
    print(f"wrote idp_response_signed.xml.b64 ({len(signed_b64)} bytes)")

    # 2. Replay (byte-identical to signed -- same assertion.id)
    shutil.copyfile(
        target / "idp_response_signed.xml.b64",
        target / "idp_response_replay.xml.b64",
    )
    print("wrote idp_response_replay.xml.b64 (byte-identical to signed)")

    # 3. Expired (text-rewritten times -- breaks signature, treated as negative)
    expired_xml = _force_expired(signed_xml)
    (target / "idp_response_expired.xml.b64").write_bytes(_b64(expired_xml))
    print("wrote idp_response_expired.xml.b64")

    # 4. Unsigned
    unsigned_xml = _build_unsigned_response_xml(server)
    (target / "idp_response_unsigned.xml.b64").write_bytes(_b64(unsigned_xml))
    print("wrote idp_response_unsigned.xml.b64")

    # 5. XSW attack
    xsw_xml = _build_xsw_attack_xml(signed_xml)
    (target / "idp_response_xsw.xml.b64").write_bytes(_b64(xsw_xml))
    print("wrote idp_response_xsw.xml.b64")


if __name__ == "__main__":
    main()  # output_dir=None → target = HERE; manual CLI behavior preserved.
