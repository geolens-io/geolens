"""The readers of a stored failure reason, and what may become one (#2010).

Three follow-ups to #2004 (#1953): a reader that renders the door's code, a
GDAL driver that names the source inside its own prose, and a query tail
carrying a signing parameter `SENSITIVE_QUERY_PARAMS` does not list.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core import failure_reason as door
from app.core.failure_reason import (
    FAILURE_REASON_SENTENCES,
    INTERNAL_FAILURE_REASON,
    describe_failure_reason,
    redact_failure_reason,
)
from app.platform.notifications.events import build_event_notification
from app.processing.ingest.ogr import IngestionError, _raise_gdal_failure

_APP = Path(__file__).resolve().parents[1] / "app"

# The source GDAL echoes for a zipped upload, and the first stderr line it
# puts that source in. `redact_filesystem_paths` cannot mask this one: its
# lookbehind refuses a run preceded by `/`, which `/vsizip/` supplies.
_STAGED_SOURCE = "/vsizip//app/staging/9f2c1a3e_march.zip"
_PROSE_PATH_LINE = (
    f"ERROR 4: `{_STAGED_SOURCE}' does not exist in the file system, "
    "and is not recognized as a supported dataset name."
)


class TestEveryCodeTheDoorCanEmitHasASentence:
    def test_every_code_constant_is_mapped(self) -> None:
        codes = {
            value
            for name, value in vars(door).items()
            if name.endswith("_FAILURE_REASON") and isinstance(value, str)
        }

        assert codes, "the enumeration found no code to check"
        assert codes <= set(FAILURE_REASON_SENTENCES)
        for code in codes:
            assert describe_failure_reason(code) != code

    def test_a_composed_reason_is_left_alone(self) -> None:
        composed = "Layer 'parcels' has no geometry column"
        assert describe_failure_reason(composed) == composed


class TestTheIngestFailureMailRendersTheSentence:
    def test_a_coded_reason_becomes_its_sentence(self) -> None:
        notification = build_event_notification(
            "ingest_failed",
            subject="Ingest failed",
            body="Ingest job failed.",
            reason=INTERNAL_FAILURE_REASON,
        )

        assert (
            notification.data["reason"]
            == (FAILURE_REASON_SENTENCES[INTERNAL_FAILURE_REASON])
        )
        assert INTERNAL_FAILURE_REASON not in notification.body

    def test_a_composed_reason_reaches_the_reader_unchanged(self) -> None:
        notification = build_event_notification(
            "ingest_failed",
            subject="Ingest failed",
            body="Ingest job failed.",
            reason="Layer 'parcels' has no geometry column",
        )

        assert notification.data["reason"] == "Layer 'parcels' has no geometry column"

    def test_no_call_site_hands_the_mail_an_unredacted_reason(self) -> None:
        offenders: list[str] = []
        for module in sorted(_APP.rglob("*.py")):
            tree = ast.parse(module.read_text())
            safe = _redacted_locals(tree)
            for value in _notification_reasons(tree):
                if _is_safe_reason(value, safe):
                    continue
                offenders.append(
                    f"{module.relative_to(_APP)}:{value.lineno} "
                    f"{ast.unparse(value)[:60]}"
                )
        assert not offenders, offenders

    def test_the_gate_above_can_see_a_violation(self) -> None:
        tree = ast.parse("build_event_notification('ingest_failed', reason=str(exc))\n")
        values = _notification_reasons(tree)

        assert len(values) == 1
        assert not _is_safe_reason(values[0], _redacted_locals(tree))


class TestAGdalReasonIsComposedFromItsFailureClass:
    @pytest.mark.parametrize(
        ("stderr_text", "expected"),
        [
            pytest.param(
                f"ERROR 1: Couldn't fetch requested layer roads.\n{_PROSE_PATH_LINE}",
                "ogrinfo failed (exit 1): the requested layer is not in the source",
                id="missing_layer",
            ),
            pytest.param(
                f"ERROR 1: HTTP error code : 502\n{_PROSE_PATH_LINE}",
                "ogrinfo failed (exit 1): the source service answered HTTP 502",
                id="http_status",
            ),
            pytest.param(
                f"ERROR 1: Failed to process SRS definition: EPSG:999999\n"
                f"{_PROSE_PATH_LINE}",
                "ogrinfo failed (exit 1): "
                "the coordinate reference system could not be resolved",
                id="unresolved_srs",
            ),
            pytest.param(
                f"{_PROSE_PATH_LINE}\nERROR 6: Unsupported field type",
                "ogrinfo failed (exit 1)",
                id="unrecognised",
            ),
        ],
    )
    def test_the_class_composes_the_reason_and_the_source_is_absent(
        self, stderr_text: str, expected: str
    ) -> None:
        with pytest.raises(IngestionError) as exc_info:
            _raise_gdal_failure("ogrinfo", 1, stderr_text, "march.zip")

        assert str(exc_info.value) == expected
        assert _STAGED_SOURCE not in str(exc_info.value)
        assert redact_failure_reason(exc_info.value) == expected

    def test_trimming_the_driver_text_would_have_kept_the_source(self) -> None:
        """The counterfactual: the reason this cut is composition, not a cut."""
        trimmed = redact_failure_reason(
            IngestionError(f"ogrinfo failed (exit 1): {_PROSE_PATH_LINE}")
        )

        assert _STAGED_SOURCE in trimmed

    def test_an_unopenable_source_still_gets_the_friendly_message(self) -> None:
        with pytest.raises(IngestionError) as exc_info:
            _raise_gdal_failure(
                "ogr2ogr", 1, "ERROR 1: file is not a database", "march.gpkg"
            )

        assert str(exc_info.value).startswith("Could not open 'march.gpkg'")


class TestTheDoorDropsAQueryTail:
    def test_a_signing_parameter_no_list_names_is_dropped(self) -> None:
        reason = redact_failure_reason(
            "Failed to download manifest source: "
            "https://example.com/a/b.gpkg?sig2=abcdef123456 timed out"
        )

        assert "abcdef123456" not in reason
        assert "sig2" not in reason
        assert reason.endswith("timed out")

    def test_prose_and_a_query_free_url_are_left_alone(self) -> None:
        assert redact_failure_reason("Is this a GeoPackage? Probably not") == (
            "Is this a GeoPackage? Probably not"
        )
        assert redact_failure_reason(
            "Failed to download manifest source: https://example.com/a/b.gpkg timed out"
        ) == (
            "Failed to download manifest source: https://example.com/a/b.gpkg timed out"
        )


_SANCTIONED_REDACTORS = frozenset(
    {"redact_failure_reason", "prefixed_failure_reason", "coded_failure_reason"}
)


def _call_names(node: ast.AST) -> set[str]:
    return {
        call.func.id
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }


def _redacted_locals(tree: ast.AST) -> set[str]:
    """Names bound from a sanctioned redactor, directly or through an alias.

    The failure tails bind the redacted text once and re-bind it under a
    lambda-safe name at the emit site, so a one-hop rule would miss them.
    """
    assigns = [
        (target.id, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    ]
    names: set[str] = set()
    growing = True
    while growing:
        growing = False
        for name, value in assigns:
            if name in names:
                continue
            if _call_names(value) & _SANCTIONED_REDACTORS or (
                isinstance(value, ast.Name) and value.id in names
            ):
                names.add(name)
                growing = True
    return names


def _notification_reasons(tree: ast.AST) -> list[ast.expr]:
    return [
        keyword.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_event_notification"
        for keyword in node.keywords
        if keyword.arg == "reason"
    ]


def _is_safe_reason(value: ast.expr, redacted: set[str]) -> bool:
    if _call_names(value) & _SANCTIONED_REDACTORS:
        return True
    if isinstance(value, ast.Constant):
        return True
    return isinstance(value, ast.Name) and value.id in redacted
