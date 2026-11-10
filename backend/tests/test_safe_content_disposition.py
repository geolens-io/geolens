"""The download header can't be broken out of by the filename it carries."""

from app.processing.export.service import safe_content_disposition


def test_quote_backslash_and_controls_become_underscores():
    header = safe_content_disposition('a"b\\c\r\nd\te\x7f.csv')

    ascii_part, _, encoded_part = header.partition("; filename*=")
    assert ascii_part == 'attachment; filename="a_b_c__d_e_.csv"'
    assert encoded_part == "UTF-8''a%22b%5Cc%0D%0Ad%09e%7F.csv"
    assert "\r" not in header and "\n" not in header


def test_plain_and_non_ascii_names_are_unchanged():
    assert safe_content_disposition("export.csv") == (
        "attachment; filename=\"export.csv\"; filename*=UTF-8''export.csv"
    )
    assert safe_content_disposition("café.csv") == (
        "attachment; filename=\"caf?.csv\"; filename*=UTF-8''caf%C3%A9.csv"
    )
