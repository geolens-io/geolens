import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  Satellite,
  Check,
  ChevronRight,
  ArrowLeft,
  Calendar,
  Layers,
  Image,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { ApiError } from '@/api/client';
import {
  connectStac,
  fetchStacCollections,
  searchStacItems,
  importStacItems,
} from '@/api/stac';
import type {
  StacConnectResponse,
  StacCollectionSummary,
  StacItemSummary,
  StacImportItem,
} from '@/types/api';
import { Button } from '@/components/ui/button';

type Step =
  | 'idle'
  | 'connecting'
  | 'collections'
  | 'loading-items'
  | 'items'
  | 'importing'
  | 'done';

export function StacImportForm() {
  const { t } = useTranslation('import');
  const [step, setStep] = useState<Step>('idle');
  const [url, setUrl] = useState('');
  const [catalogInfo, setCatalogInfo] = useState<StacConnectResponse | null>(null);
  const [collections, setCollections] = useState<StacCollectionSummary[]>([]);
  const [selectedCollection, setSelectedCollection] = useState<StacCollectionSummary | null>(null);
  const [searchResult, setSearchResult] = useState<{ items: StacItemSummary[]; matched: number | null }>({ items: [], matched: null });
  const [selectedItems, setSelectedItems] = useState<Set<string>>(new Set());
  const [importResult, setImportResult] = useState<{ created: number; skipped: number; errors: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const items = searchResult.items;
  const matchedCount = searchResult.matched;
  const selectableItems = useMemo(() => items.filter((i) => i.data_asset_href), [items]);

  const reset = () => {
    setStep('idle');
    setUrl('');
    setCatalogInfo(null);
    setCollections([]);
    setSelectedCollection(null);
    setSearchResult({ items: [], matched: null });
    setSelectedItems(new Set());
    setImportResult(null);
    setError(null);
  };

  // ── Step 1: Connect ──
  const handleConnect = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = url.trim();
    if (!trimmed) return;

    try {
      new URL(trimmed);
    } catch {
      setError('Please enter a valid URL (e.g. https://earth-search.aws.element84.com/v1)');
      return;
    }

    setStep('connecting');
    setError(null);

    try {
      const [info, collectionsResult] = await Promise.all([
        connectStac(trimmed),
        fetchStacCollections(trimmed),
      ]);
      setCatalogInfo(info);
      setCollections(collectionsResult.collections);
      setStep('collections');
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Failed to connect to STAC catalog';
      setError(msg);
      setStep('idle');
      toast.error(msg);
    }
  };

  // ── Step 2: Select collection and search items ──
  const handleCollectionSelect = async (collection: StacCollectionSummary) => {
    setSelectedCollection(collection);
    setStep('loading-items');
    setError(null);

    try {
      const result = await searchStacItems({
        url: catalogInfo!.url,
        collections: [collection.id],
        limit: 50,
      });
      setSearchResult({ items: result.items, matched: result.matched });
      setSelectedItems(new Set());
      setStep('items');
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Failed to search items';
      setError(msg);
      setStep('collections');
      toast.error(msg);
    }
  };

  // ── Step 3: Toggle item selection ──
  const toggleItem = (id: string) => {
    setSelectedItems((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (selectedItems.size === selectableItems.length) {
      setSelectedItems(new Set());
    } else {
      setSelectedItems(new Set(selectableItems.map((i) => i.id)));
    }
  };

  // ── Step 4: Import ──
  const handleImport = async () => {
    if (selectedItems.size === 0) return;

    setStep('importing');
    setError(null);

    const importItems: StacImportItem[] = selectableItems
      .filter((i) => selectedItems.has(i.id))
      .map((i) => ({
        id: i.id,
        collection: i.collection,
        title: i.title,
        data_asset_href: i.data_asset_href!,
        bbox: i.bbox,
        epsg: i.epsg,
        datetime_start: i.datetime_start,
        datetime_end: i.datetime_end,
        keywords: selectedCollection?.keywords ?? [],
      }));

    try {
      const result = await importStacItems(catalogInfo!.url, importItems);
      setImportResult({ created: result.created, skipped: result.skipped, errors: result.errors });
      setStep('done');
      if (result.created > 0) {
        toast.success(`Imported ${result.created} dataset${result.created !== 1 ? 's' : ''}`);
      }
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Import failed';
      setError(msg);
      setStep('items');
      toast.error(msg);
    }
  };

  // ── Loading states ──
  if (step === 'connecting' || step === 'loading-items' || step === 'importing') {
    const label =
      step === 'connecting' ? t('stac.connecting', { defaultValue: 'Connecting to STAC catalog...' })
      : step === 'loading-items' ? t('stac.searching', { defaultValue: 'Searching items...' })
      : `Importing ${selectedItems.size} item${selectedItems.size !== 1 ? 's' : ''}...`;
    return (
      <div className="flex items-center gap-3 rounded-xl border border-border bg-card px-5 py-8 justify-center">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <span className="text-sm text-muted-foreground">{label}</span>
      </div>
    );
  }

  // ── Done ──
  if (step === 'done' && importResult) {
    return (
      <div className="space-y-4">
        <div className="rounded-xl border border-success/30 bg-success/5 p-5">
          <div className="flex items-center gap-2 mb-3">
            <Check className="size-5 text-success" />
            <h3 className="text-[15px] font-medium">Import Complete</h3>
          </div>
          <div className="flex gap-6 text-sm text-muted-foreground">
            {importResult.created > 0 && (
              <span className="text-success">{importResult.created} created</span>
            )}
            {importResult.skipped > 0 && (
              <span>{importResult.skipped} skipped (duplicate)</span>
            )}
            {importResult.errors > 0 && (
              <span className="text-destructive">{importResult.errors} failed</span>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={reset}>
            Import more
          </Button>
          <Button variant="outline" onClick={() => { setStep('items'); setImportResult(null); }}>
            Back to results
          </Button>
        </div>
      </div>
    );
  }

  // ── Collections list ──
  if (step === 'collections' && catalogInfo) {
    return (
      <div className="space-y-5">
        {/* Connected state header */}
        <div className="rounded-xl border border-border bg-card p-5">
          <span className="mb-2.5 block font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            STAC Catalog — connected
          </span>
          <div className="flex items-stretch overflow-hidden rounded-lg border-[1.5px] border-success bg-surface-0">
            <span className="flex items-center gap-1.5 border-r border-border bg-success/10 px-3.5 font-mono text-[11px] font-semibold uppercase tracking-wider text-success">
              <Check className="size-3.5" />
              STAC {catalogInfo.stac_version}
            </span>
            <input
              type="text"
              readOnly
              value={catalogInfo.url}
              className="flex-1 bg-transparent px-3.5 py-2.5 font-mono text-[13.5px] text-foreground outline-none"
            />
            <button
              onClick={reset}
              className="border-l border-border bg-surface-2 px-4 text-[13px] font-medium text-muted-foreground hover:bg-surface-3 hover:text-foreground"
            >
              Clear
            </button>
          </div>
        </div>

        {/* Collection cards */}
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <div className="flex items-center gap-3.5 border-b border-border px-5 py-3.5">
            <span className="rounded-md bg-type-raster-bg px-2.5 py-0.5 font-mono text-[11px] font-semibold uppercase tracking-wider text-type-raster">
              STAC
            </span>
            <div className="flex-1">
              <h3 className="text-[15px] font-medium tracking-tight">{catalogInfo.title}</h3>
              <p className="font-mono text-[11px] text-muted-foreground tracking-wide">
                {collections.length} collection{collections.length !== 1 ? 's' : ''} available
              </p>
            </div>
          </div>

          <div className="grid gap-2 p-2 sm:grid-cols-2">
            {collections.length === 0 && (
              <p className="col-span-2 px-3 py-4 text-center text-sm text-muted-foreground">
                No collections found in this catalog.
              </p>
            )}
            {collections.map((col) => (
              <button
                key={col.id}
                onClick={() => handleCollectionSelect(col)}
                className="flex items-start gap-2.5 rounded-lg border border-border p-3 text-start transition-colors hover:bg-surface-2"
              >
                <Layers className="mt-0.5 size-4 shrink-0 text-type-raster" />
                <div className="flex-1 min-w-0">
                  <p className="truncate text-[12.5px] font-medium tracking-tight">
                    {col.title}
                  </p>
                  {col.description && (
                    <p className="mt-0.5 line-clamp-2 text-[11px] text-muted-foreground">
                      {col.description}
                    </p>
                  )}
                  <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[10px] text-muted-foreground/70">
                    {col.item_count != null && <span>{col.item_count} items</span>}
                    {col.license && <span>{col.license}</span>}
                    {col.temporal_start && (
                      <span className="flex items-center gap-0.5">
                        <Calendar className="size-2.5" />
                        {col.temporal_start.slice(0, 10)}
                        {col.temporal_end ? ` — ${col.temporal_end.slice(0, 10)}` : '+'}
                      </span>
                    )}
                  </div>
                </div>
                <ChevronRight className="mt-0.5 size-4 shrink-0 text-muted-foreground/40 rtl-mirror" />
              </button>
            ))}
          </div>

          {error && (
            <p className="border-t border-border px-5 py-3 text-sm text-destructive">{error}</p>
          )}
        </div>
      </div>
    );
  }

  // ── Items list with selection ──
  if (step === 'items' && selectedCollection && catalogInfo) {
    const allSelected = selectableItems.length > 0 && selectedItems.size === selectableItems.length;

    return (
      <div className="space-y-4">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-sm">
          <button
            onClick={() => { setStep('collections'); setSelectedCollection(null); }}
            className="flex items-center gap-1 text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-3.5 rtl-mirror" />
            Collections
          </button>
          <ChevronRight className="size-3 text-muted-foreground/40 rtl-mirror" />
          <span className="font-medium">{selectedCollection.title}</span>
          {matchedCount != null && (
            <span className="font-mono text-[11px] text-muted-foreground">
              ({matchedCount} total)
            </span>
          )}
        </div>

        {/* Action bar */}
        <div className="flex items-center justify-between rounded-lg border border-border bg-surface-1 px-4 py-2.5">
          <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={toggleAll}
              className="rounded border-border"
            />
            {selectedItems.size > 0
              ? `${selectedItems.size} of ${items.length} selected`
              : `${items.length} items`}
          </label>
          <Button
            size="sm"
            disabled={selectedItems.size === 0}
            onClick={handleImport}
          >
            Import {selectedItems.size > 0 ? selectedItems.size : ''} item{selectedItems.size !== 1 ? 's' : ''}
          </Button>
        </div>

        {/* Item rows */}
        <div className="overflow-hidden rounded-xl border border-border bg-card divide-y divide-border">
          {items.length === 0 && (
            <p className="px-5 py-8 text-center text-sm text-muted-foreground">
              No items found in this collection.
            </p>
          )}
          {items.map((item) => {
            const hasAsset = !!item.data_asset_href;
            const isSelected = selectedItems.has(item.id);

            return (
              <label
                key={item.id}
                className={cn(
                  'flex items-center gap-3 px-4 py-3 transition-colors',
                  hasAsset ? 'cursor-pointer hover:bg-surface-2' : 'opacity-50 cursor-not-allowed',
                  isSelected && 'bg-primary/5',
                )}
              >
                <input
                  type="checkbox"
                  checked={isSelected}
                  disabled={!hasAsset}
                  onChange={() => toggleItem(item.id)}
                  className="rounded border-border shrink-0"
                />

                {/* Thumbnail */}
                {item.thumbnail_href ? (
                  <img
                    src={item.thumbnail_href}
                    alt=""
                    className="size-10 shrink-0 rounded border border-border object-cover"
                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                  />
                ) : (
                  <div className="flex size-10 shrink-0 items-center justify-center rounded border border-border bg-surface-2">
                    <Image className="size-4 text-muted-foreground/40" />
                  </div>
                )}

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <p className="truncate text-[13px] font-medium">{item.title}</p>
                  <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0 font-mono text-[10.5px] text-muted-foreground">
                    {item.datetime_start && (
                      <span className="flex items-center gap-0.5">
                        <Calendar className="size-2.5" />
                        {item.datetime_start.slice(0, 10)}
                      </span>
                    )}
                    {item.epsg && <span>EPSG:{item.epsg}</span>}
                    {item.gsd != null && <span>{item.gsd}m GSD</span>}
                    {item.cloud_cover != null && <span>{item.cloud_cover.toFixed(0)}% cloud</span>}
                    <span>{item.asset_count} asset{item.asset_count !== 1 ? 's' : ''}</span>
                  </div>
                </div>

                {!hasAsset && (
                  <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                    No COG asset
                  </span>
                )}
              </label>
            );
          })}
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}
      </div>
    );
  }

  // ── Idle — URL input form ──
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <form onSubmit={handleConnect} className="space-y-5">
        <div>
          <label className="mb-2.5 block font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            {t('stac.label', { defaultValue: "STAC API URL — paste the catalog root endpoint" })}
          </label>
          <div className="flex items-stretch overflow-hidden rounded-lg border-[1.5px] border-border bg-surface-0 transition-colors focus-within:border-primary">
            <span className="flex items-center gap-1.5 border-r border-border bg-surface-2 px-3.5 font-mono text-[11px] uppercase tracking-wider text-muted-foreground font-medium">
              <Satellite className="size-3.5" />
              STAC
            </span>
            <input
              type="url"
              placeholder="https://earth-search.aws.element84.com/v1"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="flex-1 bg-transparent px-3.5 py-2.5 font-mono text-[13.5px] text-foreground outline-none placeholder:text-muted-foreground/50"
            />
            <button
              type="submit"
              disabled={!url.trim()}
              className="bg-primary px-4 text-[13px] font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
            >
              {t('stac.connect', { defaultValue: 'Connect' })}
            </button>
          </div>
          <div className="mt-2.5 flex flex-wrap gap-4 text-xs text-muted-foreground">
            <span>
              Browse and import raster datasets from public STAC catalogs like{' '}
              <code className="rounded bg-surface-2 px-1.5 py-px font-mono text-[11px]">
                Earth Search
              </code>{' '}
              <code className="rounded bg-surface-2 px-1.5 py-px font-mono text-[11px]">
                Planetary Computer
              </code>
            </span>
          </div>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}
      </form>
    </div>
  );
}
