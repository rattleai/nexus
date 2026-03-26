import { cn } from "@/lib/utils"
import { Check, Lock } from "lucide-react"
import { motion } from "motion/react"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type { CharacteristicValue } from "@/types/configurator"

interface OptionCardProps {
  values: CharacteristicValue[]
  selectedValue: string | undefined
  excludedValues: string[]
  isMultiSelect: boolean
  onSelect: (value: string) => void
}

function formatPriceDelta(price: number | null): string {
  if (price === null || price === 0) return "Included"
  const sign = price > 0 ? "+" : ""
  return `${sign}\u20AC${price.toLocaleString()}`
}

export function OptionCard({
  values,
  selectedValue,
  excludedValues,
  isMultiSelect,
  onSelect,
}: OptionCardProps) {
  // For multi-select, selectedValue is a comma-separated string
  const selectedValues = isMultiSelect
    ? (selectedValue?.split(",").filter(Boolean) ?? [])
    : []

  return (
    <TooltipProvider delayDuration={200}>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {values.map((value) => {
          const isSelected = isMultiSelect
            ? selectedValues.includes(value.value)
            : selectedValue === value.value
          const isExcluded = excludedValues.includes(value.value)

          const card = (
            <motion.button
              key={value.id}
              type="button"
              disabled={isExcluded}
              onClick={() => onSelect(value.value)}
              whileTap={isExcluded ? undefined : { scale: 0.98 }}
              className={cn(
                "relative flex flex-col items-start rounded-lg border p-4 text-left transition-colors",
                "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                isSelected
                  ? "border-primary bg-primary/5"
                  : "border-border hover:border-primary/50",
                isExcluded &&
                  "opacity-50 border-dashed cursor-not-allowed hover:border-border",
              )}
            >
              {isSelected && (
                <motion.div
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  className="absolute top-2 right-2 flex h-5 w-5 items-center justify-center rounded-full bg-primary"
                >
                  <Check className="h-3 w-3 text-primary-foreground" />
                </motion.div>
              )}
              {isExcluded && (
                <div className="absolute top-2 right-2 flex h-5 w-5 items-center justify-center rounded-full bg-muted border">
                  <Lock className="h-3 w-3 text-muted-foreground" />
                </div>
              )}

              <span
                className={cn(
                  "font-medium leading-snug",
                  isExcluded && "text-muted-foreground",
                )}
              >
                {value.label}
              </span>

              {value.description && (
                <span
                  className={cn(
                    "mt-1 text-sm text-muted-foreground leading-snug",
                    isExcluded && "text-muted-foreground/70",
                  )}
                >
                  {value.description}
                </span>
              )}

              <span
                className={cn(
                  "mt-2 text-sm font-semibold",
                  value.price_adjustment === null || value.price_adjustment === 0
                    ? "text-muted-foreground"
                    : "text-emerald-600 dark:text-emerald-400",
                  isExcluded && "text-muted-foreground",
                )}
              >
                {formatPriceDelta(value.price_adjustment)}
              </span>
            </motion.button>
          )

          if (isExcluded) {
            return (
              <Tooltip key={value.id}>
                <TooltipTrigger asChild>{card}</TooltipTrigger>
                <TooltipContent>
                  <p className="text-xs">
                    This option is unavailable based on your current selections
                  </p>
                </TooltipContent>
              </Tooltip>
            )
          }

          return card
        })}
      </div>
    </TooltipProvider>
  )
}
