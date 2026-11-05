import { useTranslation } from 'react-i18next';
import type { WidgetRenderProps } from '../contract';
import { AssetImage } from '../image/AssetImage';
import { ImageDescription, ImageFigure } from '../image/ImageBlockFallback';
import { readerAlt } from '../image/definition';
import { GalleryBlockFallback } from './GalleryBlockFallback';
import { entryKeys, type GalleryConfig } from './definition';

/** The block's images in a grid, each fetched once it nears the viewport, with its caption. */
export default function GalleryBlockRenderer(props: WidgetRenderProps<GalleryConfig>) {
  const { config, assetPathFor } = props;
  const { t } = useTranslation('widgets');
  if (!assetPathFor) return <GalleryBlockFallback {...props} />;
  const keys = entryKeys(config.images);
  return (
    <div className="grid grid-cols-1 items-start gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {config.images.map((image, i) => {
        const alt = readerAlt(image);
        return (
          <ImageFigure key={keys[i]} caption={image.caption}>
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
        );
      })}
    </div>
  );
}
