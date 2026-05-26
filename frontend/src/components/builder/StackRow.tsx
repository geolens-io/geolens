/* eslint-disable jsx-a11y/no-static-element-interactions, jsx-a11y/no-noninteractive-tabindex -- Phase 1111 LINT-01: stack rows are composite focus targets with nested controls, so role="button"/listbox roles are intentionally avoided. */
import { memo, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import type { DraggableAttributes, DraggableSyntheticListeners } from '@dnd-kit/core';
import { Eye, EyeOff, GripVertical, MoreVertical } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { ColorizedGeometryIcon, extractStyleHints, getLayerColors } from '@/components/map/layer-icons';
import { getLayerCapabilities } from '@/lib/layer-capabilities';
import { cn } from '@/lib/utils';
import type { MapLayerResponse } from '@/types/api';

interface DragHandleProps {
  attributes: DraggableAttributes;
  listeners?: DraggableSyntheticListeners;
  setActivatorNodeRef: (node: HTMLButtonElement | null) => void;
}

interface StackRowProps {
  layer: MapLayerResponse;
  selected: boolean;
  isDragging?: boolean;
  dragHandleProps: DragHandleProps;
  onSelectLayer: (id: string) => void;
  onToggleVisibility: (id: string) => void;
  onRemove: (id: string) => void;
  onRename: (layerId: string, newName: string | null) => void;
  onDuplicate: (id: string) => void;
  /** Existing user folder groups, used for the "Add to group…" sub-flow */
  existingFolderGroups?: Array<{ id: string; name: string }>;
  /** Called when user selects an existing group from the sub-list */
  onAddToGroup?: (layerId: string, groupId: string) => void;
  /** Called when user selects "＋ New group…" */
  onCreateGroupWithLayer?: (layerId: string) => void;
  /** Called when user selects "Move out of group" (layer is already in a group) */
  onMoveLayerOutOfGroup?: (layerId: string) => void;
  onKeyboardReorder?: (layerId: string, direction: 'up' | 'down') => void;
  /** When non-null, the layer is inside a group — "Move out of group" replaces the sub-flow */
  parentGroupId?: string | null;
  // Phase 1041: multi-selection props (POL-06, POL-07)
  isMultiSelected?: boolean;
  isMultiSelectionActive?: boolean;
  onCmdClick?: (id: string) => void;
  onShiftClick?: (id: string) => void;
  onCheckboxClick?: (id: string) => void;
  // Phase 1042 POL-15: entry animation — set true immediately after add, cleared after 200ms
  isFresh?: boolean;
}

function TypeIcon({ layer }: { layer: MapLayerResponse }) {
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
    const isDEM = layer.is_dem === true;
    const renderMode = (layer.style_config as Record<string, unknown> | null | undefined)?.render_mode;
    let glyph = '▦';
    if (isDEM) {
      if (renderMode === 'hillshade') glyph = '⛰';
      else if (renderMode === 'terrain') glyph = '◬';
      // else image → ▦ (default)
    }
    return (
      <span
        className="flex items-center justify-center h-[22px] w-[22px] rounded-sm bg-[--type-raster-bg] text-[--type-raster] text-xs font-semibold"
        aria-hidden="true"
      >
        {glyph}
      </span>
    );
  }

  // Vector layer
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

export const StackRow = memo(function StackRow({
  layer,
  selected,
  isDragging = false,
  dragHandleProps,
  onSelectLayer,
  onToggleVisibility,
  onRemove,
  onRename,
  onDuplicate,
  existingFolderGroups = [],
  onAddToGroup,
  onCreateGroupWithLayer,
  onMoveLayerOutOfGroup,
  onKeyboardReorder,
  parentGroupId = null,
  isMultiSelected = false,
  isMultiSelectionActive = false,
  onCmdClick,
  onShiftClick,
  onCheckboxClick,
  isFresh = false,
}: StackRowProps) {
  const { t } = useTranslation('builder');
  const [editing, setEditing] = useState(false);
  const [nameValue, setNameValue] = useState<string>('');
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [keyboardReorderActive, setKeyboardReorderActive] = useState(false);
  const escapeRef = useRef(false);
  const committingRef = useRef(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  // Mirrors FolderGroupRow's BUG-03 follow-up: gate Radix `restoreFocus` so
  // the rename input keeps focus after the kebab menu closes. The prior
  // `_e.preventDefault()` strategy kept the menu open and trapped focus inside
  // it, leaving the input unfocused.
  const skipCloseAutoFocusRef = useRef(false);

  const displayName = layer.display_name ?? layer.dataset_name;

  function handleStartRename() {
    setNameValue(displayName);
    setEditing(true);
  }

  function handleDragHandleKeyDown(e: KeyboardEvent<HTMLButtonElement>) {
    const isToggleKey = e.key === ' ' || e.key === 'Spacebar' || e.key === 'Enter';
    if (isToggleKey) {
      e.preventDefault();
      e.stopPropagation();
      setKeyboardReorderActive((active) => !active);
      return;
    }

    if (e.key === 'Escape' && keyboardReorderActive) {
      e.preventDefault();
      e.stopPropagation();
      setKeyboardReorderActive(false);
      return;
    }

    if (!keyboardReorderActive || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return;
    e.preventDefault();
    e.stopPropagation();
    onKeyboardReorder?.(layer.id, e.key === 'ArrowUp' ? 'up' : 'down');
  }

  // Focus + select the rename input when entering edit mode. rAF defers the
  // call so it runs after React commits the input; the onCloseAutoFocus gate
  // on DropdownMenuContent prevents Radix from stealing focus back.
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

  function commitRename() {
    if (escapeRef.current) {
      escapeRef.current = false;
      return;
    }
    if (committingRef.current) return; // block blur double-fire after Enter
    committingRef.current = true;
    setEditing(false);
    onRename(layer.id, nameValue.trim() || null);
    // committingRef stays true during the synchronous blur triggered by setEditing(false);
    // reset it async so it does not block a subsequent genuine focus+blur cycle.
    requestAnimationFrame(() => { committingRef.current = false; });
  }

  // Phase 1041: modifier-aware click handler (POL-06)
  function handleRowClick(e: React.MouseEvent) {
    if (e.metaKey || e.ctrlKey) {
      e.preventDefault();
      onCmdClick?.(layer.id);
      return;
    }
    if (e.shiftKey) {
      e.preventDefault();
      onShiftClick?.(layer.id);
      return;
    }
    onSelectLayer(layer.id);
  }

  return (
    <>
    {/* Phase 1041: visuallySelected is true for single-select focus OR multi-select membership */}
    <div
      id={`stack-row-${layer.id}`}
      data-selected={selected || isMultiSelected ? 'true' : undefined}
      aria-current={selected || isMultiSelected ? 'true' : undefined}
      tabIndex={0}
      className={cn(
        // SP-14: explicit cursor-pointer + hover:bg-[var(--surface-2)] on the row body
        // so hover affordance is discoverable across the whole row, not just child controls.
        'group/row grid grid-cols-[16px_14px_22px_22px_1fr_22px] gap-2 items-center py-2 px-2 cursor-pointer select-none',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
        // Row states — unified: either single-selection focus OR multi-selection shows primary tint
        !(selected || isMultiSelected) && !isDragging && 'hover:bg-[var(--surface-2)]',
        (selected || isMultiSelected) && 'bg-[var(--primary-50,theme(colors.accent.DEFAULT))] shadow-[inset_2px_0_0_var(--primary)]',
        isDragging && 'opacity-40 bg-[var(--surface-2)] scale-[0.98]',
        // Phase 1042 POL-15: entry animation — animate-in/fade-in from tw-animate-css
        isFresh && 'animate-in fade-in duration-[--motion-fast]',
      )}
      onClick={handleRowClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          onSelectLayer(layer.id);
        }
        if (e.key === ' ') {
          e.preventDefault();
          onCmdClick?.(layer.id); // Space = Cmd-click (toggles multi-selection)
        }
      }}
    >
      {/* Cell 1: Caret column — hidden span at rest; Checkbox during multi-selection mode (Phase 1041) */}
      {isMultiSelectionActive ? (
        <Checkbox
          className="h-3.5 w-3.5"
          checked={isMultiSelected}
          aria-checked={isMultiSelected}
          aria-label={t('bulkActions.selectRow', { name: layer.display_name ?? layer.dataset_name, defaultValue: 'Select {{name}}' })}
          onCheckedChange={() => onCheckboxClick?.(layer.id)}
          onClick={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
        />
      ) : (
        <span
          aria-hidden="true"
          style={{ visibility: 'hidden' }}
          className="text-xs text-muted-foreground"
        >
          ▸
        </span>
      )}

      {/* Cell 2: Grip handle */}
      <button
        ref={dragHandleProps.setActivatorNodeRef}
        type="button"
        {...dragHandleProps.attributes}
        {...dragHandleProps.listeners}
        aria-label={t('stackRow.dragHandle', {
          defaultValue: 'Drag to reorder {{name}}',
          name: displayName,
        })}
        className="flex items-center justify-center cursor-grab opacity-35 group-hover/row:opacity-70 text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded active:cursor-grabbing"
        // 2026-05-18: do NOT add onPointerDown={stopPropagation} — it overrides
        // dnd-kit's PointerSensor activator (spread above) and breaks pointer
        // drag. onClick stopPropagation alone suppresses row selection on grip
        // click; pointer events don't trigger onClick handlers.
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleDragHandleKeyDown}
        onBlur={() => setKeyboardReorderActive(false)}
      >
        <GripVertical className="h-3.5 w-3.5" aria-hidden="true" />
      </button>

      {/* Cell 3: Eye visibility toggle. SP-10: aria-pressed reflects the
          current visible state so screen readers announce it as a toggle. */}
      <button
        type="button"
        aria-label={t('stackRow.toggleVisibility', {
          defaultValue: 'Toggle visibility for {{name}}',
          name: displayName,
        })}
        aria-pressed={layer.visible}
        className="flex items-center justify-center h-[22px] w-[22px] rounded text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onClick={(e) => {
          e.stopPropagation();
          onToggleVisibility(layer.id);
        }}
      >
        {layer.visible ? (
          <Eye className="h-3.5 w-3.5" aria-hidden="true" />
        ) : (
          <EyeOff className="h-3.5 w-3.5" aria-hidden="true" />
        )}
      </button>

      {/* Cell 4: Type icon */}
      <div className="flex items-center justify-center h-[22px] w-[22px]">
        <TypeIcon layer={layer} />
      </div>

      {/* Cell 5: Layer name */}
      <div className="min-w-0">
        {editing ? (
          <input
            ref={inputRef}
            type="text"
            data-testid="stack-row-rename-input"
            className="h-6 w-full min-w-0 border-b border-primary bg-transparent text-sm outline-none focus:ring-1 focus:ring-ring"
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
                setNameValue(displayName);
              }
            }}
            onClick={(e) => e.stopPropagation()}
            // eslint-disable-next-line jsx-a11y/no-autofocus -- triggered by explicit rename action
            autoFocus
          />
        ) : (
          <span
            className="truncate text-sm block"
            onDoubleClick={(e) => {
              e.stopPropagation();
              handleStartRename();
            }}
          >
            {displayName}
          </span>
        )}
      </div>

      {/* Cell 6: Kebab menu — stopPropagation prevents row click when opening menu */}
      {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events */}
      <div onClick={(e) => e.stopPropagation()}>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              data-kebab-trigger=""
              aria-label={t('stackRow.kebabTrigger', {
                defaultValue: 'Layer options for {{name}}',
                name: displayName,
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
            className="w-56"
            onCloseAutoFocus={(e) => {
              if (skipCloseAutoFocusRef.current) {
                e.preventDefault();
                skipCloseAutoFocusRef.current = false;
              }
            }}
          >
            {/* Source info — read-only dataset metadata. Per v3 design,
                Source is no longer a panel section; the layer-row (···) menu
                is the right home for read-only layer-scoped info. */}
            {(() => {
              const caps = getLayerCapabilities(layer);
              const showSource =
                !!layer.dataset_name
                || layer.dataset_feature_count != null
                || !!layer.dataset_geometry_type;
              if (!showSource) return null;
              const columnCount = layer.dataset_column_info?.length ?? 0;
              return (
                <>
                  <DropdownMenuLabel className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground px-2 pt-2 pb-1">
                    {t('layerEditor.source.menuLabel', { defaultValue: 'Source' })}
                  </DropdownMenuLabel>
                  <div className="px-2 pb-2 text-xs space-y-1" data-testid="stack-row-kebab-source">
                    {layer.dataset_name && (
                      <div className="flex justify-between gap-2 min-w-0">
                        <span className="text-muted-foreground shrink-0">
                          {t('layerEditor.source.dataset', { defaultValue: 'Dataset' })}
                        </span>
                        <span className="truncate font-medium">{layer.dataset_name}</span>
                      </div>
                    )}
                    {layer.dataset_feature_count != null && (
                      <div className="flex justify-between gap-2">
                        <span className="text-muted-foreground">
                          {t('layerEditor.source.features', { defaultValue: 'Features' })}
                        </span>
                        <span className="font-medium">{layer.dataset_feature_count.toLocaleString()}</span>
                      </div>
                    )}
                    <div className="flex justify-between gap-2">
                      <span className="text-muted-foreground">
                        {t('layerEditor.source.type', { defaultValue: 'Type' })}
                      </span>
                      <span className="font-medium">{caps.kind}</span>
                    </div>
                    {layer.dataset_geometry_type && (
                      <div className="flex justify-between gap-2 min-w-0">
                        <span className="text-muted-foreground shrink-0">
                          {t('layerEditor.source.geometry', { defaultValue: 'Geometry' })}
                        </span>
                        <span className="truncate font-medium">{layer.dataset_geometry_type}</span>
                      </div>
                    )}
                    {columnCount > 0 && (
                      <div className="flex justify-between gap-2">
                        <span className="text-muted-foreground">
                          {t('layerEditor.source.columns', { defaultValue: 'Columns' })}
                        </span>
                        <span className="font-medium">{columnCount}</span>
                      </div>
                    )}
                  </div>
                  <DropdownMenuSeparator />
                </>
              );
            })()}
            <DropdownMenuItem
              onSelect={() => {
                // Let the menu close; the editing useEffect's rAF focus +
                // select runs once Radix unmounts the menu. onCloseAutoFocus
                // skips restoreFocus so the input keeps focus.
                skipCloseAutoFocusRef.current = true;
                handleStartRename();
              }}
            >
              {t('stackRow.kebabRenameLayer', { defaultValue: 'Rename layer' })}
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={() => {
                onDuplicate(layer.id);
              }}
            >
              {t('stackRow.kebabDuplicate', { defaultValue: 'Duplicate' })}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive focus:text-destructive"
              onSelect={() => {
                setConfirmingDelete(true);
              }}
            >
              {t('stackRow.kebabDeleteLayer', { defaultValue: 'Delete layer' })}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            {parentGroupId ? (
              // Layer is already inside a group: show "Move out of group"
              <DropdownMenuItem onSelect={() => onMoveLayerOutOfGroup?.(layer.id)}>
                {t('stackRow.kebabMoveOutOfGroup', { defaultValue: 'Move out of group' })}
              </DropdownMenuItem>
            ) : (
              <>
                <DropdownMenuLabel className="text-xs font-normal text-muted-foreground px-2 py-1">
                  {t('stackRow.kebabAddToGroup', { defaultValue: 'Add to group…' })}
                </DropdownMenuLabel>
                {(existingFolderGroups).map((g) => (
                  <DropdownMenuItem
                    key={g.id}
                    onSelect={() => onAddToGroup?.(layer.id, g.id)}
                  >
                    ▸ {g.name}
                  </DropdownMenuItem>
                ))}
                <DropdownMenuItem
                  className="text-primary"
                  onSelect={() => onCreateGroupWithLayer?.(layer.id)}
                >
                  {t('folderGroup.newGroupItem', { defaultValue: '＋ New group…' })}
                </DropdownMenuItem>
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>

    {/* Inline alertdialog confirm — appears below the row when kebab Delete is clicked */}
    {confirmingDelete && (
      // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions
      <div
        role="alertdialog"
        aria-label={t('layerEditor.confirmDelete.message', { defaultValue: 'Are you sure? This cannot be undone.' })}
        className="mx-2 mb-2 flex flex-col gap-2 p-3 bg-destructive/10 rounded-md"
        onClick={(e) => e.stopPropagation()}
      >
        <p className="text-sm text-destructive">
          {t('layerEditor.confirmDelete.message', { defaultValue: 'Are you sure? This cannot be undone.' })}
        </p>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="destructive"
            onClick={() => {
              onRemove(layer.id);
              setConfirmingDelete(false);
            }}
          >
            {t('layerEditor.confirmDelete.delete', { defaultValue: 'Delete' })}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setConfirmingDelete(false)}
            // eslint-disable-next-line jsx-a11y/no-autofocus -- moves focus to safe action so Enter dismisses, not destroys (AUD-09)
            autoFocus
          >
            {t('layerEditor.confirmDelete.keep', { defaultValue: 'Keep layer' })}
          </Button>
        </div>
      </div>
    )}
    </>
  );
});
