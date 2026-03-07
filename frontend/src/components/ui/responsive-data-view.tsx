import type { ColumnDef, Row } from "@tanstack/react-table"
import { useIsMobile } from "@/hooks/use-mobile"
import { DataTable } from "@/components/data-table"
import { CardList } from "@/components/ui/card-list"

interface ResponsiveDataViewProps<TData, TValue> {
  columns: ColumnDef<TData, TValue>[]
  data: TData[]
  searchKey?: string
  searchPlaceholder?: string
  pageSize?: number
  /** Column ID to use as card title on mobile */
  titleColumn?: string
  /** Column IDs to hide from the card body on mobile */
  hideColumns?: string[]
  onRowClick?: (row: Row<TData>) => void
}

/**
 * Renders a DataTable on desktop and a CardList on mobile.
 * Drop-in replacement for DataTable with mobile support.
 */
export function ResponsiveDataView<TData, TValue>({
  columns,
  data,
  searchKey,
  searchPlaceholder,
  pageSize,
  titleColumn,
  hideColumns,
  onRowClick,
}: ResponsiveDataViewProps<TData, TValue>) {
  const isMobile = useIsMobile()

  if (isMobile) {
    return (
      <CardList
        columns={columns}
        data={data}
        searchKey={searchKey}
        searchPlaceholder={searchPlaceholder}
        pageSize={pageSize}
        titleColumn={titleColumn}
        hideColumns={hideColumns}
        onRowClick={onRowClick}
      />
    )
  }

  return (
    <DataTable
      columns={columns}
      data={data}
      searchKey={searchKey}
      searchPlaceholder={searchPlaceholder}
      pageSize={pageSize}
    />
  )
}
