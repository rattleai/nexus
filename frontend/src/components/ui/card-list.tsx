import type { ColumnDef, Row } from "@tanstack/react-table"
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
  type ColumnFiltersState,
} from "@tanstack/react-table"
import { useState } from "react"
import { ChevronLeft, ChevronRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

interface CardListProps<TData, TValue> {
  columns: ColumnDef<TData, TValue>[]
  data: TData[]
  searchKey?: string
  searchPlaceholder?: string
  pageSize?: number
  /** Column IDs to show as the card title (first match used) */
  titleColumn?: string
  /** Column IDs to hide from the card body (e.g. the title column) */
  hideColumns?: string[]
  onRowClick?: (row: Row<TData>) => void
}

/**
 * Mobile-friendly card-based list view.
 * Renders each table row as a card with key-value pairs.
 * Drop-in replacement for DataTable on small screens.
 */
export function CardList<TData, TValue>({
  columns,
  data,
  searchKey,
  searchPlaceholder = "Search...",
  pageSize = 10,
  titleColumn,
  hideColumns = [],
  onRowClick,
}: CardListProps<TData, TValue>) {
  const [sorting, setSorting] = useState<SortingState>([])
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    state: { sorting, columnFilters },
    initialState: { pagination: { pageSize } },
  })

  const hiddenSet = new Set(hideColumns)
  if (titleColumn) hiddenSet.add(titleColumn)

  return (
    <div className="space-y-3">
      {searchKey && (
        <Input
          placeholder={searchPlaceholder}
          value={(table.getColumn(searchKey)?.getFilterValue() as string) ?? ""}
          onChange={(e) => table.getColumn(searchKey)?.setFilterValue(e.target.value)}
          className="w-full"
        />
      )}

      {table.getRowModel().rows.length === 0 ? (
        <div className="py-12 text-center text-muted-foreground">No results.</div>
      ) : (
        <div className="space-y-2">
          {table.getRowModel().rows.map((row) => (
            <button
              type="button"
              key={row.id}
              aria-label={
                titleColumn
                  ? `View ${row.getValue(titleColumn) ?? `item ${row.index + 1}`}`
                  : `View item ${row.index + 1}`
              }
              className={cn(
                "w-full rounded-lg border bg-card p-4 text-left shadow-sm transition-colors",
                onRowClick && "hover:bg-accent/50 active:bg-accent cursor-pointer",
              )}
              onClick={() => onRowClick?.(row)}
              disabled={!onRowClick}
            >
              {/* Title */}
              {titleColumn && row.getVisibleCells().find((c) => c.column.id === titleColumn) && (
                <div className="mb-2 font-semibold text-card-foreground">
                  {flexRender(
                    row.getVisibleCells().find((c) => c.column.id === titleColumn)!.column
                      .columnDef.cell,
                    row.getVisibleCells().find((c) => c.column.id === titleColumn)!.getContext(),
                  )}
                </div>
              )}

              {/* Key-value pairs */}
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                {row.getVisibleCells().map((cell) => {
                  if (hiddenSet.has(cell.column.id)) return null
                  const header =
                    typeof cell.column.columnDef.header === "string"
                      ? cell.column.columnDef.header
                      : cell.column.id
                  return (
                    <div key={cell.id} className="contents">
                      <span className="text-muted-foreground truncate">{header}</span>
                      <span className="text-card-foreground truncate">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </span>
                    </div>
                  )
                })}
              </div>
            </button>
          ))}
        </div>
      )}

      {table.getPageCount() > 1 && (
        <div className="flex items-center justify-between">
          <span className="text-sm text-muted-foreground">
            Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
              aria-label="Previous page"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
              aria-label="Next page"
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
