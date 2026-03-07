import type { ReactNode } from "react"
import type { UseQueryResult } from "@tanstack/react-query"
import type { ColumnDef, Row } from "@tanstack/react-table"
import type { LucideIcon } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { ResponsiveDataView } from "@/components/ui/responsive-data-view"
import { LoadingState } from "@/components/loading-state"
import { ErrorState } from "@/components/error-state"
import { EmptyState } from "@/components/empty-state"
import { PageHeader } from "@/components/page-header"
import type { CursorPaginatedResponse, PaginatedResponse } from "@/types/api"

type QueryData<T> = T[] | PaginatedResponse<T> | CursorPaginatedResponse<T>

interface ResourcePageProps<T> {
  title: string
  description?: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  queryResult: UseQueryResult<QueryData<T>, any>
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  columns: ColumnDef<T, any>[]
  searchKey?: string
  searchPlaceholder?: string
  pageSize?: number
  /** Column ID to use as card title on mobile */
  titleColumn?: string
  /** Column IDs to hide from the card body on mobile */
  hideColumns?: string[]
  onRowClick?: (row: Row<T>) => void
  emptyState: {
    icon?: LucideIcon
    title: string
    description?: string
    action?: ReactNode
  }
  actions?: ReactNode
  headerContent?: ReactNode
}

function extractItems<T>(data: QueryData<T>): T[] {
  if (Array.isArray(data)) return data
  return data.items
}

export function ResourcePage<T>({
  title,
  description,
  queryResult,
  columns,
  searchKey,
  searchPlaceholder,
  pageSize,
  titleColumn,
  hideColumns,
  onRowClick,
  emptyState,
  actions,
  headerContent,
}: ResourcePageProps<T>) {
  const { data, isLoading, error, refetch } = queryResult

  return (
    <div className="space-y-6">
      <PageHeader title={title} description={description} actions={actions} />
      {headerContent}
      <Card>
        <CardContent className="p-6">
          {isLoading ? (
            <LoadingState variant="skeleton" rows={5} />
          ) : error ? (
            <ErrorState
              message={error instanceof Error ? error.message : "Failed to load data."}
              onRetry={() => refetch()}
            />
          ) : !data || extractItems(data).length === 0 ? (
            <EmptyState
              icon={emptyState.icon}
              title={emptyState.title}
              description={emptyState.description}
              action={emptyState.action}
            />
          ) : (
            <ResponsiveDataView
              columns={columns}
              data={extractItems(data)}
              searchKey={searchKey}
              searchPlaceholder={searchPlaceholder}
              pageSize={pageSize}
              titleColumn={titleColumn}
              hideColumns={hideColumns}
              onRowClick={onRowClick}
            />
          )}
        </CardContent>
      </Card>
    </div>
  )
}
