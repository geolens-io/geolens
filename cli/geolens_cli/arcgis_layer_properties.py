# SPDX-License-Identifier: Apache-2.0
"""Report notes for the ArcGIS layer properties an import doesn't carry.

Hand-maintained. GeoLens's service probe reports, per layer, its time
settings, subtype field, M values, and time-only and timestamp-offset fields;
an imported dataset keeps none of these as ArcGIS defines them. Each note
names the layer, what was not carried over and what arrived instead.
"""

from __future__ import annotations

from typing import Any

# Every note below contains it; the report lists such notes as follow-ups.
NOT_CARRIED = "not carried over"


def _names(value: Any) -> list[str]:
    return (
        [v for v in value if isinstance(v, str) and v]
        if isinstance(value, list)
        else []
    )


def _label(layer: Any) -> str:
    title = getattr(layer, "title", None)
    return title if isinstance(title, str) and title else str(layer.name)


def property_notes(layers: Any) -> list[str]:
    """One note per property each probed layer has that an import drops."""
    notes: list[str] = []
    for layer in layers:
        label = _label(layer)
        time_fields = getattr(layer, "time_fields", None)
        if isinstance(time_fields, list):
            on = _names(time_fields)
            fields = f" on {', '.join(on)}" if on else ""
            notes.append(
                f"layer {label}: its time settings{fields} are {NOT_CARRIED}; "
                "the fields arrive as ordinary columns"
            )
        subtype_field = getattr(layer, "subtype_field", None)
        if isinstance(subtype_field, str) and subtype_field:
            notes.append(
                f"layer {label}: its subtypes are {NOT_CARRIED}; field "
                f"{subtype_field} arrives as a plain column without the subtype names"
            )
        if getattr(layer, "has_m", None) is True:
            notes.append(
                f"layer {label}: its M values are {NOT_CARRIED}; the geometries "
                "arrive without them"
            )
        if time_only := _names(getattr(layer, "time_only_fields", None)):
            notes.append(
                f"layer {label}: time-only field(s) {', '.join(time_only)} are "
                f"{NOT_CARRIED} as times; they arrive as text"
            )
        if offset := _names(getattr(layer, "timestamp_offset_fields", None)):
            notes.append(
                f"layer {label}: timestamp-offset field(s) {', '.join(offset)} are "
                f"{NOT_CARRIED} with their offsets; each arrives as the instant "
                "without its UTC offset"
            )
    return notes
