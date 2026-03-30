import { BasemapPicker } from '@/components/builder/BasemapPicker';
import type { WidgetContext } from '../types';

export function BasemapWidget({ ctx }: { ctx: WidgetContext }) {
  if (!ctx.basemap) return null;

  return (
    <BasemapPicker
      value={ctx.basemap.value}
      onChange={(id) => {
        ctx.basemap!.onChange(id);
        ctx.basemap!.onDirty();
      }}
      showLabels={ctx.basemap.showLabels}
      onToggleLabels={(v) => {
        ctx.basemap!.onToggleLabels(v);
        ctx.basemap!.onDirty();
      }}
    />
  );
}
