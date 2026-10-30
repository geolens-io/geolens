import { useCallback, useEffect, useEffectEvent, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import i18n from '@/i18n/i18n';
import {
  discardStoryDraft,
  getStoryDraft,
  publishStory,
  reportStoryWriteError,
  saveStoryDraft,
  type StoryConflict,
} from '@/api/stories';
import { queryKeys } from '@/lib/query-keys';
import type { StoryChapter, StoryDraftResponse, StoryResponse } from '@/types/api';
import { captureAccount } from './same-account';
import {
  applyDraftEdit,
  documentBytes,
  imagesMissingAlt,
  MAX_DOCUMENT_BYTES,
  type DraftEdit,
} from './story-draft';
import { useStoryUploads } from './use-story-uploads';

/** How long the author must stop editing before the draft is saved. */
const AUTOSAVE_DELAY_MS = 2000;

export type EditorBusy = 'save' | 'publish' | 'discard' | 'reload' | null;

/**
 * The editor's working copy of a story draft. Edits are saved a moment after
 * the author stops, and when the tab is hidden or the editor closes. A save
 * replaces the whole draft against the revision it was loaded at; a write that
 * loses to another tab comes back as a `stale_revision` conflict, which pauses
 * saving until it's resolved, rather than overwriting it. One operation runs
 * at a time, and each drops its response if another account has signed in
 * since it started.
 */
export function useStoryEditor(initial: StoryDraftResponse) {
  const qc = useQueryClient();
  const id = initial.id;
  const [saved, setSaved] = useState(initial);
  const [chapters, setChapters] = useState(initial.document.chapters);
  const [conflict, setConflict] = useState<StoryConflict | null>(null);
  const [busy, setBusy] = useState<EditorBusy>(null);
  // Set when a save fails; the next edit clears it and so lets autosave try again.
  const [failed, setFailed] = useState(false);
  const running = useRef(false);
  // The editor is remounted for another account, so the one it opened for is fixed.
  const [sameAccount] = useState(captureAccount);
  const uploads = useStoryUploads(initial.id);
  // Bumped when the working copy is replaced from the server; the page keys
  // the chapter editor on it, which drops a map choice still loading.
  const [generation, setGeneration] = useState(0);
  // Every adopted draft and every edit makes a new chapters array, so a
  // reference check is the dirty test; it costs nothing per keystroke.
  const dirty = chapters !== saved.document.chapters;

  const missingAlt = useMemo(() => imagesMissingAlt(chapters), [chapters]);
  const tooLarge = useMemo(() => documentBytes(chapters) > MAX_DOCUMENT_BYTES, [chapters]);
  const unsaveable = tooLarge || missingAlt > 0;
  const stale = conflict?.code === 'stale_revision';

  const edit = useCallback((change: DraftEdit) => {
    setFailed(false);
    setChapters((c) => applyDraftEdit(c, change));
  }, []);

  /** Runs one operation with `busy` set; the page disables every trigger while one runs. */
  async function run(kind: Exclude<EditorBusy, null>, body: (same: () => boolean) => Promise<void>) {
    if (running.current) return;
    running.current = true;
    const same = captureAccount();
    setBusy(kind);
    try {
      await body(same);
    } finally {
      running.current = false;
      if (same()) setBusy(null);
    }
  }

  /**
   * Takes a draft the server returned as the saved copy and the working copy.
   * Pass the chapters that were sent to keep anything typed since: the working
   * copy is replaced only if it's still what was sent.
   */
  function adopt(draft: StoryDraftResponse, sent?: StoryChapter[]) {
    setSaved(draft);
    if (sent) {
      setChapters((current) => (current === sent ? draft.document.chapters : current));
    } else {
      setChapters(draft.document.chapters);
      setGeneration((g) => g + 1);
    }
  }

  function fail(err: unknown, fallbackKey: string, same: () => boolean) {
    if (same()) reportStoryWriteError(err, fallbackKey, setConflict);
  }

  async function persist(revision: number, same: () => boolean): Promise<StoryDraftResponse | null> {
    const sent = chapters;
    try {
      const draft = await saveStoryDraft(id, revision, sent);
      if (!same()) return null;
      adopt(draft, sent);
      setConflict(null);
      setFailed(false);
      qc.invalidateQueries({ queryKey: queryKeys.stories.all });
      return draft;
    } catch (err) {
      if (same()) setFailed(true);
      fail(err, 'stories:editor.saveFailed', same);
      return null;
    }
  }

  const save = () => run('save', async (same) => void (await persist(saved.revision, same)));

  const autosave = useEffectEvent(() => void save());
  const canAutosave = dirty && busy === null && !unsaveable && !uploads.uploading && !stale && !failed;

  useEffect(() => {
    if (!canAutosave) return;
    const timer = setTimeout(autosave, AUTOSAVE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [canAutosave, chapters]);

  // A hidden tab may never come back, so save what's pending now.
  useEffect(() => {
    if (!canAutosave) return;
    const flush = () => {
      if (document.visibilityState === 'hidden') autosave();
    };
    document.addEventListener('visibilitychange', flush);
    window.addEventListener('pagehide', autosave);
    return () => {
      document.removeEventListener('visibilitychange', flush);
      window.removeEventListener('pagehide', autosave);
    };
  }, [canAutosave]);

  // Leaving the page unmounts the editor with edits still waiting out the delay;
  // a failure still reaches the author as a toast.
  const flushOnUnmount = useRef<(() => void) | null>(null);
  useEffect(() => {
    flushOnUnmount.current = canAutosave
      ? () => {
          if (sameAccount()) void persist(saved.revision, sameAccount);
        }
      : null;
  });
  useEffect(() => () => flushOnUnmount.current?.(), []);

  /** Saves the working copy over a draft changed elsewhere, at the revision the conflict reported. */
  const overwrite = () =>
    run('save', async (same) => {
      if (conflict?.code !== 'stale_revision') return;
      await persist(conflict.revision, same);
    });

  const publish = () =>
    run('publish', async (same) => {
      let revision = saved.revision;
      // The working copy as it stands when the publish goes out; anything typed
      // after that is kept when the draft is read back.
      let expected = chapters;
      if (dirty) {
        const draft = await persist(revision, same);
        if (!draft) return;
        revision = draft.revision;
        expected = draft.document.chapters;
      }
      try {
        const story = await publishStory(id, revision);
        if (!same()) return;
        applyStory(story);
        // Publishing drops scenes on deleted maps from the draft without a new
        // revision, so read the draft back.
        const draft = await getStoryDraft(id);
        if (!same()) return;
        adopt(draft, expected);
        toast.success(i18n.t('stories:editor.published'));
      } catch (err) {
        fail(err, 'stories:editor.publishFailed', same);
      }
    });

  /** Replaces the working copy with a draft from the server, dropping unsaved edits. */
  const replace = (
    kind: 'discard' | 'reload',
    request: () => Promise<StoryDraftResponse>,
    done: string | null,
    failedKey: string,
  ) =>
    run(kind, async (same) => {
      try {
        const draft = await request();
        if (!same()) return;
        adopt(draft);
        setConflict(null);
        if (done) toast.success(i18n.t(done));
      } catch (err) {
        fail(err, failedKey, same);
      }
    });

  const discard = () =>
    replace('discard', () => discardStoryDraft(id, saved.revision), 'stories:editor.discarded', 'stories:editor.discardFailed');
  const reload = () => replace('reload', () => getStoryDraft(id), null, 'stories:editor.reloadFailed');

  /** Takes in a story the server returned after publishing or a details change. */
  const applyStory = useCallback(
    (story: StoryResponse) => {
      setSaved((current) => ({
        ...current,
        title: story.title,
        summary: story.summary,
        visibility: story.visibility,
        cover_asset_id: story.cover_asset_id,
        published_at: story.published_at,
        updated_at: story.updated_at,
      }));
      qc.setQueryData(queryKeys.stories.detail(id), story);
      qc.invalidateQueries({ queryKey: queryKeys.stories.all });
    },
    [qc, id],
  );

  return {
    story: saved,
    chapters,
    dirty,
    failed,
    stale,
    uploads,
    missingAlt,
    tooLarge,
    unsaveable,
    canAutosave,
    edit,
    save,
    overwrite,
    publish,
    discard,
    reload,
    applyStory,
    busy,
    generation,
    blocked: conflict?.code === 'maps_narrower_than_story' ? conflict : null,
    missingMapIds: conflict?.code === 'story_maps_not_found' ? conflict.mapIds : null,
    clearConflict: () => setConflict(null),
  };
}
