import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, Search } from 'lucide-react';

interface ColumnsReferenceProps {
  columns: { name: string; type: string }[];
  defaultOpen?: boolean;
}

export function ColumnsReference({ columns, defaultOpen = false }: ColumnsReferenceProps) {
  const { t } = useTranslation('builder');
  const [open, setOpen] = useState(defaultOpen);
  const [search, setSearch] = useState('');

  const filtered = useMemo(() => {
    if (!search) return columns;
    const q = search.toLowerCase();
    return columns.filter((c) => c.name.toLowerCase().includes(q));
  }, [columns, search]);

  const showSearch = columns.length > 8;

  return (
    <div className="mt-2 pt-2 border-t">
      <button
        className="flex cursor-pointer items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground w-full"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3 rtl-mirror" />}
        {t('layerItem.columns')}
        <span className="text-muted-foreground/60 ms-auto">{columns.length}</span>
      </button>
      {open && (
        <div className="mt-1">
          {showSearch && (
            <div className="relative mb-1">
              <Search className="absolute start-1.5 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
              <input
                className="w-full text-xs bg-muted/50 border rounded ps-6 pe-2 py-1 outline-none focus:ring-1 focus:ring-ring"
                placeholder={t('layerItem.searchColumns', { defaultValue: 'Search columns...' })}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          )}
          <div className="space-y-0.5 max-h-32 overflow-y-auto">
            {filtered.map((col) => (
              <div key={col.name} className="text-xs text-muted-foreground">
                {col.name}{' '}
                <span className="text-muted-foreground/60">({col.type})</span>
              </div>
            ))}
            {filtered.length === 0 && (
              <div className="text-xs text-muted-foreground/60 italic">
                {t('layerItem.noColumnsMatch', { defaultValue: 'No columns match' })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
