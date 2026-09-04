"""Security tests for URL query credential rejection/redaction."""

import random
import time
from urllib.parse import urlsplit

import pytest
from pydantic import ValidationError

from app.core.url_redaction import (
    has_url_credentials,
    redact_query_credentials,
    redact_url_credentials,
)
from app.modules.catalog.datasets.domain.schemas import (
    DatasetMeta,
    ReuploadServicePreviewRequest,
)
from app.modules.catalog.sources.schemas import ProbeRequest, ServicePreviewRequest
from app.modules.catalog.sources.stac_router import StacConnectRequest, StacImportItem


def test_redact_url_credentials_masks_sensitive_query_values() -> None:
    redacted = redact_url_credentials(
        "https://example.com/wfs?f=json&token=secret&X-Amz-Signature=sig"
    )

    assert "secret" not in redacted
    assert "sig" not in redacted
    assert "f=json" in redacted
    assert "token=%3Credacted%3E" in redacted
    assert "X-Amz-Signature=%3Credacted%3E" in redacted


@pytest.mark.parametrize(
    "value",
    [
        "https://?token=secret",
        "https:///path?token=secret",
        "ESRIJSON:https://?token=secret",
        "ogrinfo failed for https://?token=secret and bailed",
    ],
)
def test_redact_url_credentials_empty_host_terminates_and_masks(value: str) -> None:
    # fix(#429 review): an http(s) URL with an empty host previously matched the
    # whole string in the regex fallback and recursed forever (RecursionError).
    # It must terminate and still mask the secret.
    redacted = redact_url_credentials(value)
    assert "secret" not in redacted


# fix(#1116): URL_LIKE_RE's optional scheme prefix used an unbounded `+`, which
# is ambiguous against the `https?` that follows. A long run of prefix-class
# characters that never completes a match made the engine retry every prefix
# length at every start position — O(n²). Free text reaches that fallback from
# GDAL/ogr2ogr stderr and uploaded-VRT <SourceFilename> values, so the run is
# attacker-influenced. Measured in-pytest on this commit (pytest --durations, not
# a standalone bench): the 200 KB run below takes 0.03s with the {1,64} bound and
# 33s without it, so the threshold has ~65x headroom for a slow CI runner while
# staying far out of reach for the quadratic form. Keep that figure in-pytest — a
# standalone bench reports a rosier 0.02s/~86x, which is not what governs whether
# this test flakes.
REDOS_INPUT_CHARS = 200_000
REDOS_THRESHOLD_S = 2.0


# Deliberately NOT marked @pytest.mark.perf. backend/pyproject.toml:163 sets
# addopts = "-m 'not perf' --dist loadgroup", so that marker deselects a test from
# both `make test` and CI — adding it here would ship a ReDoS guard that never
# runs. This test costs 0.03s, so it does not need the marker that the genuinely
# slow perf-suite tests carry.
def test_redact_url_credentials_stays_linear_on_hostile_alphanumeric_run() -> None:
    hostile = "a" * REDOS_INPUT_CHARS

    start = time.perf_counter()
    result = redact_url_credentials(hostile)
    elapsed = time.perf_counter() - start

    # Nothing here looks like a URL, so it must come back untouched. Asserting
    # this keeps the timing check honest: a regex that matched nothing at all
    # would be fast but would stop redacting.
    assert result == hostile
    assert elapsed < REDOS_THRESHOLD_S, (
        f"redacting {REDOS_INPUT_CHARS} non-URL characters took {elapsed:.2f}s "
        f"(threshold {REDOS_THRESHOLD_S}s) — the URL_LIKE_RE scheme prefix is "
        "backtracking quadratically again"
    )


@pytest.mark.parametrize("prefix_len", [1, 63, 64, 65, 200, 5_000])
def test_redact_url_credentials_masks_userinfo_behind_long_scheme_prefix(
    prefix_len: int,
) -> None:
    # fix(#1116): bounding the scheme prefix must not let a credential escape
    # when the GDAL-style prefix is longer than the bound. It cannot: the match
    # just starts later in the string and still covers the whole URL.
    value = "A" * prefix_len + ":https://user:secret@example.com/cog.tif"

    redacted = redact_url_credentials(value)

    assert "secret" not in redacted
    assert "redacted@example.com" in redacted


def test_redact_url_credentials_masks_url_after_long_free_text_run() -> None:
    # fix(#1116): the bounded prefix must still find a credential URL sitting
    # behind a long run of prefix-class characters (the GDAL-stderr shape).
    value = "a" * 100_000 + " https://user:secret@example.com/x?token=t0ken"

    redacted = redact_url_credentials(value)

    assert "secret" not in redacted
    assert "t0ken" not in redacted
    assert "redacted@example.com" in redacted
    assert "token=%3Credacted%3E" in redacted


# fix(#1119): urlsplit raises ValueError on a malformed bracketed authority and
# redact_url_credentials let it escape, so a call whose entire contract is "return
# something safe to log" raised instead. sources/preview.py and the three
# processing/ingest/validation.py sites interpolate the result into an
# IngestionError, so a malformed authority in GDAL stderr or in an uploaded VRT's
# <SourceFilename> became an unhandled 500 rather than a clean ingest failure.
#
# Checked against CPython 3.13 (what CI pins) and 3.14, which agree on all of
# these. Every entry makes urlsplit raise except ":notaport", which parses; there
# the ValueError comes from SplitResult.port, read only when userinfo is present,
# and _redacted_netloc already guards that read. It is in the list to keep that
# guard pinned alongside the new one, not because it reproduces #1119.
MALFORMED_AUTHORITY_URLS = [
    "https://.[::1]",  # data before the opening bracket
    "https://[::1",  # unclosed bracket
    "https://]::1[",  # closing bracket before the opening one
    "https://[]",  # empty bracketed host
    "https://[::1]x",  # data after the bracket with no port delimiter
    "https://[[::1]]",  # nested brackets
    "https://[127.0.0.1]",  # IPv4 in brackets
    "https://[vZ.x]",  # malformed IPvFuture
    "https://[::1]:notaport",  # non-numeric port
    "//[::1",  # scheme-less unclosed bracket
]

# Malformed authorities that also carry a credential. Making the function stop
# raising is easy to get wrong in the one way that matters: a fallback returning
# the input verbatim trades a 500 for a credential leak, which is strictly worse
# than the bug. Every secret below is the same literal so the assertion is blunt.
CREDENTIALED_MALFORMED_URLS = [
    "https://user:hunter2@.[::1]/cog.tif",
    "https://user:hunter2@[::1/cog.tif",
    "https://user:hunter2@[[::1]]/cog.tif",
    "https://user:hunter2@[::1]:notaport/cog.tif",
    "https://.[::1]/wfs?f=json&token=hunter2",
    "https://[::1/wfs?api_key=hunter2",
    "https://[]/x?X-Amz-Signature=hunter2",
    # An encoded parameter name: parse_qsl unquotes on the parsed path, so the
    # unparsable path has to as well or the two disagree about what is sensitive.
    "https://[vZ.x]/x?%74oken=hunter2",
    # fix(#1119 review): urlsplit deletes \t, \r and \n before parsing, so any
    # reader that does not delete them is judging a different string. That gap
    # leaked in three positions — the fallback's userinfo match, the fallback's
    # query-NAME match, and (widest, and reachable only through the free-text
    # wrapper below) URL_LIKE_RE truncating at the control character and handing
    # the recursion a token with no `@` left in it.
    "https://user:hunter2\n@[::1",
    "https://user:hunter2\t@[::1",
    "https://user:hunter2\r\n@[::1]/cog.tif",
    "https://[::1?to\nken=hunter2",
    "ESRIJSON:https://user:hunter2\n@[::1",
    # fix(#1119 review 3): urlsplit's _checknetloc refuses a netloc BECAUSE NFKC
    # would introduce one of /?#@: — so these reach the fallback for a reason the
    # ASCII patterns cannot see until the value is normalised the same way.
    "https://user:hunter2＠example.com/path",
    "https://example.com？token=hunter2",
    # fix(#1119 review 4): the other direction — NFKC INTRODUCES a delimiter
    # mid-credential and truncates a match that was intact in the raw view.
    "https://user:hunter2／@[::1",
    "https://[::1?token=prefix＃hunter2",
]

# fix(#1119 review 4): the two NFKC directions are one class, so sweep it rather
# than pinning the four strings that happened to get reported. Each of these
# characters normalises to a URL delimiter, so dropping one into a credential
# either reveals a boundary the raw view cannot see or invents one that
# truncates the raw view's match — and the fallback has to survive both.
NFKC_DELIMITER_EQUIVALENTS = ["＠", "／", "？", "＃", "：", "＆", "＝"]

# fix(#1119 review 2): urlsplit ends an authority at `/?#` and parse_qsl ends a
# query value at `&`/`#` — neither stops at whitespace. Delimiting the fallback
# patterns on `\s` made them keep MORE than the parsed path would, which is the
# one thing the fallback is not allowed to do.
#
# These are DIRECT-CALL ONLY, and deliberately not in the list above. Inside free
# text a space genuinely ends the URL: URL_LIKE_RE stops there, so the recursion
# never receives the tail and no redactor downstream can. That is not a gap in
# the fallback — the PARSED path is identical, measured:
#
#   "ogrinfo failed: https://example.com?token=prefix hunter2 bad"
#     -> "...token=%3Credacted%3E hunter2 bad"     (well-formed URL, parsed path)
#
# so the invariant still holds in free text. Widening URL_LIKE_RE to span spaces
# would swallow the remainder of every stderr sentence into "the URL" and reopen
# the unbounded-quantifier backtracking #1116 exists to prevent.
WHITESPACE_CREDENTIALED_MALFORMED_URLS = [
    "https://user:hunter 2@[::1",
    "https://[::1?token=prefix hunter2",
    "https://user:hunter\x0c2@[::1",
    "https://[::1?token=prefix\x0bhunter2",
]


@pytest.mark.parametrize("value", MALFORMED_AUTHORITY_URLS)
def test_redact_url_credentials_never_raises_on_malformed_authority(
    value: str,
) -> None:
    assert isinstance(redact_url_credentials(value), str)


@pytest.mark.parametrize("value", MALFORMED_AUTHORITY_URLS)
def test_redact_url_credentials_never_raises_on_malformed_authority_in_free_text(
    value: str,
) -> None:
    # A different code path from the bare-URL form above: the free text parses
    # fine and the ValueError surfaces from inside the URL_LIKE_RE.sub callback
    # recursing on the matched substring. This is the shape GDAL/ogr2ogr stderr
    # and source-preview text actually arrive in, so covering only the bare form
    # would be narrower than it reads.
    assert isinstance(redact_url_credentials(f"ogrinfo failed: {value} bad"), str)


@pytest.mark.parametrize("value", CREDENTIALED_MALFORMED_URLS)
def test_redact_url_credentials_masks_credentials_in_unparsable_url(
    value: str,
) -> None:
    assert "hunter2" not in redact_url_credentials(value)


@pytest.mark.parametrize("value", CREDENTIALED_MALFORMED_URLS)
def test_redact_url_credentials_masks_credentials_in_unparsable_free_text(
    value: str,
) -> None:
    assert "hunter2" not in redact_url_credentials(f"ogrinfo failed: {value} bad")


@pytest.mark.parametrize("delimiter", NFKC_DELIMITER_EQUIVALENTS)
@pytest.mark.parametrize(
    "template",
    [
        "https://user:hunter{d}2@[::1",
        "https://user:hunter2{d}@[::1",
        "https://user{d}:hunter2@[::1",
        "https://[::1?token=prefix{d}hunter2",
        # NOT tested: a delimiter inside the parameter NAME ("to{d}ken"). None of
        # these characters vanishes under NFKC, so "to＠ken" normalises to
        # "to@ken" and is a genuinely different parameter from "token" — the
        # PARSED path keeps it too, measured: redact_url_credentials(
        # "https://example.com?to＠ken=hunter2") returns it unchanged. Asserting
        # on it would demand the fallback out-redact the reference it is defined
        # against, which is how a redactor starts destroying valid data.
    ],
)
def test_redact_url_credentials_survives_nfkc_delimiters_anywhere(
    template: str, delimiter: str
) -> None:
    value = template.format(d=delimiter)
    redacted = redact_url_credentials(value)
    assert "hunter" not in redacted, f"{value!r} -> {redacted!r}"
    assert "hunter" not in redact_url_credentials(f"ogrinfo failed: {value} bad")


@pytest.mark.parametrize(
    ("unparsable", "parsable_equivalent"),
    [
        # ＃ normalises to a fragment delimiter, so the tail is a FRAGMENT.
        (
            "https://[::1？token=prefix＃hunter2",
            "https://example.com?token=prefix#hunter2",
        ),
        # ／ normalises to a path delimiter, so there is no userinfo at all:
        # urlsplit reports username=None, password=None, netloc='user:hunter2'.
        ("https://user:hunter2／＠[::1", "https://user:hunter2/@example.com"),
    ],
)
def test_fallback_does_not_out_redact_the_parsed_path(
    unparsable: str, parsable_equivalent: str
) -> None:
    """The fallback keeps exactly what the parsed path keeps — no more, no less.

    fix(#1119 review 5): both shapes were reported as fallback leaks. They are
    not. Once normalised, the tail of the first is a fragment and the second has
    no userinfo for any client to resolve, so the PRIMARY path keeps them too —
    asserted below so this stays a measurement rather than an argument.

    This is the invariant the whole fallback is defined against, and it cuts both
    ways. If the primary path is ever tightened to redact fragments or
    port-position material, this test fails and the fallback must follow rather
    than quietly diverge. Contrast the round-3 case, which WAS a real leak: there
    ＠ normalises to a genuine `@`, so an NFKC-normalising client resolves real
    userinfo, which is precisely why `_checknetloc` refuses the string.
    """
    assert "hunter2" in redact_url_credentials(parsable_equivalent)
    assert "hunter2" in redact_url_credentials(unparsable)


@pytest.mark.parametrize("value", WHITESPACE_CREDENTIALED_MALFORMED_URLS)
def test_redact_url_credentials_masks_credentials_across_inner_whitespace(
    value: str,
) -> None:
    # Assert on the stem, not on "hunter2"/"hunter 2": with a form feed or
    # vertical tab between the halves the literal never appears in the output
    # either way, so those two cases would pass vacuously and the RED check
    # would look like proof while covering nothing.
    assert "hunter" not in redact_url_credentials(value)


@pytest.mark.parametrize(
    ("value", "kept"),
    [
        # fix(#1119 review 2): the admission half of the widened delimiters. A
        # refusal assertion cannot notice that a legitimate input started being
        # destroyed, so the non-sensitive cases are pinned separately — widening
        # `[^&#\s]` to `[^&#]` must not swallow a benign value or the text after
        # it, and must not invent a userinfo where the string has no `@`.
        ("https://[::1?f=json text", "json text"),
        ("https://[::1?f=json&token=x", "f=json"),
        ("ogrinfo failed: https://[::1 no credentials here", "no credentials here"),
    ],
)
def test_redact_url_credentials_keeps_non_sensitive_text_in_unparsable_url(
    value: str, kept: str
) -> None:
    assert kept in redact_url_credentials(value)


def test_redact_url_credentials_keeps_free_text_around_an_unparsable_url() -> None:
    # The unparsable fallback deletes credentials in place rather than dropping
    # the string, so the stderr line an operator needs is still readable and a
    # non-sensitive parameter survives — same as on the parsed path.
    redacted = redact_url_credentials(
        "ogrinfo failed: https://user:hunter2@.[::1]/wfs?f=json&token=hunter2 exiting"
    )

    assert "hunter2" not in redacted
    assert redacted.startswith("ogrinfo failed: ")
    assert redacted.endswith(" exiting")
    assert "redacted@" in redacted
    assert "f=json" in redacted


FUZZ_SEED = 1119
FUZZ_ITERATIONS = 2_000
FUZZ_ALPHABET = [*"ab:/[]@?&=.%#-_ +1", "https://", "http://", "::1", "token="]


def test_redact_url_credentials_never_raises_on_randomized_input() -> None:
    # The list above is a sample; the property callers depend on is "never
    # raises, for any input". This is the differential fuzz that turned up #1119,
    # seeded so a failure is reproducible. Against the unfixed function it raises
    # ValueError on roughly one input in eight, so it is not a decorative test.
    rng = random.Random(FUZZ_SEED)

    for _ in range(FUZZ_ITERATIONS):
        value = "".join(rng.choice(FUZZ_ALPHABET) for _ in range(rng.randint(1, 14)))
        try:
            redact_url_credentials(value)
        except Exception as exc:
            pytest.fail(f"redact_url_credentials({value!r}) raised {exc!r}")


def test_redact_query_credentials_preserves_non_sensitive_query() -> None:
    assert redact_query_credentials("f=json&where=1%3D1") == "f=json&where=1%3D1"


# fix(#1755 item 7 lane B3): "authkey" (ArcGIS) and "maxar_api_key" (Maxar)
# joined SENSITIVE_QUERY_PARAMS alongside the existing generic names. One
# case per name, plus the mixed-case spelling since matching is
# case-insensitive (_is_sensitive_query_param lowercases before comparing).
@pytest.mark.parametrize(
    "param_name",
    [
        "authkey",
        "AuthKey",
        "AUTHKEY",
        "maxar_api_key",
        "Maxar_Api_Key",
        "MAXAR_API_KEY",
    ],
)
def test_redact_query_credentials_masks_authkey_and_maxar_api_key(
    param_name: str,
) -> None:
    redacted = redact_query_credentials(f"f=json&{param_name}=secret")

    assert "secret" not in redacted
    assert "f=json" in redacted


def test_redact_query_credentials_leaves_unrelated_param_untouched() -> None:
    # Positive control: a param name that merely contains "key" as a
    # substring ("keyword") must not be treated as sensitive by the new
    # entries, and its value must survive redaction unchanged.
    assert (
        redact_query_credentials("keyword=roads&authkey=secret")
        == "keyword=roads&authkey=%3Credacted%3E"
    )


def test_has_url_credentials_detects_blank_sensitive_param() -> None:
    assert has_url_credentials("https://example.com/arcgis?token=")


def test_has_url_credentials_detects_userinfo() -> None:
    assert has_url_credentials("https://user:secret@example.com/cog.tif")


@pytest.mark.parametrize(
    "url",
    [
        "ESRIJSON:https://user:pass@evil/x",
        "WFS:https://user:pass@evil/x",
    ],
)
def test_has_url_credentials_detects_userinfo_behind_gdal_prefix(url: str) -> None:
    # fix(#430 BA-04): urlsplit sees scheme 'esrijson'/'wfs' with no netloc, so
    # .username/.password were None and the credential slipped through. The
    # validator must strip the GDAL prefix before inspecting userinfo.
    assert has_url_credentials(url)


def _urlsplit_rejects(value: str) -> bool:
    try:
        urlsplit(value)
    except ValueError:
        return True
    return False


# fix(#1132): has_url_credentials carried the identical unguarded urlsplit — the
# mirror #430 BA-04 established between these two functions never reached the
# error path. It is therefore measured against the SAME inputs as its sibling
# rather than a fresh list, so the two cannot drift apart again silently.
#
# The list is partitioned, not reused whole: ":notaport" parses, and its
# ValueError comes from SplitResult.port, which this function never reads. So it
# belongs on the admission side, and splitting by the guard's actual
# precondition beats a hand-written exception that rots as the list grows.
UNPARSABLE_AUTHORITY_URLS = [
    value for value in MALFORMED_AUTHORITY_URLS if _urlsplit_rejects(value)
]
PARSABLE_MALFORMED_AUTHORITY_URLS = [
    value for value in MALFORMED_AUTHORITY_URLS if not _urlsplit_rejects(value)
]


def test_malformed_authority_partition_has_both_halves() -> None:
    # A partition computed at import time can quietly empty out, and an empty
    # parametrize list is a test that passes while asserting nothing. Both of
    # the two tests below depend on this, so assert it once rather than
    # discovering it as a silently green suite.
    assert UNPARSABLE_AUTHORITY_URLS
    assert PARSABLE_MALFORMED_AUTHORITY_URLS


@pytest.mark.parametrize("value", MALFORMED_AUTHORITY_URLS)
def test_has_url_credentials_never_raises_on_malformed_authority(value: str) -> None:
    assert isinstance(has_url_credentials(value), bool)


@pytest.mark.parametrize("value", UNPARSABLE_AUTHORITY_URLS)
def test_has_url_credentials_refuses_an_unparsable_authority(value: str) -> None:
    """A detector that cannot parse must not answer "no".

    fix(#1132): returning False is the smaller change and the worse answer. The
    caller that matters is _metadata_contains_secret in
    modules/catalog/sources/router.py, which asks this question of every string
    in a caller-supplied connector config — so False makes the inline-secret gate
    silently permissive on exactly the malformed input an attacker controls.
    Refusing is self-correcting: it surfaces as a 400 somebody has to look at.
    """
    assert has_url_credentials(value) is True


@pytest.mark.parametrize("value", PARSABLE_MALFORMED_AUTHORITY_URLS)
def test_has_url_credentials_admits_what_the_parser_accepts(value: str) -> None:
    # The admission half. A refusal assertion cannot notice the guard widening
    # into "anything bracket-shaped is a credential" and starting to reject
    # legitimate config, so the parsing entries are pinned separately.
    assert has_url_credentials(value) is False


@pytest.mark.parametrize("value", CREDENTIALED_MALFORMED_URLS)
def test_has_url_credentials_detects_credentials_in_malformed_url(value: str) -> None:
    # The property the gate actually depends on: no credential is ever reported
    # as absent because the parser gave up on the string carrying it.
    assert has_url_credentials(value) is True


def test_has_url_credentials_never_raises_on_randomized_input() -> None:
    # fix(#1132): the sibling of the #1119 differential fuzz, same seed and
    # alphabet so both functions are held to the same "never raises, for any
    # input" property over the same corpus. Against the unguarded function this
    # raises ValueError; it is not a decorative test.
    rng = random.Random(FUZZ_SEED)

    for _ in range(FUZZ_ITERATIONS):
        value = "".join(rng.choice(FUZZ_ALPHABET) for _ in range(rng.randint(1, 14)))
        try:
            has_url_credentials(value)
        except Exception as exc:
            pytest.fail(f"has_url_credentials({value!r}) raised {exc!r}")


def test_redact_url_credentials_masks_userinfo_and_gcs_signature() -> None:
    redacted = redact_url_credentials(
        "ESRIJSON:https://user:secret@example.com/cog.tif?"
        "X-Goog-Credential=credential&X-Goog-Signature=signature&f=json"
    )

    assert "user:secret" not in redacted
    assert "credential" not in redacted
    assert "signature" not in redacted
    assert "f=json" in redacted
    assert "redacted@example.com" in redacted
    assert "X-Goog-Credential=%3Credacted%3E" in redacted
    assert "X-Goog-Signature=%3Credacted%3E" in redacted


@pytest.mark.parametrize("model", [ProbeRequest, ServicePreviewRequest])
def test_service_requests_reject_credential_query_params(model) -> None:
    kwargs = {"url": "https://example.com/service?token=secret"}
    if model is ServicePreviewRequest:
        kwargs.update({"service_type": "WFS 2.0.0", "layer_name": "roads"})

    with pytest.raises(ValidationError):
        model(**kwargs)


def test_stac_connect_rejects_credential_query_params() -> None:
    with pytest.raises(ValidationError):
        StacConnectRequest(url="https://example.com/stac?api_key=secret")


def test_stac_connect_rejects_url_userinfo() -> None:
    with pytest.raises(ValidationError):
        StacConnectRequest(url="https://user:secret@example.com/stac")


def test_stac_import_item_rejects_signed_asset_href() -> None:
    with pytest.raises(ValidationError):
        StacImportItem(
            id="item-1",
            title="Item 1",
            data_asset_href="https://example.com/cog.tif?X-Amz-Signature=secret",
        )


def test_reupload_service_preview_rejects_credential_query_params() -> None:
    with pytest.raises(ValidationError):
        ReuploadServicePreviewRequest(
            url="https://example.com/wfs?token=secret",
            service_type="WFS 2.0.0",
            layer_name="roads",
        )


def test_dataset_meta_source_url_rejects_credentials() -> None:
    with pytest.raises(ValidationError):
        DatasetMeta(source_url="https://example.com/cog.tif?X-Goog-Signature=secret")

    with pytest.raises(ValidationError):
        DatasetMeta(source_url="https://user:secret@example.com/cog.tif")
