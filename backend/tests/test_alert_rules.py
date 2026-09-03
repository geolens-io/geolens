"""Structural guards for the Prometheus alert rules — fix(#1517).

Monitoring config is the category where a change goes green while asserting
nothing. A PromQL ``handler!~"..."`` that matches nothing, or matches
everything, reads identically to a working one in a diff, and #1517 shipped a
rule whose threshold could not be crossed by any traffic at all. These tests
check the things review cannot see:

1. Every ``histogram_quantile`` threshold in the rules is below the top finite
   bucket the app actually configures. ``histogram_quantile`` returns the
   highest FINITE bucket bound for anything landing in ``+Inf``, so a threshold
   at or above it can never be crossed. The rule looks like coverage and is dead
   on arrival. That is exactly how ``GeoLensApiInteractiveLatencyP95`` came to
   report ``1`` on all three of its firings.
2. The bulk-read selector partitions the app's real route table the way the
   rules claim, over (handler, method) PAIRS rather than paths. A path is not a
   request: ``/datasets/{dataset_id}/features`` answers GET and POST off one
   template, so a path-only check would pass while feature creation sat outside
   interactive monitoring (fix(#1521 review)).

Every expectation list is checked against the live route table, so it cannot rot
into a set of paths nothing matches.

Filesystem, YAML parse and a route-table walk. No database, no Docker.
``infra/monitoring/alerts.test.yml`` covers the rules' runtime behaviour under
promtool, and the Monitoring Rules job in ci.yml runs it; this module covers the
structure, and runs wherever the backend suite runs.
"""

from __future__ import annotations

import collections
import pathlib
import re
from typing import Any

import pytest
import yaml

from app.observability.metrics import LATENCY_LOWR_BUCKETS

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
ALERTS_PATH = REPO_ROOT / "infra" / "monitoring" / "alerts.yml"
ALERTS_TEST_PATH = REPO_ROOT / "infra" / "monitoring" / "alerts.test.yml"
PROMETHEUS_PATH = REPO_ROOT / "infra" / "monitoring" / "prometheus.yml"

# fix(#1778): metrics whose value is produced per PROCESS rather than read
# from shared state. The job counters are incremented inside whichever worker
# replica performed the terminal transition, so each replica exports its own
# series for the same queue and any alert over them has to aggregate. The
# gauges in the same family are the opposite case -- every replica polls the
# same procrastinate_jobs rows, so they all report the same number and
# `max by (queue)` is right for them.
PER_PROCESS_JOB_COUNTERS = ("geolens_jobs_completed_total", "geolens_jobs_failed_total")

# Bulk reads: the response is whatever the caller asked for, so over a second is
# the cost of the payload rather than a symptom. Excluded from the interactive
# p95 rule, covered by GeoLensApiBulkLatencyMean.
BULK_HANDLERS = {
    "/datasets/{dataset_id}/features",
    "/datasets/{dataset_id}/features/",
    "/datasets/{dataset_id}/features.geojson",
    "/datasets/{dataset_id}/export",
    "/datasets/{dataset_id}/download/cog",
    "/collections/{dataset_id}/items",
    "/collections/{dataset_id}/items/",
    "/collections/datasets/items",
    "/stac/collections/{collection_id}/items",
}

# Handlers whose paths look bulk and are not: single-object reads, and
# mutations whose name merely contains "bulk". Admin exports are here on
# purpose — see the rationale in the GeoLensApiBulkLatencyMean comment.
BULK_LOOKALIKES = {
    "/datasets/{dataset_id}/features/{gid}",
    "/datasets/{dataset_id}/features/{gid}/related/{relationship_id}",
    "/collections/{dataset_id}/items/{feature_id}",
    "/collections/datasets/items/{record_id}",
    "/stac/collections/{collection_id}/items/{item_id}",
    "/stac/items/{item_id}",
    "/datasets/bulk-delete",
    "/maps/{map_id}/layers/bulk-delete",
    "/admin/embed-tokens/bulk-revoke",
    "/ingest/register/bulk",
    "/admin/audit-logs/export/{format}",
    "/admin/users/export.csv",
    "/config-ops/export",
}

# The verbs that make a request to a bulk path an actual bulk transfer. HEAD is
# here because _register_standards_head_routes() clones the GET route with the
# same endpoint, so it does the same work and only drops the body on the wire.
READ_METHODS = {"GET", "HEAD"}


def _load_rules() -> dict[str, dict[str, Any]]:
    """Every alerting rule in alerts.yml, keyed by alert name."""
    doc = yaml.safe_load(ALERTS_PATH.read_text())
    rules = {
        rule["alert"]: rule
        for group in doc["groups"]
        for rule in group["rules"]
        if "alert" in rule
    }
    assert len(rules) >= 8, (
        f"only {len(rules)} alerting rules parsed out of {ALERTS_PATH} — the "
        "file has at least 8. Every assertion below iterates this mapping, so "
        "a parse that quietly yields few or none would pass vacuously."
    )
    return rules


def _unquote_promql_string(raw: str) -> str:
    r"""Return the regex a PromQL double-quoted string literal denotes.

    PromQL processes escapes inside ``"..."``, so the two characters ``\\`` in
    the YAML reach the regex engine as one backslash. Comparing the raw YAML
    text against handler names instead of the unescaped form is the quiet way to
    test a regex nobody is actually running.
    """
    return raw.replace("\\\\", "\\")


def _matchers(expr: str, label: str) -> list[tuple[str, str]]:
    """Every ``(operator, value)`` for *label* in a PromQL expression.

    Returns a list, not one match: the interactive rule carries a ``handler!~``
    and a ``handler=~`` in the two arms of its union, and reading only the first
    would silently skip half the rule.
    """
    return re.findall(rf'{re.escape(label)}\s*(!~|=~|!=|=)\s*"([^"]*)"', expr)


def _sole(values: list[str], what: str) -> str:
    """The single distinct value in *values*, or an assertion failure."""
    assert values, f"no {what} found"
    distinct = set(values)
    assert len(distinct) == 1, (
        f"{what} is not spelled the same everywhere it appears: {sorted(distinct)}"
    )
    return values[0]


def _bulk_selector() -> str:
    """The bulk-path regex, asserted identical everywhere it is written."""
    rules = _load_rules()
    interactive = _matchers(rules["GeoLensApiInteractiveLatencyP95"]["expr"], "handler")
    bulk = _matchers(rules["GeoLensApiBulkLatencyMean"]["expr"], "handler")

    excluded = [v for op, v in interactive if op == "!~"]
    covered = [v for op, v in interactive if op == "=~"] + [
        v for op, v in bulk if op == "=~"
    ]
    assert len(excluded) == 1, (
        f"expected exactly one handler!~ in the interactive rule, got {excluded}"
    )

    # fix(#1513): there are now TWO distinct handler selectors, each written
    # exactly three times, and the count is partitioned by value rather than
    # relaxed. The bulk set appears in the interactive union arm and both halves
    # of the bulk ratio; the export-HEAD carve-out appears in its own
    # interactive union arm and in the `unless` on each half of that ratio.
    #
    # A second selector is forced, not stylistic: Prometheus ANDs the matchers
    # inside one selector and RE2 has no lookahead, so "the bulk paths except
    # HEAD on export" cannot be spelled as a single handler matcher. Holding
    # each spelling to three copies keeps the original invariant — every copy
    # of a selector is identical — which a `>= 3` would give up entirely.
    spellings = collections.Counter(covered)
    assert sorted(spellings.values()) == [3, 3], (
        "expected exactly two handler selectors written three times each (the "
        "bulk set, and the export-HEAD carve-out), got "
        f"{ {value: count for value, count in spellings.items()} }"
    )

    tile_prefix = "/tiles/.*|"
    assert excluded[0].startswith(tile_prefix), (
        "the interactive rule's exclusion no longer starts with the tile "
        f"selector from #658: {excluded[0]!r}"
    )
    selector = excluded[0][len(tile_prefix) :]
    assert spellings.get(selector) == 3, (
        "the interactive rule excludes a different set of paths than the bulk "
        "rule covers, so something is double-alerted or unmonitored.\n"
        f"  interactive excludes: {selector!r}\n"
        f"  selectors found:      { {v: c for v, c in spellings.items()} }"
    )

    # The other spelling must be one of the alternatives the bulk selector
    # covers. A carve-out for a path the bulk rule never claimed would move
    # nothing and quietly leave the handler in both rules or neither.
    carve_outs = [value for value in spellings if value != selector]
    assert len(carve_outs) == 1, f"expected one carve-out selector, got {carve_outs}"
    assert carve_outs[0] in selector.split("|"), (
        "the carved-out handler is not one of the paths the bulk selector "
        f"covers: {carve_outs[0]!r} not in {selector.split('|')}"
    )
    assert selector.count("|") >= 4, (
        f"bulk selector has fewer alternatives than expected: {selector!r}"
    )
    return _unquote_promql_string(selector)


def _read_method_selector() -> str:
    """The read-verb alternation, asserted complementary across both rules."""
    rules = _load_rules()
    interactive = _matchers(rules["GeoLensApiInteractiveLatencyP95"]["expr"], "method")
    bulk = _matchers(rules["GeoLensApiBulkLatencyMean"]["expr"], "method")

    negated = [v for op, v in interactive if op == "!~"]
    matched = [v for op, v in bulk if op == "=~"]
    assert len(negated) == 1, (
        "the interactive rule must negate the read verbs on its bulk-path arm, "
        f"otherwise a POST to a bulk path leaves monitoring entirely: {negated}"
    )
    assert len(matched) == 2, (
        f"expected method=~ on both halves of the bulk ratio, got {len(matched)}"
    )
    selector = _sole(matched + negated, "the read-method selector")
    return selector


def _route_universe() -> set[tuple[str, str]]:
    """Every ``(handler, method)`` pair the instrumentator can label.

    The handler label is the route's fully-prefixed template path, and the
    method label is the request verb. fastapi 0.140 keeps included-router routes
    nested, so a plain walk of ``app.routes`` sees almost nothing;
    ``_iter_api_routes`` is the repo's own flattening helper.
    """
    from app.api.main import _iter_api_routes, app

    pairs = {
        (ctx.path, method)
        for ctx in _iter_api_routes(app)
        for method in (ctx.route.methods or set())
    }
    assert len(pairs) > 100, (
        f"only {len(pairs)} (handler, method) pairs resolved from the route "
        "table; the app registers several hundred. A near-empty universe would "
        "make every assertion below pass without testing anything."
    )
    return pairs


def test_histogram_quantile_thresholds_are_reachable():
    """A quantile threshold at or above the top finite bucket can never fire.

    This is the #1517 defect itself, as an assertion. Before that fix the top
    finite bucket was 1.0 and the rule's bound was ``>= 1``: satisfiable only by
    the clamp, never by a measurement.
    """
    top_finite_bucket = max(LATENCY_LOWR_BUCKETS)
    checked = 0
    for name, rule in _load_rules().items():
        expr = rule["expr"]
        if "histogram_quantile" not in expr:
            continue
        checked += 1
        bounds = re.findall(r"[<>]=?\s*([0-9.]+)\s*$", expr.strip())
        assert bounds, f"{name}: could not read a comparison bound from:\n{expr}"
        threshold = float(bounds[-1])
        assert threshold < top_finite_bucket, (
            f"{name} compares p95 against {threshold}, but the top finite "
            f"bucket in LATENCY_LOWR_BUCKETS is {top_finite_bucket}. "
            "histogram_quantile clamps there, so this rule can only fire on "
            "the clamp value, not on a latency. Widen the buckets in "
            "backend/app/observability/metrics/__init__.py or lower the bound."
        )
    assert checked, (
        "no histogram_quantile rule found in alerts.yml — this test would "
        "otherwise pass by checking nothing."
    )


def test_bulk_selector_is_spelled_identically_in_both_rules():
    """PromQL cannot share a selector, so the copies have to be kept in step."""
    assert _bulk_selector()


def test_read_method_partition_is_complementary():
    """The verbs the bulk rule claims are exactly the ones interactive gives up.

    Without this, `method=~"GET"` on one side and `method!~"GET|HEAD"` on the
    other would leave HEAD requests to bulk paths in neither rule.
    """
    selector = _read_method_selector()
    assert set(selector.split("|")) == READ_METHODS, (
        f"the rules treat {sorted(set(selector.split('|')))} as bulk reads, but "
        f"this test expects {sorted(READ_METHODS)}. If that is a deliberate "
        "change, say why HEAD does or does not do the work of a GET and update "
        "READ_METHODS with it."
    )


def test_bulk_selector_matches_exactly_the_intended_handlers():
    """Run the shipped selector against the app's real handler labels.

    PromQL label matchers are fully anchored, hence ``fullmatch``. Exact
    equality is deliberate: a new route that lands in this set is a decision
    about whether it is a bulk transfer, and this test is where that decision
    gets made rather than discovered during an incident.
    """
    universe = {path for path, _ in _route_universe()}
    pattern = re.compile(_bulk_selector())
    matched = {h for h in universe if pattern.fullmatch(h)}

    assert matched, (
        "the bulk selector matches none of the "
        f"{len(universe)} real handler labels. GeoLensApiBulkLatencyMean would "
        "never fire and GeoLensApiInteractiveLatencyP95 would keep paging on "
        "bulk traffic."
    )
    assert matched != universe, (
        "the bulk selector matches every handler — nothing is left for "
        "GeoLensApiInteractiveLatencyP95 to watch."
    )
    assert matched == BULK_HANDLERS, (
        "bulk selector no longer matches the intended handler set.\n"
        f"  unexpectedly matched: {sorted(matched - BULK_HANDLERS)}\n"
        f"  expected but missed:  {sorted(BULK_HANDLERS - matched)}"
    )


def test_bulk_rule_claims_only_read_requests():
    """fix(#1521 review): the bulk rule may not swallow writes to bulk paths.

    ``/datasets/{dataset_id}/features`` answers GET and POST off one template.
    Under a path-only selector, feature creation left the interactive p95 and
    was judged against a 5s bound built for 10MB downloads.
    """
    universe = _route_universe()
    bulk_paths = re.compile(_bulk_selector())
    read_methods = re.compile(_read_method_selector())

    writes_to_bulk_paths = {
        (path, method)
        for path, method in universe
        if bulk_paths.fullmatch(path) and not read_methods.fullmatch(method)
    }
    assert writes_to_bulk_paths, (
        "no non-read verb is registered on any bulk path, so this test proves "
        "nothing. It is guarding the case where a read and a write share one "
        "path template; if that stopped being true, say so here rather than "
        "leaving an assertion that cannot fail."
    )
    assert ("/datasets/{dataset_id}/features", "POST") in writes_to_bulk_paths, (
        "the POST that motivated this test is gone from the route table; "
        f"currently found: {sorted(writes_to_bulk_paths)}"
    )

    reads_to_bulk_paths = {
        (path, method)
        for path, method in universe
        if bulk_paths.fullmatch(path) and read_methods.fullmatch(method)
    }
    assert reads_to_bulk_paths, "the bulk rule claims no request at all"
    assert any(method == "HEAD" for _, method in reads_to_bulk_paths), (
        "no HEAD request on any bulk path, so the HEAD half of READ_METHODS is "
        "untested. _register_standards_head_routes() should be registering "
        "these; if it no longer does, drop HEAD from READ_METHODS."
    )


@pytest.mark.parametrize("handler", sorted(BULK_HANDLERS))
def test_every_named_bulk_handler_is_a_real_route(handler: str):
    """Guards the expectation list itself against rot."""
    assert handler in {path for path, _ in _route_universe()}, (
        f"{handler} is listed as a bulk handler but is not a route on the app. "
        "Either the route moved (update the selector and this list together) "
        "or the list is now fiction."
    )


def test_bulk_lookalike_handlers_stay_interactive():
    """Single-object reads and "bulk"-named mutations are not bulk transfers."""
    universe = {path for path, _ in _route_universe()}
    pattern = re.compile(_bulk_selector())

    missing = BULK_LOOKALIKES - universe
    assert not missing, (
        "these handlers no longer exist, so asserting they do not match is "
        f"testing nothing: {sorted(missing)}"
    )
    wrongly_matched = {h for h in BULK_LOOKALIKES if pattern.fullmatch(h)}
    assert not wrongly_matched, (
        "the bulk selector swallowed handlers that must stay under the "
        f"interactive p95 rule: {sorted(wrongly_matched)}"
    )


def test_tile_and_bulk_selectors_do_not_overlap():
    """Tiles keep their own rule; nothing may be claimed by both."""
    universe = {path for path, _ in _route_universe()}
    bulk = re.compile(_bulk_selector())
    tiles = re.compile(
        _unquote_promql_string(
            _sole(
                [
                    v
                    for op, v in _matchers(
                        _load_rules()["GeoLensApiTileLatencyMean"]["expr"], "handler"
                    )
                    if op == "=~"
                ],
                "the tile handler selector",
            )
        )
    )
    tile_handlers = {h for h in universe if tiles.fullmatch(h)}
    bulk_handlers = {h for h in universe if bulk.fullmatch(h)}

    assert tile_handlers, "the tile selector matches no real handler"
    assert bulk_handlers, "the bulk selector matches no real handler"
    assert not (tile_handlers & bulk_handlers), (
        "handlers claimed by both the tile and bulk rules: "
        f"{sorted(tile_handlers & bulk_handlers)}"
    )


def test_every_alert_has_a_promtool_case():
    """alerts.test.yml is where the rules' behaviour is exercised.

    It runs under promtool in the Monitoring Rules job, not under pytest, so
    nothing else stops a new rule from shipping untested or a renamed one from
    leaving a test that silently covers an alert that no longer exists.
    """
    rules = _load_rules()
    test_text = ALERTS_TEST_PATH.read_text()

    # Match `alertname:` assertions specifically, not the bare name anywhere in
    # the file: every rule is named in that file's prose too, so a substring
    # check would count a comment as coverage.
    referenced = set(re.findall(r"alertname:\s*(\w+)", test_text))
    assert referenced, f"no alertname assertions found in {ALERTS_TEST_PATH.name}"

    untested = sorted(set(rules) - referenced)
    assert not untested, (
        f"alerts.yml defines rules with no case in {ALERTS_TEST_PATH.name}: {untested}"
    )

    stale = sorted(referenced - set(rules))
    assert not stale, (
        f"{ALERTS_TEST_PATH.name} asserts on alerts that alerts.yml no longer "
        f"defines: {stale}"
    )


def test_alerts_over_per_process_job_counters_aggregate_across_replicas():
    """fix(#1778): a bare increase() on these is evaluated per series.

    The counters move at the terminal transition, in the worker process that
    performed it, so several worker replicas each export their own series for
    one queue. Under a bare `increase(...) > 5`, six failures split three and
    three across two replicas cross nothing and the alert stays silent while
    the queue is visibly failing. Every rule over one of these must sum first.

    The check is on the shape rather than on one rule's text, so a future
    throughput alert on `geolens_jobs_completed_total` cannot ship with the
    same defect.
    """
    rules = _load_rules()

    matched = []
    for name, rule in rules.items():
        expr = rule["expr"]
        for counter in PER_PROCESS_JOB_COUNTERS:
            if counter not in expr:
                continue
            matched.append((name, counter))
            # `sum by (...)` has to wrap the range function, not sit beside it:
            # `increase(sum by (queue) (x[15m]))` is not valid PromQL, and
            # `sum by (queue) (x) > 5` on a counter is a lifetime total rather
            # than a rate. Require the aggregation and the range function to
            # appear in that order.
            sum_at = expr.find("sum by")
            fn_at = min(
                (expr.find(fn) for fn in ("increase(", "rate(") if fn in expr),
                default=-1,
            )
            assert sum_at != -1, (
                f"{name} reads {counter}, which is exported per worker "
                "replica, without a `sum by` -- PromQL evaluates it per series "
                "and failures split across replicas never cross the threshold"
            )
            assert fn_at != -1, (
                f"{name} reads the counter {counter} without a range function; "
                "a raw counter is a lifetime total, not a rate"
            )
            assert sum_at < fn_at, (
                f"{name} must aggregate OUTSIDE the range function: "
                "`sum by (queue) (increase(...[15m]))`"
            )

    assert matched, (
        "no alert reads any of "
        f"{PER_PROCESS_JOB_COUNTERS} -- this test would pass vacuously. If the "
        "counters were renamed, update PER_PROCESS_JOB_COUNTERS with them."
    )


def test_the_reference_scrape_config_discovers_every_worker_replica():
    """fix(#1778): one static worker target is lossy the moment there are two.

    The job counters live in the process that did the work, so a replica
    nobody scrapes contributes nothing to the sum the alert evaluates and its
    failures are invisible. The api job stays static on purpose -- its metrics
    are per-process too, but `UVICORN_WORKERS` runs them behind one address in
    prometheus_client multiprocess mode, so one target already sees them all.
    """
    config = yaml.safe_load(PROMETHEUS_PATH.read_text())
    jobs = {job["job_name"]: job for job in config["scrape_configs"]}
    assert "geolens-worker" in jobs, (
        f"{PROMETHEUS_PATH.name} no longer defines a worker scrape job"
    )

    worker = jobs["geolens-worker"]
    discovery = [key for key in worker if key.endswith("_sd_configs")]
    assert discovery, (
        "the worker job must discover its targets (a *_sd_configs block), not "
        "name one: with several replicas a static single target drops every "
        "other replica's job counters"
    )

    statics = worker.get("static_configs") or []
    single_targets = [cfg for cfg in statics if len(cfg.get("targets", [])) == 1]
    assert not single_targets, (
        "the worker job still carries a single static target beside its "
        f"discovery block: {single_targets}"
    )
