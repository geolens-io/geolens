import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Settings } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { ColorizedGeometryIcon, extractStyleHints, getLayerColors } from '@/components/map/layer-icons';
import { getLayerCapabilities } from '@/lib/layer-capabilities';
import { cn } from '@/lib/utils';
import type { MapLayerResponse } from '@/types/api';

interface SidebarRailProps {
  layers: MapLayerResponse[];
  selectedLayerId: string | null;
  onSelectLayer: (id: string | null) => void;
  onAddDataClick: () => void;
  onSettingsClick: () => void;
}

function RailLayerIcon({ layer }: { layer: MapLayerResponse }) {
  const caps = getLayerCapabilities(layer);
  const layerColors = getLayerColors(layer);
  const styleHints = extractStyleHints(
    layer.paint ?? {},
    layer.layout ?? {},
    layer.dataset_geometry_type,
    layer.opacity,
    layer.style_config,
  );

  if (caps.kind === 'raster' || caps.kind === 'vrt') {
    return (
      <span className="text-xs font-medium" aria-hidden="true">▦</span>
    );
  }

  return (
    <ColorizedGeometryIcon
      geometryType={layer.dataset_geometry_type}
      colors={layerColors}
      layerId={layer.id}
      layerType={caps.kind}
      styleHints={styleHints}
    />
  );
}

export const SidebarRail = memo(function SidebarRail({
  layers,
  selectedLayerId,
  onSelectLayer,
  onAddDataClick,
  onSettingsClick,
}: SidebarRailProps) {
  const { t } = useTranslation('builder');

  return (
    <div className="flex w-16 flex-col items-center border-e bg-background py-2 gap-1 overflow-y-auto">
      {/* Settings */}
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={t('unifiedStack.settings', { defaultValue: 'Settings' })}
            className="flex h-10 w-10 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={onSettingsClick}
          >
            <Settings className="h-[26px] w-[26px]" aria-hidden="true" />
          </button>
        </TooltipTrigger>
        <TooltipContent side="right" sideOffset={8} className="text-xs">
          {t('unifiedStack.settings', { defaultValue: 'Settings' })}
        </TooltipContent>
      </Tooltip>

      {/* Add data */}
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={t('unifiedStack.addData', { defaultValue: '＋ Add data' })}
            className="flex h-10 w-10 items-center justify-center rounded-md bg-primary text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={onAddDataClick}
          >
            <Plus className="h-[26px] w-[26px]" aria-hidden="true" />
          </button>
        </TooltipTrigger>
        <TooltipContent side="right" sideOffset={8} className="text-xs">
          {t('unifiedStack.addData', { defaultValue: '＋ Add data' })}
        </TooltipContent>
      </Tooltip>

      {/* Divider */}
      {layers.length > 0 && (
        <div className="h-px w-8 bg-border my-1" aria-hidden="true" />
      )}

      {/* Layer buttons */}
      {layers.map((layer) => {
        const isSelected = layer.id === selectedLayerId;
        const displayName = layer.display_name ?? layer.dataset_name;
        return (
          <Tooltip key={layer.id}>
            <TooltipTrigger asChild>
              <button
                type="button"
                aria-label={displayName}
                data-selected={isSelected ? 'true' : undefined}
                className={cn(
                  'flex h-10 w-10 items-center justify-center rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  isSelected
                    ? 'bg-[var(--primary-50,theme(colors.accent.DEFAULT))] shadow-[inset_2px_0_0_var(--primary)]'
                    : 'hover:bg-accent',
                )}
                onClick={() => onSelectLayer(layer.id)}
              >
                <span className="flex h-[26px] w-[26px] items-center justify-center">
                  <RailLayerIcon layer={layer} />
                </span>
              </button>
            </TooltipTrigger>
            <TooltipContent side="right" sideOffset={8} className="text-xs max-w-[160px] truncate">
              {displayName}
            </TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
});
