import { Bot, Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"

interface ThinkingIndicatorProps {
  state: "thinking" | "acting"
  className?: string
}

export function ThinkingIndicator({ state, className }: ThinkingIndicatorProps) {
  return (
    <div className={cn("flex items-start gap-3 py-3", className)}>
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
          state === "thinking" ? "bg-purple-500/15" : "bg-blue-500/15",
        )}
      >
        <Bot
          className={cn(
            "h-4 w-4",
            state === "thinking" ? "text-purple-500" : "text-blue-500",
          )}
        />
      </div>
      <div className="flex items-center gap-2 pt-1.5">
        <Loader2
          className={cn(
            "h-3.5 w-3.5 animate-spin",
            state === "thinking" ? "text-purple-500" : "text-blue-500",
          )}
        />
        <span className="text-sm text-muted-foreground">
          {state === "thinking" ? "Thinking..." : "Executing tools..."}
        </span>
      </div>
    </div>
  )
}
