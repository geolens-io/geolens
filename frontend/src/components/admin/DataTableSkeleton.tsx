import { TableRow, TableCell } from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';

interface ColumnSpec {
  width: string;
  rounded?: boolean;
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
            <TableCell key={j}>
              <Skeleton className={`h-4 ${col.width}${col.rounded ? ' rounded-full' : ''}`} />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}
