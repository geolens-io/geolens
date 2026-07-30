import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { SliderRow } from '../HeatmapStyleControls';
import { IconPicker } from '../IconPicker';
import type { BaseStyleEditorProps } from './types';
import { useMapIcons } from '@/hooks/use-maps';
import type { SymbolStyleConfig } from '@/types/api';

// fix(#920): the anchor dropdown rendered these raw tokens in every locale.
const ICON_ANCHORS = [
  'center', 'top', 'bottom', 'left', 'right',
  'top-left', 'top-right', 'bottom-left', 'bottom-right',
] as const;

export function SymbolEditor({
  layer,
  symbolConfig,
  onSymbolConfigChange,
  t,
}: BaseStyleEditorProps) {
  const sampleColumns = layer.dataset_column_info ?? [];
  const categoryColumn = symbolConfig.categoryColumn ?? '';
  // fix(#920): show every value the backend returned instead of an arbitrary 6.
  // dataset_sample_values is a SAMPLE, not the column's distinct values — the
  // backend caps it at 10 per column, drawn from the first 10k rows — so the
  // section is labelled as a sample rather than claiming "6 of N".
  const sampleValues = categoryColumn
    ? (layer.dataset_sample_values?.[categoryColumn] ?? [])
    : [];
  const currentCategories = symbolConfig.categories ?? [];

  const iconsQuery = useMapIcons();
  const knownIcons = iconsQuery.data?.icons;
  function iconResolves(icon: string): boolean {
    // Only judge once the list has loaded — an in-flight query must not flag
    // every row as broken.
    if (!knownIcons?.length) return true;
    // The renderer accepts a fully qualified id (spriteIconId in symbol-adapter
    // keeps anything containing ':'), while /maps/icons returns the bare slug —
    // compare on the slug so `geolens:marker` is not reported as missing.
    const slug = icon.includes(':') ? icon.slice(icon.indexOf(':') + 1) : icon;
    return knownIcons.some((entry) => entry.sprite_id === slug);
  }

  function updateCategory(value: string | number | null, icon: string) {
    const existing = currentCategories.filter((entry) => entry.value !== value);
    // fix(#920): an empty icon is not a mapping. The adapter already skips it,
    // but storing {value, icon: ''} left junk in saved style_config and made the
    // row render blank instead of the fallback icon it actually draws.
    const next = icon ? [...existing, { value, icon }] : existing;
    onSymbolConfigChange({ categories: next, categoryColumn });
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
            {ICON_ANCHORS.map((anchor) => (
              <SelectItem key={anchor} value={anchor}>{t(`style.symbol.anchorOption.${anchor}`)}</SelectItem>
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
          {categoryColumn && sampleValues.length > 0 && (
            <p className="text-mini leading-snug text-muted-foreground">{t('style.symbol.sampledValues')}</p>
          )}
          {sampleValues.map((value) => {
            // `||` not `??`: a map saved by the previous handler can hold
            // {value, icon: ''}, and the adapter renders the FALLBACK for those
            // — showing a blank field and flagging it as broken would be wrong.
            const mapped = currentCategories.find((entry) => entry.value === value)?.icon
              || symbolConfig.iconImage || 'marker';
            const unknown = !iconResolves(mapped);
            return (
              <div key={String(value)} className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{String(value)}</span>
                  <Input
                    className="h-7 text-xs"
                    value={mapped}
                    aria-label={t('style.symbol.categoryIcon', { value: String(value) })}
                    aria-invalid={unknown || undefined}
                    onChange={(event) => updateCategory(value as string | number | null, event.target.value)}
                  />
                </div>
                {/* fix(#920): a typo used to land in the match expression and draw
                    nothing at all, with no indication anything was wrong. */}
                {unknown && (
                  <p className="text-mini text-warning" role="alert">
                    {t('style.symbol.unknownIcon', { icon: mapped })}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default SymbolEditor;
