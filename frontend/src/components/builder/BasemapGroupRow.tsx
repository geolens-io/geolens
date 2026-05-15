import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import type { DraggableAttributes, DraggableSyntheticListeners } from '@dnd-kit/core';
import { Eye, EyeOff, MoreVertical } from 'lucide-react';
import { Slider } from '@/components/ui/slider';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';

interface DragHandleProps {
  attributes: DraggableAttributes;
  listeners?: DraggableSyntheticListeners;
  setActivatorNodeRef: (node: HTMLButtonElement | null) => void;
}

interface BasemapGroupRowProps {
  groupId: string;
  presetName: string;
  providerLabel?: string;
  visible: boolean;
  opacity: number;
  selected: boolean;
  isExpanded: boolean;
  isDragging?: boolean;
  /** When true, the visibility eye button is rendered with aria-disabled and tabIndex={-1}
   * so it does not appear interactive. Use when the toggle is not yet wired. */
  visibilityDisabled?: boolean;
  dragHandleProps: DragHandleProps;
  onSelectGroup: (id: string) => void;
  onToggleExpand: (id: string) => void;
  onToggleVisibility: (id: string) => void;
  onOpacityChange: (id: string, opacity: number) => void;
  onSwapBasemap: () => void;
  onResetAppearance: () => void;
  // Phase 1041: boundary signal — shows cursor-not-allowed when multi-selection is active (POL-11)
  isMultiSelectionActive?: boolean;
}

export const BasemapGroupRow = memo(function BasemapGroupRow({
  groupId,
  presetName,
  providerLabel,
  visible,
  opacity,
  selected,
  isExpanded,
  isDragging = false,
  visibilityDisabled = false,
  dragHandleProps: _dragHandleProps,
  onSelectGroup,
  onToggleExpand,
  onToggleVisibility,
  onOpacityChange,
  onSwapBasemap,
  onResetAppearance,
  isMultiSelectionActive = false,
}: BasemapGroupRowProps) {
  const { t } = useTranslation('builder');

  const safeOpacity = typeof opacity === 'number' && Number.isFinite(opacity) ? opacity : 1;
  const rowName = `Basemap · ${presetName}`;

  function handleRowClick(_e: React.MouseEvent) {
    onSelectGroup(groupId);
  }

  return (
    <div
      id={`stack-row-${groupId}`}
      role="option"
      aria-selected={selected}
      tabIndex={0}
      className={cn(
        'group/row grid grid-cols-[16px_14px_22px_22px_1fr_60px_22px] gap-2 items-center py-2 px-2 cursor-pointer select-none',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
        !selected && !isDragging && 'hover:bg-[var(--surface-2,theme(colors.accent.DEFAULT))]',
        selected && 'bg-[var(--primary-50,theme(colors.accent.DEFAULT))] shadow-[inset_2px_0_0_var(--primary)]',
        isDragging && 'opacity-40 bg-[var(--surface-2,theme(colors.accent.DEFAULT))] scale-[0.98]',
        // Phase 1041 POL-11: cursor-not-allowed signals basemap boundary during multi-selection mode
        isMultiSelectionActive && 'cursor-not-allowed',
      )}
      onClick={handleRowClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelectGroup(groupId);
        }
      }}
    >
      {/* Cell 1: Caret — visible and functional for basemap group */}
      <button
        type="button"
        aria-expanded={isExpanded}
        aria-controls={`basemap-group-children-${groupId}`}
        onClick={(e) => {
          e.stopPropagation();
          onToggleExpand(groupId);
        }}
        className={cn(
          'text-xs text-muted-foreground transition-transform duration-[--motion-fast] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded',
          isExpanded && 'rotate-90',
        )}
        aria-label={t('basemapGroup.toggleExpand', { defaultValue: 'Toggle basemap group' })}
      >
        ▸
      </button>

      {/* Cell 2: Grip — hidden: basemap group is not user-draggable (AUD-04) */}
      <span aria-hidden="true" className="h-[14px] w-[14px]" />

      {/* Cell 3: Eye visibility toggle — disabled when basemap visibility is not yet wired */}
      <button
        type="button"
        aria-label={t('stackRow.toggleVisibility', {
          defaultValue: 'Toggle visibility for {{name}}',
          name: rowName,
        })}
        aria-disabled={visibilityDisabled || undefined}
        tabIndex={visibilityDisabled ? -1 : undefined}
        className={cn(
          'flex items-center justify-center h-[22px] w-[22px] rounded text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          visibilityDisabled ? 'opacity-30 cursor-default' : 'hover:text-foreground',
        )}
        onClick={(e) => {
          e.stopPropagation();
          if (!visibilityDisabled) onToggleVisibility(groupId);
        }}
      >
        {visible ? (
          <Eye className="h-3.5 w-3.5" aria-hidden="true" />
        ) : (
          <EyeOff className="h-3.5 w-3.5" aria-hidden="true" />
        )}
      </button>

      {/* Cell 4: Type icon — fixed ⊞ glyph with primary colors */}
      <div className="flex items-center justify-center h-[22px] w-[22px]">
        <span
          className="flex items-center justify-center h-[22px] w-[22px] rounded-sm text-xs font-medium"
          style={{
            backgroundColor: 'var(--primary-50, oklch(0.97 0.02 250))',
            color: 'var(--primary-700, oklch(0.46 0.16 250))',
          }}
          aria-hidden="true"
        >
          ⊞
        </span>
      </div>

      {/* Cell 5: Layer name — static, no inline rename for basemap */}
      <div className="min-w-0">
        <span className="truncate text-sm block">
          Basemap · {presetName}
          {providerLabel && (
            <span className="text-muted-foreground"> · {providerLabel}</span>
          )}
        </span>
      </div>

      {/* Cell 6: Opacity slider */}
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/click-events-have-key-events */}
      <div
        className="flex items-center"
        onPointerDown={(e) => e.stopPropagation()}
        onClick={(e) => e.stopPropagation()}
      >
        <Slider
          aria-label={t('stackRow.opacitySlider', {
            defaultValue: 'Opacity for {{name}}',
            name: rowName,
          })}
          aria-valuetext={`${Math.round(safeOpacity * 100)}%`}
          value={[safeOpacity]}
          min={0}
          max={1}
          step={0.05}
          className="w-[60px]"
          onValueChange={([value]) => {
            onOpacityChange(groupId, Number((value ?? safeOpacity).toFixed(2)));
          }}
        />
      </div>

      {/* Cell 7: Kebab menu — basemap variant with only 2 items */}
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/click-events-have-key-events */}
      <div onClick={(e) => e.stopPropagation()}>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              data-kebab-trigger=""
              aria-label={t('stackRow.kebabTrigger', {
                defaultValue: 'Layer options for {{name}}',
                name: rowName,
              })}
              className={cn(
                'flex items-center justify-center h-[22px] w-[22px] rounded text-muted-foreground',
                'opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                'hover:text-foreground hover:bg-accent',
                selected && 'opacity-100',
              )}
              onClick={(e) => e.stopPropagation()}
            >
              <MoreVertical className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-40">
            <DropdownMenuItem onSelect={() => onSwapBasemap()}>
              {t('basemapGroup.swapBasemap', { defaultValue: 'Swap basemap' })}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => onResetAppearance()}>
              {t('basemapGroup.resetAppearance', { defaultValue: 'Reset appearance' })}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
});
