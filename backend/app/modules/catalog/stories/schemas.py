"""Story request and response models, and the stored story document.

A story document is ``{"version": 1, "chapters": [...]}``. Each chapter has
an id, an optional title, an optional scene on a saved map and an ordered
list of blocks from the widget registry. The same shape is stored as a
story's draft and, once published, as its published copy.
"""

from __future__ import annotations

import enum
import json
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.catalog.widgets.schemas import ImageWidget, StoryBlock, StoryBlocks

STORY_DOCUMENT_VERSION = 1
# Each block's text is capped too, but 200 chapters of 100 blocks would still
# allow hundreds of megabytes; real stories stay far below this.
MAX_STORY_DOCUMENT_BYTES = 2 * 1024 * 1024


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StoryVisibility(str, enum.Enum):
    """Who may read a published story, besides its owner and admins."""

    private = "private"
    internal = "internal"
    public = "public"


class StoredStoryVisibility(str, enum.Enum):
    """A story's visibility as stored. ``restricted`` is reserved for story
    group sharing, which no route sets yet."""

    private = "private"
    internal = "internal"
    public = "public"
    restricted = "restricted"


Longitude = Annotated[float, Field(ge=-180, le=180)]
Latitude = Annotated[float, Field(ge=-90, le=90)]


class StoryCamera(_Strict):
    center: tuple[Longitude, Latitude] = Field(description="Longitude, latitude.")
    zoom: float = Field(ge=0, le=24)
    bearing: float = Field(default=0, ge=-360, le=360)
    pitch: float = Field(default=0, ge=0, le=85)


class StoryScene(_Strict):
    map_id: uuid.UUID
    camera: StoryCamera
    layer_visibility: dict[uuid.UUID, bool] = Field(
        default_factory=dict,
        max_length=500,
        description=(
            "Visibility by map layer id. Layers the map no longer has are "
            "ignored, and a layer left out keeps its saved visibility."
        ),
    )


class StoryChapterInput(_Strict):
    id: uuid.UUID = Field(description="Made by the client and stable across saves.")
    title: str | None = Field(default=None, max_length=200)
    scene: StoryScene | None = None
    scene_hidden: bool = Field(
        default=False,
        description=(
            "Send back as read to keep a scene on a map you can't read; with "
            "it false, a chapter without a scene loses its stored one."
        ),
    )
    blocks: StoryBlocks = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _check(self) -> StoryChapterInput:
        if self.scene_hidden and self.scene is not None:
            raise ValueError("scene_hidden needs scene to be null")
        if any(isinstance(block, ImageWidget) for block in self.blocks):
            raise ValueError("stories don't take image blocks yet")
        return self


class StoryDocumentInput(_Strict):
    version: Literal[1] = STORY_DOCUMENT_VERSION
    chapters: list[StoryChapterInput] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def _check(self) -> StoryDocumentInput:
        ids = [chapter.id for chapter in self.chapters]
        if len(set(ids)) != len(ids):
            raise ValueError("chapter ids must be unique")
        size = len(
            json.dumps(self.model_dump(mode="json"), separators=(",", ":")).encode()
        )
        if size > MAX_STORY_DOCUMENT_BYTES:
            raise ValueError(
                f"document too large (>{MAX_STORY_DOCUMENT_BYTES} bytes serialized)"
            )
        return self


class StoryChapter(BaseModel):
    id: uuid.UUID
    title: str | None = None
    scene: StoryScene | None = None
    scene_hidden: bool = Field(
        default=False,
        description=(
            "The chapter has a scene on a map you can't read, so it's shown "
            "without one."
        ),
    )
    blocks: list[StoryBlock] = Field(default_factory=list)


class StoryDocument(BaseModel):
    version: int
    chapters: list[StoryChapter]


class StoryCreate(_Strict):
    title: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)


class StoryUpdate(_Strict):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)
    visibility: StoryVisibility | None = Field(
        default=None,
        description=(
            "Refused with 409 when a map the published story uses is "
            "narrower than the new visibility."
        ),
    )


class StoryRevision(_Strict):
    revision: int = Field(
        description="The draft revision this publish or discard acts on."
    )


class StoryDraftUpdate(_Strict):
    revision: int = Field(description="The draft revision this save replaces.")
    document: StoryDocumentInput


class StorySummary(BaseModel):
    id: uuid.UUID
    title: str
    summary: str | None
    visibility: StoredStoryVisibility
    created_by: uuid.UUID | None
    published_at: datetime | None = Field(
        description="When the story was last published; null if never."
    )
    created_at: datetime
    updated_at: datetime
    can_edit: bool


class StoryResponse(StorySummary):
    document: StoryDocument | None = Field(
        description="The published document; null until the story is published."
    )


class StoryDraftResponse(StorySummary):
    revision: int
    document: StoryDocument


class StoryListResponse(BaseModel):
    stories: list[StorySummary]
    total: int


class BlockingMap(BaseModel):
    id: uuid.UUID
    name: str


class MapStoryReference(BaseModel):
    id: uuid.UUID
    title: str


class MapStoriesResponse(BaseModel):
    stories: list[MapStoryReference] = Field(
        description="Stories using the map that you can read, by title."
    )
    hidden_count: int = Field(
        description="Stories using the map that you can't read; not named."
    )
