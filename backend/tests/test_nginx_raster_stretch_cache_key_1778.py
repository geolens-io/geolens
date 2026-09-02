"""The raster tile cache key must not vary on an arg the active stretch mode
ignores, and a cache HIT must never change what an uncached request would
answer (#1778, codebase audit 2026-08-30; codex rounds 1 and 2 on #1791).

frontend/nginx.conf's raster_cache proxy_cache_key used to hold
$arg_pmin/$arg_pmax/$arg_sigma unconditionally. In
backend/app/processing/tiles/router.py, stretch=percentile is the only mode
that reads pmin/pmax (_compute_stretch_rescale) and stretch=stddev is the only
mode that reads sigma; stretch=minmax (the default) or an absent stretch reads
neither -- the fragment passed to Titiler is unchanged either way. So
``?stretch=minmax&pmin=<random>`` produced a fresh cache key holding bytes
byte-identical to the unfiltered tile, the same defeat #1785 closed for the
vector tile ``cols=`` param.

Round 1 blanked every inactive value unconditionally, which introduced a
different bug: raster_tile_proxy validated pmin/pmax/sigma whenever PRESENT,
regardless of the active stretch mode, so blanking pmin under
``?stretch=minmax&pmin=200`` collapsed it onto the same key as a cached
``?stretch=minmax`` and returned that entry's 200, though the API would 422
an out-of-range pmin uncached.

Round 2 changed the API side instead of chasing round 1's nginx-only fix
further: raster_tile_proxy now IGNORES pmin/pmax when stretch is not
percentile and sigma when it is not stddev, rather than merely leaving them
unvalidated. "Inactive" means the same thing, ignored, on both sides, so
every map below blanks an inactive value UNCONDITIONALLY -- there is no
verdict left to disagree with, because the value is never read. That also
closes the residual round 1 could not: a repeated query parameter, where
nginx's $arg_x reads the FIRST occurrence and FastAPI's scalar Query reads
the LAST.

One more residual survives even that change: the duplicate-parameter mismatch
applies to `stretch` itself too. `?stretch=minmax&stretch=percentile&pmin=5`
has nginx read stretch=minmax (blank pmin) while the API reads
stretch=percentile (uses pmin=5) -- and because blanking makes the cache key
depend on nginx's OWN reading of stretch, a second such request with a
DIFFERENT pmin would collapse onto the SAME key while rendering DIFFERENT
bytes: a collision, not just a status mismatch.
$geolens_raster_stretch_dup detects a repeated `stretch=` in the raw query
string and, when set, every map falls back to the raw value instead of
blanking -- an extra cache miss, never a collision.

These are structural (they read the conf and simulate nginx's own map
evaluation in Python, including nginx's $arg_x "first occurrence of a
repeated key" semantics), because there is no nginx binary in this test
environment to render and query directly. The companion API-level pin lives
in test_raster_colormap_proxy.py::TestRasterColormapProxy::
test_out_of_range_bounds_are_ignored_under_an_inactive_stretch_mode, which
confirms the API side of the contract these maps rely on: pmin/pmax/sigma are
ignored, not validated, whenever the active stretch mode does not read them.
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
    entry in declaration order, first match wins; ``default`` otherwise."""
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
# pmin / pmax: percentile is the active mode; sigma: stddev is.
# Round 2: blank UNCONDITIONALLY when inactive -- no well-formedness check
# needed any more, since the API ignores an inactive value regardless.
# ---------------------------------------------------------------------------


def test_active_mode_always_passes_the_value_through_raw():
    """Active mode: the value must vary the key regardless of content --
    percentile/stddev genuinely read it, unchanged from before either fix."""
    conf = _conf()
    for value in ("5", "200", "-1", "abc", ""):
        assert _derive(conf, "pmin", _qs(stretch="percentile", pmin=value)) == value
        assert _derive(conf, "pmax", _qs(stretch="percentile", pmax=value)) == value
        assert _derive(conf, "sigma", _qs(stretch="stddev", sigma=value)) == value


def test_any_value_under_an_inactive_mode_collapses_to_one_key():
    """fix(#1778 codex r2): unconditional blanking. Any value at all -- valid,
    invalid, or malformed -- under an inactive stretch mode must collapse to
    the same blank key, because the API ignores it regardless of content."""
    conf = _conf()
    values = ["", "0", "50", "100", "200", "-5", "abc", "1e10", "100.5", "0.5"]
    for param, active in (
        ("pmin", "percentile"),
        ("pmax", "percentile"),
        ("sigma", "stddev"),
    ):
        for stretch in ("minmax", ""):
            derived = {
                _derive(conf, param, _qs(stretch=stretch, **{param: v})) for v in values
            }
            assert derived == {""}, (
                f"{param} under stretch={stretch!r} collapsed to {derived!r}, "
                "expected all blank -- the API ignores this value under this "
                "mode regardless of content, so it must never defeat the cache"
            )
        assert active  # documents the pairing; not asserted here


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


# ---------------------------------------------------------------------------
# Duplicate `pmin`/`pmax`/`sigma`: closed by ignoring the inactive value
# entirely, so which occurrence either side reads no longer matters.
# ---------------------------------------------------------------------------


def test_repeated_inactive_param_still_collapses_regardless_of_occurrence_order():
    """The exact case codex found: nginx reads the FIRST occurrence, FastAPI
    reads the LAST. Both occurrences must still blank identically, because
    the API ignores the parameter under this mode no matter which value it
    resolves to."""
    conf = _conf()
    well_formed_first = _derive(
        conf, "pmin", "stretch=minmax&pmin=5&pmin=200"
    )  # nginx sees 5 (well-formed if it mattered), API would see 200
    out_of_range_first = _derive(
        conf, "pmin", "stretch=minmax&pmin=200&pmin=5"
    )  # nginx sees 200 (would have been the round-1 residual), API sees 5
    assert well_formed_first == out_of_range_first == "", (
        f"got {well_formed_first!r} and {out_of_range_first!r} -- a repeated "
        "pmin under an inactive stretch mode must blank the same way "
        "regardless of which occurrence nginx happens to read"
    )


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
    request keeps collapsing exactly as before."""
    conf = _conf()
    assert _derive(conf, "pmin", "stretch=minmax&pmin=5") == ""
    assert _derive(conf, "pmin", "stretch=minmax&pmin=200") == ""
    assert _derive(conf, "pmin", "stretch=percentile&pmin=5") == "5"
