import type { ReactNode } from "react"
import type { UseQueryResult } from "@tanstack/react-query"
import type { ColumnDef } from "@tanstack/react-table"
import type { LucideIcon } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { DataTable } from "@/components/data-table"
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
            <DataTable
              columns={columns}
              data={extractItems(data)}
              searchKey={searchKey}
              searchPlaceholder={searchPlaceholder}
              pageSize={pageSize}
            />
          )}
        </CardContent>
      </Card>
    </div>
  )
}
