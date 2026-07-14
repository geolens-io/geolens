"""Edition-neutral constants for saved-map sharing policy."""

from typing import Literal, TypeAlias

ShareExpirationPresetDays: TypeAlias = Literal[1, 7, 30, 90]

SHARE_EXPIRATION_PRESET_DAYS = frozenset({1, 7, 30, 90})
SHARE_EXPIRATION_SELECTION_ERROR = (
    "Choose either a fixed expiration preset or a custom expiration date, not both"
)
