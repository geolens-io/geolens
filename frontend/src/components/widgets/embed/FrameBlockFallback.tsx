import { useTranslation } from 'react-i18next';
import type { WidgetRenderProps } from '../contract';
import { frameUrlHost, type FrameConfig } from './frame';

/** A link to the framed page, named by the block's title, for when the frame isn't shown. */
export function FrameBlockFallback({ config }: WidgetRenderProps<FrameConfig>) {
  const { t } = useTranslation('widgets');
  const host = frameUrlHost(config.url);
  if (host === null) return <p className="text-sm break-words">{config.title}</p>;
  return (
    <p className="text-sm break-words">
      <a href={config.url} target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-2">
        {config.title}
        <span className="sr-only"> {t('types.button.opensInNewTab')}</span>
      </a>{' '}
      <span className="text-muted-foreground">({host})</span>
    </p>
  );
}
