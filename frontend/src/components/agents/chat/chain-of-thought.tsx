import * as React from "react"
import { Brain, ChevronDown, ChevronRight } from "lucide-react"
import { cn } from "@/lib/utils"
import type { ThinkingStep } from "@/stores/agent-conversation-store"

interface ChainOfThoughtProps {
  steps: ThinkingStep[]
  isStreaming?: boolean
  className?: string
}

export function ChainOfThought({ steps, isStreaming, className }: ChainOfThoughtProps) {
  const [expanded, setExpanded] = React.useState(false)

  if (steps.length === 0) return null

  // Calculate duration from first to last step
  const durationMs =
    steps.length > 1
      ? steps[steps.length - 1].timestamp - steps[0].timestamp
      : isStreaming
        ? Date.now() - steps[0].timestamp
        : 0
  const durationSec = Math.round(durationMs / 1000)

  return (
    <div className={cn("rounded-lg border border-purple-500/20 bg-purple-500/[0.03] overflow-hidden", className)}>
      <button
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-purple-500/[0.05] transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <Brain className="h-3.5 w-3.5 text-purple-500 shrink-0" />
        <span className="font-medium text-purple-700 dark:text-purple-400">
          {isStreaming ? "Thinking..." : `Thought for ${durationSec}s`}
        </span>
        <div className="flex-1" />
        {expanded ? (
          <ChevronDown className="h-3 w-3 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3 w-3 text-muted-foreground" />
        )}
      </button>

      {expanded && (
        <div className="border-t border-purple-500/20 px-3 py-2 space-y-1.5">
          {steps.map((step) => (
            <p key={step.id} className="text-xs text-muted-foreground leading-relaxed">
              {step.content}
            </p>
          ))}
          {isStreaming && (
            <span className="inline-block h-3 w-1.5 animate-pulse bg-purple-500/50 align-middle" />
          )}
        </div>
      )}
    </div>
  )
}
