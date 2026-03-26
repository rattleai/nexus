import { useState, useEffect } from "react"
import { ChevronUp, ChevronDown } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Separator } from "@/components/ui/separator"
import { useSimulatePricing } from "@/hooks/use-configurator"
import { useDebounce } from "@/hooks/use-debounce"
import type { ConfigurationPricing } from "@/types/configurator"

interface PriceSummaryBarProps {
  productId: string
  selections: Record<string, string>
}

const currencyFormatter = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "EUR",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
})

function formatCurrency(value: number): string {
  return currencyFormatter.format(value)
}

export function PriceSummaryBar({ productId, selections }: PriceSummaryBarProps) {
  const [expanded, setExpanded] = useState(false)
  const [pricing, setPricing] = useState<ConfigurationPricing | null>(null)

  const debouncedSelections = useDebounce(selections, 500)
  const simulatePricing = useSimulatePricing()

  const hasSelections = Object.keys(debouncedSelections).length > 0

  useEffect(() => {
    if (!productId || !hasSelections) return

    simulatePricing.mutate(
      { product_id: productId, selections: debouncedSelections },
      {
        onSuccess: (data) => {
          setPricing(data)
        },
      },
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productId, debouncedSelections, hasSelections])

  const isLoading = simulatePricing.isPending
  const basePrice = pricing?.base_price ?? 0
  const adjustments = pricing?.total_adjustments ?? 0
  const finalPrice = pricing?.final_price ?? 0
  const breakdown = pricing?.price_breakdown ?? []

  return (
    <div className="fixed bottom-0 left-0 right-0 z-50">
      {/* Expanded breakdown panel */}
      {expanded && pricing && (
        <div className="border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
          <div className="mx-auto max-w-5xl px-6 py-4">
            <h4 className="mb-3 text-sm font-semibold text-foreground">
              Price Breakdown
            </h4>
            <div className="space-y-2">
              {breakdown.map((item, index) => {
                const ruleName = (item as Record<string, unknown>).rule_name as string | undefined
                const ruleType = (item as Record<string, unknown>).rule_type as string | undefined
                const amount = (item as Record<string, unknown>).amount as number | undefined

                return (
                  <div key={index} className="flex items-center justify-between text-sm">
                    <div className="flex items-center gap-2">
                      <span className="text-muted-foreground">{ruleName ?? "Rule"}</span>
                      {ruleType && (
                        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                          {ruleType}
                        </span>
                      )}
                    </div>
                    <span className="font-medium tabular-nums">
                      {amount !== undefined ? formatCurrency(amount) : "--"}
                    </span>
                  </div>
                )
              })}
              {breakdown.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  No pricing rules applied yet.
                </p>
              )}
            </div>
            <Separator className="my-3" />
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Margin</span>
              <span className="text-sm font-medium tabular-nums">
                {pricing.margin_percentage.toFixed(1)}%
                {" "}({formatCurrency(pricing.margin_amount)})
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Main summary bar */}
      <div className="h-16 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="mx-auto flex h-full max-w-5xl items-center justify-between px-6">
          {/* Left: Base price */}
          <div className="flex items-center gap-1">
            {isLoading ? (
              <Skeleton className="h-5 w-28" />
            ) : (
              <span className="text-sm text-muted-foreground tabular-nums">
                Base: {formatCurrency(basePrice)}
              </span>
            )}
          </div>

          {/* Center: Options total */}
          <div className="flex items-center gap-1">
            {isLoading ? (
              <Skeleton className="h-5 w-32" />
            ) : (
              <span className="text-sm text-muted-foreground tabular-nums">
                + Options: {formatCurrency(adjustments)}
              </span>
            )}
          </div>

          {/* Right: Total + expand toggle */}
          <div className="flex items-center gap-3">
            {isLoading ? (
              <Skeleton className="h-7 w-36" />
            ) : (
              <span className="text-xl font-bold tabular-nums">
                Total: {formatCurrency(finalPrice)}
              </span>
            )}
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={() => setExpanded((prev) => !prev)}
              aria-label={expanded ? "Collapse price breakdown" : "Expand price breakdown"}
            >
              {expanded ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronUp className="h-4 w-4" />
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
