import { useRef, useEffect } from "react"
import { Check } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"
import { useConfiguratorStore } from "@/stores/configurator-store"

interface Step {
  slug: string
  name: string
  characteristicCount: number
}

interface StepNavigationProps {
  steps: Step[]
  currentStepIndex: number
  onStepChange: (index: number) => void
  completedSteps: Set<string>
}

export function StepNavigation({
  steps,
  currentStepIndex,
  onStepChange,
  completedSteps,
}: StepNavigationProps) {
  const store = useConfiguratorStore()
  const activeTabRef = useRef<HTMLButtonElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)

  // Count how many characteristics are selected per step
  const stepSelectionCounts = steps.map((step) => {
    // We count selections by checking the store
    let selected = 0
    // Since we don't have direct access to the characteristics list here,
    // we use the completedSteps set and the characteristicCount
    if (completedSteps.has(step.slug)) {
      selected = step.characteristicCount
    } else {
      // Estimate based on ratio - the parent component tracks completeness
      // For a more accurate count, we look at selections in the store
      const allSelections = {
        ...store.selections,
        ...store.autoSetValues,
      }
      // We can't know the exact slug-to-step mapping here, so we use
      // the completed flag as a heuristic. A partially completed step
      // gets a proportional estimate.
      selected = 0
    }
    return selected
  })

  // Overall progress
  const totalCharacteristics = steps.reduce(
    (acc, s) => acc + s.characteristicCount,
    0,
  )
  const totalSelected = Object.keys(store.selections).length +
    Object.keys(store.autoSetValues).length
  const progressPercent =
    totalCharacteristics > 0
      ? Math.round(
          (Math.min(totalSelected, totalCharacteristics) /
            totalCharacteristics) *
            100,
        )
      : 0

  // Auto-scroll to active tab
  useEffect(() => {
    if (activeTabRef.current) {
      activeTabRef.current.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
        inline: "center",
      })
    }
  }, [currentStepIndex])

  if (steps.length === 0) {
    return null
  }

  return (
    <div className="shrink-0 border-b bg-background">
      {/* Overall progress bar */}
      <div className="px-4 pt-3 pb-1">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[11px] font-medium text-muted-foreground">
            Configuration progress
          </span>
          <span className="text-[11px] font-semibold tabular-nums text-foreground">
            {progressPercent}%
          </span>
        </div>
        <Progress value={progressPercent} className="h-1.5" />
      </div>

      {/* Step tabs */}
      <ScrollArea className="w-full" ref={scrollContainerRef}>
        <div className="flex px-2 pb-0 min-w-max" role="tablist">
          {steps.map((step, index) => {
            const isCurrent = index === currentStepIndex
            const isCompleted = completedSteps.has(step.slug)

            return (
              <button
                key={step.slug}
                ref={isCurrent ? activeTabRef : undefined}
                role="tab"
                aria-selected={isCurrent}
                onClick={() => onStepChange(index)}
                className={cn(
                  "relative flex items-center gap-2 px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors",
                  "hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 rounded-t-md",
                  isCurrent
                    ? "text-foreground"
                    : "text-muted-foreground hover:text-foreground/80",
                )}
              >
                {/* Step indicator */}
                <span
                  className={cn(
                    "flex items-center justify-center h-5 w-5 rounded-full text-[10px] font-bold shrink-0 transition-colors",
                    isCompleted
                      ? "bg-primary text-primary-foreground"
                      : isCurrent
                        ? "bg-primary/15 text-primary border border-primary/30"
                        : "bg-muted text-muted-foreground",
                  )}
                >
                  {isCompleted ? (
                    <Check className="h-3 w-3" />
                  ) : (
                    index + 1
                  )}
                </span>

                {/* Step name */}
                <span>{step.name}</span>

                {/* Selection count badge */}
                {!isCompleted && step.characteristicCount > 0 && (
                  <Badge
                    variant="secondary"
                    className="h-4 px-1.5 text-[10px] font-normal"
                  >
                    {step.characteristicCount}
                  </Badge>
                )}

                {/* Active underline */}
                {isCurrent && (
                  <span className="absolute bottom-0 left-2 right-2 h-0.5 bg-primary rounded-full" />
                )}
              </button>
            )
          })}
        </div>
        <ScrollBar orientation="horizontal" className="h-1.5" />
      </ScrollArea>
    </div>
  )
}
