import { useState } from 'react';
import { AttributeTable, type AttributeTableProps } from '@/components/dataset/AttributeTable';
import { DockedPanelFrame, DockedPanelHeader, type DockedPanelHeaderProps } from '@/components/dataset/DockedPanelFrame';
import type { TableShellSize } from '@/components/dataset/hooks/use-table-shell-size';

interface AttributeTableShellProps extends Omit<DockedPanelHeaderProps, 'count' | 'columns'> {
  /** The resize handle's sizing and name; omitted, the host's frame sizes itself. */
  resize?: { size: TableShellSize; label: string };
  table: Omit<AttributeTableProps, 'renderHeader'>;
  /** Strings for the notice that offers to narrow the table to the selected feature. */
  selectionLabels: {
    missing: string;
    show: string;
    showing: string;
    showAll: string;
    hiddenByFilters: string;
  };
}

/**
 * A docked panel frame around an attribute table, whose header carries the
 * table's count and Columns menu. The host supplies the outer frame (a dock
 * or a sheet) sized by `resize.size`, and everything map-specific.
 */
export function AttributeTableShell({ resize, table, selectionLabels, notice, ...header }: AttributeTableShellProps) {
  // The selected feature can sit on a page the table has not loaded; this
  // narrows the rows to it through the rows route's `gid` param, on top of
  // the host's filters. It ends when nothing is selected.
  const [selectedOnly, setSelectedOnly] = useState(false);
  const filterToSelected = selectedOnly && table.selectedGid != null;

  return (
    <DockedPanelFrame resize={resize}>
      <AttributeTable
        {...table}
        onlyGid={filterToSelected ? table.selectedGid! : undefined}
        renderHeader={({ count, columns, selectedMissing }) => {
          const selectionNotice = filterToSelected
            ? {
              text: selectedMissing ? selectionLabels.hiddenByFilters : selectionLabels.showing,
              action: selectionLabels.showAll,
              narrow: false,
            }
            : selectedMissing
              ? { text: selectionLabels.missing, action: selectionLabels.show, narrow: true }
              : null;
          return (
            <DockedPanelHeader
              {...header}
              count={count}
              columns={columns}
              notice={(notice || selectionNotice) && (
                <>
                  {notice}
                  {selectionNotice && (
                    <>
                      <span role="status">{selectionNotice.text}</span>
                      <button
                        type="button"
                        className="cursor-pointer text-foreground underline underline-offset-2"
                        onClick={() => setSelectedOnly(selectionNotice.narrow)}
                      >
                        {selectionNotice.action}
                      </button>
                    </>
                  )}
                </>
              )}
            />
          );
        }}
      />
    </DockedPanelFrame>
  );
}
