from app.standards.ogc.utils import (
    content_language_for_record_languages,
    normalize_language_tag,
)


def test_normalize_language_tag_canonicalizes_basic_tags():
    assert normalize_language_tag("ES") == "es"
    assert normalize_language_tag("pt_br") == "pt-BR"
    assert normalize_language_tag("  fr-ca  ") == "fr-CA"


def test_content_language_for_record_languages_uses_homogeneous_language():
    assert content_language_for_record_languages(["es", "ES"]) == "es"
    assert content_language_for_record_languages(["fr-CA", "fr_ca"]) == "fr-CA"


def test_content_language_for_record_languages_omits_mixed_languages():
    assert content_language_for_record_languages(["es", "fr"]) is None


def test_content_language_for_record_languages_falls_back_for_empty_pages():
    assert content_language_for_record_languages([]) == "en"
    assert content_language_for_record_languages([None, ""]) == "en"
