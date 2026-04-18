import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Check } from 'lucide-react';
import { cn } from '@/lib/utils';
import { TypeTag } from './TypeTag';
import type { DataKind } from './TypeTag';
import type { BatchPhase } from '@/types/api';

type Mode = 'upload' | 'register' | 'service';

interface WorkflowRailProps {
  mode: Mode;
  phase: BatchPhase;
}

const PHASE_TO_STEP: Record<BatchPhase, number> = {
  idle: 0,
  uploading: 0,
  reviewing: 1,
  tracking: 2,
};

export function WorkflowRail({ mode, phase }: WorkflowRailProps) {
  const { t } = useTranslation('import');

  const steps = useMemo(() => [
    {
      title: t('rail.stageTitle', { defaultValue: 'Stage files' }),
      desc: t('rail.stageDesc', { defaultValue: 'Drop or pick files. No commit yet — you can remove any before detection.' }),
    },
    {
      title: t('rail.reviewTitle', { defaultValue: 'Review detection' }),
      desc: t('rail.reviewDesc', { defaultValue: 'Confirm geometry type, CRS, schema, and preview for each file.' }),
    },
    {
      title: t('rail.importTitle', { defaultValue: 'Import & catalog' }),
      desc: t('rail.importDesc', { defaultValue: 'Tile, index, publish — datasets appear in the Catalog immediately.' }),
    },
  ], [t]);

  if (mode === 'register' || mode === 'service') {
    return <NonUploadRail mode={mode} />;
  }

  const activeStep = PHASE_TO_STEP[phase];

  return (
    <aside className="sticky top-28 flex flex-col gap-4">
      {/* Workflow steps */}
      <div className="rounded-xl border border-border bg-card p-4">
        <p className="mb-3 font-mono text-[10.5px] uppercase tracking-widest text-muted-foreground">
          {t('rail.workflow', { defaultValue: 'Workflow' })}
        </p>
        <div className="flex flex-col gap-3.5">
          {steps.map((step, i) => {
            const isDone = i < activeStep;
            const isActive = i === activeStep;
            return (
              <div key={i} className="relative grid grid-cols-[22px_1fr] gap-3">
                {i < steps.length - 1 && (
                  <span className="absolute left-[10px] top-6 bottom-[-14px] w-px bg-border" />
                )}
                <span
                  className={cn(
                    'flex h-[22px] w-[22px] items-center justify-center rounded-full font-mono text-[10px] font-semibold border',
                    isDone && 'bg-success text-success-foreground border-success',
                    isActive && 'bg-primary text-primary-foreground border-primary shadow-[0_0_0_3px] shadow-primary/15',
                    !isDone && !isActive && 'bg-surface-2 text-muted-foreground border-border',
                  )}
                >
                  {isDone ? <Check className="size-3" /> : i + 1}
                </span>
                <div>
                  <h5 className="text-[13px] font-semibold leading-snug">
                    {step.title}
                    {isDone && <span className="ml-1 text-success">&#10003;</span>}
                  </h5>
                  <p className="text-xs leading-relaxed text-muted-foreground">{step.desc}</p>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* What gets imported */}
      <div className="rounded-xl border border-border bg-card p-4">
        <p className="mb-3 font-mono text-[10.5px] uppercase tracking-widest text-muted-foreground">
          {t('rail.whatImported', { defaultValue: 'What gets imported' })}
        </p>
        <div className="flex flex-col gap-2 text-[12.5px]">
          {([
            { kind: 'vector' as DataKind, label: t('rail.vectorLabel', { defaultValue: 'Vector' }), desc: t('rail.vectorDesc', { defaultValue: 'tiled to MVT, spatial index, reprojected to 3857 on read.' }) },
            { kind: 'raster' as DataKind, label: t('rail.rasterLabel', { defaultValue: 'Raster' }), desc: t('rail.rasterDesc', { defaultValue: 'converted to COG, overviews built, bands kept intact.' }) },
            { kind: 'table' as DataKind, label: t('rail.tableLabel', { defaultValue: 'Tabular' }), desc: t('rail.tableDesc', { defaultValue: 'ingested as a joinable table. Optionally specify geometry columns during import.' }) },
          ]).map(({ kind, label, desc }) => (
            <div key={kind} className="flex gap-2.5 items-start">
              <TypeTag kind={kind} size="sm" />
              <div><span className="font-medium">{label}</span> — {desc}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Tip */}
      <div className="rounded-xl border border-border bg-surface-0 p-4">
        <p className="mb-2 font-mono text-[10.5px] uppercase tracking-widest text-muted-foreground">
          {t('rail.tip', { defaultValue: 'Tip' })}
        </p>
        <p className="text-[12.5px] text-muted-foreground">
          {t('rail.tipText', {
            defaultValue: 'Drop multiple files at once to create a batch. Each file becomes its own dataset — you can review and adjust metadata before committing.',
          })}
        </p>
      </div>
    </aside>
  );
}

function NonUploadRail({ mode }: { mode: 'register' | 'service' }) {
  const { t } = useTranslation('import');
  const isRegister = mode === 'register';

  return (
    <aside className="sticky top-28 flex flex-col gap-4">
      <div className="rounded-xl border border-border bg-card p-4">
        <p className="mb-2 font-mono text-[10.5px] uppercase tracking-widest text-muted-foreground">
          {isRegister
            ? t('rail.registerHint', { defaultValue: 'Registering existing infrastructure' })
            : t('rail.serviceHint', { defaultValue: 'Connecting remote services' })}
        </p>
        <p className="mb-2.5 text-[12.5px] text-muted-foreground leading-relaxed">
          {isRegister
            ? t('rail.registerDesc', { defaultValue: 'Register existing PostGIS tables as datasets — GeoLens tiles them on the fly from your database.' })
            : t('rail.serviceDesc', { defaultValue: 'Connect a remote WFS, ArcGIS FeatureServer, or OGC API Features service. GeoLens imports the layer into the catalog for tiling and querying.' })}
        </p>
        <p className="font-mono text-[11px] text-muted-foreground tracking-wide">
          {isRegister
            ? t('rail.registerNote', { defaultValue: 'No data copied · tiles generated directly from your tables' })
            : t('rail.serviceNote', { defaultValue: 'Service tokens are used during import only and are not persisted' })}
        </p>
      </div>

      <div className="rounded-xl border border-border bg-card p-4">
        <p className="mb-2 font-mono text-[10.5px] uppercase tracking-widest text-muted-foreground">
          {t('rail.comparedToUpload', { defaultValue: 'Compared to Upload' })}
        </p>
        <p className="text-[12.5px] text-muted-foreground leading-relaxed">
          {isRegister
            ? t('rail.compareRegister', { defaultValue: 'Upload ingests from a file. Register points at an existing table — no duplication, but the table must stay in your database.' })
            : t('rail.compareService', { defaultValue: 'Upload ingests from a file. Service URL fetches from a remote API and imports the data into GeoLens for local tiling and querying.' })}
        </p>
      </div>
    </aside>
  );
}
