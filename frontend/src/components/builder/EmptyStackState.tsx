import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Check, Loader2, MapPin, Plus, Search } from 'lucide-react';
import { getDataset } from '@/api/datasets';
import { queryKeys } from '@/lib/query-keys';
import { cn } from '@/lib/utils';
import { SUGGESTED_DATASETS, type SuggestedDataset } from './suggested-datasets';

export interface EmptyStackStateProps {
  onOpenAddData: (initialQuery?: string) => void;
  onAddDataset: (datasetId: string) => void;
}

// AUD-02: shared eyebrow class string — single source of truth for 10px uppercase label
// imported by UnifiedStackPanel for the basemap-dock BASEMAP eyebrow label
export const eyebrowClassName = 'block text-[10px] font-semibold tracking-wide text-muted-foreground uppercase px-1';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

function recordTypeLabel(recordType: SuggestedDataset['record_type']): string {
  if (recordType === 'raster_dataset' || recordType === 'vrt_dataset') return 'Raster';
  return 'Vector';
}

function isRasterType(recordType: SuggestedDataset['record_type']): boolean {
  return recordType === 'raster_dataset' || recordType === 'vrt_dataset';
}

// ---------------------------------------------------------------------------
// SuggestCard — inner component for a single hand-curated suggestion
// ---------------------------------------------------------------------------

interface SuggestCardProps {
  suggestion: SuggestedDataset;
  onOpenAddData: (initialQuery?: string) => void;
  addingId: string | null;
  addedIds: Set<string>;
  onDirectAdd: (id: string) => void;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function SuggestCard({ suggestion, onOpenAddData, addingId, addedIds, onDirectAdd }: SuggestCardProps) {
  const idIsRealUuid = UUID_RE.test(suggestion.id);
  const { isError } = useQuery({
    queryKey: queryKeys.datasets.detail(suggestion.id),
    queryFn: () => getDataset(suggestion.id),
    staleTime: 60_000,
    retry: false,
    enabled: idIsRealUuid,
  });

  // Hide cards whose ID is a placeholder or whose fetch errored
  if (!idIsRealUuid) return null;
  if (isError) return null;
  // While loading the first time (no data yet) we only hide if explicitly errored.
  // If data is undefined but not errored, show optimistically (availability not yet confirmed).
  // Cards that actually 404 set isError=true, so this is the correct guard.

  const isAdding = addingId === suggestion.id;
  const isAdded = addedIds.has(suggestion.id);

  const metaParts = [
    recordTypeLabel(suggestion.record_type),
    suggestion.feature_count != null ? formatNumber(suggestion.feature_count) : null,
    suggestion.crs,
  ].filter(Boolean);
  const metaString = metaParts.join(' · ');

  const isRaster = isRasterType(suggestion.record_type);

  return (
    <li role="listitem">
      <div
        className={cn(
          'grid gap-2 items-center p-2 px-3 rounded-md border',
          'bg-[var(--surface-0)] hover:bg-[var(--surface-2)] hover:border-primary/30 hover:shadow-sm',
          'transition-colors',
          isAdding && 'pointer-events-none opacity-70',
        )}
        style={{ gridTemplateColumns: '32px 1fr 22px' }}
      >
        {/* Type icon */}
        <button
          type="button"
          role="button"
          aria-label={`Open ${suggestion.name} in Add Data modal`}
          onClick={() => onOpenAddData(suggestion.name)}
          className="flex items-center justify-center h-[32px] w-[32px] rounded-sm text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          style={{
            backgroundColor: isRaster ? 'var(--type-raster-bg)' : 'var(--type-vector-bg)',
            color: isRaster ? 'var(--type-raster)' : 'var(--type-vector)',
          }}
          tabIndex={-1}
          aria-hidden="true"
        >
          <span className="text-[10px] font-medium select-none">
            {isRaster ? '▦' : '⬡'}
          </span>
        </button>

        {/* Name + meta — card body click area */}
        <button
          type="button"
          role="button"
          aria-label={`Open ${suggestion.name} in Add Data modal`}
          onClick={() => onOpenAddData(suggestion.name)}
          className="min-w-0 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
        >
          <span className="block text-sm truncate">{suggestion.name}</span>
          {metaString && (
            <span className="block text-[10px] text-muted-foreground truncate">{metaString}</span>
          )}
        </button>

        {/* Add button */}
        <button
          type="button"
          aria-label={`Add ${suggestion.name} to map`}
          aria-busy={isAdding}
          onClick={(e) => {
            e.stopPropagation();
            onDirectAdd(suggestion.id);
          }}
          className="h-[22px] w-[22px] flex items-center justify-center rounded text-primary hover:bg-[var(--primary-50,oklch(0.97_0.02_250))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {isAdding ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          ) : isAdded ? (
            <Check className="h-3.5 w-3.5" aria-hidden="true" />
          ) : (
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          )}
        </button>
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------
// EmptyStackState — main export
// ---------------------------------------------------------------------------

export function EmptyStackState({ onOpenAddData, onAddDataset }: EmptyStackStateProps) {
  const { t } = useTranslation('builder');
  const [inlineQuery, setInlineQuery] = useState('');
  const [addingId, setAddingId] = useState<string | null>(null);
  const [addedIds, setAddedIds] = useState<Set<string>>(() => new Set());

  function handleSearchKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' && inlineQuery.trim()) {
      onOpenAddData(inlineQuery.trim());
    }
    if (e.key === 'Escape') {
      setInlineQuery('');
    }
  }

  async function handleDirectAdd(datasetId: string) {
    setAddingId(datasetId);
    try {
      await Promise.resolve(onAddDataset(datasetId));
      setAddedIds((prev) => new Set(prev).add(datasetId));
    } finally {
      setAddingId(null);
    }
  }

  return (
    <div
      role="region"
      aria-label="No layers — get started"
      className="flex flex-col gap-4 p-4 pb-2"
    >
      {/* Prompt */}
      <div className="text-center">
        <h4 className="text-sm font-semibold">
          {t('unifiedStack.emptyHeading', { defaultValue: 'Add your first layer' })}
        </h4>
        <p className="text-xs text-muted-foreground mt-1">
          {t('unifiedStack.emptyBody', { defaultValue: 'Search the catalog or pick a starter dataset below.' })}
        </p>
      </div>

      {/* Inline search */}
      <div
        className={cn(
          'flex items-center gap-2 rounded-md border',
          'bg-[var(--surface-2)] px-3',
          'focus-within:border-primary',
          'transition-colors duration-[--motion-fast]',
        )}
        style={{ height: '36px' }}
      >
        <button
          type="button"
          aria-label="Search and open Add Data modal"
          onClick={() => {
            if (inlineQuery.trim()) {
              onOpenAddData(inlineQuery.trim());
            }
          }}
          className="flex items-center justify-center text-muted-foreground hover:text-foreground focus-visible:outline-none transition-colors duration-[--motion-fast]"
        >
          <Search className="h-4 w-4" aria-hidden="true" />
        </button>
        <input
          role="searchbox"
          aria-label="Search datasets to add"
          placeholder={t('unifiedStack.emptySearchPlaceholder', { defaultValue: 'Search datasets, URLs, or files…' })}
          value={inlineQuery}
          onChange={(e) => setInlineQuery(e.target.value)}
          onKeyDown={handleSearchKeyDown}
          className="flex-1 bg-transparent border-0 outline-none text-sm"
        />
      </div>

      {/* Suggested section — or starter-help fallback when SUGGESTED_DATASETS is empty */}
      {SUGGESTED_DATASETS.length > 0 ? (
        <div className="flex flex-col gap-2">
          <span
            aria-hidden="true"
            className={eyebrowClassName}
          >
            {t('unifiedStack.suggestedLabel', { defaultValue: 'SUGGESTED' })}
          </span>
          <ul role="list" aria-label="Suggested datasets" className="flex flex-col gap-2">
            {SUGGESTED_DATASETS.map((suggestion) => (
              <SuggestCard
                key={suggestion.id}
                suggestion={suggestion}
                onOpenAddData={onOpenAddData}
                addingId={addingId}
                addedIds={addedIds}
                onDirectAdd={handleDirectAdd}
              />
            ))}
          </ul>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-3 px-4 py-4 text-center">
          <MapPin className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
          <p className="text-sm text-muted-foreground">
            {t('unifiedStack.emptyHelpBody', { defaultValue: 'Search the catalog to find datasets, or use the Upload button to add your own.' })}
          </p>
          <button
            type="button"
            aria-label="Browse catalog"
            onClick={() => onOpenAddData()}
            className="text-xs text-primary self-center hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
          >
            {t('unifiedStack.browseAllShort', { defaultValue: 'Browse catalog →' })}
          </button>
        </div>
      )}

      {/* Browse all */}
      <button
        type="button"
        aria-label="Browse all datasets in the Add Data modal"
        onClick={() => onOpenAddData()}
        className="text-xs text-primary self-start hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
      >
        {t('unifiedStack.browseAll', { defaultValue: 'Browse all datasets →' })}
      </button>
    </div>
  );
}
