import { cn } from '@/lib/utils';
import type { DataKind } from '@/types/api';

const KIND_CONFIG: Record<DataKind, { label: string; fg: string; bg: string; border: string }> = {
  vector: {
    label: 'VEC',
    fg: 'text-type-vector',
    bg: 'bg-type-vector-bg',
    border: 'border-type-vector/20',
  },
  raster: {
    label: 'RAS',
    fg: 'text-type-raster',
    bg: 'bg-type-raster-bg',
    border: 'border-type-raster/20',
  },
  table: {
    label: 'TAB',
    fg: 'text-type-table',
    bg: 'bg-type-table-bg',
    border: 'border-type-table/20',
  },
  vrt: {
    label: 'VRT',
    fg: 'text-type-vrt',
    bg: 'bg-type-vrt-bg',
    border: 'border-type-vrt/20',
  },
};

interface TypeTagProps {
  kind: DataKind;
  size?: 'sm' | 'md';
  className?: string;
}

export function TypeTag({ kind, size = 'md', className }: TypeTagProps) {
  const cfg = KIND_CONFIG[kind];
  return (
    <span
      className={cn(
        'inline-flex items-center justify-center rounded-lg border font-mono font-bold uppercase tracking-wider',
        cfg.fg,
        cfg.bg,
        cfg.border,
        size === 'sm' ? 'h-6 w-6 text-[8px]' : 'h-8 w-8 text-[8.5px]',
        className,
      )}
    >
      {cfg.label}
    </span>
  );
}

/** Inline pill variant for format badges (e.g., ".gpkg" with VEC prefix) */
export function FormatPill({ kind, ext }: { kind: DataKind; ext: string }) {
  const cfg = KIND_CONFIG[kind];
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-0 px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
      <span
        className={cn(
          'rounded px-1 py-px text-[9px] font-bold uppercase tracking-wider',
          cfg.fg,
          cfg.bg,
        )}
      >
        {cfg.label}
      </span>
      {ext}
    </span>
  );
}

/** Infer DataKind from file extension */
export function kindFromExtension(ext: string): DataKind {
  const e = ext.toLowerCase();
  if (['.tif', '.tiff', '.cog', '.nc', '.vrt'].includes(e)) return 'raster';
  if (['.csv', '.xlsx', '.xls', '.parquet'].includes(e)) return 'table';
  return 'vector';
}

export type { DataKind } from '@/types/api';
