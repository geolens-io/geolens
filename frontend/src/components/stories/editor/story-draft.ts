import { arrayMove } from '@dnd-kit/sortable';
import { IMAGE_DEFAULT_CONFIG, validImageAlt } from '@/components/widgets/image/definition';
import { deepEqual } from '@/lib/deep-equal';
import type { StoryCamera, StoryChapter, StoryScene } from '@/types/api';

export const STORY_TITLE_MAX_LENGTH = 200;
export const STORY_SUMMARY_MAX_LENGTH = 2000;
export const CHAPTER_TITLE_MAX_LENGTH = 200;
/** The server's caps on a story document (`StoryDocumentInput` in backend stories/schemas.py). */
export const MAX_CHAPTERS = 200;
export const MAX_BLOCKS_PER_CHAPTER = 100;
export const MAX_DOCUMENT_BYTES = 2 * 1024 * 1024;

type Block = NonNullable<StoryChapter['blocks']>[number];

/**
 * Edits to a draft's chapters, addressed by chapter id so an edit that lands
 * late (after a reorder or delete) reaches the right chapter or none. Each
 * returns a new list and never changes the one passed in.
 */
export type DraftEdit =
  | { type: 'addChapter'; id: string; blockId: string }
  | { type: 'removeChapter'; chapterId: string }
  | { type: 'moveChapter'; chapterId: string; by: -1 | 1 }
  | { type: 'setTitle'; chapterId: string; title: string }
  | { type: 'setMap'; chapterId: string; mapId: string; camera: StoryCamera }
  | { type: 'clearScene'; chapterId: string }
  | { type: 'setCamera'; chapterId: string; camera: StoryCamera }
  | { type: 'setLayerVisible'; chapterId: string; layerId: string; visible: boolean }
  | { type: 'addTextBlock'; chapterId: string; blockId: string }
  | { type: 'setBlockText'; chapterId: string; blockId: string; text: string }
  | { type: 'addImageBlock'; chapterId: string; blockId: string; assetId: string }
  | { type: 'setImage'; chapterId: string; blockId: string; assetId?: string; alt?: string; caption?: string }
  | { type: 'removeBlock'; chapterId: string; blockId: string };

function textBlock(id: string): Block {
  return { id, type: 'markdown', v: 1, title: null, config: { text: '' } };
}

function imageBlock(id: string, assetId: string): Block {
  return { id, type: 'image', v: 1, title: null, asset_id: assetId, config: { ...IMAGE_DEFAULT_CONFIG } };
}

/** How many image blocks still need alt text; the server refuses a draft with any. */
export function imagesMissingAlt(chapters: readonly StoryChapter[]): number {
  return chapters
    .flatMap((chapter) => chapter.blocks ?? [])
    .filter((block) => block.type === 'image' && !validImageAlt(block.config.alt)).length;
}

function update(chapters: StoryChapter[], chapterId: string, change: (c: StoryChapter) => StoryChapter) {
  return chapters.map((chapter) => (chapter.id === chapterId ? change(chapter) : chapter));
}

/** Changes a chapter's scene; a chapter without one is left alone. */
function updateScene(chapters: StoryChapter[], chapterId: string, change: (scene: StoryScene) => StoryScene) {
  return update(chapters, chapterId, (c) => (c.scene ? { ...c, scene: change(c.scene) } : c));
}

function updateBlocks(chapter: StoryChapter, change: (blocks: Block[]) => Block[]): StoryChapter {
  return { ...chapter, blocks: change(chapter.blocks ?? []) };
}

export function applyDraftEdit(chapters: StoryChapter[], edit: DraftEdit): StoryChapter[] {
  switch (edit.type) {
    case 'addChapter':
      if (chapters.length >= MAX_CHAPTERS) return chapters;
      return [
        ...chapters,
        { id: edit.id, title: null, scene: null, scene_hidden: false, blocks: [textBlock(edit.blockId)] },
      ];
    case 'removeChapter':
      return chapters.filter((c) => c.id !== edit.chapterId);
    case 'moveChapter': {
      const from = chapters.findIndex((c) => c.id === edit.chapterId);
      const to = from + edit.by;
      if (from < 0 || to < 0 || to >= chapters.length) return chapters;
      return arrayMove(chapters, from, to);
    }
    case 'setTitle':
      return update(chapters, edit.chapterId, (c) => ({ ...c, title: edit.title || null }));
    case 'setMap':
      return update(chapters, edit.chapterId, (c) => ({
        ...c,
        scene: { map_id: edit.mapId, camera: edit.camera, layer_visibility: {} },
        scene_hidden: false,
      }));
    case 'clearScene':
      // Clearing scene_hidden too drops a stored scene on a map the editor can't read.
      return update(chapters, edit.chapterId, (c) => ({ ...c, scene: null, scene_hidden: false }));
    case 'setCamera':
      return updateScene(chapters, edit.chapterId, (scene) => ({ ...scene, camera: edit.camera }));
    case 'setLayerVisible':
      return updateScene(chapters, edit.chapterId, (scene) => ({
        ...scene,
        layer_visibility: { ...scene.layer_visibility, [edit.layerId]: edit.visible },
      }));
    case 'addTextBlock':
      return update(chapters, edit.chapterId, (c) =>
        (c.blocks?.length ?? 0) >= MAX_BLOCKS_PER_CHAPTER
          ? c
          : updateBlocks(c, (blocks) => [...blocks, textBlock(edit.blockId)]),
      );
    case 'setBlockText':
      return update(chapters, edit.chapterId, (c) =>
        updateBlocks(c, (blocks) =>
          blocks.map((block) =>
            block.id === edit.blockId && block.type === 'markdown'
              ? { ...block, config: { text: edit.text } }
              : block,
          ),
        ),
      );
    case 'addImageBlock':
      return update(chapters, edit.chapterId, (c) =>
        (c.blocks?.length ?? 0) >= MAX_BLOCKS_PER_CHAPTER
          ? c
          : updateBlocks(c, (blocks) => [...blocks, imageBlock(edit.blockId, edit.assetId)]),
      );
    case 'setImage':
      return update(chapters, edit.chapterId, (c) =>
        updateBlocks(c, (blocks) =>
          blocks.map((block) => {
            if (block.id !== edit.blockId || block.type !== 'image') return block;
            const config = { ...block.config };
            if (edit.alt !== undefined) config.alt = edit.alt;
            if (edit.caption !== undefined) config.caption = edit.caption || null;
            return { ...block, asset_id: edit.assetId ?? block.asset_id, config };
          }),
        ),
      );
    case 'removeBlock':
      return update(chapters, edit.chapterId, (c) =>
        updateBlocks(c, (blocks) => blocks.filter((block) => block.id !== edit.blockId)),
      );
  }
}

/** Whether two chapter lists would save the same document. */
export function sameChapters(a: readonly StoryChapter[], b: readonly StoryChapter[]): boolean {
  return deepEqual(a, b);
}

// Python's compact `json.dumps`, which the server measures with, escapes every
// non-ASCII UTF-16 unit as six bytes (`\uXXXX`).
function jsonBytes(value: unknown): number {
  const json = JSON.stringify(value);
  let escaped = 0;
  for (let i = 0; i < json.length; i++) if (json.charCodeAt(i) > 0x7f) escaped++;
  return json.length + 5 * escaped;
}

// Edits copy only the chapters they change, so an unchanged chapter keeps its
// measured size and a keystroke re-measures one chapter, not the document.
const chapterBytes = new WeakMap<StoryChapter, number>();

/** The size the server measures a draft at, in bytes. */
export function documentBytes(chapters: readonly StoryChapter[]): number {
  let total = '{"version":1,"chapters":[]}'.length + Math.max(0, chapters.length - 1);
  for (const chapter of chapters) {
    let size = chapterBytes.get(chapter);
    if (size === undefined) {
      size = jsonBytes(chapter);
      chapterBytes.set(chapter, size);
    }
    total += size;
  }
  return total;
}
