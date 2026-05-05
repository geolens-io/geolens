import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  DndContext,
  closestCenter,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import type { DragEndEvent } from '@dnd-kit/core';
import {
  SortableContext,
  verticalListSortingStrategy,
  sortableKeyboardCoordinates,
  arrayMove,
  useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical, X, Plus } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { extractPlaceholders, validatePlaceholders } from '@/lib/popup-template';
import type { PopupConfig } from '@/types/api';

interface PopupConfigEditorProps {
  columns: { name: string; type: string }[];
  popupConfig: PopupConfig | null;
  onPopupChange: (config: PopupConfig | null) => void;
}

const DEBOUNCE_MS = 250;
const MAX_EXPRESSION_LENGTH = 500;

function SortableField({
  name,
  onRemove,
  removeLabel,
  reorderLabel,
}: {
  name: string;
  onRemove: () => void;
  removeLabel: string;
  reorderLabel: string;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: name,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="flex items-center gap-1.5 px-2 py-1 rounded bg-background border text-xs"
    >
      <button
        type="button"
        className="cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground"
        {...attributes}
        {...listeners}
        aria-label={reorderLabel}
      >
        <GripVertical className="h-3 w-3" />
      </button>
      <span className="flex-1 font-mono text-[11px] truncate">{name}</span>
      <button
        type="button"
        onClick={onRemove}
        className="text-muted-foreground hover:text-destructive"
        aria-label={removeLabel}
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  );
}

export function PopupConfigEditor({ columns, popupConfig, onPopupChange }: PopupConfigEditorProps) {
  const { t } = useTranslation('builder');
  // Popups are enabled by default — null/undefined config behaves as enabled.
  // Click handler in BuilderMap mirrors this with `enabled !== false`.
  const isOn = popupConfig?.enabled ?? true;
  const expression = popupConfig?.expression ?? '';
  const visibleFields = popupConfig?.visible_fields ?? null;

  // Debounced expression — drives validation rendering (red border + helper text).
  // The parent already gets `expression` synchronously via `update()`, so we don't
  // need a second mirror of the input value — `expression` itself is the controlled value.
  const [debouncedExpr, setDebouncedExpr] = useState(expression);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (debounceRef.current !== null) clearTimeout(debounceRef.current);
    };
  }, []);

  const columnNames = useMemo(() => columns.map((c) => c.name), [columns]);

  const placeholders = useMemo(() => extractPlaceholders(debouncedExpr), [debouncedExpr]);
  const validation = useMemo(
    () => validatePlaceholders(placeholders, columnNames),
    [placeholders, columnNames],
  );

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const mode: 'all' | 'custom' = visibleFields === null ? 'all' : 'custom';
  const usedFields = useMemo(() => new Set(visibleFields ?? []), [visibleFields]);
  const availableFields = useMemo(
    () => columnNames.filter((name) => !usedFields.has(name)),
    [columnNames, usedFields],
  );

  // Single canonical update path. Toggling off→on preserves the user's
  // last expression / visible_fields — the storage shape is the source of truth
  // and the keyed remount on layer.id (LayerEditorPanel) prevents cross-layer leakage.
  function update(partial: Partial<PopupConfig>) {
    const base: PopupConfig = popupConfig ?? {
      enabled: true,
      expression: null,
      visible_fields: null,
    };
    onPopupChange({ ...base, ...partial });
  }

  function handleToggle(checked: boolean) {
    update({ enabled: checked });
  }

  function handleExpressionChange(next: string) {
    // Empty input stores as null to match the rest of the schema's null-empty convention.
    update({ expression: next === '' ? null : next });
    if (debounceRef.current !== null) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setDebouncedExpr(next);
    }, DEBOUNCE_MS);
  }

  function handleModeChange(nextMode: 'all' | 'custom') {
    update({ visible_fields: nextMode === 'all' ? null : [] });
  }

  function handleAddField(name: string) {
    if (!visibleFields) return;
    if (visibleFields.includes(name)) return;
    update({ visible_fields: [...visibleFields, name] });
  }

  function handleRemoveField(name: string) {
    if (!visibleFields) return;
    update({ visible_fields: visibleFields.filter((f) => f !== name) });
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id || !visibleFields) return;
    const oldIndex = visibleFields.indexOf(String(active.id));
    const newIndex = visibleFields.indexOf(String(over.id));
    if (oldIndex < 0 || newIndex < 0) return;
    update({ visible_fields: arrayMove(visibleFields, oldIndex, newIndex) });
  }

  return (
    <div className="space-y-3 p-3 bg-muted/30 rounded-md border">
      <div className="flex items-center justify-between">
        <Label className="text-xs font-medium">{t('popup.enable')}</Label>
        <Switch checked={isOn} onCheckedChange={handleToggle} />
      </div>

      {isOn && (
        <>
          {/* Expression / template */}
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground" htmlFor="popup-expression">
              {t('popup.titleTemplate')}
            </Label>
            <Input
              id="popup-expression"
              type="text"
              maxLength={MAX_EXPRESSION_LENGTH}
              className={cn(
                'h-8 text-xs font-mono',
                !validation.ok && 'border-destructive focus-visible:ring-destructive/40',
              )}
              placeholder={t('popup.expressionPlaceholder')}
              value={expression}
              onChange={(e) => handleExpressionChange(e.target.value)}
              aria-invalid={!validation.ok}
              aria-describedby="popup-expression-help"
            />
            <p id="popup-expression-help" className="text-[11px] text-muted-foreground">
              {validation.ok
                ? t('popup.expressionHelp')
                : t('popup.unknownPlaceholders', { list: validation.unknown.join(', ') })}
            </p>
          </div>

          {/* Visible fields mode toggle */}
          <div className="space-y-1.5 pt-2 border-t">
            <Label className="text-xs font-medium">{t('popup.visibleFields')}</Label>
            <div className="flex gap-1">
              <button
                type="button"
                className={cn(
                  'flex-1 px-2 py-1 text-xs rounded border transition-colors',
                  mode === 'all'
                    ? 'bg-primary text-primary-foreground border-primary'
                    : 'bg-muted/50 text-muted-foreground border-border hover:bg-muted',
                )}
                onClick={() => handleModeChange('all')}
              >
                {t('popup.visibleFieldsAll')}
              </button>
              <button
                type="button"
                className={cn(
                  'flex-1 px-2 py-1 text-xs rounded border transition-colors',
                  mode === 'custom'
                    ? 'bg-primary text-primary-foreground border-primary'
                    : 'bg-muted/50 text-muted-foreground border-border hover:bg-muted',
                )}
                onClick={() => handleModeChange('custom')}
              >
                {t('popup.visibleFieldsCustom')}
              </button>
            </div>
          </div>

          {/* Custom mode: ordered list + add picker */}
          {mode === 'custom' && visibleFields !== null && (
            <div className="space-y-2">
              {columnNames.length === 0 ? (
                <p className="text-[11px] text-muted-foreground italic">
                  {t('popup.noColumns')}
                </p>
              ) : visibleFields.length === 0 ? (
                <p className="text-[11px] text-muted-foreground italic">
                  {t('popup.noFieldsSelected')}
                </p>
              ) : (
                <DndContext
                  sensors={sensors}
                  collisionDetection={closestCenter}
                  onDragEnd={handleDragEnd}
                >
                  <SortableContext items={visibleFields} strategy={verticalListSortingStrategy}>
                    <div className="space-y-1">
                      {visibleFields.map((name) => (
                        <SortableField
                          key={name}
                          name={name}
                          onRemove={() => handleRemoveField(name)}
                          removeLabel={t('popup.removeField')}
                          reorderLabel={t('layerItem.dragToReorder')}
                        />
                      ))}
                    </div>
                  </SortableContext>
                </DndContext>
              )}

              {availableFields.length > 0 && (
                <div className="space-y-1">
                  <Label className="text-[11px] text-muted-foreground">{t('popup.addField')}</Label>
                  <div className="flex flex-wrap gap-1">
                    {availableFields.map((name) => (
                      <button
                        key={name}
                        type="button"
                        onClick={() => handleAddField(name)}
                        className="flex items-center gap-1 px-1.5 py-0.5 text-[11px] font-mono rounded border border-dashed border-muted-foreground/40 text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                      >
                        <Plus className="h-3 w-3" />
                        {name}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
