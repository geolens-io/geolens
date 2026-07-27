import { useState } from 'react';
import type { FocusEvent, KeyboardEvent, MouseEvent } from 'react';
import { GripVertical } from 'lucide-react';
import type { DraggableAttributes, DraggableSyntheticListeners } from '@dnd-kit/core';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

// builder-audit #338 STACK-04: shared 6-cell grid template for every stack row
// (StackRow, FolderGroupRow, BasemapGroupRow). Hoisted to one const so a
// column-width change happens in a single place. SublayerRow keeps its own
// 7-column variant (it carries an extra indicator/opacity cell).
export const STACK_ROW_GRID = 'grid-cols-[16px_14px_22px_22px_1fr_22px]';

// fix(#585): right-click (and Shift+F10 / ContextMenu key) on a stack row opens
// its existing kebab menu, so row actions are reachable without discovering the
// hover-revealed kebab. Shared by StackRow, FolderGroupRow, and BasemapGroupRow:
// spread the returned `open`/`onOpenChange` onto the row's <DropdownMenu>, wire
// `onContextMenu` on the row container, and call `handleContextMenuKey` from the
// row's onKeyDown (returns true when it consumed the event).
export function useKebabContextMenu() {
  const [open, setOpen] = useState(false);
  function onContextMenu(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setOpen(true);
  }
  function handleContextMenuKey(e: KeyboardEvent): boolean {
    if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) {
      e.preventDefault();
      e.stopPropagation();
      setOpen(true);
      return true;
    }
    return false;
  }
  return { open, onOpenChange: setOpen, onContextMenu, handleContextMenuKey };
}

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
    selected && 'bg-primary-50 selection-inset',
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
  /** fix(#759): reflects a row-level keyboard-reorder mode on the grip, so
   *  screen readers hear the armed/disarmed state of the toggle. */
  ariaPressed?: boolean;
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
  ariaPressed,
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
      // Only override when the row drives a reorder mode — an unconditional
      // undefined would erase the aria-pressed dnd-kit manages in
      // `attributes` (the same later-prop-wins trap this file just fixed).
      {...(ariaPressed !== undefined ? { 'aria-pressed': ariaPressed } : {})}
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
      // fix(#759): second occurrence of the props-after-listeners-spread trap
      // (first: #525). A later JSX prop wins even when undefined, so an
      // unconditional onKeyDown here destroyed the dnd-kit KeyboardSensor
      // activator on EVERY row — folder and basemap groups, which pass no
      // custom handler, were left pointer-only. Compose instead: the row's
      // handler runs first, and the sensor only sees keys the row didn't
      // claim (StackRow's fallback mode preventDefaults the keys it owns).
      // codex(#794 round 3): a CLAIMED key must also stop bubbling — both the
      // sensor's activator and the custom handlers preventDefault when they
      // take a key, and the enclosing rows (folder multi-select, basemap
      // select) handle the same Space/Enter without checking defaultPrevented,
      // so a keyboard drag would simultaneously fire a conflicting row action.
      onKeyDown={(e) => {
        onKeyDown?.(e);
        if (!e.defaultPrevented && !listenersSuppressed) {
          dragHandleProps.listeners?.onKeyDown?.(e);
        }
        if (e.defaultPrevented) e.stopPropagation();
      }}
      onBlur={onBlur}
    >
      <GripVertical className="h-3.5 w-3.5" aria-hidden="true" />
    </button>
  );
}

// fix(#585): ONE inline delete-confirmation pattern for stack rows. StackRow
// and FolderGroupRow previously rendered two visually different confirm boxes
// for the same interaction; this is the single shared shape (destructive-tint
// box, small buttons, cancel autofocused per AUD-09 so Enter dismisses rather
// than destroys). BulkActionBar keeps its horizontal single-line variant — its
// confirm lives INSIDE the fixed-height toolbar, not below a row.
// ux(#777): the builder-wide destructive-confirm order is safe action first
// (left), destructive action last (right) — the same Cancel-then-Action order
// every ui/alert-dialog footer in the app renders. The DEM editor footer,
// basemap-sublayer reset, and render-as confirms mount this component (with a
// container-specific className) instead of hand-rolling their own.
//
// fix(#788): NOT an alertdialog — it is inline and non-modal (no aria-modal, no
// focus trap), so claiming the role promised dismissal semantics it didn't
// have. role="group" + role="alert" on the message announces the confirm when
// it appears, and Escape cancels it here (consumed, so it cannot bubble on to
// ancestor Escape handlers while the confirm is pending).
interface InlineDeleteConfirmProps {
  /** ids the aria-labelledby / message paragraph; must be unique per row. */
  confirmId: string;
  message: string;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  /** Container-specific spacing overrides (tailwind-merged onto the defaults). */
  className?: string;
}

export function InlineDeleteConfirm({
  confirmId,
  message,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel,
  className,
}: InlineDeleteConfirmProps) {
  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- click stops row-select propagation; keydown is the Escape-cancel guard
    <div
      role="group"
      aria-labelledby={confirmId}
      className={cn('mx-2 mb-2 flex flex-col gap-2 p-3 bg-destructive/10 rounded-md', className)}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.preventDefault();
          e.stopPropagation();
          onCancel();
        }
      }}
    >
      <p id={confirmId} role="alert" className="text-sm text-destructive">
        {message}
      </p>
      <div className="flex gap-2">
        <Button
          size="sm"
          variant="ghost"
          onClick={onCancel}
          // eslint-disable-next-line jsx-a11y/no-autofocus -- focus on the safe action so Enter dismisses, not destroys (AUD-09)
          autoFocus
        >
          {cancelLabel}
        </Button>
        <Button size="sm" variant="destructive" onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </div>
  );
}
