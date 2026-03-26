import { useState, useMemo } from "react"
import { Link } from "@tanstack/react-router"
import {
  ArrowLeft,
  Search,
  GitCompare,
  MapPin,
  PieChartIcon,
  BarChart3,
  X,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import {
  Card,
  CardContent,
  CardDescription,
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { PageHeader } from "@/components/page-header"
import { BarChart } from "@/components/charts/bar-chart"
import { PieChart } from "@/components/charts/pie-chart"
import { useConfigurations, useBOMComparison, usePartFrequency } from "@/hooks/use-configurations"
import { useWhereUsed } from "@/hooks/use-boms"
import { useProducts } from "@/hooks/use-products"
import type { WhereUsedResult } from "@/types/configurator"

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

// ── BOM Comparison Section ──────────────────────────────

function BOMComparisonSection() {
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [selectValue, setSelectValue] = useState<string>("")

  const { data: sessionsData } = useConfigurations({ page_size: "100" })
  const sessions = sessionsData?.items ?? []

  const { data: comparison, isLoading } = useBOMComparison(selectedIds)

  const addSession = (id: string) => {
    if (id && selectedIds.length < 5 && !selectedIds.includes(id)) {
      setSelectedIds([...selectedIds, id])
    }
    setSelectValue("")
  }

  const removeSession = (id: string) => {
    setSelectedIds(selectedIds.filter((sid) => sid !== id))
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <GitCompare className="h-4 w-4" />
          BOM Comparison
        </CardTitle>
        <CardDescription>
          Select 2-5 configurations to compare their bills of materials side by side.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Session picker */}
        <div className="flex items-center gap-2 flex-wrap">
          <Select value={selectValue} onValueChange={addSession}>
            <SelectTrigger className="w-[280px]">
              <SelectValue placeholder="Add a configuration..." />
            </SelectTrigger>
            <SelectContent>
              {sessions
                .filter((s) => !selectedIds.includes(s.id))
                .map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.name || s.id.slice(0, 8)}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>

          {selectedIds.map((id) => {
            const session = sessions.find((s) => s.id === id)
            return (
              <Badge key={id} variant="secondary" className="gap-1 pr-1">
                {session?.name || id.slice(0, 8)}
                <button
                  onClick={() => removeSession(id)}
                  className="ml-1 rounded-full p-0.5 hover:bg-muted"
                >
                  <X className="h-3 w-3" />
                </button>
              </Badge>
            )
          })}
        </div>

        {/* Comparison results */}
        {selectedIds.length >= 2 && isLoading && (
          <Skeleton className="h-40 w-full" />
        )}

        {comparison && (
          <div className="space-y-4">
            {/* Cost comparison */}
            <div className="flex gap-4 flex-wrap">
              {comparison.cost_comparison.map((cc, i) => (
                <div key={cc.session_id} className="rounded-lg border p-3 min-w-[160px]">
                  <p className="text-xs text-muted-foreground">
                    {comparison.sessions[i]?.name || cc.session_id.slice(0, 8)}
                  </p>
                  <p className="text-lg font-bold tabular-nums">{formatCurrency(cc.total_cost)}</p>
                  <p className="text-xs text-muted-foreground">{cc.total_parts} parts</p>
                </div>
              ))}
            </div>

            {/* Common parts */}
            {comparison.common_parts.length > 0 && (
              <div>
                <h4 className="text-sm font-medium mb-2">
                  Common Parts ({comparison.common_parts.length})
                </h4>
                <div className="rounded-md border overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Part Number</TableHead>
                        <TableHead>Name</TableHead>
                        {comparison.sessions.map((s) => (
                          <TableHead key={s.id} className="text-right">
                            {s.name || s.id.slice(0, 8)}
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {comparison.common_parts.slice(0, 50).map((part) => {
                        const hasQtyDiff = part.quantities.some(
                          (q, i) => q !== part.quantities[0],
                        )
                        return (
                          <TableRow key={part.part_number}>
                            <TableCell className="font-mono text-xs">
                              {part.part_number}
                            </TableCell>
                            <TableCell className="text-sm">{part.part_name}</TableCell>
                            {part.quantities.map((qty, i) => (
                              <TableCell
                                key={i}
                                className={`text-right tabular-nums ${hasQtyDiff ? "text-amber-600 font-medium" : ""}`}
                              >
                                {qty ?? "-"}
                              </TableCell>
                            ))}
                          </TableRow>
                        )
                      })}
                    </TableBody>
                  </Table>
                </div>
              </div>
            )}

            {/* Unique parts */}
            {comparison.unique_parts.length > 0 && (
              <div>
                <h4 className="text-sm font-medium mb-2">
                  Unique Parts ({comparison.unique_parts.length})
                </h4>
                <div className="rounded-md border overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Part Number</TableHead>
                        <TableHead>Name</TableHead>
                        {comparison.sessions.map((s) => (
                          <TableHead key={s.id} className="text-right">
                            {s.name || s.id.slice(0, 8)}
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {comparison.unique_parts.slice(0, 50).map((part) => (
                        <TableRow key={part.part_number}>
                          <TableCell className="font-mono text-xs">
                            {part.part_number}
                          </TableCell>
                          <TableCell className="text-sm">{part.part_name}</TableCell>
                          {part.quantities.map((qty, i) => (
                            <TableCell
                              key={i}
                              className={`text-right tabular-nums ${qty != null ? "text-green-600 font-medium" : "text-muted-foreground"}`}
                            >
                              {qty ?? "-"}
                            </TableCell>
                          ))}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </div>
            )}
          </div>
        )}

        {selectedIds.length < 2 && (
          <p className="text-sm text-muted-foreground text-center py-6">
            Select at least 2 configurations to compare.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

// ── Where-Used Lookup Section ───────────────────────────

function WhereUsedSection() {
  const [partSearch, setPartSearch] = useState("")
  const [searchedPart, setSearchedPart] = useState<string | null>(null)
  const { data: whereUsedResults, isLoading } = useWhereUsed(searchedPart)

  const handleSearch = () => {
    if (partSearch.trim()) {
      setSearchedPart(partSearch.trim())
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <MapPin className="h-4 w-4" />
          Where-Used Lookup
        </CardTitle>
        <CardDescription>
          Find all BOMs and products that use a specific part number.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Enter part number..."
              value={partSearch}
              onChange={(e) => setPartSearch(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              className="pl-9"
            />
          </div>
          <Button onClick={handleSearch} disabled={!partSearch.trim()}>
            Search
          </Button>
        </div>

        {isLoading && <Skeleton className="h-20 w-full" />}

        {whereUsedResults && whereUsedResults.length > 0 && (
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>BOM</TableHead>
                  <TableHead>Product</TableHead>
                  <TableHead className="text-right">Quantity</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {whereUsedResults.map((result: WhereUsedResult) => (
                  <TableRow key={result.item_id}>
                    <TableCell className="font-medium">{result.bom_name}</TableCell>
                    <TableCell>
                      <Link
                        to="/products/$productId"
                        params={{ productId: result.product_id }}
                        className="hover:underline"
                      >
                        {result.product_name}
                      </Link>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{result.quantity}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        {whereUsedResults && whereUsedResults.length === 0 && searchedPart && (
          <p className="text-sm text-muted-foreground text-center py-6">
            No results found for part "{searchedPart}".
          </p>
        )}
      </CardContent>
    </Card>
  )
}

// ── Part Frequency Section ──────────────────────────────

function PartFrequencySection() {
  const [productFilter, setProductFilter] = useState<string>("all")
  const { data: productsData } = useProducts()
  const products = productsData?.items ?? []

  const filters = useMemo(() => ({
    product_id: productFilter !== "all" ? productFilter : undefined,
    limit: "20",
  }), [productFilter])

  const { data: frequencyData, isLoading } = usePartFrequency(filters)

  const chartData = useMemo(
    () =>
      (frequencyData?.items ?? []).slice(0, 15).map((item) => ({
        name: item.part_number,
        count: item.usage_count,
      })),
    [frequencyData],
  )

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <BarChart3 className="h-4 w-4" />
              Part Frequency
            </CardTitle>
            <CardDescription>
              Most frequently used parts across {frequencyData?.total_configurations ?? 0} configurations.
            </CardDescription>
          </div>
          <Select value={productFilter} onValueChange={setProductFilter}>
            <SelectTrigger className="w-[180px]">
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
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading && <Skeleton className="h-60 w-full" />}

        {chartData.length > 0 && (
          <BarChart
            data={chartData}
            dataKey="count"
            xAxisKey="name"
            height={250}
          />
        )}

        {frequencyData && frequencyData.items.length > 0 && (
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Part Number</TableHead>
                  <TableHead>Part Name</TableHead>
                  <TableHead className="text-right">Used In</TableHead>
                  <TableHead className="text-right">% of Configs</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {frequencyData.items.map((item) => (
                  <TableRow key={item.part_number}>
                    <TableCell className="font-mono text-xs">{item.part_number}</TableCell>
                    <TableCell className="text-sm">{item.part_name}</TableCell>
                    <TableCell className="text-right tabular-nums font-medium">
                      {item.usage_count}
                    </TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">
                      {item.percentage.toFixed(1)}%
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        {frequencyData && frequencyData.items.length === 0 && (
          <p className="text-sm text-muted-foreground text-center py-6">
            No resolved BOMs found. Resolve configurations first to see part frequency.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

// ── Main Page ───────────────────────────────────────────

export function BOMAnalysisPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="BOM Analysis"
        description="Compare configurations, analyze part usage, and explore cost breakdowns"
        actions={
          <Button variant="outline" asChild>
            <Link to="/configurations">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to Configurations
            </Link>
          </Button>
        }
      />

      <div className="space-y-6">
        <BOMComparisonSection />
        <WhereUsedSection />
        <PartFrequencySection />
      </div>
    </div>
  )
}
