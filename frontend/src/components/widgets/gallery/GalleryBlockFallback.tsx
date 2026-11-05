import type { WidgetRenderProps } from '../contract';
import { ImageDescription, ImageFigure } from '../image/ImageBlockFallback';
import { readerAlt } from '../image/definition';
import { entryKeys, type GalleryConfig } from './definition';

/** Each image's alt text and caption, for when the images themselves can't be shown. */
export function GalleryBlockFallback({ config }: WidgetRenderProps<GalleryConfig>) {
  const keys = entryKeys(config.images);
  return (
    <div className="space-y-3">
      {config.images.map((image, i) => {
        const alt = readerAlt(image);
        if (!alt && !image.caption) return null;
        return (
          <ImageFigure key={keys[i]} caption={image.caption}>
            {alt && <ImageDescription alt={alt} />}
          </ImageFigure>
        );
      })}
    </div>
  );
}
