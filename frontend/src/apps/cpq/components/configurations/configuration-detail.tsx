import { useState, useMemo } from "react"
import { Link } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import {
  ArrowLeft,
  Play,
  Copy,
  Lock,
  FileDown,
  Package,
  DollarSign,
  ListChecks,
  History,
  Search,
  ChevronRight,
  ChevronDown,
  Zap,
} from "lucide-react"
import { useConfiguratorSession, useLockSession, useResolveBOM } from "@/apps/cpq/hooks/use-configurator"
import { useSessionBOM, useSessionPricing, useCloneSession, useExportSession } from "@/apps/cpq/hooks/use-configurations"
import { useProduct } from "@/apps/cpq/hooks/use-products"
import { useCharacteristicAssignments, useCharacteristics } from "@/apps/cpq/hooks/use-characteristics"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { ConfiguredBOM, ConfigurationPricing } from "@/apps/cpq/types/configurator"

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
    hour: "2-digit",
    minute: "2-digit",
  })
}

// ── Resolved BOM item type ──────────────────────────────

interface ResolvedItem {
  part_number: string
  part_name: string
  quantity: number
  unit: string
  unit_cost: number
  level: number
  parent_part: string | null
  item_type: string
  lead_time_days?: number | null
}

function parseResolvedItems(bom: ConfiguredBOM | null | undefined): ResolvedItem[] {
  if (!bom?.resolved_items) return []
  return bom.resolved_items.map((item) => ({
    part_number: (item as Record<string, unknown>).part_number as string ?? "",
    part_name: (item as Record<string, unknown>).part_name as string ?? "",
    quantity: Number((item as Record<string, unknown>).quantity) || 0,
    unit: (item as Record<string, unknown>).unit as string ?? "EA",
    unit_cost: Number((item as Record<string, unknown>).unit_cost) || 0,
    level: Number((item as Record<string, unknown>).level) || 0,
    parent_part: ((item as Record<string, unknown>).parent_part as string) ?? null,
    item_type: (item as Record<string, unknown>).item_type as string ?? "component",
    lead_time_days: (item as Record<string, unknown>).lead_time_days as number | null ?? null,
  }))
}

// ── Item type badge variant ─────────────────────────────

const itemTypeBadgeVariant: Record<string, "default" | "secondary" | "outline"> = {
  component: "default",
  sub_assembly: "secondary",
  phantom: "outline",
  reference: "outline",
}

// ── CSV export ──────────────────────────────────────────

function exportToCSV(items: ResolvedItem[], totalCost: number | null) {
  const headers = ["Level", "Part Number", "Part Name", "Type", "Quantity", "UOM", "Unit Cost", "Extended Cost"]
  const rows = items.map((item) => [
    item.level.toString(),
    item.part_number,
    `"${item.part_name.replace(/"/g, '""')}"`,
    item.item_type,
    item.quantity.toString(),
    item.unit,
    item.unit_cost.toFixed(2),
    (item.quantity * item.unit_cost).toFixed(2),
  ])
  rows.push([])
  rows.push(["", "", "", "", "", "", "Total Cost:", totalCost?.toFixed(2) ?? "N/A"])
  const csvContent = [headers.join(","), ...rows.map((row) => row.join(","))].join("\n")
  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = `bom-${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

// ── Selections Tab ──────────────────────────────────────

function SelectionsTab({ sessionId, productId }: { sessionId: string; productId: string }) {
  const { data: session } = useConfiguratorSession(sessionId)
  const { data: assignmentsData } = useCharacteristicAssignments(productId)
  const { data: characteristicsData } = useCharacteristics()

  const charMap = useMemo(() => {
    const m = new Map<string, { name: string; group_id: string | null }>()
    for (const c of characteristicsData?.items ?? []) {
      m.set(c.id, { name: c.name, group_id: c.group_id })
    }
    return m
  }, [characteristicsData])

  const selections = session?.selections ?? []

  if (selections.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <ListChecks className="mx-auto h-12 w-12 text-muted-foreground/40 mb-3" />
          <p className="text-sm text-muted-foreground">No selections made yet.</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Selections ({selections.length})</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Characteristic</TableHead>
              <TableHead>Value</TableHead>
              <TableHead>Source</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {selections.map((sel) => {
              const charInfo = charMap.get(sel.characteristic_id)
              return (
                <TableRow key={sel.id}>
                  <TableCell className="font-medium">
                    {charInfo?.name ?? sel.characteristic_id.slice(0, 8)}
                  </TableCell>
                  <TableCell>{sel.value}</TableCell>
                  <TableCell>
                    {sel.is_auto_set ? (
                      <Badge variant="secondary" className="text-[10px]">
                        <Zap className="mr-1 h-3 w-3" />
                        Auto-set
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground text-sm">Manual</span>
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

// ── BOM Tab ─────────────────────────────────────────────

function BOMTab({ sessionId }: { sessionId: string }) {
  const { data: bom, isLoading, error } = useSessionBOM(sessionId)
  const resolveBOM = useResolveBOM()
  const [bomSearch, setBomSearch] = useState("")
  const [viewMode, setViewMode] = useState<"tree" | "flat">("tree")

  const resolvedItems = useMemo(() => parseResolvedItems(bom), [bom])

  const filteredItems = useMemo(() => {
    if (!bomSearch.trim()) return resolvedItems
    const q = bomSearch.toLowerCase()
    return resolvedItems.filter(
      (item) =>
        item.part_number.toLowerCase().includes(q) ||
        item.part_name.toLowerCase().includes(q),
    )
  }, [resolvedItems, bomSearch])

  const totalExtendedCost = useMemo(
    () => resolvedItems.reduce((sum, item) => sum + item.quantity * item.unit_cost, 0),
    [resolvedItems],
  )

  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const item of resolvedItems) {
      counts[item.item_type] = (counts[item.item_type] || 0) + 1
    }
    return counts
  }, [resolvedItems])

  if (isLoading) return <Skeleton className="h-40 w-full" />

  // No BOM resolved yet (null from 404, or error)
  if (!bom) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <Package className="mx-auto h-12 w-12 text-muted-foreground/40 mb-3" />
          <p className="text-sm text-muted-foreground mb-4">
            No resolved BOM yet. Click below to generate the bill of materials.
          </p>
          <Button
            onClick={() => resolveBOM.mutate(sessionId)}
            disabled={resolveBOM.isPending}
          >
            {resolveBOM.isPending ? "Resolving..." : "Resolve BOM"}
          </Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Card>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs text-muted-foreground">Total Components</p>
            <p className="text-2xl font-bold tabular-nums">{bom?.total_components ?? resolvedItems.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs text-muted-foreground">Total Cost</p>
            <p className="text-2xl font-bold tabular-nums">
              {formatCurrency(bom?.total_cost ?? totalExtendedCost)}
            </p>
          </CardContent>
        </Card>
        {Object.entries(typeCounts).map(([type, count]) => (
          <Card key={type}>
            <CardContent className="pt-4 pb-3">
              <p className="text-xs text-muted-foreground capitalize">{type.replace("_", " ")}s</p>
              <p className="text-2xl font-bold tabular-nums">{count}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Controls */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search parts..."
            value={bomSearch}
            onChange={(e) => setBomSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <div className="flex rounded-md border">
          <Button
            variant={viewMode === "tree" ? "secondary" : "ghost"}
            size="sm"
            className="rounded-r-none"
            onClick={() => setViewMode("tree")}
          >
            Tree
          </Button>
          <Button
            variant={viewMode === "flat" ? "secondary" : "ghost"}
            size="sm"
            className="rounded-l-none"
            onClick={() => setViewMode("flat")}
          >
            Flat
          </Button>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => exportToCSV(resolvedItems, bom?.total_cost ?? totalExtendedCost)}
        >
          <FileDown className="mr-1.5 h-3.5 w-3.5" />
          Export CSV
        </Button>
      </div>

      {/* BOM Table */}
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[180px]">Part Number</TableHead>
                  <TableHead>Part Name</TableHead>
                  <TableHead className="w-[90px]">Type</TableHead>
                  <TableHead className="w-[70px] text-right">Qty</TableHead>
                  <TableHead className="w-[60px]">UOM</TableHead>
                  <TableHead className="w-[110px] text-right">Unit Cost</TableHead>
                  <TableHead className="w-[110px] text-right">Extended</TableHead>
                  <TableHead className="w-[90px] text-right">Lead Time</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredItems.map((item, index) => {
                  const extendedCost = item.quantity * item.unit_cost
                  const indentPx = viewMode === "tree" ? item.level * 20 : 0

                  return (
                    <TableRow key={`${item.part_number}-${index}`}>
                      <TableCell
                        className="font-mono text-xs"
                        style={{ paddingLeft: `${12 + indentPx}px` }}
                      >
                        {viewMode === "tree" && item.level > 0 && (
                          <span className="text-muted-foreground mr-1.5">
                            {"  ".repeat(item.level - 1)}+-{" "}
                          </span>
                        )}
                        {item.part_number}
                      </TableCell>
                      <TableCell className="text-sm">{item.part_name}</TableCell>
                      <TableCell>
                        <Badge
                          variant={itemTypeBadgeVariant[item.item_type] ?? "secondary"}
                          className="text-[10px] capitalize"
                        >
                          {item.item_type.replace("_", " ")}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right tabular-nums font-medium">
                        {item.quantity}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-xs">
                        {item.unit}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatCurrency(item.unit_cost)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums font-medium">
                        {formatCurrency(extendedCost)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">
                        {item.lead_time_days != null ? `${item.lead_time_days}d` : "-"}
                      </TableCell>
                    </TableRow>
                  )
                })}

                {/* Total row */}
                <TableRow className="bg-muted/50 font-semibold">
                  <TableCell colSpan={3} className="text-right">Total</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {filteredItems.reduce((s, i) => s + i.quantity, 0)}
                  </TableCell>
                  <TableCell />
                  <TableCell />
                  <TableCell className="text-right tabular-nums">
                    {formatCurrency(totalExtendedCost)}
                  </TableCell>
                  <TableCell />
                </TableRow>
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

// ── Pricing Tab ─────────────────────────────────────────

function PricingTab({ sessionId }: { sessionId: string }) {
  const { data: pricing, isLoading, error } = useSessionPricing(sessionId)

  if (isLoading) return <Skeleton className="h-40 w-full" />

  if (!pricing || error) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <DollarSign className="mx-auto h-12 w-12 text-muted-foreground/40 mb-3" />
          <p className="text-sm text-muted-foreground">
            No pricing resolved for this configuration. Resolve the BOM first to generate pricing.
          </p>
        </CardContent>
      </Card>
    )
  }

  const breakdownItems = (pricing.price_breakdown ?? []) as { rule?: string; type?: string; amount?: string }[]

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {/* Price Breakdown */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Price Breakdown</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex justify-between text-sm">
            <span className="text-muted-foreground">Base Price</span>
            <span className="font-medium tabular-nums">{formatCurrency(pricing.base_price)}</span>
          </div>
          {breakdownItems.map((item, i) => (
            <div key={i} className="flex justify-between text-sm">
              <span className="text-muted-foreground">{item.rule ?? item.type ?? "Adjustment"}</span>
              <span className="tabular-nums">{formatCurrency(Number(item.amount ?? 0))}</span>
            </div>
          ))}
          <div className="border-t pt-3 flex justify-between text-sm font-semibold">
            <span>Final Price</span>
            <span className="tabular-nums">{formatCurrency(pricing.final_price)}</span>
          </div>
        </CardContent>
      </Card>

      {/* Margin Analysis */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Margin Analysis</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex justify-between text-sm">
            <span className="text-muted-foreground">Total Cost (BOM)</span>
            <span className="tabular-nums">{formatCurrency(pricing.total_cost)}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-muted-foreground">Final Price</span>
            <span className="tabular-nums">{formatCurrency(pricing.final_price)}</span>
          </div>
          <div className="border-t pt-3 flex justify-between text-sm">
            <span className="text-muted-foreground">Margin Amount</span>
            <span className="font-medium tabular-nums">{formatCurrency(pricing.margin_amount)}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-muted-foreground">Margin %</span>
            <span className={`font-semibold tabular-nums ${pricing.margin_percentage >= 0 ? "text-green-600" : "text-red-600"}`}>
              {pricing.margin_percentage.toFixed(1)}%
            </span>
          </div>
          <div className="pt-2">
            <Badge variant={pricing.is_profitable ? "default" : "destructive"}>
              {pricing.is_profitable ? "Profitable" : "Not Profitable"}
            </Badge>
          </div>

          {/* Margin bar */}
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>Cost</span>
              <span>Price</span>
            </div>
            <div className="h-3 w-full rounded-full bg-muted overflow-hidden">
              {pricing.final_price > 0 && (
                <div
                  className={`h-full rounded-full transition-all ${pricing.is_profitable ? "bg-green-500" : "bg-red-500"}`}
                  style={{
                    width: `${Math.min(100, (pricing.total_cost / pricing.final_price) * 100)}%`,
                  }}
                />
              )}
            </div>
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>{formatCurrency(pricing.total_cost)}</span>
              <span>{formatCurrency(pricing.final_price)}</span>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

// ── History Tab ─────────────────────────────────────────

function HistoryTab({ sessionId }: { sessionId: string }) {
  const { data: session } = useConfiguratorSession(sessionId)

  // Build timeline from session metadata
  const events = useMemo(() => {
    const items: { type: string; label: string; date: string }[] = []
    if (session) {
      items.push({ type: "created", label: "Configuration created", date: session.created_at })
      if (session.selections?.length) {
        items.push({
          type: "selections",
          label: `${session.selections.length} selection(s) made`,
          date: session.updated_at,
        })
      }
      if (session.status === "complete" || session.status === "locked") {
        items.push({ type: "completed", label: "Configuration completed", date: session.updated_at })
      }
      if (session.status === "locked") {
        items.push({ type: "locked", label: "Configuration locked", date: session.updated_at })
      }
    }
    return items.sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())
  }, [session])

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <History className="h-4 w-4" />
          Timeline
        </CardTitle>
      </CardHeader>
      <CardContent>
        {events.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-6">No history available.</p>
        ) : (
          <div className="relative space-y-0">
            {events.map((event, i) => (
              <div key={i} className="flex gap-4 pb-6 last:pb-0">
                <div className="flex flex-col items-center">
                  <div className="h-2.5 w-2.5 rounded-full bg-primary mt-1.5" />
                  {i < events.length - 1 && <div className="w-px flex-1 bg-border mt-1" />}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium">{event.label}</p>
                  <p className="text-xs text-muted-foreground">{formatDate(event.date)}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ── Main component ──────────────────────────────────────

interface ConfigurationDetailProps {
  sessionId: string
}

export function ConfigurationDetail({ sessionId }: ConfigurationDetailProps) {
  const { t } = useTranslation()
  const { data: session, isLoading } = useConfiguratorSession(sessionId)
  const { data: product } = useProduct(session?.product_id ?? null)
  const [activeTab, setActiveTab] = useState("selections")

  const cloneSession = useCloneSession()
  const lockSession = useLockSession()
  const exportSession = useExportSession()

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-4 w-48" />
        <div className="flex items-center gap-3">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-5 w-16 rounded-full" />
        </div>
        <Skeleton className="h-10 w-full max-w-lg" />
        <Skeleton className="h-60 w-full" />
      </div>
    )
  }

  if (!session) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <h3 className="text-lg font-semibold">Configuration not found</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          The requested configuration does not exist or has been removed.
        </p>
        <Button asChild variant="outline" className="mt-4">
          <Link to="/configurations">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Configurations
          </Link>
        </Button>
      </div>
    )
  }

  const canLock = session.is_valid && session.is_complete && session.status !== "locked"

  return (
    <div className="space-y-6">
      {/* ── Breadcrumb + Header ── */}
      <div className="space-y-3">
        <Breadcrumb>
          <BreadcrumbList>
            <BreadcrumbItem>
              <BreadcrumbLink asChild>
                <Link to="/configurations">Configurations</Link>
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage>{session.name || session.id.slice(0, 8)}</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold tracking-tight sm:text-2xl">
              {session.name || `Configuration ${session.id.slice(0, 8)}`}
            </h1>
            <Badge variant={statusVariant[session.status]}>
              {statusLabel[session.status] ?? session.status}
            </Badge>
          </div>

          <div className="flex items-center gap-2">
            {product && session.status !== "locked" && (
              <Button variant="outline" size="sm" asChild>
                <Link to="/configurator/$productId" params={{ productId: product.id }}>
                  <Play className="mr-2 h-4 w-4" />
                  Resume in Configurator
                </Link>
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => cloneSession.mutate(sessionId)}
              disabled={cloneSession.isPending}
            >
              <Copy className="mr-2 h-4 w-4" />
              Clone
            </Button>
            {canLock && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => lockSession.mutate(sessionId)}
                disabled={lockSession.isPending}
              >
                <Lock className="mr-2 h-4 w-4" />
                Lock
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => exportSession.mutate({ sessionId, format: "csv" })}
            >
              <FileDown className="mr-2 h-4 w-4" />
              Export
            </Button>
          </div>
        </div>

        {/* Meta info */}
        <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
          {product && (
            <span>
              Product:{" "}
              <Link
                to="/products/$productId"
                params={{ productId: product.id }}
                className="text-foreground hover:underline"
              >
                {product.name}
              </Link>
            </span>
          )}
          <span>Created: {formatDate(session.created_at)}</span>
          <span>Updated: {formatDate(session.updated_at)}</span>
          <span>Selections: {session.selections?.length ?? 0}</span>
        </div>
      </div>

      {/* ── Tabbed content ── */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="selections">
            <ListChecks className="mr-1.5 h-4 w-4" />
            Selections
          </TabsTrigger>
          <TabsTrigger value="bom">
            <Package className="mr-1.5 h-4 w-4" />
            BOM
          </TabsTrigger>
          <TabsTrigger value="pricing">
            <DollarSign className="mr-1.5 h-4 w-4" />
            Pricing
          </TabsTrigger>
          <TabsTrigger value="history">
            <History className="mr-1.5 h-4 w-4" />
            History
          </TabsTrigger>
        </TabsList>

        <TabsContent value="selections">
          <SelectionsTab sessionId={sessionId} productId={session.product_id} />
        </TabsContent>
        <TabsContent value="bom">
          <BOMTab sessionId={sessionId} />
        </TabsContent>
        <TabsContent value="pricing">
          <PricingTab sessionId={sessionId} />
        </TabsContent>
        <TabsContent value="history">
          <HistoryTab sessionId={sessionId} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
