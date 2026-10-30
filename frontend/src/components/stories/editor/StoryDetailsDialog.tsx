import { useId, useState, type FormEvent } from 'react';
import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { reportStoryWriteError, storyAssetPath, updateStory, type MapsBlockingStory } from '@/api/stories';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { AssetImage } from '@/components/widgets/image/AssetImage';
import { getVisibilityLabel } from '@/i18n/labels';
import type { StoryDraftResponse, StoryResponse, StoryUpdate, StoryVisibility } from '@/types/api';
import { StoryTextFields } from '../StoryTextFields';
import { BlockingMapsList } from './BlockingMapsList';
import { captureAccount } from './same-account';
import { StoryImagePicker } from './StoryImagePicker';

const VISIBILITIES: StoryVisibility[] = ['private', 'internal', 'public'];

interface StoryDetailsDialogProps {
  story: StoryDraftResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (story: StoryResponse) => void;
}

/** Title, summary, visibility and cover. These apply at once, without Publish. */
export function StoryDetailsDialog({ story, open, onOpenChange, onSaved }: StoryDetailsDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* Inside the content, so the form starts from the story each time the dialog opens. */}
        <StoryDetailsForm story={story} onSaved={onSaved} onClose={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function StoryDetailsForm({
  story,
  onSaved,
  onClose,
}: {
  story: StoryDraftResponse;
  onSaved: (story: StoryResponse) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation('stories');
  const visibilityId = useId();
  const [title, setTitle] = useState(story.title);
  const [summary, setSummary] = useState(story.summary ?? '');
  const [visibility, setVisibility] = useState<string>(story.visibility);
  const [cover, setCover] = useState<string | null>(story.cover_asset_id ?? null);
  // Saving mid-upload would keep the old cover and close the dialog, cancelling the upload.
  const [coverUploading, setCoverUploading] = useState(false);
  const [blocked, setBlocked] = useState<MapsBlockingStory | null>(null);
  const update = useMutation({ mutationFn: (body: StoryUpdate) => updateStory(story.id, body) });

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const body: StoryUpdate = {};
    if (title.trim() !== story.title) body.title = title.trim();
    if ((summary.trim() || null) !== story.summary) body.summary = summary.trim() || null;
    if (visibility !== story.visibility) body.visibility = visibility as StoryVisibility;
    if (cover !== (story.cover_asset_id ?? null)) body.cover_asset_id = cover;
    if (Object.keys(body).length === 0) {
      onClose();
      return;
    }
    const same = captureAccount();
    try {
      const story = await update.mutateAsync(body);
      if (!same()) return;
      onSaved(story);
      toast.success(t('details.saved'));
      onClose();
    } catch (err) {
      if (!same()) return;
      reportStoryWriteError(err, 'stories:details.saveFailed', (conflict) => {
        if (conflict.code === 'maps_narrower_than_story') setBlocked(conflict);
      });
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <DialogHeader>
        <DialogTitle>{t('details.heading')}</DialogTitle>
        <DialogDescription>{t('details.description')}</DialogDescription>
      </DialogHeader>
      <StoryTextFields title={title} summary={summary} onTitleChange={setTitle} onSummaryChange={setSummary} />
      <div className="space-y-1">
        <Label htmlFor={visibilityId}>{t('details.visibilityLabel')}</Label>
        <Select
          value={visibility}
          onValueChange={(value) => {
            setVisibility(value);
            setBlocked(null);
          }}
        >
          <SelectTrigger id={visibilityId} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {/* A story shared with groups reads back as restricted, which this dialog can't set. */}
            {!VISIBILITIES.includes(story.visibility as StoryVisibility) && (
              <SelectItem value={story.visibility} disabled>
                {getVisibilityLabel(t, story.visibility)}
              </SelectItem>
            )}
            {VISIBILITIES.map((value) => (
              <SelectItem key={value} value={value}>
                {getVisibilityLabel(t, value)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">{t('details.visibilityHint')}</p>
      </div>
      <CoverField storyId={story.id} cover={cover} onChange={setCover} onUploadingChange={setCoverUploading} />
      {blocked && (
        <div role="alert" className="space-y-2 rounded-md border border-destructive/40 p-3 text-sm">
          <p>{t('details.visibilityBlocked')}</p>
          <BlockingMapsList maps={blocked.maps} unreadableMaps={blocked.unreadableMaps} />
        </div>
      )}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          {t('common:cancel')}
        </Button>
        <Button type="submit" disabled={!title.trim() || update.isPending || coverUploading}>
          {update.isPending ? t('details.saving') : t('details.save')}
        </Button>
      </DialogFooter>
    </form>
  );
}

function CoverField({
  storyId,
  cover,
  onChange,
  onUploadingChange,
}: {
  storyId: string;
  cover: string | null;
  onChange: (cover: string | null) => void;
  onUploadingChange: (uploading: boolean) => void;
}) {
  const { t } = useTranslation('stories');
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="space-y-2">
      <h3 id={headingId} className="text-sm font-medium">
        {t('details.cover.heading')}
      </h3>
      <AssetImage
        path={cover ? storyAssetPath(storyId, cover) : null}
        alt={t('details.cover.preview')}
        className="aspect-[2/1] w-full rounded-md object-cover"
        placeholderClassName="aspect-[2/1] w-full"
        fallback={cover ? null : <p className="text-sm text-muted-foreground">{t('details.cover.none')}</p>}
      />
      <div className="flex flex-wrap items-start gap-2">
        <StoryImagePicker
          storyId={storyId}
          label={cover ? t('details.cover.replace') : t('details.cover.choose')}
          onUploaded={(asset) => onChange(asset.id)}
          onUploadingChange={onUploadingChange}
        />
        {cover && (
          <Button type="button" variant="ghost" size="sm" onClick={() => onChange(null)}>
            {t('details.cover.remove')}
          </Button>
        )}
      </div>
      <p className="text-xs text-muted-foreground">{t('details.cover.hint')}</p>
    </section>
  );
}
