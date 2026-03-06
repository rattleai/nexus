import { cn } from "@/lib/utils"
import { PricingCard } from "./pricing-card"

interface Plan {
  id: string
  name: string
  price: number
  interval: "month" | "year"
  features: string[]
  isPopular?: boolean
}

interface PricingTableProps {
  plans: Plan[]
  currentPlanId: string | null
  onSelectPlan: (planId: string) => void
  className?: string
}

export function PricingTable({
  plans,
  currentPlanId,
  onSelectPlan,
  className,
}: PricingTableProps) {
  return (
    <div
      className={cn(
        "grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3",
        className,
      )}
    >
      {plans.map((plan) => (
        <PricingCard
          key={plan.id}
          name={plan.name}
          price={plan.price}
          interval={plan.interval}
          features={plan.features}
          isCurrent={plan.id === currentPlanId}
          isPopular={plan.isPopular ?? false}
          onSelect={() => onSelectPlan(plan.id)}
        />
      ))}
    </div>
  )
}
