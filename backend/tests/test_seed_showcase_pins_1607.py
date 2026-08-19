"""fix(#1607): the showcase content geolens-examples addresses by id stays put.

The examples repo hardcodes demo fixtures: `ci/fixtures.json` names the
meteorites dataset (viewport paging, the vector-tile handoff, a search phrase)
and the Restless Earth share token, and the gallery in `index.html` deep-links
three showcase maps by UUID. None of that is visible from inside this repo -
the only signal today is the examples' own preflight going red after the fact.

So the seeder pins them, and these tests hold the pin in place:

* the pin tuples still name what the examples load;
* `_keep_existing_map` decides the same way for every builder;
* EVERY builder's exists-check goes through that one function, so a builder
  added later cannot re-invent the bare `not force and _map_exists(...)` shape
  and quietly drop a pinned map's uuid on the floor;
* `--prune-userdata`'s classifier hard-keeps a pinned map whoever owns it;
* `--prune` refuses to delete a pinned name even if one is added to a RETIRED_*
  list, which the tests force rather than wait for.

Pure static analysis plus one fake-API unit - no database, no HTTP, no docker.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys

import pytest

from tests.repo_paths import repo_root

SCRIPT_PATH = repo_root(__file__) / "scripts" / "seed-showcase.py"


def _load_seeder():
    """Import scripts/seed-showcase.py as a module without running main().

    The filename is not an identifier (hyphen), so the plain `from scripts.X
    import ...` other seeder tests use is unavailable here. main() is guarded
    by __main__, so exec_module only evaluates constants and defs.
    """
    spec = importlib.util.spec_from_file_location("seed_showcase_1607", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seeder = _load_seeder()
SOURCE = SCRIPT_PATH.read_text(encoding="utf-8")


# --- the pin lists themselves -------------------------------------------------


def test_pinned_dataset_titles_name_every_externally_referenced_dataset():
    assert seeder.PINNED_DATASET_TITLES == (
        "NYC Subway Lines (MTA)",
        "NYC Subway Stations (MTA)",
        "swissALTI3D Matterhorn DEM (2m mosaic)",
        # geolens-examples ci/fixtures.json -> fixtures.meteorites
        "Meteorite Landings (Meteoritical Society)",
    )


def test_pinned_map_names_are_the_four_the_examples_address_by_id():
    assert seeder.PINNED_MAP_NAMES == (
        # /m/NDuwpSJc3yx4Exic5Na48xO-8bpjWiaIofJefpjqfbU (embed/iframe.html)
        "Restless Earth",
        # the three the gallery deep-links by UUID from index.html
        "Manhattan - A Century of Skyline",
        "The Matterhorn in 3D",
        "New York From Orbit - Sentinel-2, by Reference",
    )


def test_a_pinned_name_is_never_also_a_retired_one():
    """--prune deletes RETIRED_* by exact name; the two sets must not overlap."""
    assert set(seeder.PINNED_MAP_NAMES).isdisjoint(seeder.RETIRED_MAPS)
    pinned_titles = set(seeder.PINNED_DATASET_TITLES) | set(
        seeder.PINNED_FOREIGN_DATASET_TITLES
    )
    assert pinned_titles.isdisjoint(seeder.RETIRED_DATASETS)


def test_a_pinned_map_is_never_reported_as_a_stray():
    assert set(seeder.PINNED_MAP_NAMES) <= seeder._showcase_map_names()


def test_the_pin_comment_points_at_the_examples_manifest():
    """Point 3 of #1607: the comment has to name the file to diff against."""
    assert "ci/fixtures.json" in SOURCE
    assert "index.html" in SOURCE


# --- the decision -------------------------------------------------------------

PINNED = "Restless Earth"
UNPINNED = "Hurricane Alley"


@pytest.mark.parametrize(
    ("name", "exists", "force", "force_pinned", "expected"),
    [
        # Nothing there: build it, pinned or not.
        (PINNED, False, False, False, False),
        (PINNED, False, True, False, False),
        (PINNED, False, True, True, False),
        (UNPINNED, False, False, False, False),
        # No --force: the long-standing skip, unchanged.
        (PINNED, True, False, False, True),
        (UNPINNED, True, False, False, True),
        # --force: recreate, EXCEPT a pinned name.
        (UNPINNED, True, True, False, False),
        (PINNED, True, True, False, True),
        # --force-pinned lifts the pin, and only the pin.
        (PINNED, True, True, True, False),
        (UNPINNED, True, True, True, False),
    ],
)
def test_keep_existing_map_truth_table(name, exists, force, force_pinned, expected):
    assert seeder._keep_existing_map(name, exists, force, force_pinned) is expected


def test_force_pinned_alone_does_not_lift_the_pin_without_force():
    """--force-pinned is a modifier: with no --force there is nothing to lift."""
    assert seeder._keep_existing_map(PINNED, True, False, True) is True


def test_the_kept_message_names_the_override_flag(capsys):
    seeder._announce_kept_map(PINNED, force=True)
    out = capsys.readouterr().out
    assert "[pinned]" in out
    assert "--force-pinned" in out

    seeder._announce_kept_map(PINNED, force=False)
    assert "[skip]" in capsys.readouterr().out


# --- the structural guard -----------------------------------------------------


def _unguarded_map_exists_calls(source: str) -> list[int]:
    """Line numbers of `_map_exists(...)` calls not wrapped by the pin helper.

    AST rather than grep so a mention in a comment or docstring cannot pass
    for a call site, and so `def _map_exists(` is not mistaken for one.
    """
    tree = ast.parse(source)

    def _is_call_to(node: ast.AST, fname: str) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == fname
        )

    guarded: set[int] = set()
    for node in ast.walk(tree):
        if _is_call_to(node, "_keep_existing_map"):
            for arg in [*node.args, *(kw.value for kw in node.keywords)]:
                guarded.add(id(arg))

    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if _is_call_to(node, "_map_exists") and id(node) not in guarded
    )


def _guarded_map_exists_count(source: str) -> int:
    tree = ast.parse(source)
    total = sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_map_exists"
    )
    return total - len(_unguarded_map_exists_calls(source))


def test_every_builder_checks_existence_through_the_pin_helper():
    """A builder that spells the check itself cannot honour the pin."""
    unguarded = _unguarded_map_exists_calls(SOURCE)
    assert unguarded == [], (
        f"seed-showcase.py lines {unguarded} call _map_exists() outside "
        "_keep_existing_map(); route the check through the helper so the "
        "pinned maps in PINNED_MAP_NAMES survive --force (see #1607)"
    )


def test_the_guard_is_not_vacuous():
    """An empty list above must mean 'all routed', not 'no call sites left'.

    One per builder that owns a map: restless, manhattan, hurricanes,
    hurricane-exposure, meteorites, matterhorn, sentinel2, embed.
    """
    assert _guarded_map_exists_count(SOURCE) >= 8


def test_the_guard_catches_the_old_bare_shape():
    """Counterfactual: the shape every builder used before #1607 is flagged."""
    before = """
def build_something(api, force=False):
    name = "Restless Earth"
    if not force and _map_exists(api, name):
        print("skip")
        return "(skipped)"
"""
    assert _unguarded_map_exists_calls(before) == [4]
    assert _guarded_map_exists_count(before) == 0


def test_the_guard_accepts_the_new_shape():
    after = """
def build_something(api, force=False, force_pinned=False):
    name = "Restless Earth"
    if _keep_existing_map(name, _map_exists(api, name), force, force_pinned):
        _announce_kept_map(name, force)
        return "(skipped)"
"""
    assert _unguarded_map_exists_calls(after) == []
    assert _guarded_map_exists_count(after) == 1


def _function_node(source: str, name: str) -> ast.FunctionDef:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in seed-showcase.py")


def test_the_force_delete_path_rechecks_the_pin():
    """build_sentinel2's --force branch deletes map rows by id.

    Its early return already covers the pinned name, but the delete loop is
    where the uuid the gallery links actually dies, so the decision is
    re-asked there: one call for the early return, one at the delete.
    """
    body = _function_node(SOURCE, "build_sentinel2")
    calls = [
        node
        for node in ast.walk(body)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_keep_existing_map"
    ]
    assert len(calls) >= 2


# --- --prune-userdata ---------------------------------------------------------


class _FakeApi:
    """Just the surface _classify_userdata reads."""

    username = "admin"
    user_id = "u-admin"

    def __init__(self, maps, datasets):
        self._maps = maps
        self._datasets = datasets

    def list_all_maps(self):
        return self._maps

    def list_all_datasets(self):
        return self._datasets


def _classify(maps, datasets):
    api = _FakeApi(maps, datasets)
    known = seeder._showcase_map_names()
    titles = seeder._showcase_dataset_titles()
    return seeder._classify_userdata(
        api,
        known,
        lambda title: (
            title in titles or title.startswith(seeder._SHOWCASE_TITLE_PREFIXES)
        ),
    )


def test_prune_userdata_hard_keeps_a_pinned_map_whoever_owns_it():
    buckets = _classify(
        [
            {"id": "m1", "name": PINNED, "created_by_username": "admin"},
            {
                "id": "m2",
                "name": "Manhattan - A Century of Skyline",
                "created_by_username": "visitor",
            },
            {"id": "m3", "name": "A visitor's map", "created_by_username": "visitor"},
        ],
        [],
    )
    assert [m["id"] for m in buckets["pinned_maps"]] == ["m1"]
    assert [m["id"] for m in buckets["pinned_map_impostors"]] == ["m2"]
    # The delete set is the only bucket that matters for safety.
    assert [m["id"] for m in buckets["foreign_maps"]] == ["m3"]


def test_prune_userdata_keeps_the_meteorites_dataset():
    buckets = _classify(
        [],
        [
            {
                "id": "d1",
                "title": "Meteorite Landings (Meteoritical Society)",
                "created_by": "u-admin",
            },
            {"id": "d2", "title": "A visitor's upload", "created_by": "u-visitor"},
        ],
    )
    assert [d["id"] for d in buckets["pinned"]] == ["d1"]
    assert [d["id"] for d in buckets["foreign_datasets"]] == ["d2"]


def test_the_prune_report_labels_pinned_maps_as_pinned(capsys):
    seeder._report_pinned_maps(
        [{"name": PINNED}],
        [{"name": "The Matterhorn in 3D", "created_by_username": "visitor"}],
    )
    out = capsys.readouterr().out
    assert "externally pinned maps, hard-kept: 1" in out
    assert PINNED in out
    assert "visitor" in out


# --- the CLI ------------------------------------------------------------------


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_help_lists_the_override_flag():
    result = _run("--help")
    assert result.returncode == 0
    assert "--force-pinned" in result.stdout


def test_help_names_the_sentinel_exception_under_force_pinned():
    """--force-pinned does not cost the same on all four pinned maps.

    For Restless Earth, Manhattan and the Matterhorn the builder creates a
    fresh row and the old one survives with its id. build_sentinel2 runs its
    stale-map loop first, which deletes every row under the name AND their
    share links, so there the override really does destroy the uuid the
    examples link. An operator reads the help, not the source, so the help has
    to carry the exception (fix(#1607 review r3)).
    """
    result = _run("--help")
    assert result.returncode == 0
    # argparse hard-wraps to the terminal width; compare on normalised text.
    text = " ".join(result.stdout.split())
    assert "--force-pinned" in text
    assert "New York From Orbit" in text
    assert "deletes the existing row(s) and their share links" in text
    assert "For the other three" in text


def test_force_pinned_without_force_is_refused():
    """Refused before login, so this never touches a server."""
    result = _run("--force-pinned", "--password", "unused")
    assert result.returncode == 2
    assert "--force-pinned is only meaningful with --force" in result.stderr


# --- --prune ------------------------------------------------------------------


class _PruneApi:
    """Records what prune() would delete instead of deleting it."""

    def __init__(self, maps, datasets):
        self._maps = maps
        self._datasets = datasets
        self.deleted_maps = []
        self.deleted_datasets = []

    def list_maps(self):
        return self._maps

    def list_own_datasets(self):
        return self._datasets

    def collections_by_name(self):
        return {}

    def delete_map(self, map_id):
        self.deleted_maps.append(map_id)

    def delete_dataset(self, dataset_id, title):
        self.deleted_datasets.append(title)


def test_prune_keeps_a_pinned_name_that_also_appears_in_a_retired_list(monkeypatch):
    """The two lists are meant to be disjoint; prune must not rely on that.

    RETIRED_* is a plain list of names a future edit could collide with, and
    prune deletes by name. So the collision is forced here rather than waiting
    for someone to make it for real.
    """
    retired_map = "World Airports"
    retired_dataset = "World Rivers - Casing"
    assert retired_map in seeder.RETIRED_MAPS
    assert retired_dataset in seeder.RETIRED_DATASETS

    monkeypatch.setattr(seeder, "RETIRED_MAPS", [retired_map, PINNED])
    monkeypatch.setattr(
        seeder,
        "RETIRED_DATASETS",
        [retired_dataset, "Meteorite Landings (Meteoritical Society)"],
    )
    monkeypatch.setattr(seeder, "RETIRED_COLLECTIONS", [])

    api = _PruneApi(
        {retired_map: "m-retired", PINNED: "m-pinned"},
        [
            {"id": "d-retired", "title": retired_dataset},
            {
                "id": "d-pinned",
                "title": "Meteorite Landings (Meteoritical Society)",
            },
        ],
    )
    seeder.prune(api)

    assert api.deleted_maps == ["m-retired"]
    assert api.deleted_datasets == [retired_dataset]


# --- the Sentinel in-place repair (#1607 review r2) ---------------------------


class _LayerApi:
    """Just the surface _replace_map_layers touches, with a call log."""

    def __init__(self, layers):
        self._layers = list(layers)
        self.deleted = []
        self.added = []
        self.deleted_maps = []

    def get_map(self, map_id):
        return {"id": map_id, "layers": self._layers}

    def delete_layer(self, map_id, layer_id):
        self.deleted.append(layer_id)

    def add_layer(self, map_id, body):
        self.added.append(body)

    def delete_map(self, map_id):  # pragma: no cover - must never be called
        self.deleted_maps.append(map_id)


def test_replace_map_layers_swaps_the_stack_and_keeps_the_row():
    api = _LayerApi([{"id": "l-old-1"}, {"id": "l-old-2"}])
    fresh = [
        {"dataset_id": "d1", "sort_order": 0},
        {"dataset_id": "d2", "sort_order": 1},
    ]

    added = seeder._replace_map_layers(api, "m-pinned", fresh)

    assert added == 2
    assert api.deleted == ["l-old-1", "l-old-2"]
    assert api.added == fresh
    # The whole point: the map row is never touched, so its uuid and its share
    # tokens survive the repair.
    assert api.deleted_maps == []


def test_replace_map_layers_handles_a_map_whose_layers_already_cascaded():
    """Deleting the scene datasets takes their layers with them.

    MapLayer.dataset_id is ON DELETE CASCADE, so by the time the repair gets
    here the stack is usually already empty. The delete pass exists for the
    layers that did NOT cascade - a scene kept because another map shares it.
    """
    api = _LayerApi([])
    assert seeder._replace_map_layers(api, "m-pinned", [{"dataset_id": "d1"}]) == 1
    assert api.deleted == []
    assert api.added == [{"dataset_id": "d1"}]


# --- every retained duplicate is rebound (#1607 review r4) --------------------


class _MultiRowApi:
    """A fake holding several same-named rows, each with its own layer stack."""

    def __init__(self, rows):
        self._rows = {rid: list(layers) for rid, layers in rows.items()}
        self.added = {rid: [] for rid in rows}
        self.deleted_layers = {rid: [] for rid in rows}
        self.views = {}
        self.deleted_maps = []

    def get_map(self, map_id):
        return {"id": map_id, "layers": self._rows[map_id]}

    def delete_layer(self, map_id, layer_id):
        self.deleted_layers[map_id].append(layer_id)

    def add_layer(self, map_id, body):
        self.added[map_id].append(body)

    def set_view(self, map_id, **fields):
        self.views[map_id] = fields

    def visibility_check(self, map_id):
        return {"has_non_public": False}

    def delete_map(self, map_id):  # pragma: no cover - must never be called
        self.deleted_maps.append(map_id)


@pytest.mark.parametrize(
    ("newest", "retained", "expected"),
    [
        # The ordinary case: one row, resolved and retained, rebound once.
        ("m-new", ["m-new"], ["m-new"]),
        # Duplicates an older --force stacked up: all of them, primary first.
        ("m-new", ["m-new", "m-old"], ["m-new", "m-old"]),
        ("m-new", ["m-old", "m-new"], ["m-new", "m-old"]),
        # The row vanished during the STAC window: nothing to rebind, and the
        # builder falls through to create_map.
        (None, [], []),
        # --force-pinned deleted them all; the fresh row is not retained.
        (None, [], []),
        # Retained but no longer resolvable by name (renamed underneath us):
        # still rebound, because it still holds the uuid.
        (None, ["m-old"], ["m-old"]),
    ],
)
def test_rows_to_rebind(newest, retained, expected):
    assert seeder._rows_to_rebind(newest, retained) == expected


def test_every_retained_duplicate_is_rebound_and_none_is_deleted():
    """The r4 hole: the scene delete cascades EVERY retained row's layers away.

    Rebinding only the primary would leave the other rows holding their uuids
    with no layers at all - an empty map behind a link the examples may use,
    which is worse than the stale map the pin exists to avoid.
    """
    api = _MultiRowApi({"m-new": [{"id": "l-new-1"}], "m-old": [{"id": "l-old-1"}]})
    layers = [{"dataset_id": "d1", "sort_order": 0}, {"dataset_id": "d2"}]

    primary = seeder._rebind_pinned_rows(
        api, ["m-new", "m-old"], "New York From Orbit", layers, {"visibility": "public"}
    )

    assert primary == "m-new"
    for row in ("m-new", "m-old"):
        assert api.added[row] == layers, f"{row} did not get the fresh stack"
        assert api.deleted_layers[row], f"{row} kept its old layers"
        assert api.views[row] == {"visibility": "public"}, f"{row} missed set_view"
    assert api.deleted_maps == []


def test_rebinding_reports_each_duplicate(capsys):
    api = _MultiRowApi({"m-new": [], "m-old": []})
    seeder._rebind_pinned_rows(api, ["m-new", "m-old"], "n", [], {})
    out = capsys.readouterr().out
    # The primary's line is the builder's "-> map"; only the extras announce
    # themselves here, or a single-row repair would print a confusing echo.
    assert "also rebound duplicate row m-old" in out
    assert "m-new" not in out


def test_sentinel2_does_not_return_on_a_pinned_keep():
    """The pinned keep must not short-circuit the repair.

    Every other builder returns straight out of the `_keep_existing_map` block.
    build_sentinel2 has to fall through it, or `--only sentinel2 --force` -- the
    documented repair for instances seeded before item_href -- is reachable
    only via --force-pinned, which mints the new uuid the examples must not get.
    """
    body = _function_node(SOURCE, "build_sentinel2")
    guard = next(
        node
        for node in ast.walk(body)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_keep_existing_map"
        and any(
            isinstance(a, ast.Call)
            and isinstance(a.func, ast.Name)
            and a.func.id == "_map_exists"
            for a in node.args
        )
    )
    # The decision is bound to a name rather than used as a bare `if` test:
    # the repair path needs it again further down to pick reuse over create.
    assert isinstance(guard, ast.Call)
    bindings = [
        n
        for n in ast.walk(body)
        if isinstance(n, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "keep_pinned_row" for t in n.targets
        )
    ]
    assert bindings, "build_sentinel2 must keep the pin decision, not return on it"

    # And it must reuse the rows: the retained-row list feeds the rebind.
    called = {
        n.func.id
        for n in ast.walk(body)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "_rows_to_rebind" in called
    assert "_rebind_pinned_rows" in called


def _callers_of(fname: str) -> set[str]:
    return {
        node.name
        for node in ast.walk(ast.parse(SOURCE))
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(c, ast.Call)
            and isinstance(c.func, ast.Name)
            and c.func.id == fname
            for c in ast.walk(node)
        )
    }


def test_only_sentinel2_replaces_layers_in_place():
    """No other builder rebinds a stack; they create their maps outright.

    The rebind goes through _rebind_pinned_rows so that EVERY retained row is
    rebound, not just the primary - a builder reaching _replace_map_layers
    directly would be back to rebinding one row (fix(#1607 review r4)).
    """
    assert _callers_of("_replace_map_layers") == {"_rebind_pinned_rows"}
    assert _callers_of("_rebind_pinned_rows") == {"build_sentinel2"}


# --- the outcome main() reports (#1607 review r2) -----------------------------


def test_a_pinned_keep_returns_a_distinct_marker():
    assert seeder._announce_kept_map(PINNED, force=True) == "(pinned)"
    assert seeder._announce_kept_map(PINNED, force=False) == "(skipped)"


def test_the_pinned_outcome_line_does_not_tell_you_to_use_force():
    """--force is what already ran and declined; saying "use --force" is wrong."""
    line = seeder._builder_outcome_line("sentinel2", "(pinned)")
    assert line is not None
    assert "--force-pinned" in line
    assert "use --force to recreate" not in line


def test_the_ordinary_skip_line_is_unchanged():
    line = seeder._builder_outcome_line("manhattan", "(skipped)")
    assert line == "  manhattan: already exists, skipped (use --force to recreate)"


def test_a_falsy_result_still_reports_as_skipped():
    assert seeder._builder_outcome_line("embed", None) is not None
    assert seeder._builder_outcome_line("embed", "") is not None


def test_a_map_id_reports_nothing_and_counts_as_built():
    assert seeder._builder_outcome_line("manhattan", "dcae16bd-40bd") is None
    # The two builders that return a sentinel of their own must keep counting
    # as built, exactly as they did before the marker was added.
    assert seeder._builder_outcome_line("catalog", "(catalog)") is None
    assert seeder._builder_outcome_line("collections", "(none)") is None
