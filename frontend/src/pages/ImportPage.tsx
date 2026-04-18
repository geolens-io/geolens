import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload, Database, Globe } from 'lucide-react';
import { PageShell } from '@/components/layout/PageShell';
import { UploadForm } from '@/components/import/UploadForm';
import { RegisterForm } from '@/components/import/RegisterForm';
import { ServiceUrlForm } from '@/components/import/ServiceUrlForm';
import { WorkflowRail } from '@/components/import/WorkflowRail';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { cn } from '@/lib/utils';
import type { BatchPhase } from '@/types/api';

type Tab = 'upload' | 'register' | 'service';

const MODE_TABS: { value: Tab; icon: typeof Upload; labelKey: string }[] = [
  { value: 'upload', icon: Upload, labelKey: 'tabs.upload' },
  { value: 'register', icon: Database, labelKey: 'tabs.register' },
  { value: 'service', icon: Globe, labelKey: 'tabs.service' },
];

export function ImportPage() {
  const { t } = useTranslation('import');
  const [activeTab, setActiveTab] = useState<Tab>('upload');
  const [uploadPhase, setUploadPhase] = useState<BatchPhase>('idle');
  useDocumentTitle(t('common:pageTitle.import'));

  return (
    <PageShell className="space-y-0">
      {/* Hero */}
      <div className="pb-4 pt-2">
        <p className="mb-2.5 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
          {t('eyebrow', { defaultValue: 'Import' })}
        </p>
        <h1 className="text-3xl font-medium tracking-tight">
          {t('title', { defaultValue: 'Bring data into the atlas' })}
        </h1>
        <p className="mt-2.5 max-w-2xl text-[15px] text-muted-foreground">
          {t('pageDescription', {
            defaultValue:
              'Upload files, register tables from your Postgres, or connect a remote service. GeoLens detects geometry, schema, and CRS, then makes it queryable, styleable, and embeddable.',
          })}
        </p>

        {/* Mode tabs */}
        <div className="mt-6 inline-flex border-b border-border">
          {MODE_TABS.map(({ value, icon: Icon, labelKey }) => (
            <button
              key={value}
              onClick={() => setActiveTab(value)}
              className={cn(
                'inline-flex items-center gap-2 border-b-2 px-4 pb-3 pt-3 text-[13.5px] font-medium transition-colors',
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
      </div>

      {/* Two-column layout */}
      <div className="grid grid-cols-1 gap-7 pb-12 pt-6 xl:grid-cols-[1fr_320px]">
        <div className="min-w-0">
          {activeTab === 'upload' && <UploadForm onPhaseChange={setUploadPhase} />}
          {activeTab === 'register' && <RegisterForm />}
          {activeTab === 'service' && <ServiceUrlForm />}
        </div>
        <WorkflowRail
          mode={activeTab}
          phase={activeTab === 'upload' ? uploadPhase : 'idle'}
        />
      </div>
    </PageShell>
  );
}
