import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useCreateStory } from '@/hooks/use-stories';
import { StoryTextFields } from './StoryTextFields';

/** Names a new story, creates it as a private draft and opens it in the editor. */
export function StoryCreateDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* Inside the content, so the form starts empty each time the dialog opens. */}
        <CreateStoryForm onClose={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function CreateStoryForm({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation('stories');
  const navigate = useNavigate();
  const createStory = useCreateStory();
  const [title, setTitle] = useState('');
  const [summary, setSummary] = useState('');

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    try {
      const story = await createStory.mutateAsync({ title: title.trim(), summary: summary.trim() || null });
      onClose();
      navigate(`/stories/${story.id}/edit`);
    } catch {
      // useCreateStory reports the failure.
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <DialogHeader>
        <DialogTitle>{t('create.title')}</DialogTitle>
        <DialogDescription>{t('create.description')}</DialogDescription>
      </DialogHeader>
      <StoryTextFields title={title} summary={summary} onTitleChange={setTitle} onSummaryChange={setSummary} />
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          {t('common:cancel')}
        </Button>
        <Button type="submit" disabled={!title.trim() || createStory.isPending}>
          {createStory.isPending ? t('create.creating') : t('create.submit')}
        </Button>
      </DialogFooter>
    </form>
  );
}
