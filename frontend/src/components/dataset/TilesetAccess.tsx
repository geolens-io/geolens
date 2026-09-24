import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { CopyButton } from '@/components/ui/copy-button';
import { appOriginUrl } from '@/lib/dataset-access';
import type { DatasetVisibility, TilesetMetadata } from '@/types/api';

// An unresolvable key gets a 401 rather than anonymous access, so a public tileset's snippet sends none.
function cesiumSnippet(url: string, withKey: boolean): string {
  return [
    'const tileset = await Cesium.Cesium3DTileset.fromUrl(',
    '  new Cesium.Resource({',
    `    url: "${url}",`,
    ...(withKey ? ['    headers: { "X-Api-Key": "YOUR_API_KEY" },'] : []),
    '  }),',
    ');',
    'viewer.scene.primitives.add(tileset);',
  ].join('\n');
}

/** Where a 3D Tiles client loads the tileset from, and how it authenticates. */
export function TilesetAccess({
  tileset,
  visibility,
}: {
  tileset: TilesetMetadata;
  visibility: DatasetVisibility;
}) {
  const { t } = useTranslation('dataset');
  const url = appOriginUrl(tileset.url);
  const snippet = cesiumSnippet(url, visibility !== 'public');

  return (
    <section aria-labelledby="tileset-access-title" className="space-y-3">
      <h2 id="tileset-access-title" className="text-base font-semibold tracking-tight">
        {t('tileset.accessTitle')}
      </h2>
      <div className="space-y-1.5">
        <span className="text-sm text-muted-foreground">{t('tileset.urlLabel')}</span>
        <div className="flex items-center gap-2">
          <code className="flex-1 truncate rounded-sm bg-muted px-2 py-1.5 font-mono text-xs text-foreground" title={url}>
            {url}
          </code>
          <CopyButton value={url} label={t('distributions.copyUrl')} />
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        {t('tileset.headerHint')}{' '}
        <Link to="/settings" className="underline hover:text-foreground">
          {t('serviceUrls.manageApiKeys')}
        </Link>
      </p>
      <div className="rounded-lg overflow-hidden border bg-(--code-bg) text-(--code-text)">
        <div className="flex items-center gap-2 px-3.5 py-2 bg-(--code-chrome) border-b border-(--code-chrome-border)">
          <span className="font-mono text-mini text-(--code-muted)">CesiumJS</span>
          <span className="flex-1" />
          <CopyButton value={snippet} label={t('tileset.copySnippet')} />
        </div>
        <pre className="px-5 py-4 font-mono text-xs leading-7 overflow-x-auto whitespace-pre-wrap m-0">{snippet}</pre>
      </div>
    </section>
  );
}
