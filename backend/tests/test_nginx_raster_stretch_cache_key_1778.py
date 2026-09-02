"""The raster tile cache key must not vary on an arg the active stretch mode
ignores, and a cache HIT must never change what an uncached request would
answer (#1778, codebase audit 2026-08-30; codex rounds 1-3 on #1791).

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
cache HIT answer with a status an uncached request would not have gotten
(raster_tile_proxy validated pmin/pmax/sigma whenever PRESENT, regardless of
mode). Round 2 changed the API side instead of chasing that nginx-only fix
further: raster_tile_proxy now IGNORES pmin/pmax when stretch is not
percentile and sigma when it is not stddev, so blanking an inactive value
can never disagree with the API about STATUS -- there is no verdict left to
disagree with.

Round 3 found that round 2's API change is necessary but not sufficient,
because nginx's read of the query string and the API's read of it can
disagree about which VALUE, or even which MODE, is in play, independent of
what the API validates or ignores:

- percent-encoding: ``stretch=%70ercentile`` decodes to the ACTIVE spelling
  at the API (FastAPI URL-decodes query params) but nginx's raw
  ``$arg_stretch`` never matches ``percentile`` literally. Treating "not the
  literal active spelling" as "therefore inactive" blanked pmin here, so two
  requests with different pmin values collapsed onto ONE key while the API
  rendered DIFFERENT bytes for them: a cache collision, not a status
  mismatch.
- a case variant (``MinMax``), for the same reason (nginx's regex is
  case-sensitive and never normalizes).
- a malformed float (``pmin=abc``): the API's "ignore when inactive" code in
  ``raster_tile_proxy`` never runs for this, because FastAPI's
  ``pmin: float | None`` coerces the query param to a ``float`` BEFORE the
  endpoint body executes at all, and ``abc`` fails that coercion with a 422
  regardless of stretch mode. Blanking it let a cached 200 answer a request
  the API 422s uncached.

The principle that closes all three the same way: blank an argument ONLY
when nginx can be CERTAIN blanking cannot change the outcome -- the raw
``$arg_stretch`` is EXACTLY one of the canonical spellings this argument is
inactive under (no percent-encoding, no case variant: PCRE matches the
literal, decoded string only) AND the argument itself is a well-formed float
in the range that matters in the one mode where it IS active. Everything
else -- an unrecognized stretch spelling, a duplicated one
($geolens_raster_stretch_dup), a malformed or merely out-of-range value -- is
left RAW: the request misses the cache and the API decides on its own terms.
Failing toward "keep raw" only ever costs an extra cache miss; failing
toward "blank" risks a wrong tile or a wrong status.

These are structural (they read the conf and simulate nginx's own map
evaluation in Python, including nginx's $arg_x "first occurrence of a
repeated key" semantics and its PCRE case-sensitivity), because there is no
nginx binary in this test environment to render and query directly. The
companion API-level pin lives in test_raster_colormap_proxy.py::
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
        "$geolens_raster_stretch_dup:$arg_stretch:$arg_pmin",
        "$geolens_raster_pmin",
    ),
    "pmax": (
        "$geolens_raster_stretch_dup:$arg_stretch:$arg_pmax",
        "$geolens_raster_pmax",
    ),
    "sigma": (
        "$geolens_raster_stretch_dup:$arg_stretch:$arg_sigma",
        "$geolens_raster_sigma",
    ),
}
_DUP_MAP: tuple[str, str] = ("$args", "$geolens_raster_stretch_dup")


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


def _map_entries_ordered(body: str) -> tuple[list[tuple[str, str]], str]:
    """``([(pattern_without_tilde, value_template), ...], default_template)``.

    Declaration order is preserved, since nginx tries regex entries in the
    order they were written and the first match wins. Asserts every non-default
    entry is a regex (``~``-prefixed) -- a literal entry slipping in would be
    matched by nginx's hash lookup instead, which this simulation does not
    model, and a silent mismatch there is worse than a loud assertion here.
    """
    entries: list[tuple[str, str]] = []
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
        else:
            assert key.startswith("~"), f"expected a regex map entry, got {key!r}"
            entries.append((key[1:], value))
    assert default_value is not None, "map has no default entry"
    return entries, default_value


def _nginx_arg(args_string: str, name: str) -> str:
    """nginx's ``$arg_NAME``: the value of the FIRST occurrence of ``name`` in
    the raw query string, or "" if absent. nginx does not URL-decode $arg_*,
    and neither does this."""
    for pair in args_string.split("&"):
        if not pair:
            continue
        key, _, value = pair.partition("=")
        if key == name:
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
    entries: list[tuple[str, str]],
    default_value: str,
    values: dict[str, str],
) -> str:
    """Evaluate one nginx ``map`` the way nginx itself would: try each regex
    entry in declaration order (PCRE, case-sensitive, exactly as nginx's
    default), first match wins; ``default`` otherwise."""
    source = _expand(source_template, values)
    for pattern, template in entries:
        if re.match(pattern, source):
            return _expand(template, values)
    return _expand(default_value, values)


def _conf() -> str:
    return _without_comments(NGINX_CONF.read_text())


def _stretch_dup(conf: str, args_string: str) -> str:
    """``$geolens_raster_stretch_dup`` for a raw query string."""
    source_expr, dest_var = _DUP_MAP
    entries, default_value = _map_entries_ordered(
        _map_body(conf, source_expr, dest_var)
    )
    return _evaluate_map(source_expr, entries, default_value, {"args": args_string})


def _derive(conf: str, param: str, args_string: str) -> str:
    """The cache-key value nginx would compute for ``param`` given the raw
    query string ``args_string`` -- $arg_x's first-occurrence semantics and
    the duplicate-stretch guard both apply, exactly as nginx would."""
    source_template, dest_var = _MAPS[param]
    entries, default_value = _map_entries_ordered(
        _map_body(conf, source_template, dest_var)
    )
    values = {
        "geolens_raster_stretch_dup": _stretch_dup(conf, args_string),
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
    mapped variables that blank what the active stretch mode ignores."""
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
    ):
        assert mapped_var in key, f"expected {mapped_var} in proxy_cache_key: {key!r}"


# ---------------------------------------------------------------------------
# pmin / pmax: percentile is the active mode; sigma: stddev is. Round 3:
# blank ONLY when stretch is an EXACT canonical inactive spelling AND the
# value is a well-formed float in range -- everything else stays raw.
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
    # stddev is the OTHER canonical inactive spelling for pmin/pmax.
    assert {
        _derive(conf, "pmin", _qs(stretch="stddev", pmin=v)) for v in pmin_pmax_values
    } == {""}


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
    inactive spelling -- the conservative direction the coordinator's
    principle asks for: some legitimate-but-unusual values miss the cache
    that technically could not have changed the answer either, in exchange
    for never needing a more permissive, harder-to-audit numeric regex."""
    conf = _conf()
    for bad in ("200", "-5", "101", "100.5"):
        assert _derive(conf, "pmin", _qs(stretch="minmax", pmin=bad)) == bad
        assert _derive(conf, "pmax", _qs(stretch="minmax", pmax=bad)) == bad
    for bad in ("-1", "0", "0.0", "0.000"):
        assert _derive(conf, "sigma", _qs(stretch="minmax", sigma=bad)) == bad


# ---------------------------------------------------------------------------
# fix(#1778 codex r3): the three ways nginx's raw read of the query string
# can disagree with the API's decoded/coerced read, independent of what the
# API validates or ignores. Each must stay raw, never blank.
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
    assert derived_5 != derived_50, (
        "a percent-encoded active stretch spelling must not let two "
        "different pmin values collapse onto one cache key"
    )


def test_case_variant_of_a_canonical_spelling_stays_raw():
    """PCRE matching here is case-sensitive by default, same as FastAPI's
    Literal validator (which would 422 `MinMax` as an invalid literal value
    -- not decode-and-normalize it the way percent-encoding is decoded). A
    case variant must never be treated as the canonical inactive spelling."""
    conf = _conf()
    for variant in ("MinMax", "MINMAX", "Stddev", "PERCENTILE"):
        derived = _derive(conf, "pmin", _qs(stretch=variant, pmin="5"))
        assert derived == "5", (
            f"stretch={variant!r} must keep pmin raw (got {derived!r}) -- "
            "nginx must never treat a case variant as a canonical spelling"
        )


def test_malformed_float_under_an_inactive_mode_stays_raw():
    """`?stretch=minmax&pmin=abc` must miss the cache, not collapse onto the
    plain `?stretch=minmax` key. FastAPI's `pmin: float | None` coerces the
    query param to a float BEFORE raster_tile_proxy's body runs at all --
    round 2's "ignore pmin when inactive" code never gets a chance to run,
    because the framework's own type coercion 422s on a non-numeric string
    regardless of stretch mode. Blanking it here would let a cached 200
    answer that 422.

    Values chosen to be unambiguously non-numeric -- not merely large or
    signed, both of which Python's own float() parser (and therefore
    pydantic's coercion) accepts without a 422, and which the well-formed
    numeric regex already keeps raw for the "out of range" reason covered
    separately above.
    """
    conf = _conf()
    for bad in ("abc", "5,6", "50:60", "1.2.3", "five"):
        derived = _derive(conf, "pmin", _qs(stretch="minmax", pmin=bad))
        assert derived == bad, (
            f"pmin={bad!r} under stretch=minmax must stay RAW (got "
            f"{derived!r}) -- FastAPI's float coercion 422s this regardless "
            "of stretch mode, and blanking it would let a cache hit answer "
            "a 200 for what an uncached request 422s"
        )
    for bad in ("abc", "1,2", "5.6.7"):
        derived = _derive(conf, "sigma", _qs(stretch="minmax", sigma=bad))
        assert derived == bad


# ---------------------------------------------------------------------------
# Duplicate `pmin`/`pmax`/`sigma`: closed by ignoring the inactive value
# entirely at the API AND requiring well-formedness at nginx, so which
# occurrence either side reads matters only when it changes well-formedness.
# ---------------------------------------------------------------------------


def test_repeated_well_formed_inactive_param_collapses_regardless_of_occurrence_order():
    """Both duplicate occurrences are well-formed and in range, so nginx's
    FIRST-occurrence read and the API's LAST-occurrence read are both
    ignored identically under stretch=minmax -- collapsing is safe regardless
    of which one nginx happens to see."""
    conf = _conf()
    a = _derive(conf, "pmin", "stretch=minmax&pmin=5&pmin=50")
    b = _derive(conf, "pmin", "stretch=minmax&pmin=50&pmin=5")
    assert a == b == "", f"got {a!r} and {b!r}, expected both blank"


def test_repeated_param_stays_raw_when_the_first_occurrence_is_not_well_formed():
    """codex's literal example: nginx reads the FIRST occurrence of a
    repeated pmin. When that first occurrence is out of range or malformed,
    nginx must keep it raw regardless of what the API's LAST-occurrence read
    would have been -- the well-formedness gate applies to whichever
    occurrence nginx actually sees, not to some notion of "the pair"."""
    conf = _conf()
    out_of_range_first = _derive(conf, "pmin", "stretch=minmax&pmin=200&pmin=5")
    malformed_first = _derive(conf, "pmin", "stretch=minmax&pmin=abc&pmin=5")
    assert out_of_range_first == "200"
    assert malformed_first == "abc"


# ---------------------------------------------------------------------------
# Duplicate `stretch`: nginx and the API can disagree about which mode is
# ACTIVE. $geolens_raster_stretch_dup detects this and falls back to raw.
# ---------------------------------------------------------------------------


def test_stretch_dup_detects_a_repeated_stretch_key():
    conf = _conf()
    assert _stretch_dup(conf, "stretch=minmax&pmin=5") == "0"
    assert _stretch_dup(conf, "pmin=5") == "0"
    assert _stretch_dup(conf, "stretch=percentile") == "0"
    assert _stretch_dup(conf, "stretch=minmax&stretch=percentile&pmin=5") == "1"
    assert _stretch_dup(conf, "stretch=percentile&pmin=5&stretch=minmax") == "1"
    # A repeat of the SAME value is still a repeat -- harmless (nginx and the
    # API necessarily agree), but detected the same way; the raw-fallback
    # this triggers is safe either way, just occasionally unnecessary.
    assert _stretch_dup(conf, "stretch=minmax&stretch=minmax&pmin=5") == "1"


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
    derived_a = _derive(conf, "pmin", args_a)
    derived_b = _derive(conf, "pmin", args_b)
    assert derived_a == "5"
    assert derived_b == "50"
    assert derived_a != derived_b, (
        "a duplicated stretch must not let two different pmin values "
        "collapse onto one cache key"
    )


def test_non_duplicated_stretch_is_unaffected_by_the_guard():
    """The guard must not blank the fast path: an ordinary, non-duplicated
    request keeps collapsing exactly as before, and an out-of-range value
    still stays raw for the reason ordinary well-formedness does."""
    conf = _conf()
    assert _derive(conf, "pmin", "stretch=minmax&pmin=5") == ""
    assert _derive(conf, "pmin", "stretch=minmax&pmin=200") == "200"
    assert _derive(conf, "pmin", "stretch=percentile&pmin=5") == "5"
