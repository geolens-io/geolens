import { useTranslation } from 'react-i18next';
import type { WidgetRenderProps } from '../contract';
import { AssetImage } from './AssetImage';
import { ImageBlockFallback, ImageDescription, ImageFigure } from './ImageBlockFallback';
import { readerAlt, type ImageConfig } from './definition';

/**
 * An uploaded image, fetched once it nears the viewport from the path its host
 * resolved, with the reader's credentials. Nothing in the config is a URL, so a
 * block can't point the reader's browser anywhere else; without a path it
 * shows its fallback.
 */
export default function ImageBlockRenderer({ config, assetPath }: WidgetRenderProps<ImageConfig>) {
  const { t } = useTranslation('widgets');
  if (!assetPath) return <ImageBlockFallback config={config} />;
  const alt = readerAlt(config);
  return (
    <ImageFigure caption={config.caption}>
      <AssetImage
        path={assetPath}
        alt={alt}
        lazy
        className="h-auto w-full rounded-md"
        placeholderClassName="aspect-video w-full"
        loadingLabel={alt ? t('types.image.loading', { alt }) : undefined}
        fallback={alt ? <ImageDescription alt={alt} /> : null}
      />
    </ImageFigure>
  );
}
