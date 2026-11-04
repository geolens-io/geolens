import type { WidgetRenderProps } from '../contract';
import { ImageDescription, ImageFigure } from '../image/ImageBlockFallback';
import { readerAlt } from '../image/definition';
import type { GalleryConfig } from './definition';

/** Each image's alt text and caption, for when the images themselves can't be shown. */
export function GalleryBlockFallback({ config }: WidgetRenderProps<GalleryConfig>) {
  return (
    <div className="space-y-3">
      {config.images.map((image) => {
        const alt = readerAlt(image);
        if (!alt && !image.caption) return null;
        return (
          <ImageFigure key={image.asset_id} caption={image.caption}>
            {alt && <ImageDescription alt={alt} />}
          </ImageFigure>
        );
      })}
    </div>
  );
}
