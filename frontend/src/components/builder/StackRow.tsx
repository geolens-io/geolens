import { memo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { DraggableAttributes, DraggableSyntheticListeners } from '@dnd-kit/core';
import { Eye, EyeOff, GripVertical, MoreVertical } from 'lucide-react';
import { Slider } from '@/components/ui/slider';
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
  onOpacityChange: (layerId: string, opacity: number) => void;
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
  /** When non-null, the layer is inside a group — "Move out of group" replaces the sub-flow */
  parentGroupId?: string | null;
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
        className="flex items-center justify-center h-[22px] w-[22px] rounded-sm bg-[--type-raster-bg] text-[--type-raster] text-xs font-medium"
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
  onOpacityChange,
  onRemove,
  onRename,
  onDuplicate,
  existingFolderGroups = [],
  onAddToGroup,
  onCreateGroupWithLayer,
  onMoveLayerOutOfGroup,
  parentGroupId = null,
}: StackRowProps) {
  const { t } = useTranslation('builder');
  const [editing, setEditing] = useState(false);
  const [nameValue, setNameValue] = useState<string>('');
  const escapeRef = useRef(false);
  const committingRef = useRef(false);

  const displayName = layer.display_name ?? layer.dataset_name;
  const opacity = typeof layer.opacity === 'number' && Number.isFinite(layer.opacity) ? layer.opacity : 1;

  function handleStartRename() {
    setNameValue(displayName);
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
    onRename(layer.id, nameValue.trim() || null);
    // committingRef stays true during the synchronous blur triggered by setEditing(false);
    // reset it async so it does not block a subsequent genuine focus+blur cycle.
    requestAnimationFrame(() => { committingRef.current = false; });
  }

  function handleRowClick(_e: React.MouseEvent) {
    onSelectLayer(layer.id);
  }

  return (
    <div
      id={`stack-row-${layer.id}`}
      role="option"
      aria-selected={selected}
      tabIndex={0}
      className={cn(
        'group/row grid grid-cols-[16px_14px_22px_22px_1fr_60px_22px] gap-2 items-center py-2 px-2 cursor-pointer select-none',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
        // Row states
        !selected && !isDragging && 'hover:bg-[var(--surface-2,theme(colors.accent.DEFAULT))]',
        selected && 'bg-[var(--primary-50,theme(colors.accent.DEFAULT))] shadow-[inset_2px_0_0_var(--primary)]',
        isDragging && 'opacity-40 bg-[var(--surface-2,theme(colors.accent.DEFAULT))] scale-[0.98]',
      )}
      onClick={handleRowClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelectLayer(layer.id);
        }
      }}
    >
      {/* Cell 1: Caret (hidden for non-group rows) */}
      <span
        aria-hidden="true"
        style={{ visibility: 'hidden' }}
        className="text-xs text-muted-foreground"
      >
        ▸
      </span>

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
        onPointerDown={(e) => e.stopPropagation()}
        onClick={(e) => e.stopPropagation()}
      >
        <GripVertical className="h-3.5 w-3.5" aria-hidden="true" />
      </button>

      {/* Cell 3: Eye visibility toggle */}
      <button
        type="button"
        aria-label={t('stackRow.toggleVisibility', {
          defaultValue: 'Toggle visibility for {{name}}',
          name: displayName,
        })}
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

      {/* Cell 6: Opacity slider — stopPropagation prevents row click on slider drag */}
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/click-events-have-key-events */}
      <div
        className="flex items-center"
        onPointerDown={(e) => e.stopPropagation()}
        onClick={(e) => e.stopPropagation()}
      >
        <Slider
          aria-label={t('stackRow.opacitySlider', {
            defaultValue: 'Opacity for {{name}}',
            name: displayName,
          })}
          aria-valuetext={`${Math.round(opacity * 100)}%`}
          value={[opacity]}
          min={0}
          max={1}
          step={0.05}
          className="w-[60px]"
          onValueChange={([value]) => {
            onOpacityChange(layer.id, Number((value ?? opacity).toFixed(2)));
          }}
        />
      </div>

      {/* Cell 7: Kebab menu — stopPropagation prevents row click when opening menu */}
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/click-events-have-key-events */}
      <div onClick={(e) => e.stopPropagation()}>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              aria-label={t('stackRow.kebabTrigger', {
                defaultValue: 'Layer options for {{name}}',
                name: displayName,
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
            <DropdownMenuItem
              onSelect={(_e) => {
                _e.preventDefault(); // keep menu open while we set editing=true
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
                onRemove(layer.id);
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
  );
});
