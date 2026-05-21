import { Check } from "lucide-react"
import { useTranslation } from "react-i18next"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

interface PricingCardProps {
  name: string
  price: number
  interval: "month" | "year"
  features: string[]
  isCurrent?: boolean
  isPopular?: boolean
  onSelect: () => void
  disabled?: boolean
  className?: string
}

export function PricingCard({
  name,
  price,
  interval,
  features,
  isCurrent = false,
  isPopular = false,
  onSelect,
  disabled = false,
  className,
}: PricingCardProps) {
  const { t } = useTranslation("billing")

  return (
    <Card
      className={cn(
        "relative flex flex-col",
        isPopular && "border-primary shadow-md",
        className,
      )}
    >
      {isPopular && (
        <div className="absolute -top-3 left-1/2 -translate-x-1/2">
          <Badge>{t("most_popular")}</Badge>
        </div>
      )}

      <CardHeader className="pb-2">
        <CardTitle className="text-lg font-semibold text-foreground">
          {name}
        </CardTitle>
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-6">
        <div>
          <div className="flex items-baseline gap-1">
            <span className="text-3xl font-bold tracking-tight">
              ${price}
            </span>
            <span className="text-sm text-muted-foreground">
              /{interval}
            </span>
          </div>
        </div>

        <ul className="flex flex-1 flex-col gap-2.5 text-sm">
          {features.map((feature) => (
            <li key={feature} className="flex items-start gap-2">
              <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <span className="text-muted-foreground">{feature}</span>
            </li>
          ))}
        </ul>

        <Button
          onClick={onSelect}
          disabled={disabled || isCurrent}
          variant={isPopular ? "default" : "outline"}
          className="w-full"
        >
          {isCurrent ? t("current_plan") : t("select_plan")}
        </Button>
      </CardContent>
    </Card>
  )
}
