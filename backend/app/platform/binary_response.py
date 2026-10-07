"""OpenAPI ``responses`` entry for routes that return raw bytes."""

from typing import Any


def binary_response(description: str, *media_types: str) -> dict[str, Any]:
    """Declare each media type as a binary body, so a generated client returns bytes."""
    return {
        "description": description,
        "content": {
            media_type: {"schema": {"type": "string", "format": "binary"}}
            for media_type in media_types
        },
    }
