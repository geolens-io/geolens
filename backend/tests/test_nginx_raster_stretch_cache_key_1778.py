"""The raster tile cache key must not vary on an arg the active stretch mode
ignores, and a cache HIT must never change what an uncached request would
answer (#1778, codebase audit 2026-08-30; codex rounds 1-4 on #1791).

frontend/nginx.conf's raster_cache proxy_cache_key used to hold
$arg_pmin/$arg_pmax/$arg_sigma unconditionally. In
backend/app/processing/tiles/router.py, stretch=percentile is the only mode
that reads pmin/pmax (_compute_stretch_rescale) and stretch=stddev is the only
mode that reads sigma; stretch=minmax (the default) or an absent stretch reads
neither -- the fragment passed to Titiler is unchanged either way. So
``?stretch=minmax&pmin=<random>`` produced a fresh cache key holding bytes
byte-identical to the unfiltered tile, the same defeat #1785 closed for the
vector tile ``cols=`` param.

Round 1 blanked every inactive value unconditionally, which could let a
cache HIT answer with a status an uncached request would not have gotten.
Round 2 made raster_tile_proxy IGNORE pmin/pmax when stretch is not
percentile and sigma when it is not stddev, instead of merely leaving them
unvalidated, so blanking an inactive value can no longer disagree with the
API about STATUS. Round 3 found nginx's raw read of the query string can
still disagree with the API's decoded read about VALUE or MODE independent
of validation (percent-encoded or case-varied `stretch`, a malformed float),
and required an EXACT canonical spelling plus well-formedness before
blanking.

Round 4 found round 3's exact-spelling check assumed nginx's own $arg_NAME
lookup is case-sensitive on the parameter NAME. It is not: nginx's arg
matcher (ngx_http_arg -> ngx_strlcasestrn) is case-INSENSITIVE on the name,
so $arg_stretch resolves from `Stretch=`, `STRETCH=`, etc, while FastAPI's
query-param binding is exact-case. `?Stretch=minmax&stretch=percentile&pmin=5`
had nginx read stretch=minmax (the first case-insensitive match, "inactive",
blank pmin) while the API read stretch=percentile (the only EXACT-case
match, active, uses pmin=5) -- a cache collision, not a status mismatch,
because round 3's duplicate detector was itself case-sensitive-only and
never saw this as a duplicate at all.

The round-4 rule: blanking is allowed ONLY when $args is in STRICT CANONICAL
FORM -- each of stretch/pmin/pmax/sigma appears at most once (checked
CASE-INSENSITIVELY), every occurrence of each is spelled EXACTLY lowercase,
and none is percent-encoded. $geolens_raster_noncanonical checks this
directly against the raw $args string (not derived from any single $arg_*
lookup, so it cannot inherit nginx's own case-insensitivity or decoding
blind spots). When non-canonical, $geolens_raster_cache_extra folds the
ENTIRE raw $args into the cache key, so correctness there is independent of
any per-parameter reasoning: two requests share a key in the non-canonical
case if and only if their raw query strings are identical.

These are structural (they read the conf and simulate nginx's own map
evaluation in Python), because there is no nginx binary in this test
environment to render and query directly. The simulation models nginx's
actual matching semantics precisely where it matters here:
  - $arg_NAME lookup is case-INSENSITIVE on the name (see _nginx_arg).
  - map regex matching searches the WHOLE string (like re.search), not
    anchored at position 0 (like re.match) -- a pattern such as
    ``(?:^|&)stretch=.*(?:^|&)stretch=`` must still find a duplicate whose
    first occurrence is not at the very start of $args.
  - a map entry's regex can independently be case-sensitive (``~pattern``)
    or case-insensitive (``~*pattern``), exactly as nginx's map directive
    supports per entry.

The companion API-level pin lives in test_raster_colormap_proxy.py::
TestRasterColormapProxy::
test_out_of_range_bounds_are_ignored_under_an_inactive_stretch_mode, which
confirms the API side of the contract these maps rely on: pmin/pmax/sigma
are ignored, not validated, whenever the active stretch mode does not read
them.
"""

import re

from tests.repo_paths import repo_root

NGINX_CONF = repo_root(__file__) / "frontend" / "nginx.conf"

RASTER_TILES_LOCATION = r"location\s+~\s+\^/raster-tiles/"

_LOCATION_HEADER = re.compile(r"^[ \t]*location\b[^\n{]*\{", re.M)
_MAP_HEADER = re.compile(r"^map\s+(\S+)\s+(\S+)\s*\{", re.M)
_PROXY_CACHE_KEY = re.compile(r'^\s*proxy_cache_key\s+"([^"]+)"\s*;', re.M)

# (unquoted source template, dest var) for each per-parameter map.
_MAPS: dict[str, tuple[str, str]] = {
    "pmin": (
        "$geolens_raster_noncanonical:$arg_stretch:$arg_pmin",
        "$geolens_raster_pmin",
    ),
    "pmax": (
        "$geolens_raster_noncanonical:$arg_stretch:$arg_pmax",
        "$geolens_raster_pmax",
    ),
    "sigma": (
        "$geolens_raster_noncanonical:$arg_stretch:$arg_sigma",
        "$geolens_raster_sigma",
    ),
}
_NONCANONICAL_MAP: tuple[str, str] = ("$args", "$geolens_raster_noncanonical")
_CACHE_EXTRA_MAP: tuple[str, str] = (
    "$geolens_raster_noncanonical:$args",
    "$geolens_raster_cache_extra",
)


def _without_comments(text: str) -> str:
    """Drop nginx comment lines so prose can never satisfy an assertion."""
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def _balanced_body(text: str, brace_index: int) -> str:
    """Return the body between ``text[brace_index]`` and its matching brace."""
    depth = 0
    for index in range(brace_index, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[brace_index + 1 : index]
    raise AssertionError(f"unbalanced braces at offset {brace_index}")


def _location_block(text: str, header_pattern: str) -> str:
    match = re.search(header_pattern, text)
    assert match, f"expected a location block matching {header_pattern!r}"
    return _balanced_body(text, text.index("{", match.start()))


def _map_body(text: str, source_expr: str, dest_var: str) -> str:
    """Body of ``map "source_expr" dest_var { ... }`` (source_expr unquoted)."""
    quoted_source = (
        f'"{source_expr}"'
        if " " not in source_expr and ":" in source_expr
        else source_expr
    )
    # $args alone is not quoted in the conf (no ':' composition needed).
    candidates = {quoted_source, source_expr}
    for match in _MAP_HEADER.finditer(text):
        if match.group(1) in candidates and match.group(2) == dest_var:
            return _balanced_body(text, text.index("{", match.start()))
    raise AssertionError(
        f"no `map ...{source_expr}... {dest_var} {{ ... }}` block found"
    )


def _map_entries_ordered(
    body: str,
) -> tuple[list[tuple[str, bool, str]], str]:
    """``([(pattern_without_prefix, case_insensitive, value_template), ...],
    default_template)``.

    Declaration order is preserved, since nginx tries regex entries in the
    order they were written and the first match wins. Each entry's prefix is
    either ``~`` (case-sensitive) or ``~*`` (case-insensitive), exactly as
    nginx's map directive supports per entry -- a literal (non-regex) entry
    slipping in would be matched by nginx's hash lookup instead, which this
    simulation does not model, and a silent mismatch there is worse than a
    loud assertion here.
    """
    entries: list[tuple[str, bool, str]] = []
    default_value: str | None = None
    for line in body.splitlines():
        line = line.strip().rstrip(";")
        if not line:
            continue
        key, value = line.split(None, 1)
        key = key.strip('"')
        value = value.strip().strip('"')
        if key == "default":
            default_value = value
        elif key.startswith("~*"):
            entries.append((key[2:], True, value))
        elif key.startswith("~"):
            entries.append((key[1:], False, value))
        else:
            raise AssertionError(f"expected a regex map entry, got {key!r}")
    assert default_value is not None, "map has no default entry"
    return entries, default_value


def _nginx_arg(args_string: str, name: str) -> str:
    """nginx's ``$arg_NAME``: the value of the FIRST occurrence of ``name`` in
    the raw query string, matched CASE-INSENSITIVELY on the name (nginx's
    ngx_http_arg uses ngx_strlcasestrn, fix(#1778 codex r4)) -- and never
    URL-decoded."""
    for pair in args_string.split("&"):
        if not pair:
            continue
        key, _, value = pair.partition("=")
        if key.lower() == name.lower():
            return value
    return ""


def _expand(template: str, values: dict[str, str]) -> str:
    """Substitute ``$var`` tokens (bare, or ``$arg_NAME``) in a map source
    template or value against a resolved-variable dict."""

    def _sub(match: re.Match) -> str:
        return values.get(match.group(1), "")

    return re.sub(r"\$(\w+)", _sub, template)


def _evaluate_map(
    source_template: str,
    entries: list[tuple[str, bool, str]],
    default_value: str,
    values: dict[str, str],
) -> str:
    """Evaluate one nginx ``map`` the way nginx itself would: try each regex
    entry in declaration order, first match wins; ``default`` otherwise.

    Uses ``re.search``, not ``re.match``: nginx's map regex testing searches
    the whole string rather than anchoring at position 0, so a pattern like
    ``(?:^|&)stretch=.*(?:^|&)stretch=`` must find a duplicate even when the
    first occurrence of the name is not at the very start of $args. A
    genuinely anchored pattern (``^...$``) behaves identically under either,
    since ``^``/``$`` still assert the true start/end of the string.
    """
    source = _expand(source_template, values)
    for pattern, case_insensitive, template in entries:
        flags = re.IGNORECASE if case_insensitive else 0
        if re.search(pattern, source, flags):
            return _expand(template, values)
    return _expand(default_value, values)


def _conf() -> str:
    return _without_comments(NGINX_CONF.read_text())


def _noncanonical(conf: str, args_string: str) -> str:
    """``$geolens_raster_noncanonical`` for a raw query string."""
    source_expr, dest_var = _NONCANONICAL_MAP
    entries, default_value = _map_entries_ordered(
        _map_body(conf, source_expr, dest_var)
    )
    return _evaluate_map(source_expr, entries, default_value, {"args": args_string})


def _cache_extra(conf: str, args_string: str) -> str:
    """``$geolens_raster_cache_extra`` for a raw query string."""
    source_expr, dest_var = _CACHE_EXTRA_MAP
    entries, default_value = _map_entries_ordered(
        _map_body(conf, source_expr, dest_var)
    )
    values = {
        "geolens_raster_noncanonical": _noncanonical(conf, args_string),
        "args": args_string,
    }
    return _evaluate_map(source_expr, entries, default_value, values)


def _derive(conf: str, param: str, args_string: str) -> str:
    """The cache-key value nginx would compute for ``param`` given the raw
    query string ``args_string`` -- $arg_x's case-insensitive,
    first-occurrence semantics and the canonical-form guard both apply,
    exactly as nginx would."""
    source_template, dest_var = _MAPS[param]
    entries, default_value = _map_entries_ordered(
        _map_body(conf, source_template, dest_var)
    )
    values = {
        "geolens_raster_noncanonical": _noncanonical(conf, args_string),
        "arg_stretch": _nginx_arg(args_string, "stretch"),
        f"arg_{param}": _nginx_arg(args_string, param),
    }
    return _evaluate_map(source_template, entries, default_value, values)


def _qs(**params: str) -> str:
    """Build a raw query string, preserving insertion order (dict order)."""
    return "&".join(f"{k}={v}" for k, v in params.items())


# ---------------------------------------------------------------------------
# The cache key itself
# ---------------------------------------------------------------------------


def test_cache_key_does_not_hold_the_raw_stretch_args():
    """The raw args must not appear in proxy_cache_key at all -- only the
    mapped variables that blank what the active stretch mode ignores, plus
    the non-canonical escape hatch."""
    conf = _conf()
    match = _PROXY_CACHE_KEY.search(_location_block(conf, RASTER_TILES_LOCATION))
    assert match, "expected a proxy_cache_key in the /raster-tiles/ location"
    key = match.group(1)
    for raw_arg in ("$arg_pmin", "$arg_pmax", "$arg_sigma"):
        assert raw_arg not in key, (
            f"proxy_cache_key still holds {raw_arg} unconditionally: {key!r}. "
            "An anonymous caller can randomize it under stretch=minmax/absent "
            "(where it changes nothing) to mint a fresh key per request, "
            "defeating the cache the way `cols=<random>` did before #1785."
        )
    for mapped_var in (
        "$geolens_raster_pmin",
        "$geolens_raster_pmax",
        "$geolens_raster_sigma",
        "$geolens_raster_cache_extra",
    ):
        assert mapped_var in key, f"expected {mapped_var} in proxy_cache_key: {key!r}"


# ---------------------------------------------------------------------------
# pmin / pmax: percentile is the active mode; sigma: stddev is. Blank ONLY
# when stretch is an EXACT canonical inactive spelling AND the value is a
# well-formed float in range -- everything else stays raw (round 3).
# ---------------------------------------------------------------------------


def test_active_mode_always_passes_the_value_through_raw():
    """Active mode: the value must vary the key regardless of content --
    percentile/stddev genuinely read it, unchanged since round 1."""
    conf = _conf()
    for value in ("5", "200", "-1", "abc", ""):
        assert _derive(conf, "pmin", _qs(stretch="percentile", pmin=value)) == value
        assert _derive(conf, "pmax", _qs(stretch="percentile", pmax=value)) == value
        assert _derive(conf, "sigma", _qs(stretch="stddev", sigma=value)) == value


def test_well_formed_value_under_a_canonical_inactive_mode_collapses_to_one_key():
    """A random but well-formed, in-range value under the exact canonical
    inactive spelling (or absent) must still collapse -- the cache-busting
    vector #1785's shape closed stays closed for the common case."""
    conf = _conf()
    pmin_pmax_values = ["", "0", "2", "50", "98", "99.999", "100", "100.0"]
    sigma_values = ["", "0.5", "1", "2", "10", "0.001"]
    for stretch in ("minmax", ""):
        assert {
            _derive(conf, "pmin", _qs(stretch=stretch, pmin=v))
            for v in pmin_pmax_values
        } == {""}
        assert {
            _derive(conf, "pmax", _qs(stretch=stretch, pmax=v))
            for v in pmin_pmax_values
        } == {""}
    for stretch in ("minmax", "percentile", ""):
        assert {
            _derive(conf, "sigma", _qs(stretch=stretch, sigma=v)) for v in sigma_values
        } == {""}
    assert {
        _derive(conf, "pmin", _qs(stretch="stddev", pmin=v)) for v in pmin_pmax_values
    } == {""}
    for value in pmin_pmax_values:
        assert _cache_extra(conf, _qs(stretch="minmax", pmin=value)) == "", (
            "a canonical request must not add anything to the cache key"
        )


def test_sigma_still_varies_the_key_under_stddev():
    """Counterfactual for the failure mode a blanket blank-everything fix
    would introduce: two stddev requests with different sigma render
    different bytes, so sigma must still reach the cache key when
    stretch=stddev."""
    conf = _conf()
    key_match = _PROXY_CACHE_KEY.search(_location_block(conf, RASTER_TILES_LOCATION))
    assert key_match and "$geolens_raster_sigma" in key_match.group(1)
    a = _derive(conf, "sigma", _qs(stretch="stddev", sigma="2"))
    b = _derive(conf, "sigma", _qs(stretch="stddev", sigma="3"))
    assert a != b, (
        "stddev must not blank sigma out of the key, or two stddev requests "
        "with different sigma would collide on one cache entry and serve one "
        "request's bytes for the other's distinct render"
    )


def test_out_of_range_value_under_a_canonical_inactive_mode_stays_raw():
    """A value the well-formedness check rejects (out of [0, 100] for
    pmin/pmax, not > 0 for sigma) stays RAW even under an exact canonical
    inactive spelling."""
    conf = _conf()
    for bad in ("200", "-5", "101", "100.5"):
        assert _derive(conf, "pmin", _qs(stretch="minmax", pmin=bad)) == bad
        assert _derive(conf, "pmax", _qs(stretch="minmax", pmax=bad)) == bad
    for bad in ("-1", "0", "0.0", "0.000"):
        assert _derive(conf, "sigma", _qs(stretch="minmax", sigma=bad)) == bad


# ---------------------------------------------------------------------------
# fix(#1778 codex r3): percent-encoded/case-varied VALUES of stretch, and
# malformed float values, must stay raw. These are canonical-form requests
# (one exact-lowercase name each), so $geolens_raster_cache_extra is empty
# for them -- the per-parameter fallback alone closes these.
# ---------------------------------------------------------------------------


def test_percent_encoded_active_spelling_stays_raw():
    """`stretch=%70ercentile` decodes to `percentile` (ACTIVE) at the API,
    which URL-decodes query params; nginx's raw $arg_stretch is the literal
    string `%70ercentile`, which matches neither canonical inactive spelling.
    It must stay raw so two different pmin values under this encoding get
    two different keys, never one collapsed onto a rendering the API would
    actually vary by pmin."""
    conf = _conf()
    args_5 = _qs(stretch="%70ercentile", pmin="5")
    args_50 = _qs(stretch="%70ercentile", pmin="50")
    derived_5 = _derive(conf, "pmin", args_5)
    derived_50 = _derive(conf, "pmin", args_50)
    assert derived_5 == "5"
    assert derived_50 == "50"
    assert derived_5 != derived_50


def test_malformed_float_under_an_inactive_mode_stays_raw():
    """`?stretch=minmax&pmin=abc` must miss the cache. FastAPI's
    `pmin: float | None` coerces the query param to a float BEFORE
    raster_tile_proxy's body runs at all, and `abc` fails that coercion with
    a 422 regardless of stretch mode."""
    conf = _conf()
    for bad in ("abc", "5,6", "50:60", "1.2.3", "five"):
        derived = _derive(conf, "pmin", _qs(stretch="minmax", pmin=bad))
        assert derived == bad
    for bad in ("abc", "1,2", "5.6.7"):
        derived = _derive(conf, "sigma", _qs(stretch="minmax", sigma=bad))
        assert derived == bad


# ---------------------------------------------------------------------------
# fix(#1778 codex r4): the four names are matched CASE-INSENSITIVELY by
# nginx's own $arg_NAME lookup, and a case variant or percent-encoded name
# anywhere makes the WHOLE request non-canonical -- $geolens_raster_
# cache_extra then folds the entire raw $args into the key, independent of
# what any single per-parameter map would have derived.
# ---------------------------------------------------------------------------


def test_mixed_case_duplicate_is_noncanonical_and_the_whole_args_breaks_the_tie():
    """codex round 4's exact finding: nginx's $arg_stretch is case-
    INSENSITIVE, so it resolves `Stretch=minmax` (the first case-insensitive
    match) while FastAPI's exact-case binding resolves the later
    `stretch=percentile` -- a mode disagreement round 3's case-sensitive-only
    duplicate detector could not see. Two requests differing only in pmin
    must not share a key."""
    conf = _conf()
    args_5 = "Stretch=minmax&stretch=percentile&pmin=5"
    args_50 = "Stretch=minmax&stretch=percentile&pmin=50"
    assert _noncanonical(conf, args_5) == "1"
    assert _noncanonical(conf, args_50) == "1"
    extra_5 = _cache_extra(conf, args_5)
    extra_50 = _cache_extra(conf, args_50)
    assert extra_5 == args_5
    assert extra_50 == args_50
    assert extra_5 != extra_50, (
        "a mixed-case duplicated stretch must not let two different pmin "
        "values collapse onto one cache key"
    )


def test_mixed_case_single_occurrence_is_noncanonical():
    """No duplicate at all -- just one `Stretch=minmax` -- but FastAPI
    ignores it entirely (exact-case key lookup finds nothing named
    `stretch`) while nginx's case-insensitive $arg_stretch still resolves
    it. Must stay non-canonical regardless of the specific value, so this
    class cannot recur through a future change in what the API's absent-
    stretch default happens to render."""
    conf = _conf()
    args = "Stretch=minmax&pmin=5"
    assert _noncanonical(conf, args) == "1"
    assert _cache_extra(conf, args) == args


def test_encoded_name_is_noncanonical():
    """`%73tretch=percentile` decodes to the key `stretch` at the API
    (FastAPI URL-decodes query keys) but nginx never decodes $arg_* keys, so
    $arg_stretch resolves to "" here (no literal `stretch=` substring) --
    the API's real active mode is invisible to nginx entirely."""
    conf = _conf()
    args = "%73tretch=percentile&pmin=5"
    assert _noncanonical(conf, args) == "1"
    assert _cache_extra(conf, args) == args


def test_uppercase_and_all_caps_variants_of_every_name_are_noncanonical():
    conf = _conf()
    for variant_args in (
        "STRETCH=minmax&pmin=5",
        "stretch=minmax&PMIN=5",
        "stretch=minmax&Pmax=5",
        "stretch=stddev&SIGMA=2",
    ):
        assert _noncanonical(conf, variant_args) == "1", variant_args


def test_case_insensitive_duplicate_of_pmin_pmax_sigma_is_noncanonical():
    """The duplicate check itself must be case-insensitive for all four
    names, not just stretch."""
    conf = _conf()
    for variant_args in (
        "stretch=minmax&pmin=5&Pmin=200",
        "stretch=minmax&pmax=5&PMAX=200",
        "stretch=stddev&sigma=2&Sigma=200",
    ):
        assert _noncanonical(conf, variant_args) == "1", variant_args


def test_ordinary_canonical_request_is_unaffected():
    """The guard must not fire on the common path: exact lowercase names,
    each at most once, well-formed values."""
    conf = _conf()
    for args in (
        "stretch=minmax&pmin=5",
        "stretch=percentile&pmin=5&pmax=95",
        "stretch=stddev&sigma=3",
        "z=1",  # no stretch/pmin/pmax/sigma at all
    ):
        assert _noncanonical(conf, args) == "0", args
        assert _cache_extra(conf, args) == "", args


def test_duplicate_detection_finds_a_duplicate_not_starting_at_position_zero():
    """Regression guard for the simulation itself (fix(#1778 codex r4)): the
    map regex must be evaluated as an unanchored SEARCH, matching nginx's own
    semantics, not a Python re.match anchored at position 0 -- otherwise a
    duplicate whose first occurrence isn't the very first key in $args would
    be silently missed by this test suite while nginx itself still finds
    it."""
    conf = _conf()
    assert _noncanonical(conf, "pmin=5&stretch=minmax&stretch=percentile") == "1"
    assert _noncanonical(conf, "colormap_name=x&pmin=5&Pmin=200") == "1"


# ---------------------------------------------------------------------------
# Duplicate `pmin`/`pmax`/`sigma` (exact lowercase, round 2/3): closed by
# ignoring the inactive value entirely at the API AND requiring
# well-formedness at nginx, so which occurrence either side reads matters
# only when it changes well-formedness.
# ---------------------------------------------------------------------------


def test_a_repeated_pmin_is_noncanonical_even_when_both_occurrences_are_well_formed():
    """fix(#1778 codex r4): strict canonical form requires each of the four
    names to appear AT MOST ONCE, full stop -- not merely "blank is safe
    here" reasoning about what the duplicate values happen to be. A
    repeated pmin, even same-case and even with both occurrences well-formed
    and in range, is therefore non-canonical and stays raw: nginx's own
    first-occurrence reading differs between these two requests (5 vs 50),
    so they get different keys either way -- safe by keeping raw, not by
    collapsing."""
    conf = _conf()
    args_a = "stretch=minmax&pmin=5&pmin=50"
    args_b = "stretch=minmax&pmin=50&pmin=5"
    assert _noncanonical(conf, args_a) == "1"
    assert _noncanonical(conf, args_b) == "1"
    a = _derive(conf, "pmin", args_a)
    b = _derive(conf, "pmin", args_b)
    assert a == "5"
    assert b == "50"
    assert a != b


def test_repeated_param_stays_raw_when_the_first_occurrence_is_not_well_formed():
    """codex's literal example: nginx reads the FIRST occurrence of a
    repeated pmin. When that first occurrence is out of range or malformed,
    nginx must keep it raw regardless of what the API's LAST-occurrence read
    would have been."""
    conf = _conf()
    out_of_range_first = _derive(conf, "pmin", "stretch=minmax&pmin=200&pmin=5")
    malformed_first = _derive(conf, "pmin", "stretch=minmax&pmin=abc&pmin=5")
    assert out_of_range_first == "200"
    assert malformed_first == "abc"


def test_duplicated_stretch_falls_back_to_the_raw_value_instead_of_blanking():
    """fix(#1778 codex r2): the collision codex's shape (b) recommendation
    didn't cover on its own. nginx reads the FIRST `stretch` (minmax, so it
    would normally blank pmin); the API reads the LAST (percentile, so it
    actually uses pmin). Two such requests with DIFFERENT pmin values must
    NOT collapse onto one key -- that would be a genuine collision (different
    rendered bytes sharing one cache entry), worse than the status-code
    mismatch this whole fix started from."""
    conf = _conf()
    args_a = "stretch=minmax&stretch=percentile&pmin=5"
    args_b = "stretch=minmax&stretch=percentile&pmin=50"
    assert _noncanonical(conf, args_a) == "1"
    assert _cache_extra(conf, args_a) != _cache_extra(conf, args_b)


def test_non_duplicated_stretch_is_unaffected_by_the_guard():
    """The guard must not blank the fast path: an ordinary, non-duplicated
    request keeps collapsing exactly as before, and an out-of-range value
    still stays raw for the reason ordinary well-formedness does."""
    conf = _conf()
    assert _derive(conf, "pmin", "stretch=minmax&pmin=5") == ""
    assert _derive(conf, "pmin", "stretch=minmax&pmin=200") == "200"
    assert _derive(conf, "pmin", "stretch=percentile&pmin=5") == "5"
