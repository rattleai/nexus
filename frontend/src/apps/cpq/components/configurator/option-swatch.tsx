import { cn } from "@/lib/utils"
import { Lock } from "lucide-react"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type { CharacteristicValue } from "@/apps/cpq/types/configurator"

interface OptionSwatchProps {
  values: CharacteristicValue[]
  selectedValue: string | undefined
  excludedValues: string[]
  onSelect: (value: string) => void
}

function formatPriceDelta(price: number | null): string {
  if (price === null || price === 0) return "Incl."
  const sign = price > 0 ? "+" : ""
  return `${sign}\u20AC${price.toLocaleString()}`
}

export function OptionSwatch({
  values,
  selectedValue,
  excludedValues,
  onSelect,
}: OptionSwatchProps) {
  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex flex-wrap gap-4">
        {values.map((value) => {
          const isSelected = selectedValue === value.value
          const isExcluded = excludedValues.includes(value.value)

          const swatch = (
            <button
              key={value.id}
              type="button"
              disabled={isExcluded}
              onClick={() => onSelect(value.value)}
              className={cn(
                "group flex flex-col items-center gap-1.5 outline-none",
                isExcluded && "cursor-not-allowed",
              )}
            >
              <div className="relative">
                <div
                  className={cn(
                    "h-12 w-12 rounded-full border-2 transition-all duration-200",
                    "flex items-center justify-center overflow-hidden",
                    isSelected
                      ? "ring-2 ring-primary ring-offset-2 border-primary"
                      : "border-border hover:scale-105 hover:shadow-md",
                    isExcluded && "opacity-30 hover:scale-100 hover:shadow-none",
                  )}
                  style={
                    value.image_url
                      ? {
                          backgroundImage: `url(${value.image_url})`,
                          backgroundSize: "cover",
                          backgroundPosition: "center",
                        }
                      : undefined
                  }
                >
                  {!value.image_url && (
                    <span className="text-sm font-semibold text-muted-foreground select-none">
                      {value.label.charAt(0).toUpperCase()}
                    </span>
                  )}
                </div>
                {isExcluded && (
                  <div className="absolute -bottom-0.5 -right-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-muted border">
                    <Lock className="h-2.5 w-2.5 text-muted-foreground" />
                  </div>
                )}
              </div>
              <div className="flex flex-col items-center gap-0.5">
                <span
                  className={cn(
                    "text-xs font-medium leading-tight",
                    isExcluded && "text-muted-foreground",
                  )}
                >
                  {value.label}
                </span>
                <span
                  className={cn(
                    "text-[10px] leading-tight",
                    value.price_adjustment === null || value.price_adjustment === 0
                      ? "text-muted-foreground"
                      : "text-emerald-600 dark:text-emerald-400 font-medium",
                    isExcluded && "text-muted-foreground",
                  )}
                >
                  {formatPriceDelta(value.price_adjustment)}
                </span>
              </div>
            </button>
          )

          if (isExcluded) {
            return (
              <Tooltip key={value.id}>
                <TooltipTrigger asChild>{swatch}</TooltipTrigger>
                <TooltipContent>
                  <p className="text-xs">
                    This option is unavailable based on your current selections
                  </p>
                </TooltipContent>
              </Tooltip>
            )
          }

          return swatch
        })}
      </div>
    </TooltipProvider>
  )
}
