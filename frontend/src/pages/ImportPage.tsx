import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload, Database, Globe, Satellite } from 'lucide-react';
import { PageHeader } from '@/components/layout/PageHeader';
import { PageShell } from '@/components/layout/PageShell';
import { AppErrorBoundary } from '@/components/error';
import { UploadForm } from '@/components/import/UploadForm';
import { RegisterForm } from '@/components/import/RegisterForm';
import { ServiceUrlForm } from '@/components/import/ServiceUrlForm';
import { StacImportForm } from '@/components/import/StacImportForm';
import { WorkflowRail } from '@/components/import/WorkflowRail';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { cn } from '@/lib/utils';
import type { BatchPhase } from '@/types/api';

type Tab = 'upload' | 'register' | 'service' | 'stac';

const MODE_TABS: { value: Tab; icon: typeof Upload; labelKey: string }[] = [
  { value: 'upload', icon: Upload, labelKey: 'tabs.upload' },
  { value: 'register', icon: Database, labelKey: 'tabs.register' },
  { value: 'service', icon: Globe, labelKey: 'tabs.service' },
  { value: 'stac', icon: Satellite, labelKey: 'tabs.stac' },
];

export function ImportPage() {
  const { t } = useTranslation('import');
  const [activeTab, setActiveTab] = useState<Tab>('upload');
  const [uploadPhase, setUploadPhase] = useState<BatchPhase>('idle');
  useDocumentTitle(t('common:pageTitle.import'));

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
              onClick={() => setActiveTab(value)}
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
          <AppErrorBoundary>
            {activeTab === 'upload' && <UploadForm onPhaseChange={setUploadPhase} />}
            {activeTab === 'register' && <RegisterForm />}
            {activeTab === 'service' && <ServiceUrlForm />}
            {activeTab === 'stac' && <StacImportForm />}
          </AppErrorBoundary>
        </div>
        <WorkflowRail
          mode={activeTab}
          phase={activeTab === 'upload' ? uploadPhase : 'idle'}
        />
      </div>
    </PageShell>
  );
}
