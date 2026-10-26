/* eslint-disable jsx-a11y/no-static-element-interactions, jsx-a11y/no-noninteractive-tabindex -- stack rows are composite focus targets with nested controls, so role="button"/listbox roles are intentionally avoided. */
import { memo, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ClipboardPaste,
  Copy,
  CopyPlus,
  Crosshair,
  ExternalLink,
  Eye,
  EyeOff,
  FlaskConical,
  Folder,
  FolderMinus,
  FolderPlus,
  MoreVertical,
  Pencil,
  Plus,
  Table2,
  Trash2,
  Type,
} from 'lucide-react';
import { Checkbox } from '@/components/ui/checkbox';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { LayerTypeIcon } from '@/components/map/layer-icons';
import { legendFacts } from '@/components/map/legend-facts';
import { isAnalysableLayer } from '@/components/builder/analysis-eligibility';
import { canOpenAttributeTable, getLayerCapabilities } from '@/lib/layer-capabilities';
import { cn } from '@/lib/utils';
import { semanticBadgeColors } from '@/lib/status-colors';
import {
  DragGripButton,
  InlineDeleteConfirm,
  STACK_ROW_GRID,
  rowStateClasses,
  useKebabContextMenu,
  type DragHandleProps,
} from '@/components/builder/row-chrome';
import { useInlineRename } from '@/components/builder/useInlineRename';
import type { MapLayerResponse } from '@/types/api';
import { formatNumber } from '@/lib/format';

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
  // Kebab authoring actions.
  /** Frames the map to this layer's extent. */
  onZoomToLayer?: (id: string) => void;
  /** Opens the Analysis panel prefilled with this layer. Rendered
   *  only for analysable (vector dataset) layers. */
  onAnalyzeLayer?: (id: string) => void;
  /** Opens the read-only attribute-table drawer for this layer. Rendered
   *  only for layers whose dataset carries a data table. */
  onOpenAttributeTable?: (id: string) => void;
  /** Stashes this layer's geometry-compatible style in the session clipboard. */
  onCopyStyle?: (id: string) => void;
  /** Applies the clipboard style to this layer; disabled when !canPasteStyle. */
  onPasteStyle?: (id: string) => void;
  /** True when a style is copied AND its geometry class matches THIS row's layer. */
  canPasteStyle?: boolean;
  /** Existing user folder groups, used for the "Add to group…" sub-flow */
  existingFolderGroups?: Array<{ id: string; name: string }>;
  /** Called when user selects an existing group from the sub-list */
  onAddToGroup?: (layerId: string, groupId: string) => void;
  /** Called when user selects "＋ New group…" */
  onCreateGroupWithLayer?: (layerId: string) => void;
  /** Called when user selects "Move out of group" (layer is already in a group) */
  onMoveLayerOutOfGroup?: (layerId: string) => void;
  /** Returns whether the move happened, so boundary no-ops stay silent;
   *  void is treated as moved for older callers. */
  onKeyboardReorder?: (layerId: string, direction: 'up' | 'down') => boolean | void;
  /**
   * Routes reorder-mode announcements into the builder's shared aria-live
   * region, as the pointer drag path does for pickup, position and drop.
   */
  onAnnounce?: (text: string) => void;
  /** When non-null, the layer is inside a group — "Move out of group" replaces the sub-flow */
  parentGroupId?: string | null;
  // Multi-selection props
  isMultiSelected?: boolean;
  isMultiSelectionActive?: boolean;
  onCmdClick?: (id: string) => void;
  onShiftClick?: (id: string) => void;
  onCheckboxClick?: (id: string) => void;
  // Entry animation — set true immediately after add, cleared after 200ms
  isFresh?: boolean;
  // "Copy N of M" duplicate disambiguation label, computed
  // per-layer by UnifiedStackPanel from map-stack's shared helper. Null = not a
  // duplicate; render nothing.
  disambiguationLabel?: string | null;
  /**
   * Non-null when this row is the LAST child of the named group: deleting it or
   * moving it out also removes the group, so the delete confirm says so and
   * "Move out of group" gains a confirm.
   */
  dissolvesGroupName?: string | null;
  // True when this layer's dataset would be silently filtered out for some of
  // the map's audience. UnifiedStackPanel computes it from
  // isLayerHiddenFromMapAudience and, on a restricted map, the server's answer.
  audienceHidden?: boolean;
  // True when this DEM has its 2D relief overlay turned off
  // (render_mode 'terrain') and is NOT the active 3D terrain source, so it
  // currently paints nothing even though its eye is on. Computed per-layer by
  // MapBuilderPage (needs terrain_config). Recoverable by re-enabling Hillshade
  // or binding terrain — the badge just keeps the eye-on row honest.
  drawsNothing?: boolean;
}

function TypeIcon({ layer }: { layer: MapLayerResponse }) {
  return <LayerTypeIcon layer={layer} iconId={layer.id} />;
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
  onZoomToLayer,
  onAnalyzeLayer,
  onOpenAttributeTable,
  onCopyStyle,
  onPasteStyle,
  canPasteStyle = false,
  existingFolderGroups = [],
  onAddToGroup,
  onCreateGroupWithLayer,
  onMoveLayerOutOfGroup,
  onKeyboardReorder,
  onAnnounce,
  parentGroupId = null,
  isMultiSelected = false,
  isMultiSelectionActive = false,
  onCmdClick,
  onShiftClick,
  onCheckboxClick,
  isFresh = false,
  disambiguationLabel = null,
  dissolvesGroupName = null,
  audienceHidden = false,
  drawsNothing = false,
}: StackRowProps) {
  const { t } = useTranslation('builder');
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  // "Move out of group" on a group's LAST child dissolves the named group,
  // which deserves the same lightweight inline confirm the delete path uses.
  const [confirmingMoveOut, setConfirmingMoveOut] = useState(false);
  const [keyboardReorderActive, setKeyboardReorderActive] = useState(false);
  const kebabMenu = useKebabContextMenu();

  const displayName = layer.display_name ?? layer.dataset_name;

  // Shared inline-rename state machine, also used by FolderGroupRow.
  const {
    editing,
    nameValue,
    inputRef,
    inputHandlers,
    startRename,
    skipCloseAutoFocusRef,
    handleMenuCloseAutoFocus,
  } = useInlineRename({
    value: displayName,
    onCommit: (next) => onRename(layer.id, next),
    // Commit/cancel unmount the focused input; hand focus back to the row,
    // matching the delete-confirm's focus return.
    restoreFocus: () => document.getElementById(`stack-row-${layer.id}`)?.focus(),
  });

  // Derived label indicator. LabelConfig has no `enabled` field; `column` being
  // set is the sole signal. Heatmap suppresses label rendering on the map, so
  // suppress the indicator too. Symbol mode does NOT suppress labels: it
  // renders the text consolidated in the primary symbol layer (symbol-adapter
  // symbolLayout).
  const renderMode = (layer.style_config as Record<string, unknown> | null | undefined)?.render_mode as string | undefined;
  const hasLabels = !!layer.label_config?.column && renderMode !== 'heatmap';

  // Name the styled column: the icon's category bands alone can't say what the colours mean.
  const categories = legendFacts(layer)?.classes?.find((entry) => entry.mode === 'categorical');
  const categoricalSummary = categories
    ? t('stackRow.categoricalSummary', {
        column: layer.style_config?.column || categories.title,
        count: categories.items.filter((item) => !item.other).length,
        defaultValue: '{{column}} · {{count}} categories',
      })
    : null;

  function handleDragHandleKeyDown(e: KeyboardEvent<HTMLButtonElement>) {
    const isToggleKey = e.key === ' ' || e.key === 'Spacebar' || e.key === 'Enter';
    if (isToggleKey) {
      e.preventDefault();
      e.stopPropagation();
      // Mirror the pointer path's pickup/drop announcements. NOT the shared
      // dragPickup string: its "Escape to cancel" describes the real drag path,
      // where Escape reverts, whereas here every arrow applies immediately and
      // Escape only exits the mode.
      onAnnounce?.(
        keyboardReorderActive
          ? t('a11y.reorderDropped', {
              defaultValue: '{{name}} dropped.',
              name: displayName,
            })
          : t('a11y.reorderArmed', {
              defaultValue:
                'Reorder mode on for {{name}}. Arrow keys move the layer; Enter, Space, or Escape finishes.',
              name: displayName,
            }),
      );
      setKeyboardReorderActive(!keyboardReorderActive);
      return;
    }

    if (e.key === 'Escape' && keyboardReorderActive) {
      e.preventDefault();
      e.stopPropagation();
      // Arrows have already applied their moves, so "Drop cancelled" would
      // falsely promise a revert; Escape only exits the mode, like Enter/Space.
      onAnnounce?.(
        t('a11y.reorderDropped', {
          defaultValue: '{{name}} dropped.',
          name: displayName,
        }),
      );
      setKeyboardReorderActive(false);
      return;
    }

    if (!keyboardReorderActive || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return;
    e.preventDefault();
    e.stopPropagation();
    const direction = e.key === 'ArrowUp' ? 'up' : 'down';
    const moved = onKeyboardReorder?.(layer.id, direction);
    // A boundary ArrowUp/Down is a no-op; announcing a move there would give
    // screen-reader users false confirmation.
    if (moved !== false) {
      onAnnounce?.(
        t(direction === 'up' ? 'a11y.reorderMovedUp' : 'a11y.reorderMovedDown', {
          defaultValue:
            direction === 'up' ? '{{name}} moved up.' : '{{name}} moved down.',
          name: displayName,
        }),
      );
    }
  }

  // Modifier-aware click handler
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
    {/* visuallySelected is true for single-select focus OR multi-select membership */}
    <div
      id={`stack-row-${layer.id}`}
      data-selected={selected || isMultiSelected ? 'true' : undefined}
      aria-current={selected || isMultiSelected ? 'true' : undefined}
      tabIndex={0}
      className={cn(
        // Explicit cursor-pointer + hover tint on the row body so the hover
        // affordance covers the whole row, not just child controls. Shared grid
        // template + state classes.
        'group/row grid', STACK_ROW_GRID, 'gap-2 items-center py-2 px-2 cursor-pointer select-none',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
        // Row states — unified: either single-selection focus OR multi-selection shows primary tint
        rowStateClasses({ selected: selected || isMultiSelected, isDragging }),
        // Entry animation — animate-in/fade-in from tw-animate-css
        isFresh && 'animate-in fade-in duration-[--motion-fast]',
      )}
      onClick={handleRowClick}
      onContextMenu={kebabMenu.onContextMenu}
      onKeyDown={(e) => {
        if (kebabMenu.handleContextMenuKey(e)) return;
        // WCAG 2.1.1: only keys aimed at the row container itself belong to the
        // row. Without this guard the Enter/Space preventDefault below would
        // cancel native button activation on every descendant (eye toggle,
        // kebab) and swallow spaces typed into the rename input. Placed AFTER
        // the context-menu branch so Shift+F10 still opens the kebab from a
        // focused descendant.
        if (e.target !== e.currentTarget) return;
        if (e.key === 'Enter') {
          e.preventDefault();
          onSelectLayer(layer.id);
        }
        if (e.key === ' ') {
          e.preventDefault();
          onCmdClick?.(layer.id); // Space = Cmd-click (toggles multi-selection)
        }
        // Escape with the delete confirm pending dismisses the
        // confirm (consumed) instead of falling through to ancestor Escape
        // handlers. The confirm handles its own Escape when focus is inside it;
        // this covers focus resting on the row.
        if (e.key === 'Escape' && (confirmingDelete || confirmingMoveOut)) {
          e.preventDefault();
          e.stopPropagation();
          setConfirmingDelete(false);
          setConfirmingMoveOut(false);
        }
      }}
    >
      {/* Cell 1: Caret column — hidden span at rest; Checkbox during multi-selection mode */}
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

      {/* Cell 2: Grip handle (shared DragGripButton).
          Reveal the reorder grip on coarse-pointer/touch. */}
      <DragGripButton
        dragHandleProps={dragHandleProps}
        ariaLabel={t('stackRow.dragHandle', {
          defaultValue: 'Drag to reorder {{name}}',
          name: displayName,
        })}
        touchReveal
        // dnd-kit drives aria-pressed=true through `attributes`
        // while its sortable is active; the explicit prop must not report
        // unpressed during a real pointer drag.
        ariaPressed={keyboardReorderActive || isDragging}
        onKeyDown={handleDragHandleKeyDown}
        onBlur={() => setKeyboardReorderActive(false)}
      />

      {/* Cell 3: Eye visibility toggle. Aria-pressed reflects the
          current visible state so screen readers announce it as a toggle. */}
      <button
        type="button"
        aria-label={t('stackRow.toggleVisibility', {
          defaultValue: 'Toggle visibility for {{name}}',
          name: displayName,
        })}
        aria-pressed={layer.visible}
        className="flex items-center justify-center h-[22px] w-[22px] rounded-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
            // The input needs an accessible name; mirrors FolderGroupRow's.
            aria-label={t('stackRow.renameInputLabel', { defaultValue: 'Layer name' })}
            placeholder={t('stackRow.renameInputLabel', { defaultValue: 'Layer name' })}
            data-testid="stack-row-rename-input"
            className="h-6 w-full min-w-0 border-b border-primary bg-transparent text-sm outline-none focus:ring-1 focus:ring-ring"
            value={nameValue}
            {...inputHandlers}
            // eslint-disable-next-line jsx-a11y/no-autofocus -- triggered by explicit rename action
            autoFocus
          />
        ) : (
          <div className="min-w-0 flex items-center gap-1">
            <span
              title={displayName}
              className="truncate text-sm min-w-0"
              onDoubleClick={(e) => {
                e.stopPropagation();
                startRename();
              }}
            >
              {displayName}
            </span>
            {hasLabels && (
              <span
                title={t('stackRow.labelsIndicator', { column: layer.label_config!.column, defaultValue: 'Labels on: {{column}}' })}
                className="shrink-0 inline-flex items-center justify-center h-3.5 w-3.5 rounded-sm text-muted-foreground"
                data-testid="label-indicator"
              >
                <Type className="h-3 w-3" aria-hidden="true" />
                <span className="sr-only">{t('stackRow.labelsIndicator', { column: layer.label_config!.column, defaultValue: 'Labels on: {{column}}' })}</span>
              </span>
            )}
            {/* Categorical subtitle, inline like the badges so the row
                height never changes. It gives up its width before the name. */}
            {categoricalSummary && (
              <span
                title={categoricalSummary}
                data-testid="stack-row-categories"
                className="min-w-0 max-w-[45%] shrink-[1000] truncate text-2xs text-muted-foreground"
              >
                {categoricalSummary}
              </span>
            )}
            {/* Live duplicate-disambiguation badge. The label ("Copy N of M")
                is data-driven so it is rendered verbatim; the hover/sr-only
                text goes through t(). Mirrors the warning-tone badge in the
                derived stack (map-stack.ts layerBadges). */}
            {/* Badges are shrink-0 and would starve the truncating title span
                to ~2 chars at sidebar width, so cap each at 45% of the row and
                truncate inside; the title=/tooltip keeps the full text
                discoverable. */}
            {disambiguationLabel && (
              <span
                title={t('stackRow.disambiguation', { label: disambiguationLabel, defaultValue: '{{label}}' })}
                data-testid="stack-row-disambiguation"
                className={cn('min-w-0 max-w-[45%] inline-flex items-center rounded-sm px-1 text-2xs font-medium leading-tight', semanticBadgeColors.warning)}
              >
                <span className="truncate">{disambiguationLabel}</span>
                <span className="sr-only">{t('stackRow.disambiguation', { label: disambiguationLabel, defaultValue: '{{label}}' })}</span>
              </span>
            )}
            {/* Audience-visibility mismatch — this layer's dataset
                would be silently filtered out for the map's public/shared
                audience (e.g. a private dataset added to a public map). */}
            {audienceHidden && (
              <span
                title={t('stackRow.audienceHidden', { defaultValue: "Hidden from this map's viewers" })}
                data-testid="stack-row-audience-hidden"
                className={cn('min-w-0 max-w-[45%] inline-flex items-center rounded-sm px-1 text-2xs font-medium leading-tight', semanticBadgeColors.warning)}
              >
                <span className="truncate">
                  {t('stackRow.audienceHidden', { defaultValue: "Hidden from this map's viewers" })}
                </span>
              </span>
            )}
            {/* DEM overlay off + not the terrain source → paints
                nothing despite the eye being on. Keep the row honest. */}
            {drawsNothing && (
              <span
                title={t('stackRow.drawsNothing', { defaultValue: 'Not shown — enable Hillshade or 3D terrain' })}
                data-testid="stack-row-draws-nothing"
                className={cn('min-w-0 max-w-[45%] inline-flex items-center rounded-sm px-1 text-2xs font-medium leading-tight', semanticBadgeColors.warning)}
              >
                <span className="truncate">
                  {t('stackRow.drawsNothing', { defaultValue: 'Not shown — enable Hillshade or 3D terrain' })}
                </span>
              </span>
            )}
          </div>
        )}
      </div>

      {/* Cell 6: Kebab menu — stopPropagation prevents row click when opening menu */}
      {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events */}
      <div onClick={(e) => e.stopPropagation()}>
        <DropdownMenu open={kebabMenu.open} onOpenChange={kebabMenu.onOpenChange}>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              data-kebab-trigger=""
              // Reveal the kebab on coarse-pointer/touch.
              data-touch-reveal=""
              aria-label={t('stackRow.kebabTrigger', {
                defaultValue: 'Layer options for {{name}}',
                name: displayName,
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
            className="w-56"
            onCloseAutoFocus={handleMenuCloseAutoFocus}
          >
            {/* Source info: read-only dataset metadata. The layer-row (···)
                menu is the home for read-only layer-scoped info. */}
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
                  <DropdownMenuLabel className="text-2xs uppercase tracking-[0.06em] text-muted-foreground px-2 pt-2 pb-1">
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
                        <span className="font-medium">{formatNumber(layer.dataset_feature_count)}</span>
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
            {/* Navigable follow-up to the Source block: a path from the builder
                to the dataset page (where the audienceHidden badge's
                dataset-visibility fix lives). New tab on purpose: in-place
                navigation would trip the unsaved-changes guard, matching the
                "View as viewer" precedent. A real <a> so middle-click/cmd-click
                work. */}
            {layer.dataset_id && (
              <>
                <DropdownMenuItem asChild data-testid="kebab-view-dataset">
                  <a
                    href={`/datasets/${layer.dataset_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <ExternalLink className="h-3.5 w-3.5 me-2" aria-hidden="true" />
                    {t('layerItem.openDataset', { defaultValue: 'Open dataset detail' })}
                  </a>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
              </>
            )}
            <DropdownMenuItem
              onSelect={() => {
                // Let the menu close; the hook's rAF focus + select runs once
                // Radix unmounts the menu. onCloseAutoFocus skips restoreFocus so
                // the input keeps focus.
                skipCloseAutoFocusRef.current = true;
                startRename();
              }}
            >
              {/* Every kebab item carries an icon so the menu doesn't read as
                  ragged. */}
              <Pencil className="h-3.5 w-3.5 me-2" aria-hidden="true" />
              {t('stackRow.kebabRenameLayer', { defaultValue: 'Rename layer' })}
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={() => {
                onDuplicate(layer.id);
              }}
            >
              <CopyPlus className="h-3.5 w-3.5 me-2" aria-hidden="true" />
              {t('stackRow.kebabDuplicate', { defaultValue: 'Duplicate' })}
            </DropdownMenuItem>
            {/* Zoom-to-extent + copy/paste style.
                Paste is disabled when no compatible style is copied for this
                row's geometry (canPasteStyle is computed per-row upstream). */}
            <DropdownMenuSeparator />
            <DropdownMenuItem
              data-testid="kebab-zoom-to-layer"
              onSelect={() => onZoomToLayer?.(layer.id)}
            >
              <Crosshair className="h-3.5 w-3.5 me-2" aria-hidden="true" />
              {t('stackRow.kebabZoomToLayer', { defaultValue: 'Zoom to layer' })}
            </DropdownMenuItem>
            {/* Jump straight into Analysis targeting this layer.
                Gated on the panel's own eligibility predicate so a raster or
                DEM row doesn't offer an entry the panel would ignore. */}
            {onAnalyzeLayer && isAnalysableLayer(layer) && (
              <DropdownMenuItem
                data-testid="kebab-analyze-layer"
                onSelect={() => onAnalyzeLayer(layer.id)}
              >
                <FlaskConical className="h-3.5 w-3.5 me-2" aria-hidden="true" />
                {t('stackRow.kebabAnalyzeLayer', { defaultValue: 'Analyze this layer' })}
              </DropdownMenuItem>
            )}
            {/* Read-only data inspection, like Analyze: offered only where a
                table makes sense (vector dataset with a data table), so a
                raster, DEM or tileset row never opens a drawer the rows
                endpoint would refuse. */}
            {onOpenAttributeTable && canOpenAttributeTable(layer) && (
              <DropdownMenuItem
                data-testid="kebab-open-attribute-table"
                onSelect={() => onOpenAttributeTable(layer.id)}
              >
                <Table2 className="h-3.5 w-3.5 me-2" aria-hidden="true" />
                {t('stackRow.kebabAttributeTable', { defaultValue: 'Open attribute table' })}
              </DropdownMenuItem>
            )}
            <DropdownMenuItem
              data-testid="kebab-copy-style"
              onSelect={() => onCopyStyle?.(layer.id)}
            >
              <Copy className="h-3.5 w-3.5 me-2" aria-hidden="true" />
              {t('stackRow.kebabCopyStyle', { defaultValue: 'Copy style' })}
            </DropdownMenuItem>
            <DropdownMenuItem
              data-testid="kebab-paste-style"
              disabled={!canPasteStyle}
              onSelect={() => {
                if (canPasteStyle) onPasteStyle?.(layer.id);
              }}
            >
              <ClipboardPaste className="h-3.5 w-3.5 me-2" aria-hidden="true" />
              {/* Disabled items state their reason inline (tooltips
                  don't fire on disabled elements). */}
              <span className="flex flex-col items-start">
                {t('stackRow.kebabPasteStyle', { defaultValue: 'Paste style' })}
                {!canPasteStyle && (
                  <span className="text-2xs text-muted-foreground">
                    {t('stackRow.kebabPasteStyleHint', { defaultValue: 'Copy a style from a matching layer first' })}
                  </span>
                )}
              </span>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive focus:text-destructive"
              onSelect={() => {
                setConfirmingDelete(true);
              }}
            >
              <Trash2 className="h-3.5 w-3.5 me-2" aria-hidden="true" />
              {t('stackRow.kebabDeleteLayer', { defaultValue: 'Delete layer' })}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            {parentGroupId ? (
              // Layer is already inside a group: show "Move out of group".
              // Moving the LAST child out dissolves the named group, so route
              // through the inline confirm instead of destroying it silently.
              <DropdownMenuItem
                onSelect={() => {
                  if (dissolvesGroupName) setConfirmingMoveOut(true);
                  else onMoveLayerOutOfGroup?.(layer.id);
                }}
              >
                <FolderMinus className="h-3.5 w-3.5 me-2" aria-hidden="true" />
                {t('stackRow.kebabMoveOutOfGroup', { defaultValue: 'Move out of group' })}
              </DropdownMenuItem>
            ) : (
              // Submenu instead of a flat inline list: the group list grows
              // unbounded with many groups and would push Delete off-screen.
              <DropdownMenuSub>
                <DropdownMenuSubTrigger data-testid="kebab-add-to-group">
                  <FolderPlus className="h-3.5 w-3.5 me-2" aria-hidden="true" />
                  {t('stackRow.kebabAddToGroup', { defaultValue: 'Add to group…' })}
                </DropdownMenuSubTrigger>
                <DropdownMenuSubContent>
                  {(existingFolderGroups).map((g) => (
                    <DropdownMenuItem
                      key={g.id}
                      onSelect={() => onAddToGroup?.(layer.id, g.id)}
                    >
                      <Folder className="h-3.5 w-3.5 me-2" aria-hidden="true" />
                      {g.name}
                    </DropdownMenuItem>
                  ))}
                  {existingFolderGroups.length > 0 && <DropdownMenuSeparator />}
                  <DropdownMenuItem
                    className="text-primary"
                    onSelect={() => onCreateGroupWithLayer?.(layer.id)}
                  >
                    <Plus className="h-3.5 w-3.5 me-2" aria-hidden="true" />
                    {t('folderGroup.newGroupItem', { defaultValue: 'New group…' })}
                  </DropdownMenuItem>
                </DropdownMenuSubContent>
              </DropdownMenuSub>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>

    {/* Shared inline confirm — appears below the row when kebab Delete is clicked */}
    {confirmingDelete && (
      <InlineDeleteConfirm
        confirmId={`confirm-delete-${layer.id}`}
        // Deleting a group's last child also removes the named group; the
        // confirm must promise the whole effect.
        message={
          dissolvesGroupName
            ? t('layerEditor.confirmDelete.messageDissolvesGroup', {
                group: dissolvesGroupName,
                defaultValue:
                  'Are you sure? This cannot be undone, and the group "{{group}}" will also be removed.',
              })
            : t('layerEditor.confirmDelete.message', { defaultValue: 'Are you sure? This cannot be undone.' })
        }
        confirmLabel={t('layerEditor.confirmDelete.delete', { defaultValue: 'Delete' })}
        cancelLabel={t('layerEditor.confirmDelete.keep', { defaultValue: 'Keep layer' })}
        onConfirm={() => {
          onRemove(layer.id);
          setConfirmingDelete(false);
        }}
        onCancel={() => {
          setConfirmingDelete(false);
          // The confirm owned focus (autofocused Cancel button), so
          // dismissing it must hand focus back to the row instead of <body>.
          document.getElementById(`stack-row-${layer.id}`)?.focus();
        }}
      />
    )}

    {/* Confirm before "Move out of group" dissolves the named group (last-child
        case); same shared inline confirm as delete. */}
    {confirmingMoveOut && (
      <InlineDeleteConfirm
        confirmId={`confirm-move-out-${layer.id}`}
        message={t('stackRow.moveOutConfirmMessage', {
          group: dissolvesGroupName,
          defaultValue:
            'Move this layer out of "{{group}}"? The empty group will also be removed.',
        })}
        confirmLabel={t('stackRow.moveOutConfirmAction', { defaultValue: 'Move out' })}
        cancelLabel={t('stackRow.moveOutConfirmCancel', { defaultValue: 'Keep in group' })}
        onConfirm={() => {
          onMoveLayerOutOfGroup?.(layer.id);
          setConfirmingMoveOut(false);
        }}
        onCancel={() => {
          setConfirmingMoveOut(false);
          // Hand focus back to the row instead of <body>.
          document.getElementById(`stack-row-${layer.id}`)?.focus();
        }}
      />
    )}
    </>
  );
});
