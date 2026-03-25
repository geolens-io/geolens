import { useState, useMemo, useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  type ColumnDef,
} from '@tanstack/react-table';
import { toast } from 'sonner';
import { useDatasetRows } from '@/hooks/use-dataset';
import { useUpdateFeature } from '@/hooks/use-features';
import { useDebouncedValue } from '@/hooks/use-debounce';
import { DEFAULT_ROWS_PAGE_SIZE, PAGE_SIZE_OPTIONS } from '@/lib/constants';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import { formatNumber } from '@/lib/format';
import { Loader2 } from 'lucide-react';

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
}

function InlineCellEditor({
  initialValue,
  onSave,
  onCancel,
  isSaving,
}: {
  initialValue: string;
  onSave: (value: string) => void;
  onCancel: () => void;
  isSaving: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState(initialValue);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      onSave(value);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onCancel();
    }
  };

  if (isSaving) {
    return <Loader2 className="h-3 w-3 animate-spin" />;
  }

  return (
    <Input
      ref={inputRef}
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={() => onSave(value)}
      onKeyDown={handleKeyDown}
      className="h-7 text-xs px-1"
    />
  );
}

export function AttributeTable({ datasetId, canEdit = false }: AttributeTableProps) {
  const { t } = useTranslation('dataset');
  const [cursor, setCursor] = useState(0);
  const [cursorHistory, setCursorHistory] = useState<number[]>([0]);
  const [editingCell, setEditingCell] = useState<EditingCell | null>(null);
  const [columnFilters, setColumnFilters] = useState<Record<string, string>>({});
  const [pageSize, setPageSize] = useState(DEFAULT_ROWS_PAGE_SIZE);
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

  const { data, isLoading, isFetching } = useDatasetRows(
    datasetId,
    pageSize,
    cursor,
    activeFilters,
  );

  const handleFilterChange = useCallback((colName: string, value: string) => {
    setColumnFilters((prev) => ({ ...prev, [colName]: value }));
  }, []);

  const handleCellSave = async (rowGid: number, column: string, newValue: string) => {
    setEditingCell(null);
    try {
      await updateFeature.mutateAsync({
        datasetId,
        gid: rowGid,
        properties: { [column]: newValue || null },
      });
      toast.success(t('attributes.editSaved'));
    } catch {
      toast.error(t('attributes.editFailed'));
    }
  };

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

  const columns = useMemo<ColumnDef<Record<string, unknown>>[]>(() => {
    if (!data?.columns) return [];
    return data.columns.map((col) => ({
      accessorKey: col.name,
      header: `${col.name} (${col.type})`,
      enableColumnFilter: !NON_FILTERABLE_COLUMNS.has(col.name),
      cell: (info) => {
        const rowData = info.row.original;
        const gid = rowData.gid as number;
        const isEditing =
          editingCell?.rowGid === gid && editingCell?.column === col.name;

        if (isEditing) {
          return (
            <InlineCellEditor
              initialValue={String(info.getValue() ?? '')}
              onSave={(val) => handleCellSave(gid, col.name, val)}
              onCancel={() => setEditingCell(null)}
              isSaving={updateFeature.isPending}
            />
          );
        }

        const cellValue = String(info.getValue() ?? '');

        if (canEdit && !NON_EDITABLE_COLUMNS.has(col.name)) {
          return (
            <button
              type="button"
              className="rounded px-0.5 -mx-0.5 text-left hover:bg-muted/50"
              onClick={() => setEditingCell({ rowGid: gid, column: col.name })}
            >
              {cellValue}
            </button>
          );
        }

        return cellValue;
      },
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.columns, editingCell, canEdit, updateFeature.isPending]);

  const table = useReactTable({
    data: data?.rows ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

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

  if (effectiveTotal === 0 && !activeFilters && (!data?.rows || data.rows.length === 0)) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        {t('attributes.noData')}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="rounded-md border overflow-auto">
        <Table>
          <TableHeader className="sticky top-0 bg-muted/80 backdrop-blur-sm">
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead key={header.id}>
                    {header.isPlaceholder
                      ? null
                      : flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )}
                  </TableHead>
                ))}
              </TableRow>
            ))}
            {/* Filter row */}
            <TableRow>
              {table.getHeaderGroups()[0]?.headers.map((header) => (
                <TableHead key={`filter-${header.id}`} className="py-1">
                  {!NON_FILTERABLE_COLUMNS.has(header.column.id) ? (
                    <Input
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
            {table.getRowModel().rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={columns.length} className="text-center text-muted-foreground py-8">
                  {t('attributes.noResults')}
                </TableCell>
              </TableRow>
            ) : (
              table.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id} className="max-w-xs truncate">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between text-sm">
        <div className="flex items-center gap-3">
          <span className="text-muted-foreground">
            {isExact
              ? t('attributes.showingExact', { start: formatNumber(rangeStart), end: formatNumber(rangeEnd), total: formatNumber(effectiveTotal) })
              : t('attributes.showing', { start: formatNumber(rangeStart), end: formatNumber(rangeEnd), total: formatNumber(effectiveTotal) })}
            {isFetching && (
              <Loader2 className="inline h-3 w-3 animate-spin ml-2" />
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
              <SelectTrigger className="h-7 w-[70px] text-xs">
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
