import { useState, useMemo, useRef, useEffect, useCallback, useId } from 'react';
import { useTranslation } from 'react-i18next';
import {
  useTable,
  tableFeatures,
  rowSortingFeature,
  columnVisibilityFeature,
  createSortedRowModel,
  sortFn_alphanumeric,
  sortFn_alphanumericCaseSensitive,
  sortFn_basic,
  sortFn_datetime,
  sortFn_text,
  sortFn_textCaseSensitive,
  type ColumnDef,
  type SortingState,
  type ColumnVisibilityState,
} from '@tanstack/react-table';
import { useVirtualizer } from '@tanstack/react-virtual';
import { toast } from 'sonner';
import { useDatasetRows } from '@/components/dataset/hooks/use-dataset';
import { useUpdateFeature } from '@/hooks/use-features';
import { useDebouncedValue } from '@/hooks/use-debounce';
import { DEFAULT_ROWS_PAGE_SIZE, PAGE_SIZE_OPTIONS } from '@/lib/constants';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
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
import { Loader2, ArrowUpDown, Settings2, Pencil } from 'lucide-react';

// react-table v9 requires row models and sort functions to be registered
// explicitly (v8 wired getSortedRowModel() as a table option and auto-detected
// sortingFns). Columns here are built dynamically from the dataset's Postgres
// column list with no per-column sortFn set, so all six built-ins must be
// registered by name — the auto-detected sortFn (alphanumeric/text/datetime/
// basic) still resolves by sampling each column's data, but only if its name
// is present in this map. Registered individually rather than via the
// library's bundled `sortFns` export, which is deprecated in favor of
// importing only the functions actually used.
export const features = tableFeatures({
  rowSortingFeature,
  columnVisibilityFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns: {
    alphanumeric: sortFn_alphanumeric,
    alphanumericCaseSensitive: sortFn_alphanumericCaseSensitive,
    basic: sortFn_basic,
    datetime: sortFn_datetime,
    text: sortFn_text,
    textCaseSensitive: sortFn_textCaseSensitive,
  },
});

/** Columns that are not user-editable */
const NON_EDITABLE_COLUMNS = new Set(['gid', 'geom']);
/** Columns that are not filterable */
const NON_FILTERABLE_COLUMNS = new Set(['geom', 'geom_4326']);

interface EditingCell {
  rowGid: number;
  column: string;
}

interface AttributeTableProps {
  datasetId: string;
  canEdit?: boolean;
  compact?: boolean;
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

  // fix(#1628): keyed on isSaving, not []. The saving branch below swaps the
  // input out for a spinner, and a save that fails leaves the editor open —
  // before #1628 the editor was remounted wholesale on every render, so this
  // effect happened to re-run and put the caret back. It no longer remounts,
  // so re-focus explicitly when the input comes back.
  useEffect(() => {
    if (isSaving) return;
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [isSaving]);

  // fix(#458 E-35): an unchanged value is a cancel, not a save — blur used to
  // commit a no-op PATCH that bumped updated_at, rolled the tile version, and
  // wrote an attribute.edit audit event for a non-change.
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
        // fix(#820): the input must fit inside the fixed row height for its
        // density mode (44px default / 28px compact) so an open editor cannot
        // stretch the row past the virtualizer's per-mode row size.
        className={`${compact ? 'h-6' : 'h-7'} text-xs px-1`}
        // fix(#458 E-39): name the editor (column + row) and tie the rejection
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

export function AttributeTable({ datasetId, canEdit = false, compact = false }: AttributeTableProps) {
  const { t } = useTranslation('dataset');
  const [cursor, setCursor] = useState(0);
  const [cursorHistory, setCursorHistory] = useState<number[]>([0]);
  const [editingCell, setEditingCell] = useState<EditingCell | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  // Scroll container ref used by the row virtualizer (PERF-07).
  const parentRef = useRef<HTMLDivElement>(null);
  const [columnFilters, setColumnFilters] = useState<Record<string, string>>({});
  const [pageSize, setPageSize] = useState(DEFAULT_ROWS_PAGE_SIZE);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [columnVisibility, setColumnVisibility] = useState<ColumnVisibilityState>({});
  const updateFeature = useUpdateFeature();

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

  // Reset cursor and history when filters change
  useEffect(() => {
    setCursor(0);
    setCursorHistory([0]);
  }, [debouncedFilters]);

  // fix(#458 E-51): an open cell editor survives a page/filter/page-size
  // change; if the edited row leaves the result set the in-progress edit
  // silently vanishes. Close it (and clear any error) when the row set moves.
  useEffect(() => {
    setEditingCell(null);
    setEditError(null);
  }, [cursor, activeFilters, pageSize]);

  const { data, isLoading, isFetching, isError } = useDatasetRows(
    datasetId,
    pageSize,
    cursor,
    activeFilters,
  );

  const handleFilterChange = useCallback((colName: string, value: string) => {
    setColumnFilters((prev) => ({ ...prev, [colName]: value }));
  }, []);

  const handleCellSave = useCallback(async (rowGid: number, column: string, colType: string, newValue: string) => {
    // fix(#458 E-03): the inline editor is a plain text input; coerce to the
    // column's wire type instead of sending a string into a typed column.
    const coerced = coerceAttributeValue(newValue, colType);
    if (!coerced.ok) {
      const msg = t('attributes.editInvalidValue', { type: colType });
      // fix(#458 E-39): mirror the toast into field-associated state so the
      // open editor carries aria-invalid/aria-describedby.
      setEditError(msg);
      toast.error(msg);
      return; // keep the editor open so the value can be corrected
    }
    setEditError(null);
    // fix(#458 E-22): keep the cell in edit mode through the await so the saving
    // spinner (InlineCellEditor isSaving) actually renders; clearing editingCell
    // before awaiting made that branch unreachable and showed the stale value.
    try {
      await updateFeature.mutateAsync({
        datasetId,
        gid: rowGid,
        properties: { [column]: coerced.value },
      });
      setEditingCell(null);
      toast.success(t('attributes.editSaved'));
    } catch (err) {
      // fix(#458 E-21): surface the backend's specific reason (geometry-type
      // mismatch, unknown column, …) instead of a generic toast, and keep the
      // editor open so the value can be corrected rather than silently reverting.
      toast.error(formatMutationError('dataset:attributes.editFailed', err));
    }
  }, [datasetId, updateFeature, t]);

  // fix(#1628): everything the cell renderer needs that changes from render to
  // render, read through one ref so `columns` below never has to list it.
  //
  // TanStack's `<table.FlexRender cell={cell} />` renders `columnDef.cell` as
  // the React component TYPE (`React.createElement(def.cell, ctx)`), so a new
  // `columns` array is a new element type at every cell position and React
  // unmounts and remounts the whole cell subtree instead of re-rendering it.
  // That resets InlineCellEditor's `value` state back to the stored cell value.
  // `columns` used to depend on `handleCellSave`, whose own dep list carries
  // the object react-query's useMutation returns — and that is rebuilt on
  // EVERY render (`return { ...result, mutate, mutateAsync: result.mutate }`,
  // react-query 5.101 useMutation.ts). So any re-render at all, from anywhere
  // in the page, silently threw away what the user had typed into an open
  // cell editor. Enter then hit commit()'s value === initialValue branch: no
  // PATCH, no validation message, editor just closes. That is the #1628 e2e
  // flake, and the same reset also defeated the "keep the editor open so the
  // value can be corrected" behaviour of E-03/E-21 for real users.
  //
  // Reading state from a ref during render is the pattern this component
  // already used for `editingCell`: the ref is written in this render pass,
  // before FlexRender renders the cells that read it.
  const cellRenderState = {
    editingCell,
    editError,
    isSaving: updateFeature.isPending,
    canEdit,
    compact,
    onSave: handleCellSave,
  };
  const cellRenderRef = useRef(cellRenderState);
  cellRenderRef.current = cellRenderState;

  const handleNextPage = useCallback(() => {
    if (data?.next_cursor != null) {
      setCursorHistory((prev) => [...prev, data.next_cursor!]);
      setCursor(data.next_cursor!);
    }
  }, [data?.next_cursor]);

  const handlePreviousPage = useCallback(() => {
    setCursorHistory((prev) => {
      if (prev.length <= 1) return prev;
      const newHistory = prev.slice(0, -1);
      setCursor(newHistory[newHistory.length - 1]);
      return newHistory;
    });
  }, []);

  const columns = useMemo<ColumnDef<typeof features, Record<string, unknown>>[]>(() => {
    if (!data?.columns) return [];
    return data.columns.map((col) => ({
      accessorKey: col.name,
      header: `${col.name} (${col.type})`,
      cell: (info) => {
        const {
          editingCell: currentEdit,
          editError: cellError,
          isSaving,
          canEdit: cellsEditable,
          compact: isCompact,
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

        if (cellsEditable && !NON_EDITABLE_COLUMNS.has(col.name)) {
          return (
            <button
              type="button"
              className="group/cell flex items-center gap-1 rounded-sm px-0.5 -mx-0.5 text-start hover:bg-muted/50 w-full"
              onClick={() => setEditingCell({ rowGid: gid, column: col.name })}
            >
              <span className="truncate">{cellValue}</span>
              <Pencil className="h-2.5 w-2.5 shrink-0 text-muted-foreground/0 group-hover/cell:text-muted-foreground/50" />
            </button>
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
    // fix(#1628): the column list and `t` ONLY. Every other input the renderer
    // needs comes from cellRenderRef, because adding any of them back here
    // remounts every cell — and with it any open editor — whenever they change.
    // `t` is safe to keep: react-i18next caches its useSyncExternalStore
    // snapshot and only hands back a new `t` on a language change, which is a
    // legitimate reason to rebuild the columns.
  }, [data?.columns, t]);

  const table = useTable(
    {
      features,
      data: data?.rows ?? [],
      columns,
      state: { sorting, columnVisibility },
      onSortingChange: setSorting,
      onColumnVisibilityChange: setColumnVisibility,
    },
    (state) => state,
  );

  // PERF-07: virtualize the body so that 100-row pages render only the visible
  // window (~10-20 rows + overscan), keeping DOM-node count flat regardless of
  // page size or column count. The virtualizer iterates over the post-sort,
  // post-filter row model from TanStack Table — sort/filter state changes flow
  // through naturally on each render via `count: rows.length`.
  const rows = table.getRowModel().rows;
  // fix(#820): fixed-height rows only — never reintroduce dynamic row
  // measurement here. With a Chrome AX tree attached (screen reader, CDP
  // Accessibility.enable), the measure→layout→re-render edge fed back
  // synchronously and locked the page in an infinite render loop.
  //
  // The row height is enforced, not estimated: each body cell carries an
  // explicit height class (h-11 / h-7 below) matching this value, and in a
  // collapsed-border table an explicit cell height yields exactly that row
  // pitch (measured in Chromium: 44/28px in both densities, editor open or
  // not — the border is absorbed into the specified height). Keep rowHeight
  // and the cell height classes in lockstep.
  const rowHeight = compact ? 28 : 44;
  // fix(#1407): react-hooks/incompatible-library only reports the first
  // flagged hook it finds per component. The removed useReactTable() call
  // used to occupy that slot (suppressed below it), which silently masked
  // this same warning on useVirtualizer() below.
  // eslint-disable-next-line react-hooks/incompatible-library -- TanStack Virtual returns imperative helpers; this component keeps virtualizer state local.
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => rowHeight,
    overscan: 8,
  });
  const virtualItems = virtualizer.getVirtualItems();

  // fix(#851): TanStack Virtual (virtual-core 3.17.x) does not include
  // estimateSize in its measurement-cache deps (getMeasurementOptions covers
  // count/padding/scrollMargin/getItemKey/enabled/lanes/gap only), so when
  // the density toggle flips rowHeight 44↔28 the cells resize immediately but
  // getTotalSize() and item offsets keep the old density. measure() is the
  // documented reset: it clears the item-size cache and recomputes. Skip the
  // mount pass — the initial layout is already built from the right size.
  const prevCompactRef = useRef(compact);
  useEffect(() => {
    if (prevCompactRef.current !== compact) {
      prevCompactRef.current = compact;
      virtualizer.measure();
    }
  }, [compact, virtualizer]);

  const approximateTotal = data?.approximate_total ?? 0;
  const rowCount = data?.rows?.length ?? 0;
  const effectiveTotal = approximateTotal > 0 ? approximateTotal : rowCount;
  const isExact = approximateTotal === 0 && rowCount > 0;
  const rangeStart = rowCount > 0 ? (cursorHistory.length - 1) * pageSize + 1 : 0;
  const rangeEnd = rangeStart > 0 ? rangeStart + rowCount - 1 : 0;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (isError) return <div className="p-4 text-sm text-destructive">{t('attributes.loadFailed', { defaultValue: 'Failed to load data. Please try again.' })}</div>;

  if (effectiveTotal === 0 && !activeFilters && (!data?.rows || data.rows.length === 0)) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        {t('attributes.noData')}
      </div>
    );
  }

  // fix(#820): exact per-density cell height (py-0 + h-*) instead of padding,
  // so real row pitch always equals `rowHeight` and the virtualizer's offset
  // math stays correct without dynamic measurement.
  const cellClass = compact ? 'h-7 py-0 text-xs' : 'h-11 py-0';

  return (
    <div className="space-y-3">
      {/* Toolbar: column visibility */}
      <div className="flex items-center justify-end">
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
                  className="capitalize text-xs"
                  checked={col.getIsVisible()}
                  onCheckedChange={(value) => col.toggleVisibility(!!value)}
                >
                  {col.id}
                </DropdownMenuCheckboxItem>
              ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/*
        PERF-07: scroll container is `parentRef`. Virtualization is applied to
        the <tbody> only — the native <table>/<thead>/<tr>/<td> structure is
        preserved so column auto-sizing and sticky headers keep working. The
        table is `w-max` (content-sized): wide tables overflow and scroll via
        the inner shadcn Table container's `overflow-x-auto`; few-column tables
        size to their content instead of stretching to fill (no empty columns).
        Vertical scroll is captured here (max-h + overflow-auto).

        The recommended TanStack pattern for native-table virtualization
        (https://tanstack.com/virtual/latest/docs/framework/react/examples/table)
        keeps rendered <tr>s in document flow and shifts each one back to its
        virtualized offset via `translateY(virtualRow.start - index * size)`.
        Total scrollable height is enforced by an inner spacer div wrapping
        the <table>.
      */}
      <div
        ref={parentRef}
        className="rounded-md border relative max-h-[60vh] overflow-auto"
      >
        <div
          style={
            rows.length === 0
              ? undefined
              : { height: `${virtualizer.getTotalSize()}px`, width: '100%' }
          }
        >
          <Table aria-label={t('attributes.tableLabel')} className="w-max">
            <TableHeader className="sticky top-0 z-10 bg-muted/80 backdrop-blur-sm">
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => {
                    // fix(#438): A11Y-04 — announce sort state on the column header.
                    const sorted = header.column.getIsSorted();
                    const ariaSort = sorted === 'asc'
                      ? 'ascending'
                      : sorted === 'desc'
                        ? 'descending'
                        : header.column.getCanSort()
                          ? 'none'
                          : undefined;
                    return (
                    <TableHead key={header.id} aria-sort={ariaSort}>
                      {header.isPlaceholder ? null : (
                        <button
                          type="button"
                          className="flex items-center gap-1 hover:text-foreground"
                          onClick={header.column.getToggleSortingHandler()}
                        >
                          <table.FlexRender header={header} />
                          {header.column.getIsSorted() === 'asc' ? (
                            <span> ↑</span>
                          ) : header.column.getIsSorted() === 'desc' ? (
                            <span> ↓</span>
                          ) : (
                            <ArrowUpDown className="h-3 w-3 text-muted-foreground/50" />
                          )}
                        </button>
                      )}
                    </TableHead>
                    );
                  })}
                </TableRow>
              ))}
              {/* Filter row */}
              <TableRow>
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
                  <TableCell colSpan={columns.length} className="text-center text-muted-foreground py-8">
                    {t('attributes.noResults')}
                  </TableCell>
                </TableRow>
              ) : (
                virtualItems.map((virtualRow, index) => {
                  const row = rows[virtualRow.index];
                  return (
                    <TableRow
                      key={row.id}
                      className={virtualRow.index % 2 === 1 ? 'bg-muted/30' : ''}
                      style={{
                        // Shift each rendered <tr> from its document-flow position
                        // to its virtualized offset. All rendered rows form a
                        // contiguous block of equal-height items, so subtracting
                        // index * size collapses them onto virtualRow.start.
                        transform: `translateY(${virtualRow.start - index * virtualRow.size}px)`,
                      }}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id} className={`max-w-xs truncate ${cellClass}`}>
                          <table.FlexRender cell={cell} />
                        </TableCell>
                      ))}
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between text-sm">
        <div className="flex items-center gap-3">
          <span className="text-muted-foreground">
            {isExact
              ? t('attributes.showingExact', { start: formatNumber(rangeStart), end: formatNumber(rangeEnd), total: formatNumber(effectiveTotal) })
              : t('attributes.showing', { start: formatNumber(rangeStart), end: formatNumber(rangeEnd), total: formatNumber(effectiveTotal) })}
            {isFetching && (
              <Loader2 className="inline h-3 w-3 animate-spin ms-2" />
            )}
          </span>
          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground text-xs">{t('attributes.rowsPerPage')}</span>
            <Select
              value={String(pageSize)}
              onValueChange={(val) => {
                setPageSize(Number(val));
                setCursor(0);
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
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handlePreviousPage}
            disabled={cursorHistory.length <= 1}
          >
            {t('attributes.previous')}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleNextPage}
            disabled={data?.next_cursor == null}
          >
            {t('common:next')}
          </Button>
        </div>
      </div>
    </div>
  );
}
