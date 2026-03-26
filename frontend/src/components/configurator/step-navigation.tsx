import { useRef, useEffect } from "react"
import { Check } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"

interface Step {
  slug: string
  name: string
  characteristicCount: number
  requiredCharacteristicCount: number
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
  const activeTabRef = useRef<HTMLButtonElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)

  // Progress tracks the fraction of steps that have all required fields filled.
  // This is consistent with the Complete button's completedSteps.size gate
  // and aligned with the backend's _check_completeness (required-only) logic.
  const progressPercent =
    steps.length > 0
      ? Math.round((completedSteps.size / steps.length) * 100)
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
