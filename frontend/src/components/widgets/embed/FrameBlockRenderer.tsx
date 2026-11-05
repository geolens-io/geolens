import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import type { WidgetRenderProps } from '../contract';
import { FrameBlockFallback } from './FrameBlockFallback';
import { approvedFrameHost, frameSandbox, useStoryFrameHosts, type FrameConfig } from './frame';

/**
 * A sandboxed, lazily loaded frame of a page on an approved host, with a link
 * to the page under it. While the list loads, or when the host is no longer on
 * it, the reader gets only the link; the page CSP would block the frame anyway.
 */
export function FrameBlockRenderer({ config, kind }: WidgetRenderProps<FrameConfig> & { kind: 'embed' | 'video' }) {
  const { t } = useTranslation('widgets');
  const { data: hosts } = useStoryFrameHosts();
  if (hosts === undefined) return <FrameBlockFallback config={config} />;
  const entry = approvedFrameHost(hosts, config.url);
  if (entry === undefined) {
    return (
      <div className="space-y-1 rounded-md border border-dashed p-3">
        <p className="text-sm text-muted-foreground">{t(`types.${kind}.unavailable`)}</p>
        <FrameBlockFallback config={config} />
      </div>
    );
  }
  // A browser that blocks the frame reports nothing to the page, so the link always stays.
  return (
    <figure className="space-y-1">
      <iframe
        src={config.url}
        title={config.title}
        loading="lazy"
        sandbox={frameSandbox(entry)}
        referrerPolicy="strict-origin-when-cross-origin"
        allowFullScreen={kind === 'video'}
        className={cn('w-full rounded-md border', kind === 'video' ? 'aspect-video' : 'h-[28rem]')}
      />
      <figcaption>
        <p className="text-xs text-muted-foreground">{t('types.embed.originalLink')}</p>
        <FrameBlockFallback config={config} />
      </figcaption>
    </figure>
  );
}
