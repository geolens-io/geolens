"""SEC-09: SVG icon validator re-serializes via defusedxml so attribute-encoded
bypasses are rejected.

Pins the v13.13 closure of M-71. The original denylist (script tag,
foreignObject, javascript:, on*=) matched literal byte strings only; entity
encodings like &lt;script&gt; or &#106;avascript: slipped through. After this
plan, defusedxml re-serializes the SVG, normalizing entities into canonical
bytes BEFORE the denylist runs.
"""

from io import BytesIO

import pytest
from PIL import Image

from app.modules.catalog.maps.sprites import validate_icon_upload


def _png_bytes() -> bytes:
    """Return a real 1x1 RGBA PNG (PIL-encoded). Mirrors test_map_sprites helper."""
    out = BytesIO()
    Image.new("RGBA", (1, 1), (255, 0, 0, 255)).save(out, format="PNG")
    return out.getvalue()


VALID_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    b'<circle cx="12" cy="12" r="10"/></svg>'
)


def test_valid_svg_round_trips_via_defusedxml():
    """A clean SVG passes validation and the returned content is the
    defusedxml-canonicalized form (still parses, still has the namespace)."""
    slug, media_type, sanitized = validate_icon_upload(
        "plain.svg", "image/svg+xml", VALID_SVG
    )
    assert media_type == "image/svg+xml"
    assert b"<circle" in sanitized
    # Re-serialized bytes preserve the namespace declaration so MapLibre /
    # downstream sprite consumers still parse it correctly.
    assert b"http://www.w3.org/2000/svg" in sanitized


def test_text_encoded_script_is_serialized_as_text_not_active_tag():
    """An SVG with &lt;script&gt;...&lt;/script&gt; as text content (NOT a real
    tag) is re-serialized as text by defusedxml, so the denylist does not
    fire — this documents the residual: the denylist alone would not catch a
    text-encoded payload, which is why Task 2's CSP sandbox header is the
    second defense layer."""
    payload = (
        b'<svg xmlns="http://www.w3.org/2000/svg">'
        b"&lt;script&gt;alert(1)&lt;/script&gt;</svg>"
    )
    slug, media_type, sanitized = validate_icon_upload(
        "text-encoded.svg", "image/svg+xml", payload
    )
    # The entity-encoded text remains entity-encoded after re-serialization
    # (text content is not auto-converted into a tag). This is the documented
    # residual closed by the CSP sandbox in Task 2.
    assert media_type == "image/svg+xml"
    assert b"&lt;script&gt;" in sanitized


def test_numeric_entity_in_attribute_normalized_then_rejected():
    """href="&#106;avascript:alert(1)" — numeric entity for 'j' — is
    normalized by defusedxml into literal `javascript:`, then the denylist
    rejects it. This is the real bypass vector closed by SEC-09."""
    payload = (
        b'<svg xmlns="http://www.w3.org/2000/svg" '
        b'xmlns:xlink="http://www.w3.org/1999/xlink">'
        b'<a xlink:href="&#106;avascript:alert(1)" /></svg>'
    )
    with pytest.raises(ValueError, match="active content"):
        validate_icon_upload("encoded-href.svg", "image/svg+xml", payload)


def test_event_handler_still_rejected():
    """Regression: event handlers like onclick="..." are still caught by the
    denylist after re-serialization (defusedxml preserves attribute names)."""
    payload = (
        b'<svg xmlns="http://www.w3.org/2000/svg">'
        b'<circle onclick="alert(1)" cx="5" cy="5" r="5"/></svg>'
    )
    with pytest.raises(ValueError, match="active content"):
        validate_icon_upload("clickable.svg", "image/svg+xml", payload)


def test_literal_script_tag_still_rejected():
    """Regression: a literal <script> tag is still rejected (the plain-bytes
    case the original denylist already caught)."""
    payload = b'<svg xmlns="http://www.w3.org/2000/svg"><script>x</script></svg>'
    with pytest.raises(ValueError, match="active content"):
        validate_icon_upload("scripted.svg", "image/svg+xml", payload)


def test_png_unchanged_by_svg_path():
    """PNG content is returned bytewise-unchanged; the SVG re-serialization
    branch does not run."""
    png = _png_bytes()
    slug, media_type, sanitized = validate_icon_upload(
        "dot.png", "image/png", png
    )
    assert media_type == "image/png"
    # PNG path returns content unchanged
    assert sanitized == png


def test_malformed_xml_rejected():
    """Truncated / malformed XML raises a clean ValueError, not an XML
    parser exception that surfaces to the request handler."""
    payload = b"<svg><circle"  # truncated, malformed
    with pytest.raises(ValueError, match="SVG icon content is invalid"):
        validate_icon_upload("broken.svg", "image/svg+xml", payload)
