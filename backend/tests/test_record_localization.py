from types import SimpleNamespace

from starlette.requests import Request

from app.modules.catalog.records.localization import select_localized_record_text
from app.standards.ogc.utils import parse_accept_language, parse_accept_languages


def _request(header: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"accept-language", header.encode())],
        }
    )


def _record():
    return SimpleNamespace(
        language="en",
        title="Rivers",
        summary="River networks",
        translations=[
            SimpleNamespace(language="fr", title="Rivières", summary="Réseaux"),
            SimpleNamespace(language="pt-BR", title="Rios brasileiros", summary=None),
        ],
    )


def test_parse_accept_languages_honors_quality_and_zero_weight():
    request = _request("de;q=0, pt-BR;q=0.8, fr-CA;q=0.9, en;q=0.7")
    assert parse_accept_languages(request) == ["fr-CA", "pt-BR", "en"]


def test_ui_language_parser_remains_restricted_to_supported_languages():
    request = _request("pt-BR, fr;q=0.8")
    assert parse_accept_language(request) == "fr"


def test_localized_text_prefers_exact_then_base_language():
    exact = select_localized_record_text(_record(), ["pt-BR"])
    assert (exact.language, exact.title) == ("pt-BR", "Rios brasileiros")

    base = select_localized_record_text(_record(), ["fr-CA"])
    assert (base.language, base.title, base.summary) == (
        "fr",
        "Rivières",
        "Réseaux",
    )


def test_localized_text_falls_back_to_primary_and_reports_actual_language():
    selected = select_localized_record_text(_record(), ["ja"])
    assert (selected.language, selected.title, selected.summary) == (
        "en",
        "Rivers",
        "River networks",
    )


def test_localized_text_uses_script_aware_progressive_lookup():
    record = SimpleNamespace(
        language="en",
        title="Chinese maps",
        summary=None,
        translations=[
            SimpleNamespace(language="zh-Hans", title="简体", summary=None),
            SimpleNamespace(language="zh-Hant", title="繁體", summary=None),
        ],
    )

    selected = select_localized_record_text(record, ["zh-Hant-TW"])

    assert (selected.language, selected.title) == ("zh-Hant", "繁體")


def test_parse_accept_languages_rejects_invalid_quality_and_tags():
    request = _request("fr;q=1.1, de;q=NaN, es;q=Infinity, not_a_tag, zh-Hant;q=0.8")
    assert parse_accept_languages(request) == ["zh-Hant"]
