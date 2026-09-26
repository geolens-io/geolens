import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { CopyButton } from '@/components/ui/copy-button';
import { appOriginUrl } from '@/lib/dataset-access';
import type { DatasetVisibility } from '@/types/api';

type Client = 'qgis' | 'potree' | 'copc';

function clientSnippet(client: Client, url: string, withKey: boolean): string {
  if (client === 'qgis') {
    const steps = `QGIS 3.26+ → Layer > Add Layer > Add Point Cloud Layer\nSource type: Protocol: HTTP(S), cloud, etc.\nURL: ${url}`;
    return withKey
      ? `${steps}\nAuthentication: API Header → X-Api-Key: YOUR_API_KEY`
      : steps;
  }

  if (client === 'potree') {
    const potreeUrl = withKey ? `${url}?api_key=YOUR_API_KEY` : url;
    return [
      `Potree.loadPointCloud("${potreeUrl}", "Point cloud", function (event) {`,
      '  viewer.scene.addPointCloud(event.pointcloud);',
      '  viewer.fitToScreen();',
      '});',
    ].join('\n');
  }

  if (!withKey) {
    return [
      'import { Copc } from "copc";',
      `const copc = await Copc.create("${url}");`,
      'console.log(copc.header.pointCount);',
    ].join('\n');
  }

  return [
    'import { Copc } from "copc";',
    `const url = "${url}";`,
    'const get = async (begin, end) => {',
    '  const response = await fetch(url, {',
    '    headers: { Range: `bytes=${begin}-${end - 1}`, "X-Api-Key": "YOUR_API_KEY" },',
    '  });',
    '  if (response.status !== 206) throw new Error(`COPC range request failed: ${response.status}`);',
    '  return new Uint8Array(await response.arrayBuffer());',
    '};',
    'const copc = await Copc.create(get);',
    'console.log(copc.header.pointCount);',
  ].join('\n');
}

/** The versioned file URL and client examples for a published COPC file. */
export function PointCloudAccess({ url: path, visibility }: { url: string; visibility: DatasetVisibility }) {
  const { t } = useTranslation('dataset');
  const [client, setClient] = useState<Client>('qgis');
  const url = appOriginUrl(path);
  const withKey = visibility !== 'public';
  const snippet = clientSnippet(client, url, withKey);

  return (
    <section aria-labelledby="pointcloud-access-title" className="space-y-3">
      <h2 id="pointcloud-access-title" className="text-base font-semibold tracking-tight">
        {t('pointcloud.accessTitle')}
      </h2>
      <div className="space-y-1.5">
        <span className="text-sm text-muted-foreground">{t('pointcloud.urlLabel')}</span>
        <div className="flex items-center gap-2">
          <code className="flex-1 truncate rounded-sm bg-muted px-2 py-1.5 font-mono text-xs text-foreground" title={url}>
            {url}
          </code>
          <CopyButton value={url} label={t('pointcloud.copyUrl')} />
        </div>
      </div>
      {withKey && (
        <p className="text-xs text-muted-foreground">
          {t('pointcloud.privateHint')}{' '}
          <Link to="/settings" className="underline hover:text-foreground">
            {t('serviceUrls.manageApiKeys')}
          </Link>
        </p>
      )}
      <div role="group" aria-label={t('pointcloud.clientLabel')} className="flex flex-wrap gap-1 rounded-lg border bg-muted/40 p-1 w-fit">
        {(['qgis', 'potree', 'copc'] as const).map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={client === option}
            onClick={() => setClient(option)}
            className={`rounded-md px-3 py-1.5 text-xs font-medium ${client === option ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
          >
            {option === 'qgis' ? 'QGIS 3.26+' : option === 'potree' ? 'Potree' : 'copc.js'}
          </button>
        ))}
      </div>
      {client === 'potree' && withKey && (
        <p className="text-xs text-muted-foreground">{t('pointcloud.potreeHint')}</p>
      )}
      <div className="rounded-lg overflow-hidden border bg-(--code-bg) text-(--code-text)">
        <div className="flex items-center gap-2 px-3.5 py-2 bg-(--code-chrome) border-b border-(--code-chrome-border)">
          <span className="font-mono text-mini text-(--code-muted)">
            {client === 'qgis' ? 'QGIS 3.26+' : client === 'potree' ? 'Potree' : 'copc.js'}
          </span>
          <span className="flex-1" />
          <CopyButton value={snippet} label={t('pointcloud.copySnippet')} />
        </div>
        <pre className="px-5 py-4 font-mono text-xs leading-7 overflow-x-auto whitespace-pre-wrap m-0">{snippet}</pre>
      </div>
    </section>
  );
}
