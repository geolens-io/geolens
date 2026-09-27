import { useTranslation } from 'react-i18next';
import { AlertCircle, Check } from 'lucide-react';
import { cn } from '@/lib/utils';
import { TypeTag } from './TypeTag';
import type { BatchPhase, DataKind } from '@/types/api';

type Mode = 'upload' | 'url' | 'register' | 'service' | 'stac';

interface WorkflowRailProps {
  mode: Mode;
  phase: BatchPhase;
  outcome?: 'complete' | 'partial' | null;
  completedKinds?: DataKind[];
}

const PHASE_TO_STEP: Record<BatchPhase, number> = {
  idle: 0,
  uploading: 0,
  reviewing: 1,
  tracking: 2,
};

export function WorkflowRail({ mode, phase, outcome = null, completedKinds = [] }: WorkflowRailProps) {
  const { t } = useTranslation('import');
  const allKinds = (kind: DataKind) => completedKinds.length > 0 && completedKinds.every((entry) => entry === kind);
  let importDesc = t('rail.importDesc');
  if (outcome === 'partial') importDesc = t('rail.partialDesc');
  if (outcome === 'complete') {
    if (allKinds('table')) importDesc = t('rail.completeTableDesc');
    else if (allKinds('tiles3d')) importDesc = t('rail.completeTilesetDesc');
    else if (allKinds('pointcloud')) importDesc = t('rail.completePointCloudDesc');
    else importDesc = t('rail.completeDesc');
  }

  const steps = [
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
      desc: importDesc,
    },
  ];

  if (mode === 'url' || mode === 'register' || mode === 'service' || mode === 'stac') {
    return <NonUploadRail mode={mode} />;
  }

  const activeStep = PHASE_TO_STEP[phase];

  return (
    <aside
      aria-label={t('rail.asideLabel', { defaultValue: 'Import workflow' })}
      className="sticky top-28 flex flex-col gap-4"
    >
      {/* Workflow steps */}
      <div className="rounded-lg border border-border bg-card p-4">
        <p className="eyebrow mb-3">
          {t('rail.workflow', { defaultValue: 'Workflow' })}
        </p>
        <div className="flex flex-col gap-3.5">
          {steps.map((step, i) => {
            const isDone = i < activeStep || (i === activeStep && outcome === 'complete');
            const isPartial = i === activeStep && outcome === 'partial';
            const isActive = i === activeStep && outcome === null;
            return (
              <div key={i} className="relative grid grid-cols-[22px_1fr] gap-3">
                {i < steps.length - 1 && (
                  <span className="absolute left-[10px] top-6 bottom-[-14px] w-px bg-border" />
                )}
                <span
                  className={cn(
                    'flex h-[22px] w-[22px] items-center justify-center rounded-full font-mono text-2xs font-semibold border',
                    isDone && 'bg-success text-success-foreground border-success',
                    isActive && 'bg-primary text-primary-foreground border-primary ring-2 ring-primary/20',
                    isPartial && 'bg-warning/15 text-warning border-warning',
                    !isDone && !isActive && !isPartial && 'bg-surface-2 text-muted-foreground border-border',
                  )}
                >
                  {isDone ? <Check className="size-3" /> : isPartial ? <AlertCircle className="size-3" /> : i + 1}
                </span>
                <div>
                  <h5 className="text-xs font-semibold leading-snug">
                    {step.title}
                    {isDone && <span className="ms-1 text-success">&#10003;</span>}
                    {isPartial && <span className="ms-1 text-warning">{t('rail.partialStatus')}</span>}
                  </h5>
                  <p className="text-xs leading-relaxed text-muted-foreground">{step.desc}</p>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* What gets imported */}
      <div className="rounded-lg border border-border bg-card p-4">
        <p className="eyebrow mb-3">
          {t('rail.whatImported', { defaultValue: 'What gets imported' })}
        </p>
        <div className="flex flex-col gap-2 text-xs">
          {([
            { kind: 'vector' as DataKind, label: t('rail.vectorLabel', { defaultValue: 'Vector' }), desc: t('rail.vectorDesc', { defaultValue: 'tiled to MVT, spatial index, reprojected to 3857 on read.' }) },
            { kind: 'raster' as DataKind, label: t('rail.rasterLabel', { defaultValue: 'Raster' }), desc: t('rail.rasterDesc', { defaultValue: 'converted to COG, overviews built, bands kept intact.' }) },
            { kind: 'table' as DataKind, label: t('rail.tableLabel', { defaultValue: 'Tabular' }), desc: t('rail.tableDesc', { defaultValue: 'ingested as a joinable table. Optionally specify geometry columns during import.' }) },
            { kind: 'tiles3d' as DataKind, label: t('rail.tiles3dLabel'), desc: t('rail.tiles3dDesc') },
            { kind: 'pointcloud' as DataKind, label: t('rail.pointcloudLabel'), desc: t('rail.pointcloudDesc') },
          ]).map(({ kind, label, desc }) => (
            <div key={kind} className="flex gap-2.5 items-start">
              <TypeTag kind={kind} size="sm" />
              <div><span className="font-medium">{label}</span> — {desc}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Tip */}
      <div className="rounded-lg border border-border bg-surface-0 p-4">
        <p className="eyebrow mb-2">
          {t('rail.tip', { defaultValue: 'Tip' })}
        </p>
        <p className="text-xs text-muted-foreground">
          {t('rail.tipText', {
            defaultValue: 'Drop multiple files at once to create a batch. Each file becomes its own dataset — you can review and adjust metadata before committing.',
          })}
        </p>
      </div>
    </aside>
  );
}

function NonUploadRail({ mode }: { mode: 'url' | 'register' | 'service' | 'stac' }) {
  const { t } = useTranslation('import');
  const isRegister = mode === 'register';
  const isStac = mode === 'stac';
  const isUrl = mode === 'url';

  // feat(#1705): URL import gets its own rail copy — it copies data in like
  // Upload (unlike Register/Service, which point at live sources).
  if (isUrl) {
    return (
      <aside
        aria-label={t('rail.asideLabel', { defaultValue: 'Import workflow' })}
        className="sticky top-28 flex flex-col gap-4"
      >
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="eyebrow mb-2">{t('rail.urlHint')}</p>
          <p className="mb-2.5 text-xs text-muted-foreground leading-relaxed">
            {t('rail.urlDesc')}
          </p>
          <p className="font-mono text-mini text-muted-foreground tracking-wide">
            {t('rail.urlNote')}
          </p>
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <p className="eyebrow mb-2">
            {t('rail.comparedToUpload', { defaultValue: 'Compared to Upload' })}
          </p>
          <p className="text-xs text-muted-foreground leading-relaxed">
            {t('rail.compareUrl')}
          </p>
        </div>
      </aside>
    );
  }

  return (
    // Same label as the upload-mode aside above — they are alternative
    // branches of the one import-workflow sidebar landmark.
    <aside
      aria-label={t('rail.asideLabel', { defaultValue: 'Import workflow' })}
      className="sticky top-28 flex flex-col gap-4"
    >
      <div className="rounded-lg border border-border bg-card p-4">
        <p className="eyebrow mb-2">
          {isRegister
            ? t('rail.registerHint', { defaultValue: 'Registering existing infrastructure' })
            : isStac
              ? t('rail.stacHint', { defaultValue: 'Importing from STAC' })
              : t('rail.serviceHint', { defaultValue: 'Connecting remote services' })}
        </p>
        <p className="mb-2.5 text-xs text-muted-foreground leading-relaxed">
          {isRegister
            ? t('rail.registerDesc', { defaultValue: 'Register existing PostGIS tables as datasets — GeoLens tiles them on the fly from your database.' })
            : isStac
              ? t('rail.stacDesc', { defaultValue: 'Connect a STAC catalog or collection and import selected assets into GeoLens.' })
              : t('rail.serviceDesc', { defaultValue: 'Connect a remote WFS, ArcGIS FeatureServer, or OGC API Features service. GeoLens imports the layer into the catalog for tiling and querying.' })}
        </p>
        <p className="font-mono text-mini text-muted-foreground tracking-wide">
          {isRegister
            ? t('rail.registerNote', { defaultValue: 'No data copied · tiles generated directly from your tables' })
            : isStac
              ? t('rail.stacNote', { defaultValue: 'STAC metadata is discovered first, then selected assets are imported' })
              : t('rail.serviceNote', { defaultValue: 'Service tokens are used for this import and are never stored with the dataset' })}
        </p>
      </div>

      <div className="rounded-lg border border-border bg-card p-4">
        <p className="eyebrow mb-2">
          {t('rail.comparedToUpload', { defaultValue: 'Compared to Upload' })}
        </p>
        <p className="text-xs text-muted-foreground leading-relaxed">
          {isRegister
            ? t('rail.compareRegister', { defaultValue: 'Upload ingests from a file. Register points at an existing table — no duplication, but the table must stay in your database.' })
            : isStac
              ? t('rail.compareStac', { defaultValue: 'Upload ingests local files. STAC imports discover remote assets first, then stages selected items for catalog use.' })
              : t('rail.compareService', { defaultValue: 'Upload ingests from a file. Service URL fetches from a remote API and imports the data into GeoLens for local tiling and querying.' })}
        </p>
      </div>
    </aside>
  );
}
