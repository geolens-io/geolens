import { useCallback, useEffect, useEffectEvent, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router';
import { ArrowLeft, BookOpen, Settings2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '@/api/client';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { EmptyState } from '@/components/layout/EmptyState';
import { ErrorState } from '@/components/layout/ErrorState';
import { LoadingState } from '@/components/layout/LoadingState';
import { StoryMapPane, type StoryMapPaneHandle } from '@/components/stories/StoryMapPane';
import { StoryUnavailableState } from '@/components/stories/StoryUnavailableState';
import { canEditStory } from '@/components/stories/can-edit-story';
import { BlockingMapsList } from '@/components/stories/editor/BlockingMapsList';
import { ChapterEditor } from '@/components/stories/editor/ChapterEditor';
import { ChapterList } from '@/components/stories/editor/ChapterList';
import { StoryDetailsDialog } from '@/components/stories/editor/StoryDetailsDialog';
import { MAX_CHAPTERS, sameChapters } from '@/components/stories/editor/story-draft';
import { useStoryEditor, type EditorBusy } from '@/components/stories/editor/use-story-editor';
import { resolveScene } from '@/components/stories/story-scenes';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { usePermissions } from '@/hooks/use-permissions';
import { useStory, useStoryDraft } from '@/hooks/use-stories';
import { useUnsavedGuard } from '@/hooks/use-unsaved-guard';
import { randomId } from '@/lib/random-id';
import { useAuthStore } from '@/stores/auth-store';
import type { StoryDraftResponse } from '@/types/api';

/** /stories/:id/edit: the draft editor, for the story's owner or an admin. */
export function StoryEditorPage() {
  const { t } = useTranslation('stories');
  const { id } = useParams<{ id: string }>();
  const { can, isLoading: permissionsLoading } = usePermissions();
  const userId = useAuthStore((s) => s.user?.id ?? null);
  // The editor works from a copy taken at mount, so it waits for a fresh read
  // rather than starting from a cached draft another tab may have replaced.
  const { data, isFetchedAfterMount, error, refetch } = useStoryDraft(id);
  const status = error instanceof ApiError ? error.status : undefined;
  const editing =
    isFetchedAfterMount && !permissionsLoading && !error && !!data && canEditStory(can, data);
  // The editor names the page after the story, including a renamed one.
  useDocumentTitle(editing ? null : t('pageTitle'));

  if (!isFetchedAfterMount || permissionsLoading) return <LoadingState className="flex-1" message={t('editor.loading')} />;
  if (status === 404) return <StoryUnavailableState returnTo={`/stories/${id}/edit`} />;
  if (status === 403 || (data && !canEditStory(can, data))) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <EmptyState
          icon={BookOpen}
          className="w-full max-w-xl"
          title={t('editor.forbidden')}
          description={t('editor.forbiddenDescription')}
          action={
            <Button asChild variant="outline">
              <Link to={`/stories/${id}`}>{t('editor.viewStory')}</Link>
            </Button>
          }
        />
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <ErrorState message={t('editor.loadFailed')} onRetry={() => refetch()} />
      </div>
    );
  }
  // Keyed by account as well, for the reason in captureAccount.
  return <StoryEditor key={`${userId}:${data.id}`} initial={data} />;
}

interface SaveState {
  busy: EditorBusy;
  dirty: boolean;
  failed: boolean;
  stale: boolean;
  uploading: boolean;
  missingAlt: number;
}

function statusKey(
  { busy, dirty, failed, stale, uploading, missingAlt }: SaveState,
  everPublished: boolean,
  hasUnpublished: boolean,
) {
  if (busy === 'save') return 'editor.status.saving';
  if (dirty) {
    if (stale) return 'editor.status.unsaved';
    if (failed) return 'editor.status.saveFailed';
    if (uploading) return 'editor.status.waitingForUpload';
    if (missingAlt > 0) return 'editor.status.waitingForAlt';
    return 'editor.status.unsaved';
  }
  if (!everPublished) return 'editor.status.neverPublished';
  if (hasUnpublished) return 'editor.status.unpublishedChanges';
  return 'editor.status.published';
}

function StoryEditor({ initial }: { initial: StoryDraftResponse }) {
  const { t } = useTranslation('stories');
  const editor = useStoryEditor(initial);
  const { story, chapters, dirty, edit, busy, blocked, failed, stale, uploads, missingAlt, tooLarge, unsaveable } = editor;
  const everPublished = story.published_at !== null;
  const { data: published } = useStory(story.id, { enabled: everPublished });
  const [selectedId, setSelectedId] = useState(initial.document.chapters[0]?.id ?? null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [confirmReload, setConfirmReload] = useState(false);
  const [confirmOverwrite, setConfirmOverwrite] = useState(false);
  const [removing, setRemoving] = useState<number | null>(null);
  const [focusTitleId, setFocusTitleId] = useState<string | null>(null);
  // Set on a confirmed delete: the row to focus next, or null for Add chapter.
  const focusAfterRemove = useRef<{ id: string | null } | null>(null);
  const paneRef = useRef<StoryMapPaneHandle>(null);
  const blocker = useUnsavedGuard(dirty);
  // Leaving saves pending edits first and asks only when they can't be saved.
  // A failed save keeps the author here, where its error or conflict shows.
  const [askToLeave, setAskToLeave] = useState(false);
  const onLeave = useEffectEvent(() => {
    if (!editor.canAutosave) {
      setAskToLeave(true);
      return;
    }
    void editor.save().then((saved) => (saved ? blocker.proceed?.() : blocker.reset?.()));
  });
  useEffect(() => {
    if (blocker.state === 'blocked') onLeave();
  }, [blocker.state]);
  useDocumentTitle(t('editor.pageTitle', { title: story.title }));

  // A selection that's gone (a discard or reload replaced the chapters) falls back to the first chapter.
  const current = Math.max(0, chapters.findIndex((c) => c.id === selectedId));
  const chapter = chapters[current];
  const publishedChapters = published?.document?.chapters;
  const hasUnpublished = useMemo(
    () =>
      !everPublished ||
      (publishedChapters !== undefined && !sameChapters(publishedChapters, story.document.chapters)),
    [everPublished, publishedChapters, story.document.chapters],
  );
  const missingMapChapterIds = useMemo(() => {
    const missing = new Set(editor.missingMapIds ?? []);
    return new Set(chapters.filter((c) => c.scene && missing.has(c.scene.map_id)).map((c) => c.id));
  }, [chapters, editor.missingMapIds]);
  const saveState = { busy, dirty, failed, stale, uploading: uploads.uploading, missingAlt };
  const replacing = busy === 'discard' || busy === 'reload';

  // Text edits replace the chapter but keep its scene object, so the map pane
  // sees the same scene, and doesn't re-render, on every keystroke.
  const found = resolveScene(chapters, current);
  const scene = found?.scene;
  const sceneChapterId = found?.chapterId;
  const resolved = useMemo(
    () => (scene && sceneChapterId ? { scene, chapterId: sceneChapterId } : null),
    [scene, sceneChapterId],
  );

  const readView = useCallback(() => paneRef.current?.getView() ?? null, []);

  const addChapter = useCallback(() => {
    const id = randomId();
    edit({ type: 'addChapter', id, blockId: randomId() });
    setSelectedId(id);
    setFocusTitleId(id);
  }, [edit]);

  const selectChapter = useCallback((index: number) => setSelectedId(chapters[index].id), [chapters]);
  const moveChapter = useCallback(
    (index: number, by: -1 | 1) => edit({ type: 'moveChapter', chapterId: chapters[index].id, by }),
    [edit, chapters],
  );

  function confirmRemove() {
    if (removing === null) return;
    const removed = chapters[removing];
    const neighbour = chapters[removing + 1] ?? chapters[removing - 1];
    focusAfterRemove.current = { id: neighbour?.id ?? null };
    edit({ type: 'removeChapter', chapterId: removed.id });
    if (removed.id === selectedId) setSelectedId(neighbour?.id ?? null);
    setRemoving(null);
  }

  function focusAfterRemoveClose(event: Event) {
    const next = focusAfterRemove.current;
    if (!next) return;
    focusAfterRemove.current = null;
    event.preventDefault();
    const { id } = next;
    const target = id
      ? document.querySelector<HTMLElement>(`[data-chapter-id="${id}"] [data-chapter-select]`)
      : document.querySelector<HTMLElement>('[data-chapter-add]');
    target?.focus();
  }

  function loadLatest() {
    if (dirty) setConfirmReload(true);
    else void editor.reload();
  }

  return (
    <div className="flex min-h-0 w-full flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b bg-background px-4 py-2">
        <Button asChild variant="ghost" size="sm">
          <Link to={`/stories/${story.id}`}>
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            {t('editor.viewStory')}
          </Link>
        </Button>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-base font-semibold">{story.title}</h1>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <p role="status">{t(statusKey(saveState, everPublished, hasUnpublished))}</p>
            {failed && !stale && (
              <Button
                variant="link"
                size="sm"
                className="h-auto p-0 text-xs"
                onClick={() => void editor.save()}
                disabled={busy !== null}
              >
                {t('editor.status.retry')}
              </Button>
            )}
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={() => setDetailsOpen(true)}>
          <Settings2 className="h-4 w-4" aria-hidden="true" />
          {t('editor.details')}
        </Button>
        {(dirty || hasUnpublished) && everPublished && (
          <Button variant="outline" size="sm" onClick={() => setDiscardOpen(true)} disabled={busy !== null}>
            {t('editor.discard')}
          </Button>
        )}
        <Button
          size="sm"
          onClick={() => void editor.publish()}
          disabled={chapters.length === 0 || busy !== null || unsaveable || uploads.uploading || (!dirty && !hasUnpublished)}
        >
          {busy === 'publish' ? t('editor.publishing') : t('editor.publish')}
        </Button>
      </div>

      {stale && (
        <div role="alert" className="flex flex-wrap items-center gap-3 border-b bg-warning/10 px-4 py-2 text-sm">
          <span className="flex-1">{t('editor.stale')}</span>
          <Button size="sm" variant="outline" onClick={loadLatest} disabled={busy !== null}>
            {t('editor.loadLatest')}
          </Button>
          <Button size="sm" variant="outline" onClick={() => setConfirmOverwrite(true)} disabled={busy !== null}>
            {t('editor.overwrite')}
          </Button>
        </div>
      )}
      {missingMapChapterIds.size > 0 && (
        <div role="alert" className="border-b bg-destructive/10 px-4 py-2 text-sm">
          {t('editor.mapsMissing', { count: missingMapChapterIds.size })}
        </div>
      )}
      {tooLarge && (
        <div role="alert" className="border-b bg-destructive/10 px-4 py-2 text-sm">
          {t('editor.limits.size')}
        </div>
      )}
      {missingAlt > 0 && (
        <div role="status" className="border-b bg-warning/10 px-4 py-2 text-sm">
          {t('editor.limits.altMissing', { count: missingAlt })}
        </div>
      )}

      <div className="flex min-h-0 flex-1 flex-col-reverse md:flex-row">
        {/* inert while a discard or reload replaces the draft: edits made then would be lost. */}
        <div
          inert={replacing}
          className="min-h-0 flex-1 space-y-6 overflow-y-auto border-e bg-background p-4 md:w-[28rem] md:flex-none lg:w-[32rem]"
        >
          <ChapterList
            chapters={chapters}
            selected={current}
            onSelect={selectChapter}
            onMove={moveChapter}
            onRemove={setRemoving}
            onAdd={addChapter}
            canAdd={chapters.length < MAX_CHAPTERS}
            missingMapChapterIds={missingMapChapterIds}
          />
          {chapter ? (
            <section aria-labelledby="story-editor-chapter" className="space-y-4 border-t pt-4">
              <h2 id="story-editor-chapter" className="text-lg font-semibold">
                {t('reader.chapterOf', { index: current + 1, total: chapters.length })}
              </h2>
              <ChapterEditor
                // A new generation (the draft replaced from the server) remounts it,
                // which drops a map choice still loading for the old copy.
                key={`${editor.generation}:${chapter.id}`}
                storyId={story.id}
                uploads={uploads}
                chapter={chapter}
                index={current}
                edit={edit}
                readView={readView}
                mapMissing={missingMapChapterIds.has(chapter.id)}
                focusTitle={chapter.id === focusTitleId}
              />
            </section>
          ) : (
            <p className="text-sm text-muted-foreground">{t('editor.noChapters')}</p>
          )}
        </div>
        <div className="relative h-[40vh] shrink-0 md:h-auto md:min-w-0 md:flex-1">
          <StoryMapPane
            ref={paneRef}
            resolved={resolved}
            emptyHint={t('editor.mapHint')}
            resetKey={editor.generation}
          />
        </div>
      </div>

      <StoryDetailsDialog
        story={story}
        open={detailsOpen}
        onOpenChange={setDetailsOpen}
        onSaved={editor.applyStory}
      />
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        onCloseAutoFocus={focusAfterRemoveClose}
        title={t('editor.removeChapterTitle')}
        description={t('editor.removeChapterDescription', {
          title:
            removing !== null
              ? chapters[removing]?.title || t('reader.untitledChapter', { index: removing + 1 })
              : '',
        })}
        confirm={{ label: t('editor.removeChapter'), onClick: confirmRemove, variant: 'destructive' }}
      />
      <ConfirmDialog
        open={discardOpen}
        onOpenChange={setDiscardOpen}
        title={t('editor.discardTitle')}
        description={t('editor.discardDescription')}
        confirm={{
          label: t('editor.discard'),
          variant: 'destructive',
          pending: busy === 'discard',
          onClick: () => {
            void editor.discard().then(() => setDiscardOpen(false));
          },
        }}
      />
      <ConfirmDialog
        open={confirmReload}
        onOpenChange={setConfirmReload}
        title={t('editor.reloadTitle')}
        description={t('editor.reloadDescription')}
        confirm={{ label: t('editor.loadLatest'), variant: 'destructive', onClick: () => void editor.reload() }}
      />
      <ConfirmDialog
        open={confirmOverwrite}
        onOpenChange={setConfirmOverwrite}
        title={t('editor.overwriteTitle')}
        description={t('editor.overwriteDescription')}
        confirm={{ label: t('editor.overwrite'), variant: 'destructive', onClick: () => void editor.overwrite() }}
      />
      <ConfirmDialog
        open={blocked !== null}
        onOpenChange={(open) => !open && editor.clearConflict()}
        title={t('publish.blockedTitle')}
        description={t('publish.blockedDescription')}
        cancelLabel={t('publish.close')}
      >
        {blocked && (
          <div className="text-sm">
            <BlockingMapsList maps={blocked.maps} unreadableMaps={blocked.unreadableMaps} />
          </div>
        )}
      </ConfirmDialog>
      <ConfirmDialog
        open={askToLeave && blocker.state === 'blocked'}
        onOpenChange={(open) => {
          if (open) return;
          setAskToLeave(false);
          blocker.reset?.();
        }}
        title={t('editor.leaveTitle')}
        description={t('editor.leaveDescription')}
        cancelLabel={t('editor.stay')}
        confirm={{ label: t('editor.leave'), variant: 'destructive', onClick: () => blocker.proceed?.() }}
      />
    </div>
  );
}
