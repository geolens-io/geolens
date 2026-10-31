import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import type { WidgetRenderProps } from '../contract';
import { readerAlt, type ImageConfig } from './definition';

export function ImageFigure({ caption, children }: { caption?: string | null; children: ReactNode }) {
  return (
    <figure className="space-y-1">
      {children}
      {caption && <figcaption className="text-xs text-muted-foreground">{caption}</figcaption>}
    </figure>
  );
}

/** The alt text in place of an image that can't be shown. */
export function ImageDescription({ alt }: { alt: string }) {
  const { t } = useTranslation('widgets');
  return (
    <div className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
      {t('types.image.description', { alt })}
    </div>
  );
}

/** The image's alt text and caption, for when the image itself can't be shown. */
export function ImageBlockFallback({ config }: WidgetRenderProps<ImageConfig>) {
  const alt = readerAlt(config);
  if (!alt && !config.caption) return null;
  return (
    <ImageFigure caption={config.caption}>
      {alt && <ImageDescription alt={alt} />}
    </ImageFigure>
  );
}
