import { useState, useMemo, useCallback } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { FileDown, RefreshCw, Package } from "lucide-react"
import { useResolveBOM } from "@/hooks/use-configurator"
import type { ConfiguredBOM } from "@/types/configurator"

interface ResolvedBOMViewProps {
  sessionId: string
}

// ── Types for resolved items ──────────────────────────────

interface ResolvedItem {
  part_number: string
  part_name: string
  quantity: number
  unit: string
  unit_cost: number
  level: number
  parent_part: string | null
  item_type: string
}

// ── Currency formatter ────────────────────────────────────

const currencyFormatter = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "EUR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

function formatCurrency(value: number): string {
  return currencyFormatter.format(value)
}

// ── Item type badge variant mapping ───────────────────────

const itemTypeBadgeVariant: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  component: "default",
  sub_assembly: "secondary",
  phantom: "outline",
  reference: "outline",
}

// ── CSV export helper ────────────────────────────────────

function exportToCSV(items: ResolvedItem[], totalCost: number | null) {
  const headers = [
    "Level",
    "Part Number",
    "Part Name",
    "Type",
    "Quantity",
    "UOM",
    "Unit Cost",
    "Extended Cost",
    "Parent Part",
  ]

  const rows = items.map((item) => [
    item.level.toString(),
    item.part_number,
    `"${item.part_name.replace(/"/g, '""')}"`,
    item.item_type,
    item.quantity.toString(),
    item.unit,
    item.unit_cost.toFixed(2),
    (item.quantity * item.unit_cost).toFixed(2),
    item.parent_part ?? "",
  ])

  // Add total row
  rows.push([])
  rows.push(["", "", "", "", "", "", "Total Cost:", totalCost?.toFixed(2) ?? "N/A", ""])

  const csvContent = [
    headers.join(","),
    ...rows.map((row) => (Array.isArray(row) && row.length > 0 ? row.join(",") : "")),
  ].join("\n")

  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = `bom-resolved-${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

// ── Main component ────────────────────────────────────────

export function ResolvedBOMView({ sessionId }: ResolvedBOMViewProps) {
  const [bom, setBom] = useState<ConfiguredBOM | null>(null)
  const resolveBOM = useResolveBOM()

  const handleResolve = useCallback(() => {
    resolveBOM.mutate(sessionId, {
      onSuccess: (data) => {
        setBom(data)
      },
    })
  }, [sessionId, resolveBOM])

  // Parse resolved items from the ConfiguredBOM
  const resolvedItems: ResolvedItem[] = useMemo(() => {
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
    }))
  }, [bom])

  // Total extended cost
  const totalExtendedCost = useMemo(
    () => resolvedItems.reduce((sum, item) => sum + item.quantity * item.unit_cost, 0),
    [resolvedItems],
  )

  const handleExportCSV = () => {
    if (resolvedItems.length > 0) {
      exportToCSV(resolvedItems, bom?.total_cost ?? totalExtendedCost)
    }
  }

  // Format resolution duration
  const resolutionDuration = bom?.resolution_duration_ms
    ? bom.resolution_duration_ms < 1000
      ? `${bom.resolution_duration_ms}ms`
      : `${(bom.resolution_duration_ms / 1000).toFixed(2)}s`
    : null

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
        <CardTitle className="flex items-center gap-2 text-base">
          <Package className="h-5 w-5" />
          Resolved BOM
        </CardTitle>
        <div className="flex items-center gap-2">
          {bom && resolvedItems.length > 0 && (
            <Button variant="outline" size="sm" onClick={handleExportCSV}>
              <FileDown className="h-3.5 w-3.5 mr-1.5" />
              Export CSV
            </Button>
          )}
          <Button
            size="sm"
            onClick={handleResolve}
            disabled={resolveBOM.isPending}
          >
            <RefreshCw
              className={`h-3.5 w-3.5 mr-1.5 ${resolveBOM.isPending ? "animate-spin" : ""}`}
            />
            {bom ? "Re-resolve" : "Resolve BOM"}
          </Button>
        </div>
      </CardHeader>

      <CardContent>
        {/* Loading state */}
        {resolveBOM.isPending && (
          <div className="space-y-3">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-3/4" />
          </div>
        )}

        {/* Empty state: not yet resolved */}
        {!bom && !resolveBOM.isPending && (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <Package className="h-12 w-12 text-muted-foreground/40 mb-3" />
            <p className="text-sm text-muted-foreground">
              Click "Resolve BOM" to generate the bill of materials for this configuration.
            </p>
          </div>
        )}

        {/* Resolved BOM data */}
        {bom && !resolveBOM.isPending && (
          <div className="space-y-4">
            {/* Summary row */}
            <div className="flex items-center gap-4 text-sm">
              <div className="flex items-center gap-1.5">
                <span className="text-muted-foreground">Components:</span>
                <span className="font-semibold tabular-nums">
                  {bom.total_components}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-muted-foreground">Total Cost:</span>
                <span className="font-semibold tabular-nums">
                  {bom.total_cost != null ? formatCurrency(bom.total_cost) : formatCurrency(totalExtendedCost)}
                </span>
              </div>
              {resolutionDuration && (
                <div className="flex items-center gap-1.5">
                  <span className="text-muted-foreground">Resolved in:</span>
                  <Badge variant="secondary" className="text-[10px]">
                    {resolutionDuration}
                  </Badge>
                </div>
              )}
            </div>

            {/* BOM tree-table */}
            {resolvedItems.length > 0 ? (
              <div className="rounded-md border overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-[180px]">Part Number</TableHead>
                      <TableHead>Part Name</TableHead>
                      <TableHead className="w-[80px]">Type</TableHead>
                      <TableHead className="w-[70px] text-right">Qty</TableHead>
                      <TableHead className="w-[60px]">UOM</TableHead>
                      <TableHead className="w-[110px] text-right">Unit Cost</TableHead>
                      <TableHead className="w-[110px] text-right">Extended</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {resolvedItems.map((item, index) => {
                      const extendedCost = item.quantity * item.unit_cost
                      const indentPx = item.level * 20

                      return (
                        <TableRow key={`${item.part_number}-${index}`}>
                          <TableCell
                            className="font-mono text-xs"
                            style={{ paddingLeft: `${12 + indentPx}px` }}
                          >
                            {item.level > 0 && (
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
                        </TableRow>
                      )
                    })}

                    {/* Total row */}
                    <TableRow className="bg-muted/50 font-semibold">
                      <TableCell colSpan={3} className="text-right">
                        Total
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {resolvedItems.reduce((s, i) => s + i.quantity, 0)}
                      </TableCell>
                      <TableCell />
                      <TableCell />
                      <TableCell className="text-right tabular-nums">
                        {formatCurrency(totalExtendedCost)}
                      </TableCell>
                    </TableRow>
                  </TableBody>
                </Table>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-6">
                No items in the resolved BOM.
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
