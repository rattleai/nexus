import { useState, useMemo, useCallback } from "react"
import { useTranslation } from "react-i18next"
import { Link } from "@tanstack/react-router"
import {
  Search,
  MoreHorizontal,
  Eye,
  Copy,
  Lock,
  FileDown,
  Trash2,
  ClipboardList,
  Play,
  CheckSquare,
  BarChart3,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Checkbox } from "@/components/ui/checkbox"
import { Card, CardContent } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { PageHeader } from "@/components/page-header"
import { LoadingState } from "@/components/loading-state"
import { ErrorState } from "@/components/error-state"
import { EmptyState } from "@/components/empty-state"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { useProducts } from "@/hooks/use-products"
import {
  useConfigurations,
  useCloneSession,
  useDeleteSession,
  useBulkAction,
  useExportSession,
} from "@/hooks/use-configurations"
import { useLockSession } from "@/hooks/use-configurator"
import type { ConfigurationSession } from "@/types/configurator"

// ── Status badge mapping ────────────────────────────────

const statusVariant: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  in_progress: "secondary",
  complete: "default",
  locked: "outline",
  invalid: "destructive",
}

const statusLabel: Record<string, string> = {
  in_progress: "In Progress",
  complete: "Complete",
  locked: "Locked",
  invalid: "Invalid",
}

// ── Currency formatter ──────────────────────────────────

const currencyFormatter = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "EUR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

function formatCurrency(value: number | null | undefined): string {
  if (value == null) return "-"
  return currencyFormatter.format(value)
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  })
}

// ── Main component ──────────────────────────────────────

export function ConfigurationsList() {
  const { t } = useTranslation()

  const [search, setSearch] = useState("")
  const [statusFilter, setStatusFilter] = useState<string>("all")
  const [productFilter, setProductFilter] = useState<string>("all")
  const [bomFilter, setBomFilter] = useState<string>("all")
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  const filters = useMemo(
    () => ({
      status: statusFilter !== "all" ? statusFilter : undefined,
      product_id: productFilter !== "all" ? productFilter : undefined,
      search: search.trim() || undefined,
      has_bom: bomFilter !== "all" ? bomFilter : undefined,
    }),
    [statusFilter, productFilter, search, bomFilter],
  )

  const { data, isLoading, error, refetch } = useConfigurations(filters)
  const { data: productsData } = useProducts()

  const cloneSession = useCloneSession()
  const deleteSession = useDeleteSession()
  const lockSession = useLockSession()
  const bulkAction = useBulkAction()
  const exportSession = useExportSession()

  const products = productsData?.items ?? []
  const productMap = useMemo(
    () => new Map(products.map((p) => [p.id, p])),
    [products],
  )

  const sessions = data?.items ?? []

  const allSelected = sessions.length > 0 && selectedIds.size === sessions.length
  const someSelected = selectedIds.size > 0

  const toggleAll = useCallback(() => {
    if (allSelected) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(sessions.map((s) => s.id)))
    }
  }, [allSelected, sessions])

  const toggleOne = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }, [])

  const handleBulkLock = () => {
    bulkAction.mutate(
      { session_ids: Array.from(selectedIds), action: "lock" },
      { onSuccess: () => setSelectedIds(new Set()) },
    )
  }

  const handleBulkDelete = () => {
    bulkAction.mutate(
      { session_ids: Array.from(selectedIds), action: "delete" },
      { onSuccess: () => setSelectedIds(new Set()) },
    )
  }

  const handleBulkResolveBom = () => {
    bulkAction.mutate(
      { session_ids: Array.from(selectedIds), action: "resolve_bom" },
      { onSuccess: () => setSelectedIds(new Set()) },
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("nav.configurations", "Configurations")}
        description="Manage product configurations and their bills of materials"
        actions={
          <Button variant="outline" asChild>
            <Link to="/configurations/bom-analysis">
              <BarChart3 className="mr-2 h-4 w-4" />
              BOM Analysis
            </Link>
          </Button>
        }
      />

      {/* Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search configurations..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select value={productFilter} onValueChange={setProductFilter}>
          <SelectTrigger className="w-full sm:w-[180px]">
            <SelectValue placeholder="Product" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All products</SelectItem>
            {products.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-full sm:w-[150px]">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="in_progress">In Progress</SelectItem>
            <SelectItem value="complete">Complete</SelectItem>
            <SelectItem value="locked">Locked</SelectItem>
            <SelectItem value="invalid">Invalid</SelectItem>
          </SelectContent>
        </Select>
        <Select value={bomFilter} onValueChange={setBomFilter}>
          <SelectTrigger className="w-full sm:w-[140px]">
            <SelectValue placeholder="BOM" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All</SelectItem>
            <SelectItem value="true">BOM Resolved</SelectItem>
            <SelectItem value="false">No BOM</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Bulk actions toolbar */}
      {someSelected && (
        <div className="flex items-center gap-2 rounded-lg border bg-muted/50 p-3">
          <span className="text-sm font-medium">
            {selectedIds.size} selected
          </span>
          <div className="flex-1" />
          <Button variant="outline" size="sm" onClick={handleBulkResolveBom} disabled={bulkAction.isPending}>
            <CheckSquare className="mr-1.5 h-3.5 w-3.5" />
            Resolve BOMs
          </Button>
          <Button variant="outline" size="sm" onClick={handleBulkLock} disabled={bulkAction.isPending}>
            <Lock className="mr-1.5 h-3.5 w-3.5" />
            Lock
          </Button>
          <ConfirmDialog
            title="Delete configurations"
            description={`Are you sure you want to delete ${selectedIds.size} configuration(s)? Locked configurations will be skipped.`}
            variant="destructive"
            confirmLabel="Delete"
            onConfirm={handleBulkDelete}
          >
            <Button variant="outline" size="sm" disabled={bulkAction.isPending}>
              <Trash2 className="mr-1.5 h-3.5 w-3.5" />
              Delete
            </Button>
          </ConfirmDialog>
        </div>
      )}

      {/* Content */}
      <Card>
        <CardContent className="p-6">
          {isLoading ? (
            <LoadingState variant="skeleton" rows={5} />
          ) : error ? (
            <ErrorState
              message={error instanceof Error ? error.message : "Failed to load configurations."}
              onRetry={() => refetch()}
            />
          ) : sessions.length === 0 ? (
            <EmptyState
              icon={ClipboardList}
              title="No configurations yet"
              description="Configurations are created when you configure a product in the Configurator."
            />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[40px]">
                      <Checkbox
                        checked={allSelected}
                        onCheckedChange={toggleAll}
                        aria-label="Select all"
                      />
                    </TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead>Product</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-center">Selections</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead className="w-[50px]">
                      <span className="sr-only">Actions</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sessions.map((session) => {
                    const product = productMap.get(session.product_id)
                    return (
                      <TableRow key={session.id}>
                        <TableCell>
                          <Checkbox
                            checked={selectedIds.has(session.id)}
                            onCheckedChange={() => toggleOne(session.id)}
                            aria-label={`Select ${session.name || session.id}`}
                          />
                        </TableCell>
                        <TableCell className="font-medium">
                          <Link
                            to="/configurations/$sessionId"
                            params={{ sessionId: session.id }}
                            className="hover:underline"
                          >
                            {session.name || session.id.slice(0, 8) + "..."}
                          </Link>
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {product ? (
                            <Link
                              to="/products/$productId"
                              params={{ productId: product.id }}
                              className="hover:underline"
                            >
                              {product.name}
                            </Link>
                          ) : (
                            "-"
                          )}
                        </TableCell>
                        <TableCell>
                          <Badge variant={statusVariant[session.status] ?? "secondary"}>
                            {statusLabel[session.status] ?? session.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-center tabular-nums">
                          {session.selections?.length ?? 0}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {formatDate(session.created_at)}
                        </TableCell>
                        <TableCell>
                          <SessionActions
                            session={session}
                            productId={session.product_id}
                            onClone={() => cloneSession.mutate(session.id)}
                            onLock={() => lockSession.mutate(session.id)}
                            onDelete={() => deleteSession.mutate(session.id)}
                            onExport={(format) =>
                              exportSession.mutate({ sessionId: session.id, format })
                            }
                          />
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

// ── Row Actions ─────────────────────────────────────────

function SessionActions({
  session,
  productId,
  onClone,
  onLock,
  onDelete,
  onExport,
}: {
  session: ConfigurationSession
  productId: string
  onClone: () => void
  onLock: () => void
  onDelete: () => void
  onExport: (format: "csv" | "json") => void
}) {
  const canLock = session.is_valid && session.is_complete && session.status !== "locked"
  const canDelete = session.status !== "locked"

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="h-8 w-8">
          <MoreHorizontal className="h-4 w-4" />
          <span className="sr-only">Open menu</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem asChild>
          <Link to="/configurations/$sessionId" params={{ sessionId: session.id }}>
            <Eye className="mr-2 h-4 w-4" />
            View Details
          </Link>
        </DropdownMenuItem>
        {session.status !== "locked" && (
          <DropdownMenuItem asChild>
            <Link to="/configurator/$productId" params={{ productId }}>
              <Play className="mr-2 h-4 w-4" />
              Resume in Configurator
            </Link>
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={onClone}>
          <Copy className="mr-2 h-4 w-4" />
          Clone
        </DropdownMenuItem>
        {canLock && (
          <DropdownMenuItem onClick={onLock}>
            <Lock className="mr-2 h-4 w-4" />
            Lock
          </DropdownMenuItem>
        )}
        <DropdownMenuItem onClick={() => onExport("csv")}>
          <FileDown className="mr-2 h-4 w-4" />
          Export CSV
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => onExport("json")}>
          <FileDown className="mr-2 h-4 w-4" />
          Export JSON
        </DropdownMenuItem>
        {canDelete && (
          <>
            <DropdownMenuSeparator />
            <ConfirmDialog
              title="Delete configuration"
              description={`Are you sure you want to delete "${session.name || session.id}"? This action cannot be undone.`}
              variant="destructive"
              confirmLabel="Delete"
              onConfirm={onDelete}
            >
              <DropdownMenuItem
                onSelect={(e) => e.preventDefault()}
                className="text-destructive focus:text-destructive"
              >
                <Trash2 className="mr-2 h-4 w-4" />
                Delete
              </DropdownMenuItem>
            </ConfirmDialog>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
