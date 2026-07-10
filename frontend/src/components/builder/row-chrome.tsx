import type { FocusEvent, KeyboardEvent, MouseEvent } from 'react';
import { GripVertical } from 'lucide-react';
import type { DraggableAttributes, DraggableSyntheticListeners } from '@dnd-kit/core';
import { cn } from '@/lib/utils';

// builder-audit #338 STACK-04: shared 6-cell grid template for every stack row
// (StackRow, FolderGroupRow, BasemapGroupRow). Hoisted to one const so a
// column-width change happens in a single place. SublayerRow keeps its own
// 7-column variant (it carries an extra indicator/opacity cell).
export const STACK_ROW_GRID = 'grid-cols-[16px_14px_22px_22px_1fr_22px]';

export interface DragHandleProps {
  attributes: DraggableAttributes;
  listeners?: DraggableSyntheticListeners;
  setActivatorNodeRef: (node: HTMLButtonElement | null) => void;
}

// builder-audit #338 STACK-04: shared selected / hover / dragging tint block. All
// three rows previously copy-pasted near-identical cn() expressions; the
// `--surface-2` theme fallback variant is the superset and is used everywhere.
export function rowStateClasses({
  selected,
  isDragging = false,
}: {
  selected: boolean;
  isDragging?: boolean;
}): string {
  return cn(
    !selected && !isDragging && 'hover:bg-[var(--surface-2,theme(colors.accent.DEFAULT))]',
    selected && 'bg-[var(--primary-50,theme(colors.accent.DEFAULT))] shadow-[inset_2px_0_0_var(--primary)]',
    isDragging && 'opacity-40 bg-[var(--surface-2,theme(colors.accent.DEFAULT))] scale-[0.98]',
  );
}

interface DragGripButtonProps {
  dragHandleProps: DragHandleProps;
  ariaLabel: string;
  /** When true the dnd-kit listeners are NOT spread (drag suppressed) and the
   *  grip shows a not-allowed cursor — used by the basemap row during
   *  multi-selection where drag and multi-select are mutually exclusive. */
  listenersSuppressed?: boolean;
  /** Adds data-touch-reveal="" so coarse-pointer/touch styling can reveal the grip. */
  touchReveal?: boolean;
  testId?: string;
  className?: string;
  onClick?: (e: MouseEvent<HTMLButtonElement>) => void;
  onKeyDown?: (e: KeyboardEvent<HTMLButtonElement>) => void;
  onBlur?: (e: FocusEvent<HTMLButtonElement>) => void;
}

// builder-audit #338 STACK-04: the grip <button> + its load-bearing dnd-kit warning
// previously lived (copy-pasted) in StackRow, FolderGroupRow, and BasemapGroupRow.
// Consolidated here so the warning is stated once and cannot drift.
export function DragGripButton({
  dragHandleProps,
  ariaLabel,
  listenersSuppressed = false,
  touchReveal = false,
  testId,
  className,
  onClick,
  onKeyDown,
  onBlur,
}: DragGripButtonProps) {
  return (
    <button
      ref={dragHandleProps.setActivatorNodeRef}
      type="button"
      {...dragHandleProps.attributes}
      {...(listenersSuppressed ? {} : dragHandleProps.listeners)}
      aria-label={ariaLabel}
      data-testid={testId}
      {...(touchReveal ? { 'data-touch-reveal': '' } : {})}
      className={cn(
        'flex items-center justify-center cursor-grab opacity-35 group-hover/row:opacity-70 text-muted-foreground',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-sm active:cursor-grabbing',
        listenersSuppressed && 'cursor-not-allowed opacity-20',
        className,
      )}
      // 2026-05-18 (builder-audit #338 STACK-04): do NOT add onPointerDown={stopPropagation}
      // here — it overrides dnd-kit's PointerSensor activator (spread above) and breaks
      // pointer drag entirely. onClick stopPropagation alone suppresses row selection on
      // grip click; pointer events do not trigger onClick handlers.
      onClick={onClick ?? ((e) => e.stopPropagation())}
      onKeyDown={onKeyDown}
      onBlur={onBlur}
    >
      <GripVertical className="h-3.5 w-3.5" aria-hidden="true" />
    </button>
  );
}
