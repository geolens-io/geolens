import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { storyAssetPath } from '@/api/stories';
import { parseStoredWidget } from '@/components/widgets/registry';
import { WidgetView } from '@/components/widgets/WidgetView';
import type { StoryChapter } from '@/types/api';

export function chapterHeadingId(chapter: StoryChapter) {
  return `story-chapter-${chapter.id}`;
}

/**
 * A chapter's heading and blocks, with a notice when its scene is on a map the
 * reader can't open. Memoized so a chapter change doesn't re-render every block.
 */
export const StoryChapterBody = memo(function StoryChapterBody({
  storyId,
  chapter,
  index,
}: {
  storyId: string;
  chapter: StoryChapter;
  index: number;
}) {
  const { t } = useTranslation('stories');
  return (
    <>
      <h2 id={chapterHeadingId(chapter)} className="text-lg font-semibold text-foreground">
        {chapter.title || t('reader.untitledChapter', { index: index + 1 })}
      </h2>
      <div className="space-y-4">
        {chapter.scene_hidden && (
          <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
            {t('reader.sceneHidden')}
          </p>
        )}
        {(chapter.blocks ?? []).map((block) => (
          <WidgetView
            key={block.id}
            parsed={parseStoredWidget(block, 'story')}
            assetPath={block.type === 'image' ? storyAssetPath(storyId, block.asset_id) : undefined}
          />
        ))}
      </div>
    </>
  );
});
