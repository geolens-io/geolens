import { useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import type { WidgetRenderProps } from '../contract';
import { AssetImage } from '../image/AssetImage';
import { ImageDescription, ImageFigure } from '../image/ImageBlockFallback';
import { readerAlt } from '../image/definition';
import { GalleryBlockFallback } from './GalleryBlockFallback';
import { entryKeys, type GalleryConfig } from './definition';

/** The block's images in a grid, each fetched once it nears the viewport, with its caption. A thumbnail opens its image full size. */
export default function GalleryBlockRenderer(props: WidgetRenderProps<GalleryConfig>) {
  const { config, assetPathFor } = props;
  const { t } = useTranslation('widgets');
  const [open, setOpen] = useState<number | null>(null);
  // The image stays chosen while the dialog closes, so it can animate out.
  const [dialogOpen, setDialogOpen] = useState(false);
  if (!assetPathFor) return <GalleryBlockFallback {...props} />;
  const keys = entryKeys(config.images);
  const total = config.images.length;
  // A refresh may have shortened the gallery under an open dialog.
  const index = open === null ? null : Math.min(open, total - 1);
  const shown = index === null ? null : config.images[index];
  const shownAlt = shown ? readerAlt(shown) : '';
  const position = index === null ? '' : t('types.carousel.position', { current: index + 1, total });
  const go = (by: -1 | 1) => setOpen((index! + by + total) % total);
  return (
    <>
      <div className="grid grid-cols-1 items-start gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {config.images.map((image, i) => {
          const alt = readerAlt(image);
          return (
            <ImageFigure key={keys[i]} caption={image.caption}>
              <button
                type="button"
                className="block w-full cursor-zoom-in rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                aria-label={t('types.gallery.open', { current: i + 1, total })}
                onClick={() => {
                  setOpen(i);
                  setDialogOpen(true);
                }}
              >
                <AssetImage
                  path={assetPathFor(image.asset_id)}
                  alt={alt}
                  lazy
                  className="h-auto w-full rounded-md"
                  placeholderClassName="aspect-video w-full"
                  loadingLabel={alt ? t('types.image.loading', { alt }) : undefined}
                  fallback={alt ? <ImageDescription alt={alt} /> : null}
                />
              </button>
            </ImageFigure>
          );
        })}
      </div>
      <Dialog open={dialogOpen && shown !== null} onOpenChange={setDialogOpen}>
        {shown && (
          <DialogContent
            aria-describedby={undefined}
            className="max-h-[95vh] w-auto max-w-[95vw] justify-items-center overflow-y-auto sm:max-w-[95vw]"
          >
            <DialogTitle className="sr-only">{shown.caption || shownAlt || position}</DialogTitle>
            <AssetImage
              path={assetPathFor(shown.asset_id)}
              alt={shownAlt}
              className="max-h-[70vh] max-w-[90vw] object-contain"
              placeholderClassName="h-64 w-96 max-w-full"
              loadingLabel={shownAlt ? t('types.image.loading', { alt: shownAlt }) : undefined}
              fallback={shownAlt ? <ImageDescription alt={shownAlt} /> : null}
            />
            {shown.caption && <p className="text-sm text-muted-foreground">{shown.caption}</p>}
            {total > 1 && (
              <div className="flex items-center justify-center gap-3">
                <Button type="button" variant="outline" size="icon" aria-label={t('types.carousel.previous')} onClick={() => go(-1)}>
                  <ChevronLeft className="h-4 w-4" aria-hidden="true" />
                </Button>
                <span className="text-sm tabular-nums text-muted-foreground">{position}</span>
                <Button type="button" variant="outline" size="icon" aria-label={t('types.carousel.next')} onClick={() => go(1)}>
                  <ChevronRight className="h-4 w-4" aria-hidden="true" />
                </Button>
              </div>
            )}
          </DialogContent>
        )}
      </Dialog>
    </>
  );
}
