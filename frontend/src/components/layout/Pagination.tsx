import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';

interface PaginationProps {
  total: number;
  offset: number;
  limit: number;
  onPageChange: (offset: number) => void;
}

export function Pagination({ total, offset, limit, onPageChange }: PaginationProps) {
  const { t } = useTranslation();
  if (total <= 0) return null;

  const start = offset + 1;
  const end = Math.min(offset + limit, total);
  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.ceil(total / limit);
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;

  return (
    <div className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <span className="text-sm text-muted-foreground">
        {t('pagination.showing', { start, end, total })}
      </span>

      <div className="flex w-full items-center justify-between gap-2 sm:w-auto sm:justify-end">
        <Button
          variant="outline"
          size="sm"
          disabled={!hasPrev}
          onClick={() => onPageChange(Math.max(0, offset - limit))}
          className="whitespace-nowrap"
        >
          <ChevronLeft className="size-4 rtl-mirror" />
          {t('pagination.previous')}
        </Button>

        <span className="px-2 text-sm tabular-nums text-muted-foreground whitespace-nowrap">
          {t('pagination.pageOf', { currentPage, totalPages })}
        </span>

        <Button
          variant="outline"
          size="sm"
          disabled={!hasNext}
          onClick={() => onPageChange(offset + limit)}
          className="whitespace-nowrap"
        >
          {t('pagination.next')}
          <ChevronRight className="size-4 rtl-mirror" />
        </Button>
      </div>
    </div>
  );
}
