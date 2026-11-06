import { useId, useState, type KeyboardEvent } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import type { WidgetRenderProps } from '../contract';
import { GalleryBlockFallback } from '../gallery/GalleryBlockFallback';
import type { GalleryConfig } from '../gallery/definition';
import { AssetImage } from '../image/AssetImage';
import { ImageDescription, ImageFigure } from '../image/ImageBlockFallback';
import { readerAlt } from '../image/definition';

/**
 * One image at a time, moved by the buttons or the arrow keys. It never
 * advances on its own, and the swap has no animation unless the reader allows
 * motion.
 */
export default function CarouselBlockRenderer(props: WidgetRenderProps<GalleryConfig>) {
  const { config, assetPathFor } = props;
  const { t } = useTranslation('widgets');
  const labelId = useId();
  const [index, setIndex] = useState(0);
  if (!assetPathFor) return <GalleryBlockFallback {...props} />;

  const total = config.images.length;
  const current = Math.min(index, total - 1);
  const image = config.images[current];
  const alt = readerAlt(image);
  const position = t('types.carousel.position', { current: current + 1, total });
  const go = (by: -1 | 1) => setIndex((current + by + total) % total);

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    if (total < 2 || (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight')) return;
    event.preventDefault();
    event.stopPropagation();
    go(event.key === 'ArrowLeft' ? -1 : 1);
  };

  return (
    // Arrow keys reach this handler only from the carousel's own buttons, which hold focus.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <section
      role="group"
      aria-roledescription={t('types.carousel.roleDescription')}
      aria-labelledby={labelId}
      className="space-y-2"
      onKeyDown={onKeyDown}
    >
      <span id={labelId} className="sr-only">
        {t('types.carousel.label')}
      </span>
      <div
        role="group"
        aria-roledescription={t('types.carousel.slideRoleDescription')}
        aria-label={position}
        key={image.asset_id}
        className="motion-safe:animate-in motion-safe:fade-in motion-safe:duration-200"
      >
        <ImageFigure caption={image.caption}>
          <AssetImage
            path={assetPathFor(image.asset_id)}
            alt={alt}
            lazy
            className="h-auto w-full rounded-md"
            placeholderClassName="aspect-video w-full"
            loadingLabel={alt ? t('types.image.loading', { alt }) : undefined}
            fallback={alt ? <ImageDescription alt={alt} /> : null}
          />
        </ImageFigure>
      </div>
      {total > 1 && (
        <div className="flex items-center justify-center gap-3">
          <Button type="button" variant="outline" size="icon" aria-label={t('types.carousel.previous')} onClick={() => go(-1)}>
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          </Button>
          <span className="text-sm tabular-nums text-muted-foreground" aria-hidden="true">
            {position}
          </span>
          <Button type="button" variant="outline" size="icon" aria-label={t('types.carousel.next')} onClick={() => go(1)}>
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
      )}
      <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {alt ? `${position}. ${alt}` : position}
      </p>
    </section>
  );
}
