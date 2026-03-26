import { useState } from "react"
import { useTranslation } from "react-i18next"
import { Package, ChevronRight, ChevronDown } from "lucide-react"
import { useBOMs, useBOM } from "@/hooks/use-boms"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/empty-state"
import type { BOMItem, BOMItemType } from "@/types/configurator"

// ── Types ───────────────────────────────────────────────

interface ProductBOMProps {
  productId: string
}

// ── Item type badge mapping ─────────────────────────────

const itemTypeVariant: Record<
  BOMItemType,
  "default" | "secondary" | "outline" | "destructive"
> = {
  component: "default",
  sub_assembly: "secondary",
  phantom: "outline",
  reference: "destructive",
}

// ── Recursive BOM item row ──────────────────────────────

function BOMItemRow({
  item,
  depth,
  t,
}: {
  item: BOMItem
  depth: number
  t: (key: string, fallback: string) => string
}) {
  const [expanded, setExpanded] = useState(depth < 1)
  const hasChildren = item.children && item.children.length > 0

  return (
    <>
      <TableRow>
        <TableCell style={{ paddingLeft: `${depth * 24 + 16}px` }}>
          <div className="flex items-center gap-1">
            {hasChildren ? (
              <button
                type="button"
                onClick={() => setExpanded(!expanded)}
                className="p-0.5 rounded hover:bg-muted"
              >
                {expanded ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
              </button>
            ) : (
              <span className="w-5" />
            )}
            <span className="font-medium text-sm">{item.part_number}</span>
          </div>
        </TableCell>
        <TableCell className="text-sm">{item.part_name}</TableCell>
        <TableCell>
          <Badge variant={itemTypeVariant[item.item_type]}>{item.item_type}</Badge>
        </TableCell>
        <TableCell className="text-sm text-right">
          {item.quantity} {item.unit_of_measure}
        </TableCell>
        <TableCell className="text-sm text-right text-muted-foreground">
          {item.unit_cost != null ? `$${item.unit_cost.toFixed(2)}` : "—"}
        </TableCell>
        <TableCell>
          {item.is_optional && (
            <Badge variant="outline">
              {t("bom.optional", "Optional")}
            </Badge>
          )}
        </TableCell>
      </TableRow>
      {expanded &&
        hasChildren &&
        item.children.map((child) => (
          <BOMItemRow key={child.id} item={child} depth={depth + 1} t={t} />
        ))}
    </>
  )
}

// ── Component ───────────────────────────────────────────

export function ProductBOM({ productId }: ProductBOMProps) {
  const { t } = useTranslation()
  const { data: bomsData, isLoading: loadingBOMs } = useBOMs(productId)
  const [selectedBOMId, setSelectedBOMId] = useState<string | null>(null)

  const boms = bomsData?.items ?? []

  // Auto-select first BOM if available
  const activeBOMId = selectedBOMId ?? (boms.length > 0 ? boms[0].id : null)
  const { data: bomDetail, isLoading: loadingDetail } = useBOM(activeBOMId)

  if (loadingBOMs) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-4 w-80" />
        </CardHeader>
        <CardContent className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <div className="space-y-1.5">
          <CardTitle>{t("products.bom", "Bill of Materials")}</CardTitle>
          <CardDescription>
            {t("products.bomDescription", "Manage the product's bill of materials.")}
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          {boms.length > 0 && (
            <Select
              value={activeBOMId ?? ""}
              onValueChange={(val) => setSelectedBOMId(val)}
            >
              <SelectTrigger className="w-[200px]">
                <SelectValue placeholder={t("bom.selectBOM", "Select BOM...")} />
              </SelectTrigger>
              <SelectContent>
                {boms.map((b) => (
                  <SelectItem key={b.id} value={b.id}>
                    {b.name}
                    {b.is_primary && " (Primary)"}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>
      </CardHeader>

      <CardContent>
        {boms.length === 0 ? (
          <EmptyState
            icon={Package}
            title={t("products.noBOMs", "No bill of materials")}
            description={t(
              "products.noBOMsDescription",
              "Create a BOM to define the component structure of this product.",
            )}
          />
        ) : loadingDetail ? (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : bomDetail && bomDetail.items.length > 0 ? (
          <div>
            <div className="mb-3 flex items-center gap-2 text-sm text-muted-foreground">
              <span>
                {t("bom.type", "Type")}: <Badge variant="outline">{bomDetail.bom_type}</Badge>
              </span>
              {bomDetail.is_primary && (
                <Badge variant="default">{t("bom.primary", "Primary")}</Badge>
              )}
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("bom.partNumber", "Part Number")}</TableHead>
                  <TableHead>{t("bom.partName", "Part Name")}</TableHead>
                  <TableHead>{t("bom.itemType", "Type")}</TableHead>
                  <TableHead className="text-right">{t("bom.quantity", "Qty")}</TableHead>
                  <TableHead className="text-right">{t("bom.unitCost", "Unit Cost")}</TableHead>
                  <TableHead>{t("bom.flags", "Flags")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {bomDetail.items.map((item) => (
                  <BOMItemRow key={item.id} item={item} depth={0} t={t} />
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <EmptyState
            icon={Package}
            title={t("bom.noItems", "No items in this BOM")}
            description={t("bom.noItemsDescription", "Add components to build the product structure.")}
          />
        )}
      </CardContent>
    </Card>
  )
}
