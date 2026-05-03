"""Core permission constants and default role matrix."""

from __future__ import annotations

UPLOAD = "upload"
CREATE_LAYERS = "create_layers"
EXPORT = "export"
EDIT_METADATA = "edit_metadata"
MANAGE_COLLECTIONS = "manage_collections"
USE_AI_CHAT = "use_ai_chat"
MANAGE_USERS = "manage_users"
MANAGE_SETTINGS = "manage_settings"

ALL_CAPABILITIES: list[str] = [
    UPLOAD,
    CREATE_LAYERS,
    EXPORT,
    EDIT_METADATA,
    MANAGE_COLLECTIONS,
    USE_AI_CHAT,
    MANAGE_USERS,
    MANAGE_SETTINGS,
]

DEFAULT_ROLE_PERMISSIONS: dict[str, dict[str, bool]] = {
    "viewer": {
        UPLOAD: False,
        CREATE_LAYERS: False,
        EXPORT: True,
        EDIT_METADATA: False,
        MANAGE_COLLECTIONS: False,
        USE_AI_CHAT: False,
        MANAGE_USERS: False,
        MANAGE_SETTINGS: False,
    },
    "editor": {
        UPLOAD: True,
        CREATE_LAYERS: True,
        EXPORT: True,
        EDIT_METADATA: True,
        MANAGE_COLLECTIONS: True,
        USE_AI_CHAT: True,
        MANAGE_USERS: False,
        MANAGE_SETTINGS: False,
    },
    "admin": {
        UPLOAD: True,
        CREATE_LAYERS: True,
        EXPORT: True,
        EDIT_METADATA: True,
        MANAGE_COLLECTIONS: True,
        USE_AI_CHAT: True,
        MANAGE_USERS: True,
        MANAGE_SETTINGS: True,
    },
}
