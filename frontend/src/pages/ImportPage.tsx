import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload, Link, Database, Globe, Satellite } from 'lucide-react';
import { PageHeader } from '@/components/layout/PageHeader';
import { PageShell } from '@/components/layout/PageShell';
import { AppErrorBoundary } from '@/components/error';
import { UploadForm } from '@/components/import/UploadForm';
import { UrlImportForm } from '@/components/import/UrlImportForm';
import { RegisterForm } from '@/components/import/RegisterForm';
import { ServiceUrlForm } from '@/components/import/ServiceUrlForm';
import { StacImportForm } from '@/components/import/StacImportForm';
import { WorkflowRail } from '@/components/import/WorkflowRail';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { cn } from '@/lib/utils';
import type { BatchPhase } from '@/types/api';

type Tab = 'upload' | 'url' | 'register' | 'service' | 'stac';

const MODE_TABS: { value: Tab; icon: typeof Upload; labelKey: string }[] = [
  { value: 'upload', icon: Upload, labelKey: 'tabs.upload' },
  // feat(#1705): URL variant of upload — server-side fetch into staging.
  { value: 'url', icon: Link, labelKey: 'tabs.url' },
  { value: 'register', icon: Database, labelKey: 'tabs.register' },
  { value: 'service', icon: Globe, labelKey: 'tabs.service' },
  { value: 'stac', icon: Satellite, labelKey: 'tabs.stac' },
];

export function ImportPage() {
  const { t } = useTranslation('import');
  const [activeTab, setActiveTab] = useState<Tab>('upload');
  const [uploadPhase, setUploadPhase] = useState<BatchPhase>('idle');
  useDocumentTitle(t('common:pageTitle.import'));

  // fix(#1712): a tab is mounted on first visit and never unmounted again.
  //
  // These panels used to render as `activeTab === x && <Form />`, so switching
  // tabs mid-import UNMOUNTED the running form. The request kept going, since
  // the server does not stop working when a client goes away, and its response
  // landed in dead component state: the job became unreachable from the UI and
  // its staged bytes sat there until the stale-pending sweep took them.
  //
  // Aborting on unmount is not a fix, for the same reason #1708 gives for the
  // URL tab: the abort strands the identical server-side state and throws away
  // the id needed to find it. Not unmounting is the direct answer, and it costs
  // one Set: an in-flight XHR's progress callbacks keep writing to live state
  // because the component they belong to is still there.
  //
  // Mount-on-FIRST-VISIT rather than mount-everything, because these forms do
  // real work when they mount -- RegisterForm lists unregistered tables -- and
  // rendering all five up front would fire that for tabs nobody opened.
  //
  // This closes tab switching, which is what #1712 reports. It does NOT survive
  // leaving the Import route entirely; only a module-scoped session outside
  // React does that, which is what #1708 built for the URL tab. #1712 stays
  // open for the batch version of that work.
  const [visited, setVisited] = useState<ReadonlySet<Tab>>(() => new Set<Tab>(['upload']));

  const selectTab = useCallback((value: Tab) => {
    setActiveTab(value);
    setVisited((prev) => (prev.has(value) ? prev : new Set(prev).add(value)));
  }, []);

  const panelFor = (value: Tab) => {
    switch (value) {
      case 'upload':
        return <UploadForm onPhaseChange={setUploadPhase} />;
      case 'url':
        return <UrlImportForm />;
      case 'register':
        return <RegisterForm />;
      case 'service':
        return <ServiceUrlForm />;
      case 'stac':
        return <StacImportForm />;
    }
  };

  return (
    <PageShell>
      <PageHeader
        title={t('title', { defaultValue: 'Bring data into the atlas' })}
        description={t('pageDescription', {
          defaultValue:
            'Upload files, register tables from your Postgres, or connect a remote service. GeoLens detects geometry, schema, and CRS, then makes it queryable, styleable, and embeddable.',
        })}
      />

      {/* Mode tabs */}
      <nav
        aria-label={t('tabs.label', { defaultValue: 'Import sources' })}
        className="max-w-full overflow-x-auto"
      >
        <div className="inline-flex min-w-max border-b border-border">
          {MODE_TABS.map(({ value, icon: Icon, labelKey }) => (
            <button
              key={value}
              type="button"
              onClick={() => selectTab(value)}
              aria-current={activeTab === value ? 'page' : undefined}
              className={cn(
                'inline-flex items-center gap-2 border-b-2 px-4 pb-3 pt-3 text-sm font-medium transition-colors',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
                activeTab === value
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground',
              )}
            >
              <Icon
                className={cn(
                  'size-4',
                  activeTab === value ? 'text-primary' : 'text-muted-foreground',
                )}
              />
              {t(labelKey)}
            </button>
          ))}
        </div>
      </nav>

      {/* Two-column layout */}
      <div className="grid grid-cols-1 gap-6 pb-12 xl:grid-cols-[1fr_320px]">
        <div className="min-w-0">
          {MODE_TABS.filter(({ value }) => visited.has(value)).map(({ value }) => (
            // `hidden` rather than unmounting: it takes the panel out of the
            // a11y tree and the tab order while leaving the component alive.
            // One boundary PER panel, because a shared one would let a hidden
            // tab's error blank the tab the user is actually looking at.
            <div key={value} hidden={activeTab !== value}>
              <AppErrorBoundary>{panelFor(value)}</AppErrorBoundary>
            </div>
          ))}
        </div>
        <WorkflowRail
          mode={activeTab}
          phase={activeTab === 'upload' ? uploadPhase : 'idle'}
        />
      </div>
    </PageShell>
  );
}
