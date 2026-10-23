"""Limits on the code labels an attribute carries."""

import json

MAX_VALUE_LABELS = 5000
MAX_VALUE_LABEL_LENGTH = 500
# Across one dataset's columns. The per-field caps alone allow megabytes per
# column, and the attributes list returns every column's labels.
MAX_DATASET_VALUE_LABEL_BYTES = 1024 * 1024


def value_labels_bytes(labels: dict[str, str] | None) -> int:
    """Size of the labels as the budget counts it: their JSON text in UTF-8."""
    return len(json.dumps(labels, ensure_ascii=False).encode()) if labels else 0
