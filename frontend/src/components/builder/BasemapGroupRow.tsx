/* eslint-disable jsx-a11y/no-static-element-interactions, jsx-a11y/no-noninteractive-tabindex -- Phase 1111 LINT-01: stack rows are composite focus targets with nested controls, so role="button"/listbox roles are intentionally avoided. */
import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import type { DraggableAttributes, DraggableSyntheticListeners } from '@dnd-kit/core';
import { ChevronRight, Eye, EyeOff, GripVertical, MoreVertical } from 'lucide-react';
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
  selected,
  isExpanded,
  isDragging = false,
  visibilityDisabled = false,
  dragHandleProps,
  onSelectGroup,
  onToggleExpand,
  onToggleVisibility,
  onSwapBasemap,
  onResetAppearance,
  isMultiSelectionActive = false,
}: BasemapGroupRowProps) {
  const { t } = useTranslation('builder');

  // Phase 1051 IN-01: single source for the display name string. Used by
  // aria-label (visibility toggle), aria-label (kebab trigger), and the visible
  // row name in Cell 5 — three call sites that previously drifted independently.
  const rowName = t('basemapGroup.rowName', {
    defaultValue: 'Basemap · {{name}}',
    name: presetName,
  });

  function handleRowClick(_e: React.MouseEvent) {
    // Phase 1051 CR-02: cursor-not-allowed at line 78 + suppressed drag listeners
    // at line 122 advertise the row as non-interactive during multi-selection.
    // Without this guard, the click still fires onSelectGroup, unmounting the
    // BulkActionBar mid-selection — a UX contract violation.
    if (isMultiSelectionActive) return;
    onSelectGroup(groupId);
  }

  return (
    <div
      id={`stack-row-${groupId}`}
      data-selected={selected ? 'true' : undefined}
      aria-current={selected ? 'true' : undefined}
      tabIndex={0}
      className={cn(
        'group/row grid grid-cols-[16px_14px_22px_22px_1fr_22px] gap-2 items-center py-2 px-2 cursor-pointer select-none',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
        !selected && !isDragging && 'hover:bg-[var(--surface-2,theme(colors.accent.DEFAULT))]',
        selected && 'bg-[var(--primary-50,theme(colors.accent.DEFAULT))] shadow-[inset_2px_0_0_var(--primary)]',
        isDragging && 'opacity-40 bg-[var(--surface-2,theme(colors.accent.DEFAULT))] scale-[0.98]',
        // Phase 1041 POL-11: cursor-not-allowed signals basemap boundary during multi-selection mode
        isMultiSelectionActive && 'cursor-not-allowed',
      )}
      onClick={handleRowClick}
      onKeyDown={(e) => {
        // Phase 1051 CR-02: mirror handleRowClick — keyboard activation must
        // honor the multi-selection boundary, matching the visual signal.
        if (isMultiSelectionActive) return;
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelectGroup(groupId);
        }
      }}
    >
      {/* Cell 1: Caret — visible and functional for basemap group.
          UX-01 (Phase 1051 Plan 04): h-6 w-6 (24×24 hit target) + -mx-1 extends the visual
          box 4px past each side of the 16px grid column without altering the grid template
          (sketch 002 A "A-strict"). ChevronRight Lucide icon at h-4 w-4 (16px visible glyph)
          replaces the Unicode ▸ text character. */}
      <button
        type="button"
        aria-expanded={isExpanded}
        aria-controls={`basemap-group-children-${groupId}`}
        onClick={(e) => {
          e.stopPropagation();
          onToggleExpand(groupId);
        }}
        className={cn(
          'flex items-center justify-center h-6 w-6 -mx-1 rounded text-muted-foreground',
          'transition-transform duration-[--motion-fast]',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          isExpanded && 'rotate-90',
        )}
        aria-label={t('basemapGroup.toggleExpand', { defaultValue: 'Toggle basemap group' })}
      >
        <ChevronRight className="h-4 w-4" aria-hidden="true" />
      </button>

      {/* Cell 2: Grip — UX-03 (Phase 1051 Plan 06): basemap group IS user-draggable
          for top/bottom reordering. AUD-04's "pinned-at-bottom" decision is reversed
          per sketch findings (3D maps need basemap rendered above data). Mirrors
          FolderGroupRow.tsx:196-210 grip pattern. When isMultiSelectionActive is
          true, the listeners are suppressed (drag + multi-select are mutually
          exclusive per UI-SPEC §"Cross-Plan Visual Conflict Check"). */}
      <button
        ref={dragHandleProps.setActivatorNodeRef}
        type="button"
        {...dragHandleProps.attributes}
        {...(isMultiSelectionActive ? {} : dragHandleProps.listeners)}
        aria-label={t('basemapGroup.dragHandle', { defaultValue: 'Drag to reorder basemap' })}
        data-testid="basemap-drag-handle"
        className={cn(
          'flex items-center justify-center cursor-grab opacity-35 group-hover/row:opacity-70 text-muted-foreground',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded active:cursor-grabbing',
          isMultiSelectionActive && 'cursor-not-allowed opacity-20',
        )}
        // 2026-05-18: do NOT add onPointerDown={stopPropagation} — it overrides
        // dnd-kit's PointerSensor activator (spread above), breaking pointer
        // drag entirely. onClick stopPropagation alone is enough to suppress
        // row selection on grip click.
        onClick={(e) => e.stopPropagation()}
      >
        <GripVertical className="h-3.5 w-3.5" aria-hidden="true" />
      </button>

      {/* Cell 3: Eye visibility toggle.
          SP-13: when visibilityDisabled (current v1 behavior), render a non-interactive
          <span> glyph with a tooltip rather than a disabled <button>. The slot footprint
          is identical to the active button so layout doesn't shift.
          SP-10: aria-pressed reflects the visible state so AT users hear "Basemap pressed"
          when the toggle is actually wired. */}
      {visibilityDisabled ? (
        <span
          role="img"
          aria-label={t('basemapGroup.visibilityLocked', {
            defaultValue: 'Basemap is always visible — use Remove basemap to hide.',
          })}
          title={t('basemapGroup.visibilityLocked', {
            defaultValue: 'Basemap is always visible — use Remove basemap to hide.',
          })}
          data-testid="basemap-visibility-locked"
          className="flex items-center justify-center h-[22px] w-[22px] rounded text-muted-foreground opacity-40 cursor-default"
        >
          <Eye className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
      ) : (
        <button
          type="button"
          aria-label={t('stackRow.toggleVisibility', {
            defaultValue: 'Toggle visibility for {{name}}',
            name: rowName,
          })}
          aria-pressed={visible}
          className="flex items-center justify-center h-[22px] w-[22px] rounded text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          onClick={(e) => {
            e.stopPropagation();
            onToggleVisibility(groupId);
          }}
        >
          {visible ? (
            <Eye className="h-3.5 w-3.5" aria-hidden="true" />
          ) : (
            <EyeOff className="h-3.5 w-3.5" aria-hidden="true" />
          )}
        </button>
      )}

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
          {rowName}
          {providerLabel && (
            <span className="text-muted-foreground"> · {providerLabel}</span>
          )}
        </span>
      </div>

      {/* Cell 6: Kebab menu — basemap variant with only 2 items */}
      {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events */}
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
                'hover:text-foreground hover:bg-[var(--surface-2)]',
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
