import {
  applyDraftEdit,
  documentBytes,
  MAX_BLOCKS_PER_CHAPTER,
  MAX_CHAPTERS,
  sameChapters,
} from '../story-draft';
import type { StoryChapter } from '@/types/api';

const camera = { center: [-70, 25] as [number, number], zoom: 3, bearing: 0, pitch: 0 };

function chapter(id: string, overrides: Partial<StoryChapter> = {}): StoryChapter {
  return {
    id,
    title: id,
    scene: null,
    scene_hidden: false,
    blocks: [{ id: `${id}-b`, type: 'markdown', v: 1, title: null, config: { text: `${id} text` } }],
    ...overrides,
  };
}

const ids = (chapters: StoryChapter[]) => chapters.map((c) => c.id);

describe('chapter list edits', () => {
  const three = [chapter('a'), chapter('b'), chapter('c')];

  it('appends a chapter with one empty text block', () => {
    const next = applyDraftEdit(three, { type: 'addChapter', id: 'd', blockId: 'd-b' });
    expect(ids(next)).toEqual(['a', 'b', 'c', 'd']);
    expect(next[3].blocks).toMatchObject([{ id: 'd-b', type: 'markdown', config: { text: '' } }]);
  });

  it('removes and reorders chapters by id, refusing a move past either end', () => {
    expect(ids(applyDraftEdit(three, { type: 'removeChapter', chapterId: 'b' }))).toEqual(['a', 'c']);
    expect(ids(applyDraftEdit(three, { type: 'moveChapter', chapterId: 'c', by: -1 }))).toEqual(['a', 'c', 'b']);
    expect(applyDraftEdit(three, { type: 'moveChapter', chapterId: 'a', by: -1 })).toBe(three);
    expect(applyDraftEdit(three, { type: 'moveChapter', chapterId: 'c', by: 1 })).toBe(three);
  });

  it('lands an edit on its chapter after a reorder, and nowhere once the chapter is gone', () => {
    const moved = applyDraftEdit(three, { type: 'moveChapter', chapterId: 'a', by: 1 });
    const titled = applyDraftEdit(moved, { type: 'setTitle', chapterId: 'a', title: 'First' });
    expect(titled.find((c) => c.id === 'a')?.title).toBe('First');
    expect(titled.find((c) => c.id === 'b')?.title).toBe('b');

    const removed = applyDraftEdit(three, { type: 'removeChapter', chapterId: 'a' });
    const late = applyDraftEdit(removed, { type: 'setMap', chapterId: 'a', mapId: 'm1', camera });
    expect(late.every((c) => c.scene === null)).toBe(true);
  });

  it('stores an empty title as no title', () => {
    expect(applyDraftEdit(three, { type: 'setTitle', chapterId: 'a', title: '' })[0].title).toBeNull();
  });

  it('never changes the list it was given', () => {
    const before = JSON.stringify(three);
    applyDraftEdit(three, { type: 'moveChapter', chapterId: 'a', by: 1 });
    applyDraftEdit(three, { type: 'setBlockText', chapterId: 'a', blockId: 'a-b', text: 'x' });
    expect(JSON.stringify(three)).toBe(before);
  });
});

describe('scene edits', () => {
  it('starts a new map with no layer overrides and clears a hidden scene', () => {
    const hidden = [chapter('a', { scene_hidden: true })];
    const [next] = applyDraftEdit(hidden, { type: 'setMap', chapterId: 'a', mapId: 'm1', camera });
    expect(next.scene).toEqual({ map_id: 'm1', camera, layer_visibility: {} });
    expect(next.scene_hidden).toBe(false);
  });

  it('clears the scene and the hidden flag, so a scene on a map the editor cannot read is dropped', () => {
    const [next] = applyDraftEdit([chapter('a', { scene_hidden: true })], { type: 'clearScene', chapterId: 'a' });
    expect(next).toMatchObject({ scene: null, scene_hidden: false });
  });

  it('sets the camera and layer visibility only on a chapter that has a scene', () => {
    const withScene = applyDraftEdit([chapter('a')], { type: 'setMap', chapterId: 'a', mapId: 'm1', camera });
    const moved = applyDraftEdit(withScene, { type: 'setCamera', chapterId: 'a', camera: { ...camera, zoom: 8 } });
    expect(moved[0].scene?.camera.zoom).toBe(8);
    const toggled = applyDraftEdit(moved, { type: 'setLayerVisible', chapterId: 'a', layerId: 'l1', visible: false });
    expect(toggled[0].scene?.layer_visibility).toEqual({ l1: false });

    const textOnly = [chapter('b')];
    expect(applyDraftEdit(textOnly, { type: 'setCamera', chapterId: 'b', camera })[0].scene).toBeNull();
  });
});

describe('block edits', () => {
  it('adds, edits and removes text blocks', () => {
    const added = applyDraftEdit([chapter('a')], { type: 'addTextBlock', chapterId: 'a', blockId: 'new' });
    expect(added[0].blocks).toHaveLength(2);
    const edited = applyDraftEdit(added, { type: 'setBlockText', chapterId: 'a', blockId: 'a-b', text: 'new' });
    expect(edited[0].blocks?.[0]).toMatchObject({ config: { text: 'new' } });
    const removed = applyDraftEdit(edited, { type: 'removeBlock', chapterId: 'a', blockId: 'a-b' });
    expect(removed[0].blocks?.map((b) => b.id)).not.toContain('a-b');
  });
});

describe('document caps', () => {
  it('adds no chapter past the cap and no block past the per-chapter cap', () => {
    const full = Array.from({ length: MAX_CHAPTERS }, (_, i) => chapter(`c${i}`));
    expect(applyDraftEdit(full, { type: 'addChapter', id: 'x', blockId: 'x-b' })).toBe(full);

    const blocks = Array.from({ length: MAX_BLOCKS_PER_CHAPTER }, (_, i) => ({
      id: `b${i}`, type: 'markdown' as const, v: 1 as const, title: null, config: { text: '' },
    }));
    const crowded = [chapter('a', { blocks })];
    expect(applyDraftEdit(crowded, { type: 'addTextBlock', chapterId: 'a', blockId: 'more' })[0].blocks).toHaveLength(
      MAX_BLOCKS_PER_CHAPTER,
    );
  });

  it('adds up per-chapter sizes to exactly the whole document, and re-measures an edited chapter', () => {
    const measure = (chapters: StoryChapter[]) => {
      const json = JSON.stringify({ version: 1, chapters });
      return json.length + 5 * [...json].filter((c) => c.charCodeAt(0) > 0x7f).length;
    };
    const three = [chapter('a'), chapter('b', { title: 'caf\u00e9' }), chapter('c')];
    expect(documentBytes([])).toBe(measure([]));
    expect(documentBytes(three)).toBe(measure(three));
    const edited = applyDraftEdit(three, { type: 'setTitle', chapterId: 'b', title: 'a much longer title' });
    expect(documentBytes(edited)).toBe(measure(edited));
  });

  it('measures the document as the server does, six bytes per escaped non-ASCII character', () => {
    const ascii = documentBytes([chapter('a', { title: 'abc' })]);
    expect(documentBytes([chapter('a', { title: 'abé' })])).toBe(ascii + 5);
  });
});

describe('sameChapters', () => {
  it('compares by content', () => {
    expect(sameChapters([chapter('a')], [chapter('a')])).toBe(true);
    expect(sameChapters([chapter('a')], [chapter('a', { title: 'other' })])).toBe(false);
  });
});
