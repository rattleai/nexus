import { useMemo } from "react"
import { AlertCircle, ArrowRight } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import type { ConfiguratorValidationError } from "@/apps/cpq/hooks/use-configurator"
import type { Characteristic, CharacteristicGroup } from "@/apps/cpq/types/configurator"

interface Step {
  slug: string
  name: string
}

interface MissingItemsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  errors: ConfiguratorValidationError[]
  characteristics: Characteristic[]
  groups: CharacteristicGroup[]
  steps: Step[]
  onNavigateToStep: (stepIndex: number) => void
}

interface GroupedErrors {
  stepName: string
  stepIndex: number
  items: {
    charName: string
    errorType: string
    message: string
  }[]
}

function errorLabel(errorType: string): string {
  switch (errorType) {
    case "required_missing":
      return "Required"
    case "domain_empty":
      return "No valid values"
    case "invalid_value":
      return "Invalid"
    default:
      return errorType
  }
}

export function MissingItemsDialog({
  open,
  onOpenChange,
  errors,
  characteristics,
  groups,
  steps,
  onNavigateToStep,
}: MissingItemsDialogProps) {
  const errorsByStep = useMemo(() => {
    const charBySlug = new Map(characteristics.map((c) => [c.slug, c]))
    const groupById = new Map(groups.map((g) => [g.id, g]))
    const stepIndexBySlug = new Map(steps.map((s, i) => [s.slug, i]))

    const grouped = new Map<string, GroupedErrors>()

    for (const error of errors) {
      const char = charBySlug.get(error.characteristic_slug)
      if (!char) continue

      const group = char.group_id ? groupById.get(char.group_id) : null
      const stepSlug = group?.slug ?? "_general"
      const stepName = group?.name ?? "General"
      const stepIndex = stepIndexBySlug.get(stepSlug) ?? 0

      if (!grouped.has(stepSlug)) {
        grouped.set(stepSlug, { stepName, stepIndex, items: [] })
      }
      grouped.get(stepSlug)!.items.push({
        charName: char.name,
        errorType: error.error_type,
        message: error.message,
      })
    }

    // Sort by step index
    return [...grouped.values()].sort((a, b) => a.stepIndex - b.stepIndex)
  }, [errors, characteristics, groups, steps])

  const firstMissingStepIndex = errorsByStep[0]?.stepIndex ?? 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertCircle className="h-4.5 w-4.5 text-destructive" />
            Configuration Incomplete
          </DialogTitle>
          <DialogDescription>
            The following required characteristics need values before the
            configuration can be completed.
          </DialogDescription>
        </DialogHeader>

        <ScrollArea className="max-h-[360px] -mx-6 px-6">
          <div className="space-y-4 py-1">
            {errorsByStep.map(({ stepName, stepIndex, items }) => (
              <div key={stepName} className="space-y-2">
                <div className="flex items-center justify-between">
                  <h4 className="text-sm font-semibold">{stepName}</h4>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs gap-1"
                    onClick={() => onNavigateToStep(stepIndex)}
                  >
                    Go to step
                    <ArrowRight className="h-3 w-3" />
                  </Button>
                </div>
                <div className="space-y-1.5">
                  {items.map((item) => (
                    <div
                      key={item.charName}
                      className="flex items-center gap-2 rounded-md border bg-muted/30 px-3 py-2"
                    >
                      <AlertCircle className="h-3.5 w-3.5 text-destructive shrink-0" />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium">{item.charName}</p>
                        {item.errorType !== "required_missing" && (
                          <p className="text-xs text-muted-foreground">
                            {item.message}
                          </p>
                        )}
                      </div>
                      <Badge variant="outline" className="text-[10px] shrink-0">
                        {errorLabel(item.errorType)}
                      </Badge>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </ScrollArea>

        <DialogFooter className="flex-row gap-2 sm:justify-between">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onOpenChange(false)}
          >
            Close
          </Button>
          {errorsByStep.length > 0 && (
            <Button
              size="sm"
              onClick={() => onNavigateToStep(firstMissingStepIndex)}
            >
              Go to first missing
              <ArrowRight className="h-3.5 w-3.5 ml-1.5" />
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
