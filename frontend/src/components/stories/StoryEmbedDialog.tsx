import { Code } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { CopyButton } from '@/components/ui/copy-button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { useTileConfig } from '@/hooks/use-settings';
import { getShareableBaseUrl } from '@/lib/public-urls';
import { storyEmbedCode } from './story-embed';

/** The iframe snippet for a published public story, behind an "Embed" button. */
export function StoryEmbedDialog({ storyId, title }: { storyId: string; title: string }) {
  const { t } = useTranslation('stories');
  const { data: tileConfig } = useTileConfig();
  const origin = getShareableBaseUrl(tileConfig, window.location.origin);
  const code = storyEmbedCode({ origin, storyId, title });

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Code className="h-4 w-4" aria-hidden="true" />
          {t('embed.open')}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('embed.title')}</DialogTitle>
          <DialogDescription>{t('embed.description')}</DialogDescription>
        </DialogHeader>
        <div className="relative">
          <Textarea
            readOnly
            value={code}
            rows={4}
            aria-label={t('embed.codeLabel')}
            className="resize-none bg-muted/30 pe-10 font-mono text-xs"
            onFocus={(event) => event.currentTarget.select()}
          />
          <CopyButton
            value={code}
            label={t('embed.copy')}
            className="absolute end-1.5 top-1.5 inline-flex h-7 w-7 items-center justify-center rounded-sm border bg-background hover:bg-muted"
          />
        </div>
      </DialogContent>
    </Dialog>
  );
}
