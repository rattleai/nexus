import { useState, useEffect, useRef, useMemo } from "react"
import { Zap, AlertTriangle, X } from "lucide-react"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import type { ConflictExplanation } from "@/apps/cpq/types/configurator"

interface ConstraintFeedbackProps {
  autoSetValues: Record<string, string>
  excludedValues: Record<string, string[]>
  conflictExplanations: ConflictExplanation[]
  onDismiss: () => void
}

interface AutoSetNotification {
  characteristic: string
  value: string
  triggeredBy: string | null
}

/**
 * Returns a human-readable explanation for why a specific value is excluded
 * for a given characteristic. Returns null if no explanation is found.
 */
export function getExclusionReason(
  charSlug: string,
  value: string,
  explanations: ConflictExplanation[],
): string | null {
  for (const explanation of explanations) {
    if (explanation.characteristic !== charSlug) continue

    for (const step of explanation.trace) {
      if (step.target_char !== charSlug) continue
      if (!step.removed_values.includes(value)) continue

      const triggerParts = Object.entries(step.triggered_by).map(
        ([char, val]) => `${char} = ${val}`,
      )
      const triggerStr = triggerParts.join(", ")

      if (step.rule_name) {
        return `"${value}" is unavailable because ${step.rule_name} (triggered by ${triggerStr})`
      }

      return `"${value}" is unavailable due to ${step.constraint_type} constraint (triggered by ${triggerStr})`
    }
  }

  return null
}

export function ConstraintFeedback({
  autoSetValues,
  excludedValues: _excludedValues,
  conflictExplanations,
  onDismiss,
}: ConstraintFeedbackProps) {
  const [notifications, setNotifications] = useState<AutoSetNotification[]>([])
  const [conflictDialogOpen, setConflictDialogOpen] = useState(false)
  const [activeConflict, setActiveConflict] = useState<ConflictExplanation | null>(null)
  const prevAutoSetRef = useRef<Record<string, string>>({})

  // Track auto-set value changes and create notifications
  useEffect(() => {
    const prev = prevAutoSetRef.current
    const newNotifs: AutoSetNotification[] = []

    for (const [char, value] of Object.entries(autoSetValues)) {
      if (prev[char] !== value) {
        const explanation = conflictExplanations.find(
          (e) => e.characteristic === char,
        )
        let triggeredBy: string | null = null

        if (explanation && explanation.contributing_selections) {
          const parts = Object.entries(explanation.contributing_selections).map(
            ([c, v]) => `${c} = ${v}`,
          )
          triggeredBy = parts.join(", ")
        }

        newNotifs.push({ characteristic: char, value, triggeredBy })
      }
    }

    if (newNotifs.length > 0) {
      setNotifications((current) => [...newNotifs, ...current].slice(0, 5))
    }
    prevAutoSetRef.current = { ...autoSetValues }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoSetValues, conflictExplanations])

  // Derive contradictions from conflict explanations
  const contradiction = useMemo(() => {
    return conflictExplanations.find(
      (e) =>
        e.trace.some((step) => step.constraint_type === "excludes") &&
        Object.keys(e.contributing_selections).length > 1,
    ) ?? null
  }, [conflictExplanations])

  // Show conflict dialog when contradictions are detected
  useEffect(() => {
    if (contradiction) {
      setActiveConflict(contradiction)
      setConflictDialogOpen(true)
    }
  }, [contradiction])

  const dismissNotification = (index: number) => {
    setNotifications((prev) => prev.filter((_, i) => i !== index))
  }

  const handleConflictKeepCurrent = () => {
    setConflictDialogOpen(false)
    setActiveConflict(null)
  }

  const handleConflictApplyChange = () => {
    setConflictDialogOpen(false)
    setActiveConflict(null)
    onDismiss()
  }

  const conflictSourceEntries = activeConflict
    ? Object.entries(activeConflict.contributing_selections)
    : []

  return (
    <>
      {/* Auto-set notifications */}
      {notifications.length > 0 && (
        <div className="space-y-2">
          {notifications.map((notification, index) => (
            <Alert
              key={`${notification.characteristic}-${notification.value}-${index}`}
              className="border-amber-500/30 bg-amber-50/50 dark:bg-amber-950/20"
            >
              <Zap className="h-4 w-4 text-amber-600 dark:text-amber-400" />
              <AlertDescription className="flex items-center justify-between">
                <span className="text-sm">
                  <span className="font-medium">{notification.value}</span>
                  {" was auto-selected for "}
                  <span className="font-medium">{notification.characteristic}</span>
                  {notification.triggeredBy && (
                    <span className="text-muted-foreground">
                      {" "}(required by {notification.triggeredBy})
                    </span>
                  )}
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 shrink-0"
                  onClick={() => dismissNotification(index)}
                  aria-label="Dismiss notification"
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              </AlertDescription>
            </Alert>
          ))}
        </div>
      )}

      {/* Conflict resolution dialog */}
      <AlertDialog open={conflictDialogOpen} onOpenChange={setConflictDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-destructive" />
              Selection Conflict
            </AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-3">
                <p>
                  This selection conflicts with your current configuration.
                </p>
                {activeConflict && (
                  <div className="rounded-md border bg-muted/50 p-3 text-sm">
                    <p className="font-medium text-foreground">
                      Conflicting selections:
                    </p>
                    <ul className="mt-1.5 list-inside list-disc space-y-1 text-muted-foreground">
                      {conflictSourceEntries.map(([char, value]) => (
                        <li key={char}>
                          {char} = <span className="font-medium text-foreground">{value}</span>
                        </li>
                      ))}
                    </ul>
                    {activeConflict.trace[0]?.rule_name && (
                      <p className="mt-2 text-xs text-muted-foreground">
                        Rule: {activeConflict.trace[0].rule_name}
                      </p>
                    )}
                  </div>
                )}
                <p>
                  Would you like to keep your current selection or apply the new change?
                </p>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={handleConflictKeepCurrent}>
              Keep Current
            </AlertDialogCancel>
            <AlertDialogAction onClick={handleConflictApplyChange}>
              Apply Change
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
