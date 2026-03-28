import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Loader2 } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { searchDatasets } from '@/api/search';
import { queryKeys } from '@/lib/query-keys';
import { useDebouncedValue } from '@/hooks/use-debounce';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { getGeometryTypeLabel } from '@/i18n/labels';

interface DatasetSearchPanelProps {
  onAddDataset: (datasetId: string) => void;
  existingDatasetIds: string[];
  isAdding: boolean;
}

export function DatasetSearchPanel({
  onAddDataset,
  existingDatasetIds,
  isAdding,
}: DatasetSearchPanelProps) {
  const { t } = useTranslation('builder');
  const [query, setQuery] = useState('');
  const [recordType, setRecordType] = useState('');
  const debouncedQuery = useDebouncedValue(query, 300);

  const searchParams: Record<string, string> = { limit: '10' };
  if (debouncedQuery.trim()) searchParams.q = debouncedQuery;
  if (recordType) searchParams.record_type = recordType;

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.datasetSearch.results(debouncedQuery, recordType),
    queryFn: () => searchDatasets(searchParams),
    enabled: debouncedQuery.trim().length > 0 || recordType !== '',
  });

  const results = data?.features ?? [];

  return (
    <div>
      <h3 className="text-sm font-medium px-2 mb-2">{t('search.title')}</h3>
      <div className="px-2 mb-2">
        <Input
          placeholder={t('search.placeholder')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="h-8 text-sm"
        />
      </div>
      <div className="px-2 mb-2">
        <ToggleGroup
          type="single"
          value={recordType || 'all'}
          onValueChange={(val) => setRecordType(val === 'all' ? '' : val)}
          className="w-full"
        >
          <ToggleGroupItem value="all" className="flex-1 text-xs h-7">
            {t('search.allTypes', { defaultValue: 'All' })}
          </ToggleGroupItem>
          <ToggleGroupItem value="vector_dataset" className="flex-1 text-xs h-7">
            {t('search.vector', { defaultValue: 'Vector' })}
          </ToggleGroupItem>
          <ToggleGroupItem value="raster_dataset" className="flex-1 text-xs h-7">
            {t('search.raster', { defaultValue: 'Raster' })}
          </ToggleGroupItem>
        </ToggleGroup>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-3">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        </div>
      )}

      {debouncedQuery.trim().length > 0 && !isLoading && results.length === 0 && (
        <p className="text-xs text-muted-foreground px-2 py-2">{t('search.noResults')}</p>
      )}

      {results.length > 0 && (
        <div className="space-y-0.5 max-h-48 overflow-y-auto px-1">
          {results.map((record) => {
            const isAdded = existingDatasetIds.includes(record.id);
            return (
              <div
                key={record.id}
                className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-accent/50"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm truncate">{record.properties.title}</p>
                  {record.properties.record_type === 'raster_dataset' ? (
                    <Badge variant="outline" className="text-[10px] mt-0.5 text-emerald-600 border-emerald-400 dark:text-emerald-400">
                      {t('search.raster', { defaultValue: 'Raster' })}
                    </Badge>
                  ) : record.properties.geometry_type ? (
                    <Badge variant="outline" className="text-[10px] mt-0.5">
                      {getGeometryTypeLabel(t, record.properties.geometry_type)}
                    </Badge>
                  ) : null}
                </div>
                {isAdded ? (
                  <span className="text-xs text-muted-foreground shrink-0">{t('search.added')}</span>
                ) : (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 shrink-0"
                    onClick={() => onAddDataset(record.id)}
                    disabled={isAdding}
                    title={t('search.addToMap')}
                    aria-label={t('search.addToMap')}
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </Button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
