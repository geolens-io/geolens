/* eslint-disable jsx-a11y/no-static-element-interactions, jsx-a11y/no-noninteractive-tabindex -- Phase 1111 LINT-01: stack rows are composite focus targets with nested controls, so role="button"/listbox roles are intentionally avoided. */
import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronRight, Eye, EyeOff, MoreVertical } from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';
import {
  DragGripButton,
  STACK_ROW_GRID,
  rowStateClasses,
  type DragHandleProps,
} from '@/components/builder/row-chrome';

interface BasemapGroupRowProps {
  groupId: string;
  presetName: string;
  providerLabel?: string;
  visible: boolean;
  selected: boolean;
  isExpanded: boolean;
  isDragging?: boolean;
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
        // builder-audit #338 STACK-04: shared grid template + state classes.
        'group/row grid', STACK_ROW_GRID, 'gap-2 items-center py-2 px-2 cursor-pointer select-none',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
        rowStateClasses({ selected, isDragging }),
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
          per sketch findings (3D maps need basemap rendered above data). When
          isMultiSelectionActive is true, the listeners are suppressed (drag +
          multi-select are mutually exclusive per UI-SPEC §"Cross-Plan Visual
          Conflict Check"). builder-audit #338 STACK-04: shared DragGripButton.
          Phase 1199 STACK-05: reveal the reorder grip on coarse-pointer/touch. */}
      <DragGripButton
        dragHandleProps={dragHandleProps}
        ariaLabel={t('basemapGroup.dragHandle', { defaultValue: 'Drag to reorder basemap' })}
        testId="basemap-drag-handle"
        touchReveal
        listenersSuppressed={isMultiSelectionActive}
      />

      {/* Cell 3: Eye visibility toggle.
          builder-audit #338 STACK-06: the dead visibilityDisabled locked-eye branch was
          removed — no call site ever passed it (the basemap dock wires a real toggle).
          SP-10: aria-pressed reflects the visible state so AT users hear "Basemap pressed". */}
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
              // Phase 1199 STACK-05: reveal the kebab on coarse-pointer/touch.
              data-touch-reveal=""
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
