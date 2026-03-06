import * as React from "react"
import {
  Brain,
  ClipboardList,
  Search,
  GitBranch,
  ChevronRight,
  Loader2,
} from "lucide-react"
import { cn } from "@/lib/utils"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"

export interface ReasoningStep {
  id: string
  type: "thinking" | "planning" | "analyzing" | "deciding"
  content: string
  timestamp?: string
}

export interface ReasoningDisplayProps {
  steps: ReasoningStep[]
  isStreaming?: boolean
  defaultOpen?: boolean
  className?: string
}

const STEP_ICONS: Record<
  ReasoningStep["type"],
  React.ComponentType<{ className?: string }>
> = {
  thinking: Brain,
  planning: ClipboardList,
  analyzing: Search,
  deciding: GitBranch,
}

const STEP_LABELS: Record<ReasoningStep["type"], string> = {
  thinking: "Thinking",
  planning: "Planning",
  analyzing: "Analyzing",
  deciding: "Deciding",
}

function getElapsedLabel(steps: ReasoningStep[]): string {
  if (steps.length < 2) return ""
  const first = steps[0].timestamp
  const last = steps[steps.length - 1].timestamp
  if (!first || !last) return ""

  const elapsed =
    (new Date(last).getTime() - new Date(first).getTime()) / 1000
  if (elapsed < 1) return "< 1 second"
  if (elapsed < 60) return `${Math.round(elapsed)} seconds`
  return `${Math.round(elapsed / 60)} minutes`
}

export function ReasoningDisplay({
  steps,
  isStreaming = false,
  defaultOpen = false,
  className,
}: ReasoningDisplayProps) {
  const [open, setOpen] = React.useState(defaultOpen)
  const elapsed = getElapsedLabel(steps)

  return (
    <Collapsible open={open} onOpenChange={setOpen} className={className}>
      <CollapsibleTrigger asChild>
        <button
          type="button"
          className={cn(
            "flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
            "bg-muted/50 hover:bg-muted",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          )}
          aria-label={
            isStreaming ? "Thinking in progress" : "View reasoning steps"
          }
        >
          {isStreaming ? (
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          ) : (
            <Brain className="h-4 w-4 text-muted-foreground" />
          )}
          <span className="text-muted-foreground">
            {isStreaming
              ? "Thinking..."
              : elapsed
                ? `Thought for ${elapsed}`
                : `${steps.length} reasoning step${steps.length !== 1 ? "s" : ""}`}
          </span>
          <ChevronRight
            className={cn(
              "ml-auto h-4 w-4 text-muted-foreground transition-transform",
              open && "rotate-90",
            )}
          />
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mt-2 space-y-2 pl-2">
          {steps.map((step, index) => {
            const Icon = STEP_ICONS[step.type]
            const isLast = index === steps.length - 1

            return (
              <div
                key={step.id}
                className="relative flex gap-3 pl-3"
              >
                {/* Vertical connector line */}
                {index < steps.length - 1 && (
                  <div className="absolute left-[21px] top-6 h-[calc(100%+0.25rem)] w-px bg-border" />
                )}

                <div
                  className={cn(
                    "relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border bg-background",
                    isStreaming && isLast && "border-primary",
                  )}
                >
                  <Icon className="h-3 w-3 text-muted-foreground" />
                </div>

                <div className="min-w-0 flex-1 pb-3">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-muted-foreground">
                      {STEP_LABELS[step.type]}
                    </span>
                    {step.timestamp && (
                      <span className="text-[10px] text-muted-foreground/60">
                        {new Date(step.timestamp).toLocaleTimeString()}
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 text-sm leading-relaxed text-foreground/80">
                    {step.content}
                    {isStreaming && isLast && (
                      <span className="ml-0.5 inline-block h-4 w-1 animate-pulse bg-foreground/60" />
                    )}
                  </p>
                </div>
              </div>
            )
          })}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}
