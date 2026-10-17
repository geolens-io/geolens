/* eslint-disable jsx-a11y/no-static-element-interactions, jsx-a11y/no-noninteractive-tabindex -- stack rows are composite focus targets with nested controls, so role="button"/listbox roles are intentionally avoided. */
import { memo, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronRight, Eye, EyeOff, FolderMinus, MoreVertical, Pencil, Plus, Trash2 } from 'lucide-react';
import { Checkbox } from '@/components/ui/checkbox';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';
import {
  DragGripButton,
  InlineDeleteConfirm,
  STACK_ROW_GRID,
  rowStateClasses,
  useKebabContextMenu,
  type DragHandleProps,
} from '@/components/builder/row-chrome';
import { useInlineRename } from '@/components/builder/useInlineRename';

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
  // Multi-selection props
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
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const kebabMenu = useKebabContextMenu();

  // Shared inline-rename state machine (was duplicated
  // verbatim with StackRow, including the focus-race gating). Empty input
  // is a silent revert: onCommit ignores a null name.
  const {
    editing,
    setEditing,
    nameValue,
    inputRef,
    inputHandlers,
    startRename,
    skipCloseAutoFocusRef,
    handleMenuCloseAutoFocus,
  } = useInlineRename({
    value: groupName,
    onCommit: (next) => {
      if (next) onRenameGroup(groupId, next);
    },
    // a11y(v1.6.0 audit A7): commit/cancel unmount the focused input — hand
    // focus back to the row, matching the delete-confirm's focus return.
    restoreFocus: () => document.getElementById(`stack-row-${groupId}`)?.focus(),
  });

  // Reset state on groupId change
  useEffect(() => {
    setEditing(false);
    setConfirmingDelete(false);
  }, [groupId, setEditing]);

  // Modifier-aware click handler
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
      onContextMenu={kebabMenu.onContextMenu}
      onKeyDown={(e) => {
        if (kebabMenu.handleContextMenuKey(e)) return;
        // a11y(v1.6.0 audit A7, WCAG 2.1.1): keys from descendant controls
        // (caret, eye, rename input, delete-confirm buttons) keep their native
        // activation — the container only handles keys aimed at the row
        // itself. AFTER the context-menu branch so Shift+F10 still works from
        // a focused descendant.
        if (e.target !== e.currentTarget) return;
        if (e.key === 'Enter') {
          e.preventDefault();
          onSelectGroup(groupId);
        }
        if (e.key === ' ') {
          e.preventDefault();
          onCmdClick?.(groupId); // Space = Cmd-click (toggles multi-selection)
        }
        // Escape with the delete confirm pending dismisses the
        // confirm (consumed) instead of falling through to ancestor Escape
        // handlers. The confirm handles its own Escape when focus is inside it;
        // this covers focus resting on the row.
        if (e.key === 'Escape' && confirmingDelete) {
          e.preventDefault();
          e.stopPropagation();
          setConfirmingDelete(false);
        }
      }}
    >
      {/* Row grid: shared grid template + state classes. */}
      <div
        className={cn(
          'group/row grid', STACK_ROW_GRID, 'gap-2 items-center py-2 px-2 cursor-pointer select-none',
          rowStateClasses({ selected: selected || isMultiSelected, isDragging }),
        )}
      >
        {/* Cell 1: Caret column — Checkbox during multi-selection mode; caret button otherwise */}
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
          // h-6 w-6 (24×24 hit target) + -mx-1 extends the
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
              'flex items-center justify-center h-6 w-6 -mx-1 rounded-sm text-muted-foreground',
              'transition-transform duration-[--motion-fast]',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              isExpanded && 'rotate-90',
            )}
          >
            <ChevronRight className={cn('h-4 w-4', !isExpanded && 'rtl-mirror')} aria-hidden="true" />
          </button>
        )}

        {/* Cell 2: Grip handle (shared DragGripButton). */}
        <DragGripButton
          dragHandleProps={dragHandleProps}
          ariaLabel={t('stackRow.dragHandle', {
            defaultValue: 'Drag to reorder {{name}}',
            name: groupName,
          })}
        />

        {/* Cell 3: Eye visibility toggle.
            aria-pressed reflects the visible state so AT announces it as a toggle,
            matching StackRow and BasemapGroupRow. */}
        <button
          type="button"
          aria-label={t('stackRow.toggleVisibility', {
            defaultValue: 'Toggle visibility for {{name}}',
            name: groupName,
          })}
          aria-pressed={visible}
          className="flex items-center justify-center h-[22px] w-[22px] rounded-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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

        {/* Cell 4: Type icon — folder group.
            Was an inline OKLCH amber with no dark variant;
            now the theme-aware --type-folder token pair. */}
        <span
          className="flex items-center justify-center h-[22px] w-[22px] rounded-sm text-xs font-medium bg-type-folder-bg text-type-folder"
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
              {...inputHandlers}
              // eslint-disable-next-line jsx-a11y/no-autofocus -- triggered by explicit rename action
              autoFocus
            />
          ) : (
            <span
              className="text-sm font-semibold truncate block"
              onDoubleClick={(e) => {
                e.stopPropagation();
                startRename();
              }}
            >
              {groupName}
            </span>
          )}
        </div>

        {/* Cell 6: Kebab menu */}
        {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events */}
        <div onClick={(e) => e.stopPropagation()}>
          <DropdownMenu open={kebabMenu.open} onOpenChange={kebabMenu.onOpenChange}>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                data-kebab-trigger=""
                // Reveal the kebab on coarse-pointer/touch.
                data-touch-reveal=""
                aria-label={t('stackRow.kebabGroupTrigger', {
                  defaultValue: 'Group options for {{name}}',
                  name: groupName,
                })}
                className={cn(
                  'flex items-center justify-center h-[22px] w-[22px] rounded-sm text-muted-foreground',
                  'opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  'hover:text-foreground hover:bg-[var(--surface-2)]',
                  'data-[state=open]:opacity-100',
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
              onCloseAutoFocus={handleMenuCloseAutoFocus}
            >
              <DropdownMenuItem
                onSelect={() => {
                  // Let Radix close the menu cleanly; the rename input mounts in
                  // the next render and is focused by the hook's rAF. The
                  // skipCloseAutoFocusRef flag prevents Radix from stealing focus
                  // back to the kebab.
                  skipCloseAutoFocusRef.current = true;
                  startRename();
                }}
              >
                {/* Kebab items carry icons, matching StackRow. */}
                <Pencil className="h-3.5 w-3.5 me-2" aria-hidden="true" />
                {t('stackRow.kebabRenameGroup', { defaultValue: 'Rename group' })}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => onAddLayer(groupId)}>
                <Plus className="h-3.5 w-3.5 me-2" aria-hidden="true" />
                {t('stackRow.kebabAddLayer', { defaultValue: 'Add layer' })}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => onUngroup(groupId)}>
                <FolderMinus className="h-3.5 w-3.5 me-2" aria-hidden="true" />
                {t('stackRow.kebabUngroup', { defaultValue: 'Ungroup' })}
              </DropdownMenuItem>
              <DropdownMenuItem
                className="text-destructive focus:text-destructive"
                onSelect={() => setConfirmingDelete(true)}
              >
                <Trash2 className="h-3.5 w-3.5 me-2" aria-hidden="true" />
                {t('stackRow.kebabDeleteGroup', { defaultValue: 'Delete group' })}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Shared inline confirm — sibling of grid row, NOT inside DropdownMenuContent */}
      {confirmingDelete && (
        <InlineDeleteConfirm
          confirmId={`confirm-delete-${groupId}`}
          message={t('folderGroup.deleteConfirmMessage', { defaultValue: 'Delete this group and all its layers?' })}
          confirmLabel={t('folderGroup.deleteConfirmAction', { defaultValue: 'Delete all' })}
          cancelLabel={t('folderGroup.deleteConfirmCancel', { defaultValue: 'Keep group' })}
          onConfirm={() => {
            onDeleteGroup(groupId);
            setConfirmingDelete(false);
          }}
          onCancel={() => {
            setConfirmingDelete(false);
            // The confirm owned focus (autofocused Cancel button), so
            // dismissing it must hand focus back to the row instead of <body>.
            document.getElementById(`stack-row-${groupId}`)?.focus();
          }}
        />
      )}
    </div>
  );
});
