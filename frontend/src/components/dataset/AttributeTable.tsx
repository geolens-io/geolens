import { useState, useMemo, useRef, useEffect, useCallback, useId, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import {
  useTable,
  tableFeatures,
  rowSortingFeature,
  columnVisibilityFeature,
  type ColumnDef,
  type SortingState,
  type ColumnVisibilityState,
} from '@tanstack/react-table';
import { useVirtualizer } from '@tanstack/react-virtual';
import { toast } from 'sonner';
import { ApiError } from '@/api/client';
import { useDatasetRows } from '@/components/dataset/hooks/use-dataset';
import { useDeleteFeatures, useUpdateFeature } from '@/hooks/use-features';
import { useDebouncedValue } from '@/hooks/use-debounce';
import { DEFAULT_ROWS_PAGE_SIZE, PAGE_SIZE_OPTIONS } from '@/lib/constants';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuCheckboxItem,
} from '@/components/ui/dropdown-menu';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { formatNumber } from '@/lib/format';
import { formatMutationError } from '@/lib/error-map';
import { coerceAttributeValue } from '@/lib/attribute-values';
import { valueLabelFor, type ValueLabels } from '@/lib/value-labels';
import { cn } from '@/lib/utils';
import { Loader2, ArrowDown, ArrowUp, ArrowUpDown, Settings2, Pencil, Trash2 } from 'lucide-react';
import { useAuthStore } from '@/stores/auth-store';

// Sorting is server-side (manualSorting), so no sorted row model is registered:
// a page holds only `limit` rows, and sorting those alone would misrepresent
// the column's order.
const features = tableFeatures({
  rowSortingFeature,
  columnVisibilityFeature,
});

/** Columns that are not user-editable */
const NON_EDITABLE_COLUMNS = new Set(['gid', 'geom']);
/** Columns that are not filterable */
const NON_FILTERABLE_COLUMNS = new Set(['geom', 'geom_4326']);

/** PostgreSQL's own short names for the verbose information_schema types. */
const SHORT_TYPES: Record<string, string> = {
  'character varying': 'varchar',
  character: 'char',
  'double precision': 'float8',
  real: 'float4',
  smallint: 'int2',
  integer: 'int4',
  bigint: 'int8',
  boolean: 'bool',
  'timestamp with time zone': 'timestamptz',
  'timestamp without time zone': 'timestamp',
  'time with time zone': 'timetz',
  'time without time zone': 'time',
};

function shortType(type: string): string {
  return SHORT_TYPES[type] ?? type.toLowerCase();
}

/** The detail code of a structured API refusal, if it has one. */
function refusalCode(err: unknown): string | undefined {
  if (!(err instanceof ApiError)) return undefined;
  return (err.body as { code?: string } | undefined)?.code;
}

interface EditingCell {
  rowGid: number;
  column: string;
}

interface AttributeTableProps {
  datasetId: string;
  canEdit?: boolean;
  compact?: boolean;
  /** CQL2-JSON filter expression sent as the rows request's `filter` param. */
  cql2Filter?: string;
  /** Row activation (Enter/click), e.g. the builder drawer finding a row on the map. */
  onRowClick?: (gid: number) => void;
  /**
   * The highlighted row's gid (the builder drawer's map highlight). Set, every
   * rendered row carries aria-selected — the match "true" with the inset
   * primary marker, the others "false" — and the marker follows the prop.
   * Omitted, no selection is rendered (the dataset page).
   */
  selectedGid?: number | null;
  /** Leading toolbar content, shown on the row that holds the Columns menu. */
  heading?: ReactNode;
  /** Trailing toolbar controls, after the Columns menu. */
  actions?: ReactNode;
  /**
   * When set, renders the caller's node as the table's header row, receiving
   * the row count and the Columns control; the count then no longer renders
   * in the pagination bar, and the rows-per-page select is omitted (the
   * caller's header owns the table's combobox — the builder drawer's layer
   * picker). Unset, the toolbar and pagination bar render exactly as before.
   */
  renderHeader?: (parts: { count: ReactNode; columns: ReactNode }) => ReactNode;
  /** Code labels per column; a labelled cell shows its label and keeps the code reachable. */
  valueLabels?: ReadonlyMap<string, ValueLabels>;
}

/** Postgres numeric types get a decimal input mode on touch keyboards. */
const NUMERIC_COL_TYPES = /^(smallint|integer|bigint|numeric|decimal|real|double precision)/;

function InlineCellEditor({
  initialValue,
  label,
  colType,
  error,
  onSave,
  onCancel,
  isSaving,
  compact,
}: {
  initialValue: string;
  label: string;
  colType: string;
  error?: string | null;
  onSave: (value: string) => void;
  onCancel: () => void;
  isSaving: boolean;
  compact: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState(initialValue);
  const errorId = useId();

  // Keyed on isSaving, not []. The saving branch below swaps the
  // input out for a spinner, and a save that fails leaves the editor open.
  // The editor is not remounted on re-render, so re-focus explicitly when the
  // input comes back.
  useEffect(() => {
    if (isSaving) return;
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [isSaving]);

  // An unchanged value is a cancel, not a save: a no-op PATCH would bump
  // updated_at, roll the tile version and write an attribute.edit audit event.
  const commit = () => {
    if (value === initialValue) {
      onCancel();
      return;
    }
    onSave(value);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      commit();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onCancel();
    }
  };

  if (isSaving) {
    return <Loader2 className="h-3 w-3 animate-spin" />;
  }

  return (
    <>
      <Input
        ref={inputRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={commit}
        onKeyDown={handleKeyDown}
        // The input must fit inside the fixed row height for its
        // density mode (44px default / 28px compact) so an open editor cannot
        // stretch the row past the virtualizer's per-mode row size.
        className={`${compact ? 'h-6' : 'h-7'} text-xs px-1`}
        // Name the editor (column + row) and tie the rejection
        // reason to the field so it isn't just a transient toast for SR users.
        aria-label={label}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        inputMode={NUMERIC_COL_TYPES.test(colType) ? 'decimal' : undefined}
      />
      {error ? (
        <span id={errorId} className="sr-only" role="alert">
          {error}
        </span>
      ) : null}
    </>
  );
}

export function AttributeTable({
  datasetId,
  canEdit = false,
  compact = false,
  cql2Filter,
  onRowClick,
  selectedGid,
  heading,
  actions,
  renderHeader,
  valueLabels,
}: AttributeTableProps) {
  const { t } = useTranslation('dataset');
  const [cursorHistory, setCursorHistory] = useState<number[]>([0]);
  const cursor = cursorHistory[cursorHistory.length - 1];
  const [editingCell, setEditingCell] = useState<EditingCell | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const parentRef = useRef<HTMLDivElement>(null);
  const deleteConfirmedRef = useRef(false);
  const [columnFilters, setColumnFilters] = useState<Record<string, string>>({});
  const [pageSize, setPageSize] = useState(DEFAULT_ROWS_PAGE_SIZE);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [columnVisibility, setColumnVisibility] = useState<ColumnVisibilityState>({});
  const updateFeature = useUpdateFeature();
  const deleteFeatures = useDeleteFeatures();
  const [selection, setSelection] = useState<ReadonlySet<number>>(() => new Set());
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const authIdentity = useAuthStore((state) => `${state.sessionEpoch}:${state.user?.id ?? ''}`);
  const requestScopeRef = useRef({ datasetId, authIdentity });
  if (
    requestScopeRef.current.datasetId !== datasetId
    || requestScopeRef.current.authIdentity !== authIdentity
  ) {
    requestScopeRef.current = { datasetId, authIdentity };
  }
  const editingCellRef = useRef(editingCell);
  editingCellRef.current = editingCell;

  // Debounce filters to avoid hammering the API on every keystroke
  const debouncedFilters = useDebouncedValue(columnFilters, 300);

  // Strip empty values for the API call
  const activeFilters = useMemo(() => {
    const f: Record<string, string> = {};
    for (const [k, v] of Object.entries(debouncedFilters)) {
      if (v) f[k] = v;
    }
    return Object.keys(f).length > 0 ? f : undefined;
  }, [debouncedFilters]);

  const sort = useMemo(
    () => (sorting[0] ? { column: sorting[0].id, desc: sorting[0].desc } : undefined),
    [sorting],
  );

  // A cursor is a position within one filter + sort order. Reset paging during
  // render, not in an effect, so no request goes out with the new order and
  // the old cursor.
  const pagingScope = JSON.stringify([activeFilters ?? null, sort ?? null, cql2Filter ?? null]);
  const [pagedScope, setPagedScope] = useState(pagingScope);
  if (pagedScope !== pagingScope) {
    setPagedScope(pagingScope);
    setCursorHistory([0]);
  }

  // When the row set moves (page, filter, sort, page size), an open cell
  // editor would silently lose its in-progress edit as the row leaves, so
  // close it and clear any error. The new rows start at the top; keep the
  // horizontal position.
  useEffect(() => {
    setEditingCell(null);
    setEditError(null);
    if (parentRef.current) parentRef.current.scrollTop = 0;
  }, [datasetId, cursor, activeFilters, sort, pageSize, cql2Filter]);

  const { data, error, isLoading, isFetching, isError, isPlaceholderData } = useDatasetRows(
    datasetId,
    pageSize,
    cursor,
    activeFilters,
    sort,
    cql2Filter,
  );
  // A schema edit, in GeoLens or on a live table, can drop or retype the sorted
  // column, and the server reports that as a 400 whose text depends on where it
  // failed. Fall back to unsorted rows; a 400 that persists without the sort is
  // shown as usual.
  if (sort && error instanceof ApiError && error.status === 400) {
    setSorting([]);
  }

  // A selection belongs to one page of one query against one table, since a
  // replacement table reuses gids. Like paging above, it is reset during
  // render so no frame offers to delete rows the user did not select.
  const selectionScope = JSON.stringify([
    datasetId, authIdentity, pagingScope, pageSize, cursor, data?.table_id,
  ]);
  const [selectedScope, setSelectedScope] = useState(selectionScope);
  if (selectedScope !== selectionScope) {
    setSelectedScope(selectionScope);
    setSelection(new Set());
  }
  // A bigint gid past 2^53 arrives rounded, so it could name another row.
  const pageGids = useMemo(
    () => (data?.rows ?? []).map((row) => row.gid as number).filter(Number.isSafeInteger),
    [data?.rows],
  );
  const selectedGids = useMemo(
    () => pageGids.filter((gid) => selection.has(gid)),
    [selection, pageGids],
  );
  const selectable = canEdit && pageGids.length > 0;
  // A refetch can drop every selected row, e.g. deleted by someone else,
  // while the confirmation is open; there is then nothing to confirm.
  if (deleteConfirmOpen && selectedGids.length === 0) setDeleteConfirmOpen(false);

  const toggleRow = useCallback((gid: number, checked: boolean) => {
    setSelection((prev) => {
      const next = new Set(prev);
      if (checked) next.add(gid);
      else next.delete(gid);
      return next;
    });
  }, []);

  const togglePage = useCallback((checked: boolean) => {
    setSelection(new Set(checked ? pageGids : []));
  }, [pageGids]);

  const handleDeleteRows = useCallback(async () => {
    const gids = selectedGids;
    const submittedScope = requestScopeRef.current;
    try {
      const result = await deleteFeatures.mutateAsync({
        datasetId,
        gids,
        tableId: data?.table_id,
      });
      if (requestScopeRef.current !== submittedScope) return;
      setSelection((prev) => new Set([...prev].filter((gid) => !gids.includes(gid))));
      toast.success(t('attributes.rowsDeleted', {
        count: result.deleted,
        formattedCount: formatNumber(result.deleted),
      }));
    } catch (err) {
      if (requestScopeRef.current !== submittedScope) return;
      const code = refusalCode(err);
      if (code === 'dataset_replaced') toast.error(t('map.featureDatasetReplaced'));
      else if (code === 'feature_not_found') toast.error(t('attributes.deleteRowsMissing'));
      else toast.error(formatMutationError('dataset:attributes.deleteRowsFailed', err));
    }
  }, [selectedGids, datasetId, data?.table_id, deleteFeatures, t]);

  const handleFilterChange = useCallback((colName: string, value: string) => {
    setColumnFilters((prev) => ({ ...prev, [colName]: value }));
  }, []);

  const handleCellSave = useCallback(async (rowGid: number, column: string, colType: string, newValue: string) => {
    const submittedDatasetId = datasetId;
    const submittedScope = requestScopeRef.current;
    const submittedCell = editingCellRef.current;
    // The inline editor is a plain text input; coerce to the
    // column's wire type instead of sending a string into a typed column.
    const coerced = coerceAttributeValue(newValue, colType);
    if (!coerced.ok) {
      const msg = t('attributes.editInvalidValue', { type: colType });
      // Mirror the toast into field-associated state so the
      // open editor carries aria-invalid/aria-describedby.
      setEditError(msg);
      toast.error(msg);
      return; // keep the editor open so the value can be corrected
    }
    setEditError(null);
    // Keep the cell in edit mode through the await so the saving spinner
    // (InlineCellEditor isSaving) renders; clearing editingCell first made that
    // branch unreachable and showed the stale value.
    try {
      await updateFeature.mutateAsync({
        datasetId: submittedDatasetId,
        gid: rowGid,
        properties: { [column]: coerced.value },
      });
      if (
        requestScopeRef.current !== submittedScope
        || editingCellRef.current !== submittedCell
      ) return;
      setEditingCell(null);
      toast.success(t('attributes.editSaved'));
    } catch (err) {
      if (
        requestScopeRef.current !== submittedScope
        || editingCellRef.current !== submittedCell
      ) return;
      // Surface the backend's specific reason (geometry-type
      // mismatch, unknown column, …) instead of a generic toast, and keep the
      // editor open so the value can be corrected rather than silently reverting.
      const msg = formatMutationError('dataset:attributes.editFailed', err);
      setEditError(msg);
      toast.error(msg);
    }
  }, [datasetId, updateFeature, t]);

  // Everything the cell renderer needs that changes render to render, read
  // through one ref so `columns` below never has to list it.
  //
  // TanStack's `<table.FlexRender cell={cell} />` renders `columnDef.cell` as
  // the React component TYPE, so a new `columns` array is a new element type at
  // every cell position and React remounts the cell subtree, resetting
  // InlineCellEditor's `value` to the stored value. Depending on
  // `handleCellSave` would do exactly that: its deps carry the object
  // react-query's useMutation returns, rebuilt on EVERY render (react-query
  // 5.101 useMutation.ts), so any re-render would throw away what the user
  // typed into an open editor, and Enter would hit commit()'s value ===
  // initialValue branch and close without a PATCH or validation message.
  //
  // The ref is written in this render pass, before FlexRender renders the
  // cells that read it, as for `editingCell`.
  const cellRenderState = {
    editingCell,
    editError,
    isSaving: updateFeature.isPending,
    canEdit,
    compact,
    valueLabels,
    onSave: handleCellSave,
  };
  const cellRenderRef = useRef(cellRenderState);
  cellRenderRef.current = cellRenderState;

  const handleNextPage = useCallback(() => {
    if (data?.next_cursor != null) {
      setCursorHistory((prev) => [...prev, data.next_cursor!]);
    }
  }, [data?.next_cursor]);

  const handlePreviousPage = useCallback(() => {
    setCursorHistory((prev) => (prev.length <= 1 ? prev : prev.slice(0, -1)));
  }, []);

  const columns = useMemo<ColumnDef<typeof features, Record<string, unknown>>[]>(() => {
    if (!data?.columns) return [];
    // An API without the field offers no sorting rather than a failing one.
    const sortable = new Set(data.sortable_columns ?? []);
    return data.columns.map((col) => ({
      accessorKey: col.name,
      header: () => (
        <>
          {col.name}
          <span className="font-normal text-muted-foreground" title={col.type}>
            {shortType(col.type)}
          </span>
        </>
      ),
      enableSorting: sortable.has(col.name),
      cell: (info) => {
        const {
          editingCell: currentEdit,
          editError: cellError,
          isSaving,
          canEdit: cellsEditable,
          compact: isCompact,
          valueLabels: labelsByColumn,
          onSave,
        } = cellRenderRef.current;
        const rowData = info.row.original;
        const gid = rowData.gid as number;
        const isEditing =
          currentEdit?.rowGid === gid && currentEdit?.column === col.name;

        if (isEditing) {
          return (
            <InlineCellEditor
              initialValue={String(info.getValue() ?? '')}
              label={t('attributes.cellEditorLabel', {
                column: col.name,
                gid,
                defaultValue: 'Edit {{column}} for feature {{gid}}',
              })}
              colType={col.type}
              error={cellError}
              onSave={(val) => onSave(gid, col.name, col.type, val)}
              onCancel={() => {
                setEditError(null);
                setEditingCell(null);
              }}
              isSaving={isSaving}
              compact={isCompact}
            />
          );
        }

        const cellValue = String(info.getValue() ?? '');
        const codeLabel = valueLabelFor(labelsByColumn?.get(col.name), info.getValue());
        if (cellsEditable && !NON_EDITABLE_COLUMNS.has(col.name)) {
          // The code shows beside its label on hover and focus, and screen
          // readers always read it.
          const shown = codeLabel === undefined ? cellValue : (
            <>
              {codeLabel}{' '}
              <span className="text-muted-foreground opacity-0 group-hover/cell:opacity-100 group-focus-visible/cell:opacity-100">
                ({cellValue})
              </span>
            </>
          );
          return (
            <button
              type="button"
              className="group/cell flex items-center gap-1 rounded-sm px-0.5 -mx-0.5 text-start hover:bg-muted/50 w-full"
              onClick={() => setEditingCell({ rowGid: gid, column: col.name })}
            >
              <span className="truncate">{shown}</span>
              <Pencil className="h-2.5 w-2.5 shrink-0 text-muted-foreground/0 group-hover/cell:text-muted-foreground/50" />
            </button>
          );
        }

        if (codeLabel !== undefined) {
          return (
            <Tooltip>
              <TooltipTrigger asChild>
                <button type="button" className="block max-w-full truncate rounded-sm text-start">
                  {codeLabel}
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="max-w-sm break-all">
                {cellValue}
              </TooltipContent>
            </Tooltip>
          );
        }

        if (cellValue.length > 30) {
          return (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="block truncate">{cellValue}</span>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="max-w-sm break-all">
                {cellValue}
              </TooltipContent>
            </Tooltip>
          );
        }

        return cellValue;
      },
    }));
    // The column lists and `t` ONLY: adding any other input remounts every
    // cell, and with it any open editor, whenever it changes. `t` is safe
    // because react-i18next caches its useSyncExternalStore snapshot and hands
    // back a new `t` only on a language change, a legitimate reason to rebuild.
  }, [data?.columns, data?.sortable_columns, t]);

  const table = useTable(
    {
      features,
      data: data?.rows ?? [],
      columns,
      state: { sorting, columnVisibility },
      onSortingChange: setSorting,
      onColumnVisibilityChange: setColumnVisibility,
      manualSorting: true,
      enableMultiSort: false,
      sortDescFirst: false,
    },
    (state) => state,
  );

  // Virtualize the body so 100-row pages render only the visible window (~10-20
  // rows + overscan), keeping DOM-node count flat. Rows arrive filtered and
  // sorted from the server.
  const rows = table.getRowModel().rows;
  // Fixed-height rows only: never reintroduce dynamic row measurement. With a
  // Chrome AX tree attached (screen reader, CDP Accessibility.enable), the
  // measure→layout→re-render edge fed back synchronously and locked the page
  // in an infinite render loop.
  //
  // The row height is enforced, not estimated: each body cell carries an
  // explicit height class (h-11 / h-7 below) matching this value, and in a
  // collapsed-border table that yields exactly that row pitch (measured in
  // Chromium: 44/28px in both densities, editor open or not). Keep rowHeight
  // and the cell height classes in lockstep.
  const rowHeight = compact ? 28 : 44;
  // react-hooks/incompatible-library only reports the first flagged hook it
  // finds per component, so the suppression below applies to useVirtualizer().
  // eslint-disable-next-line react-hooks/incompatible-library -- TanStack Virtual returns imperative helpers; this component keeps virtualizer state local.
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => rowHeight,
    overscan: 8,
  });
  const virtualItems = virtualizer.getVirtualItems();

  // TanStack Virtual (virtual-core 3.17.x) leaves estimateSize out of its
  // measurement-cache deps (getMeasurementOptions covers count/padding/
  // scrollMargin/getItemKey/enabled/lanes/gap only), so when the density toggle
  // flips rowHeight 44↔28 the cells resize but getTotalSize() and item offsets
  // keep the old density. measure() clears the item-size cache and recomputes.
  // Skip the mount pass: the initial layout already uses the right size.
  const prevCompactRef = useRef(compact);
  useEffect(() => {
    if (prevCompactRef.current !== compact) {
      prevCompactRef.current = compact;
      virtualizer.measure();
    }
  }, [compact, virtualizer]);

  const approximateTotal = data?.approximate_total ?? 0;
  const totalKind = data?.total_kind ?? 'estimate';
  const rowCount = data?.rows?.length ?? 0;
  // A filtered page's total is counted, so zero means no match rather than no statistics.
  const counted = totalKind !== 'estimate';
  const effectiveTotal = counted || approximateTotal > 0 ? approximateTotal : rowCount;
  const isExact = totalKind === 'exact' || (!counted && approximateTotal === 0 && rowCount > 0);
  const rangeStart = rowCount > 0 ? (cursorHistory.length - 1) * pageSize + 1 : 0;
  const rangeEnd = rangeStart > 0 ? rangeStart + rowCount - 1 : 0;

  // The row count text: the pagination bar renders it by default, a
  // renderHeader caller embeds it in its own header instead.
  const countNode = (
    <span className="text-muted-foreground">
      {t(
        totalKind === 'at_least'
          ? 'attributes.showingAtLeast'
          : isExact
            ? 'attributes.showingExact'
            : 'attributes.showing',
        { start: formatNumber(rangeStart), end: formatNumber(rangeEnd), total: formatNumber(effectiveTotal) },
      )}
      {isFetching && (
        <Loader2 className="inline h-3 w-3 animate-spin ms-2" />
      )}
    </span>
  );

  const columnsMenu = columns.length > 0 ? (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="h-7 text-xs gap-1.5">
          <Settings2 className="h-3.5 w-3.5" />
          {t('attributes.columns')}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-64 overflow-y-auto">
        {table.getAllColumns()
          .filter((col) => col.getCanHide())
          .map((col) => (
            <DropdownMenuCheckboxItem
              key={col.id}
              className="text-xs"
              checked={col.getIsVisible()}
              onCheckedChange={(value) => col.toggleVisibility(!!value)}
            >
              {col.id}
            </DropdownMenuCheckboxItem>
          ))}
      </DropdownMenuContent>
    </DropdownMenu>
  ) : null;

  const deleteRowsAction = selectedGids.length > 0 ? (
    <Button
      variant="destructive"
      size="sm"
      className="h-7 text-xs gap-1.5"
      onClick={() => setDeleteConfirmOpen(true)}
      disabled={deleteFeatures.isPending}
    >
      <Trash2 className="h-3.5 w-3.5" />
      {t('attributes.deleteRows', {
        count: selectedGids.length,
        formattedCount: formatNumber(selectedGids.length),
      })}
    </Button>
  ) : null;

  // The root is a shrinkable flex column: inside a height-bounded parent
  // (DataTab) the scroll region absorbs the overflow, so the toolbar and the
  // pagination bar stay on screen. A renderHeader caller owns the header row,
  // so the shell drops the inter-row gap (the caller's header borders the
  // table directly).
  const shell = (body: ReactNode) => (
    <div className={cn('flex min-h-0 flex-1 flex-col', !renderHeader && 'gap-3')}>
      {renderHeader ? (
        renderHeader({ count: countNode, columns: columnsMenu })
      ) : (
        heading || actions || columnsMenu ? (
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {heading}
            <div className="ms-auto flex items-center gap-1">
              {deleteRowsAction}
              {columnsMenu}
              {actions}
            </div>
          </div>
        ) : null
      )}
      {body}
    </div>
  );

  if (isLoading) {
    return shell(
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>,
    );
  }

  if (isError) return shell(<div className="p-4 text-sm text-destructive">{t('attributes.loadFailed', { defaultValue: 'Failed to load data. Please try again.' })}</div>);

  // A CQL2 filter that matched nothing is a filter result, not an empty
  // dataset: it flows through the normal path (header, toolbar, noResults).
  if (effectiveTotal === 0 && !activeFilters && !cql2Filter && (!data?.rows || data.rows.length === 0)) {
    return shell(
      <div className="text-center py-12 text-muted-foreground">
        {t('attributes.noData')}
      </div>,
    );
  }

  // Exact per-density cell height (py-0 + h-*) instead of padding,
  // so real row pitch always equals `rowHeight` and the virtualizer's offset
  // math stays correct without dynamic measurement.
  const cellClass = compact ? 'h-7 py-0 text-xs' : 'h-11 py-0';
  const lastItem = virtualItems[virtualItems.length - 1];
  const paddingTop = virtualItems[0]?.start ?? 0;
  const paddingBottom = lastItem
    ? virtualizer.getTotalSize() - (lastItem.start + lastItem.size)
    : 0;
  const visibleColumnCount = table.getVisibleLeafColumns().length + (selectable ? 1 : 0);
  const pageChecked = selectedGids.length === 0
    ? false
    : selectedGids.length === pageGids.length
      ? true
      : 'indeterminate';

  return shell(
    <>
      {/*
        `parentRef` is the only scroll container, for both axes, so the
        sticky header and the horizontal scrollbar belong to the visible box.
        The shared Table renders `bare` because its own overflow wrapper would
        nest a second scroll container that grows to the rendered rows and
        clips them. The table is `w-max` (content-sized): wide tables scroll
        sideways and few-column tables don't stretch into empty columns.

        Only the <tbody> is virtualized, and spacer rows above and below the
        rendered window give the table its full height. A sticky <thead> stays
        pinned only while its table is that tall; rows shifted with transforms
        would leave the table short and let the header scroll away.
      */}
      <div
        ref={parentRef}
        role="region"
        aria-label={t('attributes.tableLabel')}
        tabIndex={0} // eslint-disable-line jsx-a11y/no-noninteractive-tabindex -- scrollable region must be keyboard-focusable
        className="relative min-h-0 overflow-auto rounded-md border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        <table data-slot="table" className="w-max caption-bottom text-sm">
          <TableHeader className="sticky top-0 z-10 bg-muted">
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {selectable ? (
                  <TableHead className="w-10">
                    <Checkbox
                      aria-label={t('attributes.selectPage')}
                      checked={pageChecked}
                      disabled={isPlaceholderData}
                      onCheckedChange={(value) => togglePage(value === true)}
                    />
                  </TableHead>
                ) : null}
                {headerGroup.headers.map((header) => {
                  // Announce sort state on the column header.
                  const sorted = header.column.getIsSorted();
                  const canSort = header.column.getCanSort();
                  const ariaSort = sorted === 'asc'
                    ? 'ascending'
                    : sorted === 'desc'
                      ? 'descending'
                      : canSort
                        ? 'none'
                        : undefined;
                  return (
                  <TableHead key={header.id} aria-sort={ariaSort} className="normal-case">
                    {header.isPlaceholder ? null : canSort ? (
                      <button
                        type="button"
                        className="flex items-center gap-1.5 hover:text-foreground"
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        <table.FlexRender header={header} />
                        {sorted === 'asc' ? (
                          <ArrowUp className="h-3 w-3" />
                        ) : sorted === 'desc' ? (
                          <ArrowDown className="h-3 w-3" />
                        ) : (
                          <ArrowUpDown className="h-3 w-3 text-muted-foreground/50" />
                        )}
                      </button>
                    ) : (
                      <span className="flex items-center gap-1.5">
                        <table.FlexRender header={header} />
                      </span>
                    )}
                  </TableHead>
                  );
                })}
              </TableRow>
            ))}
            {/* Filter row */}
            <TableRow>
              {selectable ? <TableHead className="py-1" /> : null}
              {table.getHeaderGroups()[0]?.headers.map((header) => (
                <TableHead key={`filter-${header.id}`} className="py-1">
                  {!NON_FILTERABLE_COLUMNS.has(header.column.id) ? (
                    <Input
                      aria-label={t('attributes.filterColumn', { column: header.column.id })}
                      value={columnFilters[header.column.id] ?? ''}
                      onChange={(e) => handleFilterChange(header.column.id, e.target.value)}
                      placeholder={t('attributes.filter')}
                      className="bg-transparent border-0 border-b rounded-none text-xs h-7 focus-visible:ring-0 focus-visible:border-primary"
                    />
                  ) : null}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={visibleColumnCount} className="text-center text-muted-foreground py-8">
                  {t('attributes.noResults')}
                </TableCell>
              </TableRow>
            ) : (
              <>
                {paddingTop > 0 ? (
                  <tr aria-hidden="true">
                    <td colSpan={visibleColumnCount} style={{ height: paddingTop, padding: 0 }} />
                  </tr>
                ) : null}
                {virtualItems.map((virtualRow) => {
                  const row = rows[virtualRow.index];
                  const gid = row.original.gid as number;
                  const activatable = onRowClick && Number.isSafeInteger(gid);
                  const selected = selectedGid !== undefined && gid === selectedGid;
                  return (
                    <TableRow
                      key={row.id}
                      data-index={virtualRow.index}
                      aria-selected={selectedGid === undefined ? undefined : selected ? 'true' : 'false'}
                      className={cn(
                        virtualRow.index % 2 === 1 ? 'bg-muted/30' : '',
                        activatable && 'cursor-pointer hover:bg-primary-50/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
                        selected && 'selection-inset',
                      )}
                      tabIndex={activatable ? 0 : undefined}
                      aria-label={activatable ? t('attributes.rowActionLabel', { gid, defaultValue: 'Show row {{gid}} on the map' }) : undefined}
                      onClick={activatable ? () => onRowClick(gid) : undefined}
                      onKeyDown={activatable ? (e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          onRowClick(gid);
                        }
                      } : undefined}
                    >
                      {selectable ? (
                        <TableCell className={`w-10 ${cellClass}`}>
                          <Checkbox
                            aria-label={t('attributes.selectRow', { gid })}
                            checked={selectedGids.includes(gid)}
                            disabled={isPlaceholderData || !Number.isSafeInteger(gid)}
                            onCheckedChange={(value) => toggleRow(gid, value === true)}
                          />
                        </TableCell>
                      ) : null}
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id} className={`max-w-xs truncate ${cellClass}`}>
                          <table.FlexRender cell={cell} />
                        </TableCell>
                      ))}
                    </TableRow>
                  );
                })}
                {paddingBottom > 0 ? (
                  <tr aria-hidden="true">
                    <td colSpan={visibleColumnCount} style={{ height: paddingBottom, padding: 0 }} />
                  </tr>
                ) : null}
              </>
            )}
          </TableBody>
        </table>
      </div>

      <AlertDialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
        <AlertDialogContent
          onCloseAutoFocus={(event) => {
            // The opener is disabled during a delete and gone once nothing is selected.
            if (!deleteConfirmedRef.current && selectedGids.length > 0) return;
            deleteConfirmedRef.current = false;
            event.preventDefault();
            parentRef.current?.focus();
          }}
        >
          <AlertDialogHeader>
            <AlertDialogTitle>{t('attributes.deleteRowsTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('attributes.deleteRowsDescription', {
                count: selectedGids.length,
                formattedCount: formatNumber(selectedGids.length),
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common:cancel')}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={deleteFeatures.isPending}
              onClick={() => {
                deleteConfirmedRef.current = true;
                handleDeleteRows();
                setDeleteConfirmOpen(false);
              }}
            >
              {t('common:delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Pagination */}
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          {!renderHeader && countNode}
          {!renderHeader && (
            <div className="flex items-center gap-1.5">
              <span className="text-muted-foreground text-xs">{t('attributes.rowsPerPage')}</span>
              <Select
                value={String(pageSize)}
                onValueChange={(val) => {
                  setPageSize(Number(val));
                  setCursorHistory([0]);
                }}
              >
                <SelectTrigger
                  className="h-7 w-[70px] text-xs"
                  aria-label={t('attributes.rowsPerPage')}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PAGE_SIZE_OPTIONS.map((opt) => (
                    <SelectItem key={opt} value={String(opt)}>
                      {opt}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handlePreviousPage}
            disabled={cursorHistory.length <= 1 || isPlaceholderData}
          >
            {t('attributes.previous')}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleNextPage}
            // Placeholder rows belong to the previous page or order, so their
            // cursor would pair the old position with the new query.
            disabled={data?.next_cursor == null || isPlaceholderData}
          >
            {t('common:next')}
          </Button>
        </div>
      </div>
    </>,
  );
}
