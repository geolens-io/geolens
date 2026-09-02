"""The raster tile cache key must not vary on an arg the active stretch mode
ignores, and a cache HIT must never change what an uncached request would
answer (#1778, codebase audit 2026-08-30; codex rounds 1-6 on #1791).

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

Round 5 found round 3's well-formedness check was stricter than it needed
to be, in a way that reopened the exact cache-amplification vector this
whole fix exists to close. It required a value to be WELL-FORMED AND IN THE
RANGE THAT MATTERS FOR THE ACTIVE MODE (0-100 for pmin/pmax, positive for
sigma) before blanking it under an inactive one -- a round-1 leftover from
before round 2 made the API ignore an inactive value outright. Since the API
never applies that range check to a value it never reads that far into, an
out-of-range-but-syntactically-valid value (pmin=101, pmin=102, ...) stayed
RAW, so an anonymous caller could still mint a distinct one-hour cache entry
per distinct out-of-range value, all holding the identical tile.

The round-5 rule: when the query is canonical and the parameter is
inactive, blank every value FastAPI's float coercion would ACCEPT --
matching its grammar (optional sign, digits, decimal point, exponent), not
its semantic range -- and keep raw only what FastAPI cannot parse at all
(its 422 path, unaffected by round 5, still covered by
test_malformed_float_under_an_inactive_mode_stays_raw).

Round 6 found round 4's fix for the non-canonical case introduced a new
problem while closing the collision: $geolens_raster_cache_extra folded the
ENTIRE raw $args into proxy_cache_key, and this endpoint accepts the
deprecated ?api_key= query lane (_resolve_api_key,
app/modules/auth/dependencies.py), so a non-canonical request carrying one
wrote that credential, in the clear, into the cache key -- reachable
through raster_cache's on-disk files and any backup of them, even though
access logging already strips query strings for exactly this reason.

The round-6 rule: proxy_cache_key must be built ONLY from the sanitised
$geolens_raster_* variables (plus $dataset_id/$z/$x/$y/$fmt/$arg_v/
$arg_colormap_name/$arg_stretch, none of which can carry a credential) --
never raw $args, never any other raw $arg_*. A non-canonical request is
instead served UNCACHED: $geolens_raster_noncanonical now also drives
proxy_cache_bypass and proxy_no_cache on the raster-tiles location, so
bypass skips the lookup and no_cache skips the store, and nothing about
that request -- credential included -- is ever written to the cache at
all. $geolens_raster_cache_extra and its map are gone.

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


_PROXY_CACHE_BYPASS = re.compile(r"^\s*proxy_cache_bypass\s+([^;]+);", re.M)
_PROXY_NO_CACHE = re.compile(r"^\s*proxy_no_cache\s+([^;]+);", re.M)


def _cache_bypass_vars(conf: str) -> tuple[list[str], list[str]]:
    """The variable lists ``proxy_cache_bypass``/``proxy_no_cache`` reference
    in the /raster-tiles/ location, or ``[]`` if the directive is absent."""
    block = _location_block(conf, RASTER_TILES_LOCATION)
    bypass = _PROXY_CACHE_BYPASS.search(block)
    no_cache = _PROXY_NO_CACHE.search(block)
    return (
        bypass.group(1).split() if bypass else [],
        no_cache.group(1).split() if no_cache else [],
    )


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


def test_cache_key_never_includes_raw_args_or_a_credential_name():
    """fix(#1778 codex r6): $geolens_raster_cache_extra used to fold the
    ENTIRE raw $args into this key for a non-canonical request, and this
    endpoint accepts the deprecated ?api_key= query lane
    (_resolve_api_key, app/modules/auth/dependencies.py). A raw $args (or
    any single unsanitised $arg_*) in the key means that credential lands,
    in the clear, in raster_cache's on-disk cache files and any backup of
    them. The key must be built ONLY from the named, sanitised variables --
    never $args, never a bare reference to a credential-carrying name."""
    conf = _conf()
    match = _PROXY_CACHE_KEY.search(_location_block(conf, RASTER_TILES_LOCATION))
    assert match
    key = match.group(1)
    assert "$args" not in key, f"proxy_cache_key embeds the raw query string: {key!r}"
    for credential_name in ("api_key", "token", "authorization"):
        assert credential_name not in key.lower(), (
            f"proxy_cache_key mentions {credential_name!r}: {key!r}"
        )


def test_noncanonical_requests_bypass_the_cache_instead_of_being_keyed_on_it():
    """fix(#1778 codex r6): rather than keying a non-canonical request on
    anything (which is how the $args/credential leak happened), it must be
    served UNCACHED -- $geolens_raster_noncanonical drives BOTH
    proxy_cache_bypass (skip the lookup) and proxy_no_cache (skip the
    store)."""
    conf = _conf()
    bypass_vars, no_cache_vars = _cache_bypass_vars(conf)
    assert "$geolens_raster_noncanonical" in bypass_vars, (
        f"expected proxy_cache_bypass to reference $geolens_raster_noncanonical, "
        f"got {bypass_vars!r}"
    )
    assert "$geolens_raster_noncanonical" in no_cache_vars, (
        f"expected proxy_no_cache to reference $geolens_raster_noncanonical, "
        f"got {no_cache_vars!r}"
    )


def test_noncanonical_request_with_an_api_key_leaks_nothing_and_is_marked_bypass():
    """fix(#1778 codex r6): the exact scenario in the finding. A public
    raster request carrying ?api_key=SECRET alongside a non-canonical
    stretch spelling must (a) resolve $geolens_raster_noncanonical to "1"
    (bypass/no_cache both trigger, per the test above) and (b) never let
    SECRET reach any of the actual key-building variables."""
    conf = _conf()
    args = "api_key=SECRET&Stretch=minmax&stretch=percentile&pmin=5"
    assert _noncanonical(conf, args) == "1"
    for param in ("pmin", "pmax", "sigma"):
        derived = _derive(conf, param, args)
        assert "SECRET" not in derived, (
            f"$geolens_raster_{param} leaked the api_key: {derived!r}"
        )


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
        assert _noncanonical(conf, _qs(stretch="minmax", pmin=value)) == "0", (
            "a canonical request must not trigger the non-canonical bypass"
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


def test_out_of_range_but_syntactically_valid_value_under_a_canonical_inactive_mode_blanks():
    """fix(#1778 codex r5): the API IGNORES an inactive pmin/pmax/sigma
    outright (fix(#1778 codex r2)), so it never applies a [0, 100] / positive
    range check to a value it never reads that far into. The previous
    range-restricted well-formedness check left every out-of-range-but-
    parseable value RAW, so an anonymous caller could mint a distinct
    one-hour cache entry per distinct out-of-range value (101, 102, 103, ...)
    even though every one of them renders the IDENTICAL tile -- the exact
    cache-amplification vector this whole fix exists to close, reopened
    through a side door. Range is irrelevant for an inactive parameter;
    only a value FastAPI cannot parse as a float AT ALL stays raw (see
    test_malformed_float_under_an_inactive_mode_stays_raw right below)."""
    conf = _conf()
    for value in ("200", "-5", "101", "100.5", "1e3", "-1e10", "+5"):
        assert _derive(conf, "pmin", _qs(stretch="minmax", pmin=value)) == ""
        assert _derive(conf, "pmax", _qs(stretch="minmax", pmax=value)) == ""
    for value in ("-1", "0", "0.0", "0.000", "-3.5e2"):
        assert _derive(conf, "sigma", _qs(stretch="minmax", sigma=value)) == ""


def test_the_coordinators_named_out_of_range_examples_collapse_to_the_blank_key():
    """fix(#1778 codex r5): the literal cases named in the finding --
    pmin=101, pmin=-5, sigma=0, pmax=1e3 under an inactive mode all blank,
    and pmin=abc (unparseable, not merely out of range) still stays raw."""
    conf = _conf()
    assert _derive(conf, "pmin", _qs(stretch="minmax", pmin="101")) == ""
    assert _derive(conf, "pmin", _qs(stretch="minmax", pmin="-5")) == ""
    assert _derive(conf, "sigma", _qs(stretch="minmax", sigma="0")) == ""
    assert _derive(conf, "pmax", _qs(stretch="minmax", pmax="1e3")) == ""
    assert _derive(conf, "pmin", _qs(stretch="minmax", pmin="abc")) == "abc"


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
    # fix(#1778 codex r6): both requests bypass the cache entirely (asserted
    # structurally in test_noncanonical_requests_bypass_the_cache_instead_of_
    # being_keyed_on_it), so neither is ever cached in the first place --
    # the per-parameter fallback below is a second, independent reason they
    # could never collide even if bypass were somehow misconfigured off.
    derived_5 = _derive(conf, "pmin", args_5)
    derived_50 = _derive(conf, "pmin", args_50)
    assert derived_5 == "5"
    assert derived_50 == "50"
    assert derived_5 != derived_50, (
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


def test_encoded_name_is_noncanonical():
    """`%73tretch=percentile` decodes to the key `stretch` at the API
    (FastAPI URL-decodes query keys) but nginx never decodes $arg_* keys, so
    $arg_stretch resolves to "" here (no literal `stretch=` substring) --
    the API's real active mode is invisible to nginx entirely."""
    conf = _conf()
    args = "%73tretch=percentile&pmin=5"
    assert _noncanonical(conf, args) == "1"


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
    assert _noncanonical(conf, args_b) == "1"
    # fix(#1778 codex r6): both bypass the cache entirely -- see
    # test_noncanonical_requests_bypass_the_cache_instead_of_being_keyed_on_it
    # -- so "must not collapse onto one key" is moot; neither is ever
    # written. The per-parameter values still differ too, independently.
    assert _derive(conf, "pmin", args_a) != _derive(conf, "pmin", args_b)


def test_non_duplicated_stretch_is_unaffected_by_the_guard():
    """The guard must not blank the fast path: an ordinary, non-duplicated
    request keeps collapsing exactly as before, an out-of-range-but-valid
    value ALSO blanks (fix(#1778 codex r5) -- range no longer matters for an
    inactive parameter), and the active mode still keeps a value raw."""
    conf = _conf()
    assert _derive(conf, "pmin", "stretch=minmax&pmin=5") == ""
    assert _derive(conf, "pmin", "stretch=minmax&pmin=200") == ""
    assert _derive(conf, "pmin", "stretch=percentile&pmin=5") == "5"
