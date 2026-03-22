import { useTranslation } from 'react-i18next';
import type { DiscoveredTable } from '@/types/api';
import { Checkbox } from '@/components/ui/checkbox';
import { Badge } from '@/components/ui/badge';
import { getGeometryTypeLabel } from '@/i18n/labels';

interface TablePickerProps {
  tables: DiscoveredTable[];
  selected: Set<string>;
  onToggle: (tableName: string) => void;
  onToggleAll: () => void;
}

export function TablePicker({
  tables,
  selected,
  onToggle,
  onToggleAll,
}: TablePickerProps) {
  const { t } = useTranslation('import');
  const allSelected = tables.length > 0 && selected.size === tables.length;
  const someSelected = selected.size > 0 && selected.size < tables.length;

  return (
    <div className="space-y-2">
      <label className="flex items-center gap-2 px-2 py-1.5 cursor-pointer">
        <Checkbox
          checked={allSelected ? true : someSelected ? 'indeterminate' : false}
          onCheckedChange={onToggleAll}
        />
        <span className="text-sm font-medium">
          {t('tablePicker.selectAll', { count: tables.length })}
        </span>
      </label>

      <div className="max-h-80 overflow-y-auto border rounded-md divide-y">
        {tables.map((table) => (
          <label
            key={table.table_name}
            className="flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-muted/50"
          >
            <Checkbox
              checked={selected.has(table.table_name)}
              onCheckedChange={() => onToggle(table.table_name)}
            />
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <span className="text-sm font-medium font-mono truncate">
                {table.table_name}
              </span>
              <Badge variant="outline">
                {table.geometry_type ? getGeometryTypeLabel(t, table.geometry_type) : t('tablePicker.nonSpatial')}
              </Badge>
            </div>
            <div className="flex items-center gap-3 shrink-0 text-xs text-muted-foreground">
              {table.estimated_rows != null && (
                <span>{t('tablePicker.estimatedRows', { count: table.estimated_rows })}</span>
              )}
              {table.srid != null && <span>EPSG:{table.srid}</span>}
            </div>
          </label>
        ))}
      </div>
    </div>
  );
}
