/* eslint-disable jsx-a11y/no-static-element-interactions, jsx-a11y/no-noninteractive-tabindex -- Phase 1111 LINT-01: stack rows are composite focus targets with nested controls, so role="button"/listbox roles are intentionally avoided. */
import { memo, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { DraggableAttributes, DraggableSyntheticListeners } from '@dnd-kit/core';
import { ChevronRight, Eye, EyeOff, GripVertical, MoreVertical } from 'lucide-react';
import { Checkbox } from '@/components/ui/checkbox';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';

interface DragHandleProps {
  attributes: DraggableAttributes;
  listeners?: DraggableSyntheticListeners;
  setActivatorNodeRef: (node: HTMLButtonElement | null) => void;
}

interface FolderGroupRowProps {
  groupId: string;
  groupName: string;
  visible: boolean;
  selected: boolean;
  isExpanded: boolean;
  isDragging?: boolean;
  dragHandleProps: DragHandleProps;
  onSelectGroup: (id: string) => void;
  onToggleExpand: (id: string) => void;
  onToggleVisibility: (id: string) => void;
  onRenameGroup: (id: string, name: string) => void;
  onAddLayer: (id: string) => void;
  onUngroup: (id: string) => void;
  onDeleteGroup: (id: string) => void;
  // Phase 1041: multi-selection props (POL-06, POL-07)
  isMultiSelected?: boolean;
  isMultiSelectionActive?: boolean;
  onCmdClick?: (id: string) => void;
  onShiftClick?: (id: string) => void;
  onCheckboxClick?: (id: string) => void;
}

export const FolderGroupRow = memo(function FolderGroupRow({
  groupId,
  groupName,
  visible,
  selected,
  isExpanded,
  isDragging = false,
  dragHandleProps,
  onSelectGroup,
  onToggleExpand,
  onToggleVisibility,
  onRenameGroup,
  onAddLayer,
  onUngroup,
  onDeleteGroup,
  isMultiSelected = false,
  isMultiSelectionActive = false,
  onCmdClick,
  onShiftClick,
  onCheckboxClick,
}: FolderGroupRowProps) {
  const { t } = useTranslation('builder');
  const [editing, setEditing] = useState(false);
  const [nameValue, setNameValue] = useState<string>('');
  const escapeRef = useRef(false);
  const committingRef = useRef(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  // BUG-03 follow-up (2026-05-18 MCP smoke): the single-rAF strategy in the
  // editing useEffect lost the focus race to Radix DropdownMenu's
  // `restoreFocus` in real browsers (jsdom did not exercise the race, so the
  // unit test passed). This ref gates Radix's `onCloseAutoFocus` so that
  // restoreFocus is skipped specifically when the rename item was just
  // selected; other dismiss paths (Escape, outside click) still restore focus
  // to the kebab trigger as expected.
  const skipCloseAutoFocusRef = useRef(false);

  // Reset state on groupId change
  useEffect(() => {
    setEditing(false);
    setConfirmingDelete(false);
  }, [groupId]);

  // Auto-focus + select input text when entering edit mode. The rAF defer is
  // defense-in-depth alongside the onCloseAutoFocus gate below — without the
  // gate, Radix's restoreFocus reliably wins the race in real browsers.
  useEffect(() => {
    if (editing) {
      requestAnimationFrame(() => {
        if (inputRef.current) {
          inputRef.current.focus();
          inputRef.current.select();
        }
      });
    }
  }, [editing]);

  function handleStartRename() {
    setNameValue(groupName);
    setEditing(true);
  }

  function commitRename() {
    if (escapeRef.current) {
      escapeRef.current = false;
      return;
    }
    if (committingRef.current) return; // block blur double-fire after Enter
    committingRef.current = true;
    setEditing(false);
    const trimmed = nameValue.trim();
    if (trimmed) onRenameGroup(groupId, trimmed);
    // else: silent revert per UI-SPEC
    // committingRef stays true during the synchronous blur triggered by setEditing(false);
    // reset it async so it does not block a subsequent genuine focus+blur cycle.
    requestAnimationFrame(() => { committingRef.current = false; });
  }

  // Phase 1041: modifier-aware click handler (POL-06)
  function handleRowClick(e: React.MouseEvent) {
    if (e.metaKey || e.ctrlKey) {
      e.preventDefault();
      onCmdClick?.(groupId);
      return;
    }
    if (e.shiftKey) {
      e.preventDefault();
      onShiftClick?.(groupId);
      return;
    }
    onSelectGroup(groupId);
  }

  return (
    <div
      id={`stack-row-${groupId}`}
      data-selected={selected || isMultiSelected ? 'true' : undefined}
      aria-current={selected || isMultiSelected ? 'true' : undefined}
      tabIndex={0}
      className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
      onClick={handleRowClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          onSelectGroup(groupId);
        }
        if (e.key === ' ') {
          e.preventDefault();
          onCmdClick?.(groupId); // Space = Cmd-click (toggles multi-selection)
        }
      }}
    >
      {/* Row grid */}
      <div
        className={cn(
          'group/row grid grid-cols-[16px_14px_22px_22px_1fr_22px] gap-2 items-center py-2 px-2 cursor-pointer select-none',
          !(selected || isMultiSelected) && !isDragging && 'hover:bg-[var(--surface-2,theme(colors.accent.DEFAULT))]',
          (selected || isMultiSelected) && 'bg-[var(--primary-50,theme(colors.accent.DEFAULT))] shadow-[inset_2px_0_0_var(--primary)]',
          isDragging && 'opacity-40 bg-[var(--surface-2,theme(colors.accent.DEFAULT))] scale-[0.98]',
        )}
      >
        {/* Cell 1: Caret column — Checkbox during multi-selection mode; caret button otherwise (Phase 1041) */}
        {isMultiSelectionActive ? (
          <Checkbox
            className="h-3.5 w-3.5"
            checked={isMultiSelected}
            aria-checked={isMultiSelected}
            aria-label={t('bulkActions.selectGroup', { name: groupName, defaultValue: 'Select {{name}}' })}
            onCheckedChange={() => onCheckboxClick?.(groupId)}
            onClick={(e) => e.stopPropagation()}
            onPointerDown={(e) => e.stopPropagation()}
          />
        ) : (
          // UX-01 (Phase 1051 Plan 04): h-6 w-6 (24×24 hit target) + -mx-1 extends the
          // visual box 4px past each side of the 16px grid column without altering the grid
          // template (sketch 002 A "A-strict"). ChevronRight Lucide icon at h-4 w-4 (16px
          // visible glyph) replaces the Unicode ▸ text character.
          <button
            type="button"
            aria-expanded={isExpanded}
            aria-controls={`folder-group-children-${groupId}`}
            aria-label={t('folderGroup.toggleExpand', { defaultValue: 'Toggle folder group' })}
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
          >
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </button>
        )}

        {/* Cell 2: Grip handle */}
        <button
          ref={dragHandleProps.setActivatorNodeRef}
          type="button"
          {...dragHandleProps.attributes}
          {...dragHandleProps.listeners}
          aria-label={t('stackRow.dragHandle', {
            defaultValue: 'Drag to reorder {{name}}',
            name: groupName,
          })}
          className="flex items-center justify-center cursor-grab opacity-35 group-hover/row:opacity-70 text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded active:cursor-grabbing"
          // 2026-05-18: do NOT add onPointerDown={stopPropagation} — it overrides
          // dnd-kit's PointerSensor activator (spread above) and breaks pointer
          // drag. onClick stopPropagation alone suppresses row selection.
          onClick={(e) => e.stopPropagation()}
        >
          <GripVertical className="h-3.5 w-3.5" aria-hidden="true" />
        </button>

        {/* Cell 3: Eye visibility toggle */}
        <button
          type="button"
          aria-label={t('stackRow.toggleVisibility', {
            defaultValue: 'Toggle visibility for {{name}}',
            name: groupName,
          })}
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

        {/* Cell 4: Type icon — folder group amber variant */}
        <span
          className="flex items-center justify-center h-[22px] w-[22px] rounded-sm text-xs font-medium"
          style={{ backgroundColor: 'oklch(0.93 0.03 80)', color: 'oklch(0.45 0.10 80)' }}
          aria-hidden="true"
        >
          ▸
        </span>

        {/* Cell 5: Group name — toggle between input and span based on editing */}
        <div className="min-w-0">
          {editing ? (
            <input
              ref={inputRef}
              type="text"
              aria-label={t('folderGroup.renameInputPlaceholder', { defaultValue: 'Group name' })}
              placeholder={t('folderGroup.renameInputPlaceholder', { defaultValue: 'Group name' })}
              className="h-6 w-full min-w-0 border-b border-primary bg-transparent text-sm font-semibold outline-none focus:ring-1 focus:ring-ring"
              value={nameValue}
              onChange={(e) => setNameValue(e.target.value)}
              onBlur={commitRename}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  commitRename();
                }
                if (e.key === 'Escape') {
                  escapeRef.current = true;
                  setEditing(false);
                  setNameValue(groupName);
                }
              }}
              onClick={(e) => e.stopPropagation()}
              // eslint-disable-next-line jsx-a11y/no-autofocus -- triggered by explicit rename action
              autoFocus
            />
          ) : (
            <span
              className="text-sm font-semibold truncate block"
              onDoubleClick={(e) => {
                e.stopPropagation();
                handleStartRename();
              }}
            >
              {groupName}
            </span>
          )}
        </div>

        {/* Cell 6: Kebab menu */}
        {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events */}
        <div onClick={(e) => e.stopPropagation()}>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                data-kebab-trigger=""
                aria-label={t('stackRow.kebabGroupTrigger', {
                  defaultValue: 'Group options for {{name}}',
                  name: groupName,
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
            <DropdownMenuContent
              align="end"
              className="w-44"
              onCloseAutoFocus={(e) => {
                // Gate Radix's restoreFocus: when the rename item was just
                // selected, the editing useEffect's rAF focus should land on
                // the input — not be overridden back to the kebab trigger.
                if (skipCloseAutoFocusRef.current) {
                  e.preventDefault();
                  skipCloseAutoFocusRef.current = false;
                }
              }}
            >
              <DropdownMenuItem
                onSelect={() => {
                  // Let Radix close the menu cleanly; the rename input mounts
                  // in the next render and gets focused by the editing
                  // useEffect. The skipCloseAutoFocusRef flag prevents Radix
                  // from immediately stealing focus back to the kebab.
                  skipCloseAutoFocusRef.current = true;
                  handleStartRename();
                }}
              >
                {t('stackRow.kebabRenameGroup', { defaultValue: 'Rename group' })}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => onAddLayer(groupId)}>
                {t('stackRow.kebabAddLayer', { defaultValue: 'Add layer' })}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => onUngroup(groupId)}>
                {t('stackRow.kebabUngroup', { defaultValue: 'Ungroup' })}
              </DropdownMenuItem>
              <DropdownMenuItem
                className="text-destructive focus:text-destructive"
                onSelect={() => setConfirmingDelete(true)}
              >
                {t('stackRow.kebabDeleteGroup', { defaultValue: 'Delete group' })}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Inline alertdialog for delete confirmation — sibling of grid row, NOT inside DropdownMenuContent */}
      {confirmingDelete && (
        // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions
        <div
          role="alertdialog"
          aria-labelledby={`confirm-delete-${groupId}`}
          className="mx-2 mb-2 p-3 rounded-md border bg-popover space-y-2"
          onClick={(e) => e.stopPropagation()}
        >
          <p id={`confirm-delete-${groupId}`} className="text-sm text-destructive text-center">
            {t('folderGroup.deleteConfirmMessage', { defaultValue: 'Delete this group and all its layers?' })}
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="destructive"
              className="flex-1"
              onClick={() => {
                onDeleteGroup(groupId);
                setConfirmingDelete(false);
              }}
            >
              {t('folderGroup.deleteConfirmAction', { defaultValue: 'Delete all' })}
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="flex-1"
              onClick={() => setConfirmingDelete(false)}
              // eslint-disable-next-line jsx-a11y/no-autofocus -- focus on safe choice per UI-SPEC accessibility
              autoFocus
            >
              {t('folderGroup.deleteConfirmCancel', { defaultValue: 'Keep group' })}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
});
