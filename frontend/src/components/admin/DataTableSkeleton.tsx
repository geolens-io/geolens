import { TableRow, TableCell } from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';

interface ColumnSpec {
  width: string;
  rounded?: boolean;
  /** Applied to the cell, so a column can hide at the widths its header does. */
  cellClassName?: string;
}

interface DataTableSkeletonProps {
  columns: ColumnSpec[];
  rows?: number;
}

export function DataTableSkeleton({ columns, rows = 5 }: DataTableSkeletonProps) {
  return (
    <>
      {Array.from({ length: rows }).map((_, i) => (
        <TableRow key={i}>
          {columns.map((col, j) => (
            <TableCell key={j} className={col.cellClassName}>
              <Skeleton className={`h-4 ${col.width}${col.rounded ? ' rounded-full' : ''}`} />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}
