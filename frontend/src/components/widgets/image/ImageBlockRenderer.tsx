import { useTranslation } from 'react-i18next';
import type { WidgetRenderProps } from '../contract';
import { AssetImage } from './AssetImage';
import { ImageBlockFallback, ImageDescription, ImageFigure } from './ImageBlockFallback';
import type { ImageConfig } from './definition';

/**
 * An uploaded image, fetched once it nears the viewport from the path its host
 * resolved, with the reader's credentials. Nothing in the config is a URL, so a
 * block can't point the reader's browser anywhere else; without a path it
 * shows its fallback.
 */
export default function ImageBlockRenderer({ config, assetPath }: WidgetRenderProps<ImageConfig>) {
  const { t } = useTranslation('widgets');
  if (!assetPath) return <ImageBlockFallback config={config} />;
  return (
    <ImageFigure caption={config.caption}>
      <AssetImage
        path={assetPath}
        alt={config.alt}
        lazy
        className="h-auto w-full rounded-md"
        placeholderClassName="aspect-video w-full"
        loadingLabel={t('types.image.loading', { alt: config.alt })}
        fallback={<ImageDescription alt={config.alt} />}
      />
    </ImageFigure>
  );
}
