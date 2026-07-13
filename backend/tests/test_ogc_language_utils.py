from app.standards.ogc.utils import (
    content_language_for_record_languages,
    link_header_value,
    normalize_language_tag,
    standards_api_path,
)


def test_normalize_language_tag_canonicalizes_basic_tags():
    assert normalize_language_tag("ES") == "es"
    assert normalize_language_tag("pt_br") == "pt-BR"
    assert normalize_language_tag("  fr-ca  ") == "fr-CA"
    assert normalize_language_tag("zh-hANT-tw") == "zh-Hant-TW"
    assert normalize_language_tag("not_a_valid_tag") is None


def test_content_language_for_record_languages_uses_homogeneous_language():
    assert content_language_for_record_languages(["es", "ES"]) == "es"
    assert content_language_for_record_languages(["fr-CA", "fr_ca"]) == "fr-CA"


def test_content_language_for_record_languages_omits_mixed_languages():
    assert content_language_for_record_languages(["es", "fr"]) is None


def test_content_language_for_record_languages_falls_back_for_empty_pages():
    assert content_language_for_record_languages([]) == "en"
    assert content_language_for_record_languages([None, ""]) == "en"


def test_link_header_value_serializes_navigation_links():
    value = link_header_value(
        [
            {
                "href": "https://api.example/collections?offset=1",
                "rel": "next",
                "type": "application/json",
            }
        ]
    )
    assert value == (
        '<https://api.example/collections?offset=1>; rel="next"; '
        'type="application/json"'
    )


def test_standards_api_path_recognizes_nested_dcat_routes():
    assert standards_api_path("/datasets/dcat/") == "/datasets/dcat/"
    assert (
        standards_api_path("/datasets/abc/dcat-us/3.0/") == "/datasets/abc/dcat-us/3.0/"
    )
    assert (
        standards_api_path("/api/datasets/abc/geodcat-ap/", root_path="/api")
        == "/datasets/abc/geodcat-ap/"
    )
    assert standards_api_path("/datasets/abc") is None
