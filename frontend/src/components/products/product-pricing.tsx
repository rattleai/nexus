import { useTranslation } from "react-i18next"
import { DollarSign } from "lucide-react"
import { usePricingRules } from "@/hooks/use-pricing-rules"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
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
import type { PricingRuleType } from "@/types/configurator"

// ── Types ───────────────────────────────────────────────

interface ProductPricingProps {
  productId: string
}

// ── Rule type badge mapping ─────────────────────────────

const ruleTypeVariant: Record<
  PricingRuleType,
  "default" | "secondary" | "outline" | "destructive"
> = {
  base_price: "default",
  option_surcharge: "secondary",
  volume_discount: "outline",
  conditional: "secondary",
  formula: "outline",
  tiered: "secondary",
  margin: "destructive",
}

// ── Helper: extract display amount from expression ──────

function extractDisplayAmount(expression: Record<string, unknown>): string {
  if ("amount" in expression && typeof expression.amount === "number") {
    return `$${expression.amount.toFixed(2)}`
  }
  if ("percentage" in expression && typeof expression.percentage === "number") {
    return `${expression.percentage}%`
  }
  if ("base_amount" in expression && typeof expression.base_amount === "number") {
    return `$${(expression.base_amount as number).toFixed(2)}`
  }
  return "—"
}

// ── Component ───────────────────────────────────────────

export function ProductPricing({ productId }: ProductPricingProps) {
  const { t } = useTranslation()
  const { data: rulesData, isLoading } = usePricingRules(productId)

  const rules = (rulesData?.items ?? []).sort((a, b) => a.priority - b.priority)

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-4 w-80" />
        </CardHeader>
        <CardContent className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("products.pricing", "Pricing Rules")}</CardTitle>
        <CardDescription>
          {t(
            "products.pricingDescription",
            "Pricing rules are evaluated in priority order to compute the final price.",
          )}
        </CardDescription>
      </CardHeader>

      <CardContent>
        {rules.length === 0 ? (
          <EmptyState
            icon={DollarSign}
            title={t("products.noPricingRules", "No pricing rules")}
            description={t(
              "products.noPricingRulesDescription",
              "Add pricing rules to calculate product prices based on configuration selections.",
            )}
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-12">{t("products.priority", "Priority")}</TableHead>
                <TableHead>{t("common.name", "Name")}</TableHead>
                <TableHead>{t("pricing.ruleType", "Type")}</TableHead>
                <TableHead className="text-right">{t("pricing.amount", "Amount")}</TableHead>
                <TableHead>{t("pricing.currency", "Currency")}</TableHead>
                <TableHead>{t("common.active", "Active")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rules.map((rule) => (
                <TableRow key={rule.id}>
                  <TableCell className="text-center font-mono text-sm">
                    {rule.priority}
                  </TableCell>
                  <TableCell>
                    <div>
                      <span className="text-sm font-medium">{rule.name}</span>
                      {rule.description && (
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {rule.description}
                        </p>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={ruleTypeVariant[rule.rule_type]}>
                      {rule.rule_type.replace(/_/g, " ")}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm">
                    {extractDisplayAmount(rule.expression)}
                  </TableCell>
                  <TableCell>
                    <span className="text-xs text-muted-foreground uppercase">
                      {rule.currency}
                    </span>
                  </TableCell>
                  <TableCell>
                    <Badge variant={rule.is_active ? "default" : "outline"}>
                      {rule.is_active
                        ? t("common.active", "Active")
                        : t("common.inactive", "Inactive")}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
