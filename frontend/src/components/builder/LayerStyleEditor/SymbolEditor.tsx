import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { SliderRow } from '../HeatmapStyleControls';
import { IconPicker } from '../IconPicker';
import type { BaseStyleEditorProps } from './types';
import type { SymbolStyleConfig } from '@/types/api';

export function SymbolEditor({
  layer,
  symbolConfig,
  onSymbolConfigChange,
  t,
}: BaseStyleEditorProps) {
  const sampleColumns = layer.dataset_column_info ?? [];
  const categoryColumn = symbolConfig.categoryColumn ?? '';
  const sampleValues = categoryColumn
    ? (layer.dataset_sample_values?.[categoryColumn] ?? []).slice(0, 6)
    : [];
  const currentCategories = symbolConfig.categories ?? [];

  function updateCategory(value: string | number | null, icon: string) {
    const existing = currentCategories.filter((entry) => entry.value !== value);
    onSymbolConfigChange({ categories: [...existing, { value, icon }], categoryColumn });
  }

  return (
    <div className="space-y-3">
      <div className="text-xs font-medium">{t('style.symbol.title')}</div>
      <IconPicker
        label={t('style.symbol.iconImage')}
        uploadAriaLabel={t('style.symbol.uploadIcon')}
        value={symbolConfig.iconImage ?? 'marker'}
        onChange={(iconImage) => onSymbolConfigChange({ iconImage })}
      />
      <SliderRow
        label={t('style.symbol.size')}
        value={symbolConfig.iconSize ?? 1}
        min={0.25}
        max={3}
        step={0.05}
        display={String(symbolConfig.iconSize ?? 1)}
        onChange={(val) => onSymbolConfigChange({ iconSize: val })}
      />
      <SliderRow
        label={t('style.symbol.rotation')}
        value={symbolConfig.iconRotation ?? 0}
        min={0}
        max={360}
        step={1}
        display={`${symbolConfig.iconRotation ?? 0}°`}
        onChange={(val) => onSymbolConfigChange({ iconRotation: val })}
      />
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">{t('style.symbol.anchor')}</span>
        <Select
          value={symbolConfig.iconAnchor ?? 'center'}
          onValueChange={(value) => onSymbolConfigChange({ iconAnchor: value as SymbolStyleConfig['iconAnchor'] })}
        >
          <SelectTrigger className="h-8 text-xs w-36">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {['center', 'top', 'bottom', 'left', 'right', 'top-left', 'top-right', 'bottom-left', 'bottom-right'].map((anchor) => (
              <SelectItem key={anchor} value={anchor}>{anchor}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <SliderRow
          label={t('style.symbol.offsetX')}
          value={symbolConfig.iconOffset?.[0] ?? 0}
          min={-4}
          max={4}
          step={0.25}
          display={String(symbolConfig.iconOffset?.[0] ?? 0)}
          onChange={(val) => onSymbolConfigChange({ iconOffset: [val, symbolConfig.iconOffset?.[1] ?? 0] })}
        />
        <SliderRow
          label={t('style.symbol.offsetY')}
          value={symbolConfig.iconOffset?.[1] ?? 0}
          min={-4}
          max={4}
          step={0.25}
          display={String(symbolConfig.iconOffset?.[1] ?? 0)}
          onChange={(val) => onSymbolConfigChange({ iconOffset: [symbolConfig.iconOffset?.[0] ?? 0, val] })}
        />
      </div>
      {sampleColumns.length > 0 && (
        <div className="space-y-2 border-t pt-2">
          <div className="text-xs font-medium">{t('style.symbol.categoryMapping')}</div>
          <Select
            value={categoryColumn || '__none__'}
            onValueChange={(value) => onSymbolConfigChange({
              categoryColumn: value === '__none__' ? undefined : value,
              categories: value === '__none__' ? undefined : currentCategories,
            })}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">{t('style.none', { defaultValue: 'None' })}</SelectItem>
              {sampleColumns.map((column) => (
                <SelectItem key={column.name} value={column.name}>{column.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {sampleValues.map((value) => {
            const mapped = currentCategories.find((entry) => entry.value === value)?.icon ?? symbolConfig.iconImage ?? 'marker';
            return (
              <div key={String(value)} className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{String(value)}</span>
                <Input
                  className="h-7 text-xs"
                  value={mapped}
                  aria-label={t('style.symbol.categoryIcon', { value: String(value) })}
                  onChange={(event) => updateCategory(value as string | number | null, event.target.value)}
                />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default SymbolEditor;
