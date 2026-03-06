import * as React from "react"
import { cn } from "@/lib/utils"
import { formatCompactNumber } from "@/lib/format"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import type { TokenUsage } from "@/types/ai"

export type { TokenUsage }

export interface TokenUsageDisplayProps {
  usage: TokenUsage
  maxTokens?: number
  model?: string
  showCost?: boolean
  costPerInputToken?: number
  costPerOutputToken?: number
  variant?: "badge" | "detailed" | "inline"
  className?: string
}

function formatCost(
  inputTokens: number,
  outputTokens: number,
  costPerInput: number,
  costPerOutput: number,
): string {
  const cost = inputTokens * costPerInput + outputTokens * costPerOutput
  if (cost < 0.01) {
    return `$${cost.toFixed(4)}`
  }
  return `$${cost.toFixed(2)}`
}

function getUsageColor(ratio: number): string {
  if (ratio >= 0.9) return "text-destructive"
  if (ratio >= 0.75) return "text-amber-600 dark:text-amber-400"
  return "text-muted-foreground"
}

function BadgeVariant({
  usage,
  maxTokens,
  className,
}: {
  usage: TokenUsage
  maxTokens?: number
  className?: string
}) {
  const ratio = maxTokens ? usage.totalTokens / maxTokens : 0
  return (
    <Badge
      variant="secondary"
      className={cn(maxTokens && getUsageColor(ratio), className)}
    >
      {formatCompactNumber(usage.totalTokens)} tokens
    </Badge>
  )
}

function InlineVariant({
  usage,
  showCost,
  costPerInputToken,
  costPerOutputToken,
  className,
}: {
  usage: TokenUsage
  showCost?: boolean
  costPerInputToken?: number
  costPerOutputToken?: number
  className?: string
}) {
  return (
    <span className={cn("text-xs text-muted-foreground", className)}>
      In: {formatCompactNumber(usage.inputTokens)} | Out:{" "}
      {formatCompactNumber(usage.outputTokens)}
      {showCost && costPerInputToken != null && costPerOutputToken != null && (
        <>
          {" "}
          |{" "}
          {formatCost(
            usage.inputTokens,
            usage.outputTokens,
            costPerInputToken,
            costPerOutputToken,
          )}
        </>
      )}
    </span>
  )
}

function DetailedVariant({
  usage,
  maxTokens,
  model,
  showCost,
  costPerInputToken,
  costPerOutputToken,
  className,
}: {
  usage: TokenUsage
  maxTokens?: number
  model?: string
  showCost?: boolean
  costPerInputToken?: number
  costPerOutputToken?: number
  className?: string
}) {
  const ratio = maxTokens ? (usage.totalTokens / maxTokens) * 100 : 0

  return (
    <Card className={cn(className)}>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium">
          Token Usage
          {model && (
            <span className="ml-2 font-normal text-muted-foreground">
              {model}
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-3 gap-4 text-center">
          <div>
            <p className="text-lg font-bold tabular-nums">
              {formatCompactNumber(usage.inputTokens)}
            </p>
            <p className="text-xs text-muted-foreground">Input</p>
          </div>
          <div>
            <p className="text-lg font-bold tabular-nums">
              {formatCompactNumber(usage.outputTokens)}
            </p>
            <p className="text-xs text-muted-foreground">Output</p>
          </div>
          <div>
            <p className="text-lg font-bold tabular-nums">
              {formatCompactNumber(usage.totalTokens)}
            </p>
            <p className="text-xs text-muted-foreground">Total</p>
          </div>
        </div>

        {maxTokens && (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <span className={getUsageColor(ratio / 100)}>
                {ratio.toFixed(1)}% used
              </span>
              <span className="text-muted-foreground">
                {formatCompactNumber(maxTokens)} max
              </span>
            </div>
            <Progress value={Math.min(ratio, 100)} className="h-2" />
          </div>
        )}

        {showCost &&
          costPerInputToken != null &&
          costPerOutputToken != null && (
            <div className="flex items-center justify-between border-t pt-3 text-sm">
              <span className="text-muted-foreground">Estimated cost</span>
              <span className="font-medium">
                {formatCost(
                  usage.inputTokens,
                  usage.outputTokens,
                  costPerInputToken,
                  costPerOutputToken,
                )}
              </span>
            </div>
          )}
      </CardContent>
    </Card>
  )
}

export function TokenUsageDisplay({
  usage,
  maxTokens,
  model,
  showCost,
  costPerInputToken,
  costPerOutputToken,
  variant = "badge",
  className,
}: TokenUsageDisplayProps) {
  switch (variant) {
    case "badge":
      return (
        <BadgeVariant
          usage={usage}
          maxTokens={maxTokens}
          className={className}
        />
      )
    case "inline":
      return (
        <InlineVariant
          usage={usage}
          showCost={showCost}
          costPerInputToken={costPerInputToken}
          costPerOutputToken={costPerOutputToken}
          className={className}
        />
      )
    case "detailed":
      return (
        <DetailedVariant
          usage={usage}
          maxTokens={maxTokens}
          model={model}
          showCost={showCost}
          costPerInputToken={costPerInputToken}
          costPerOutputToken={costPerOutputToken}
          className={className}
        />
      )
  }
}
