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
MAX_LISTED = 8


def _names(value: Any) -> list[str]:
    return (
        [v for v in value if isinstance(v, str) and v]
        if isinstance(value, list)
        else []
    )


def _label(layer: Any) -> str:
    title = getattr(layer, "title", None)
    name = title if isinstance(title, str) and title else str(layer.name)
    # Two layers of a service may share a name; their notes must stay apart.
    layer_id = getattr(layer, "layer_id", None)
    return name if layer_id is None else f"{name} (layer {layer_id})"


def _get(layer: Any, key: str) -> Any:
    """A probe field; an older SDK model keeps keys it doesn't know in
    ``additional_properties``."""
    value = getattr(layer, key, None)
    if value is None:
        extra = getattr(layer, "additional_properties", None)
        value = extra.get(key) if isinstance(extra, dict) else None
    return value


def _listed(names: list[str]) -> str:
    """The first few *names*; a long list would push the note past the state's
    length cap."""
    shown = ", ".join(names[:MAX_LISTED])
    more = len(names) - MAX_LISTED
    return f"{shown} and {more} more" if more > 0 else shown


def property_notes(layers: Any) -> list[str]:
    """One note per property each probed layer has that an import drops."""
    notes: list[str] = []
    for layer in layers:
        label = _label(layer)
        time_fields = _get(layer, "time_fields")
        if isinstance(time_fields, list):
            on = _names(time_fields)
            fields = f" ({_listed(on)})" if on else ""
            notes.append(
                f"layer {label}: its time settings are {NOT_CARRIED}; "
                f"the fields arrive as ordinary columns{fields}"
            )
        subtype_field = _get(layer, "subtype_field")
        if isinstance(subtype_field, str) and subtype_field:
            notes.append(
                f"layer {label}: its subtypes are {NOT_CARRIED}; field "
                f"{subtype_field} arrives as a plain column without the "
                "type or subtype names"
            )
        if _get(layer, "has_m") is True:
            notes.append(
                f"layer {label}: its M values are {NOT_CARRIED}; the geometries "
                "arrive without them"
            )
        if time_only := _names(_get(layer, "time_only_fields")):
            notes.append(
                f"layer {label}: time-only fields are {NOT_CARRIED} as times; "
                f"they may arrive as text ({_listed(time_only)})"
            )
        if offset := _names(_get(layer, "timestamp_offset_fields")):
            notes.append(
                f"layer {label}: timestamp-offset fields are {NOT_CARRIED} with "
                "their offsets; each arrives as the instant without its UTC "
                f"offset ({_listed(offset)})"
            )
    return notes


def recorded_notes(entry: Any) -> list[str]:
    """The loss notes of an item: those in its notes and those kept for each
    layer it imported, which an item that failed on another layer still has."""
    held = [n for key in entry.layer_datasets for n in entry.layer_notes.get(key, [])]
    own = [n for n in entry.notes if n.startswith("layer ") and NOT_CARRIED in n]
    return list(dict.fromkeys([*own, *held]))
