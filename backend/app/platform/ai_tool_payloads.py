"""Trim AI tool results before they are echoed back into the model's context.

A chat tool result serves two consumers with very different needs:

- the **action collector**, which forwards map payload (GeoJSON overlays) to
  the browser, and
- the **model**, which is re-fed the tool result as conversation context so it
  can narrate the outcome.

Geometry is exclusively the first consumer's business — the model narrates from
``feature_count`` / ``row_count`` / ``rows``, never from raw coordinates. Left
in, a single ``run_analysis`` buffer preview of a 412-feature layer serialized
to ~1.3 MB (~325k tokens), blowing MAX_REQUEST_TOKEN_BUDGET in one round and
billing the user for coordinates the model cannot use. ``query_data``'s overlay
(capped at 50 features) was quietly paying a smaller version of the same tax.

Call this at every point where a tool result is serialized *for the provider*;
the action collector must keep receiving the untrimmed dict.
"""

from __future__ import annotations

# Keys whose whole purpose is client-side map rendering. `bbox` deliberately
# stays: it is four numbers and gives the model useful spatial context.
_MAP_ONLY_KEYS = frozenset({"geojson"})


def model_safe_tool_result(result: dict) -> dict:
    """Return ``result`` without map-only payload, for provider serialization.

    Returns the original object when there is nothing to strip, so the common
    path allocates nothing.
    """
    if not any(key in result for key in _MAP_ONLY_KEYS):
        return result
    return {k: v for k, v in result.items() if k not in _MAP_ONLY_KEYS}
