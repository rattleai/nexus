import { cn } from "@/lib/utils"
import { Switch } from "@/components/ui/switch"
import type { Characteristic } from "@/apps/cpq/types/configurator"

interface BooleanSelectorProps {
  characteristic: Characteristic
  selectedValue: string | undefined
  onSelect: (value: string) => void
}

function formatPriceDelta(price: number | null): string | null {
  if (price === null || price === 0) return null
  const sign = price > 0 ? "+" : ""
  return `${sign}\u20AC${price.toLocaleString()}`
}

export function BooleanSelector({
  characteristic,
  selectedValue,
  onSelect,
}: BooleanSelectorProps) {
  const isChecked = selectedValue === "true"

  // Find the "true" value entry to get its price adjustment
  const trueValue = characteristic.values.find((v) => v.value === "true")
  const priceDelta = trueValue ? formatPriceDelta(trueValue.price_adjustment) : null

  const handleCheckedChange = (checked: boolean) => {
    onSelect(checked ? "true" : "false")
  }

  return (
    <div
      className={cn(
        "flex items-center justify-between rounded-lg border p-4 transition-colors",
        isChecked ? "border-primary bg-primary/5" : "border-border",
      )}
    >
      <div className="flex flex-col gap-0.5 pr-4">
        <span className="font-medium leading-snug">{characteristic.name}</span>
        {characteristic.description && (
          <span className="text-sm text-muted-foreground leading-snug">
            {characteristic.description}
          </span>
        )}
        {priceDelta && (
          <span className="mt-1 text-sm font-semibold text-emerald-600 dark:text-emerald-400">
            {priceDelta}
          </span>
        )}
      </div>
      <Switch checked={isChecked} onCheckedChange={handleCheckedChange} />
    </div>
  )
}
