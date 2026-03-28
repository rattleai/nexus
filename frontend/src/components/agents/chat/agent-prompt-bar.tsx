import { Square, AlertCircle } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { PromptInput } from "@/components/chat/prompt-input"
import { cn } from "@/lib/utils"
import type { ConversationStatus } from "@/stores/agent-conversation-store"

const MAX_PROMPT_LENGTH = 100_000 // Match backend ConversationReplyRequest.message max_length

interface AgentPromptBarProps {
  status: ConversationStatus
  agentState: "idle" | "thinking" | "acting" | "complete" | "error"
  error?: string
  onSend: (message: string) => void
  onStop: () => void
  className?: string
}

export function AgentPromptBar({
  status,
  agentState,
  error,
  onSend,
  onStop,
  className,
}: AgentPromptBarProps) {
  const isStreaming = status === "streaming"
  const isDisabled = isStreaming

  const handleSend = (msg: string) => {
    if (msg.length > MAX_PROMPT_LENGTH) {
      toast.error(`Message is too long (${msg.length.toLocaleString()} chars). Maximum is ${MAX_PROMPT_LENGTH.toLocaleString()}.`)
      return
    }
    onSend(msg)
  }

  const placeholder =
    status === "streaming"
      ? agentState === "thinking"
        ? "Agent is thinking..."
        : agentState === "acting"
          ? "Agent is executing tools..."
          : "Agent is responding..."
      : status === "error"
        ? "Retry or send a new message..."
        : status === "awaiting-input"
          ? "Send a follow-up message..."
          : "Type a message to start..."

  return (
    <div className={cn("border-t bg-background", className)}>
      {/* Error banner */}
      {error && status === "error" && (
        <div className="flex items-center gap-2 px-4 py-2 border-b bg-red-500/[0.05]">
          <AlertCircle className="h-3.5 w-3.5 text-red-500 shrink-0" />
          <span className="text-xs text-red-600 dark:text-red-400 truncate">{error}</span>
        </div>
      )}

      {/* Input area */}
      <div className="flex items-end gap-2 p-3">
        {/* Status pill when streaming */}
        {isStreaming && (
          <div
            className={cn(
              "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs shrink-0",
              agentState === "thinking" && "bg-purple-500/15 text-purple-600 dark:text-purple-400",
              agentState === "acting" && "bg-blue-500/15 text-blue-600 dark:text-blue-400",
            )}
          >
            <span
              className={cn(
                "h-1.5 w-1.5 rounded-full animate-pulse",
                agentState === "thinking" && "bg-purple-500",
                agentState === "acting" && "bg-blue-500",
              )}
            />
            {agentState === "thinking" ? "Thinking" : "Acting"}
          </div>
        )}

        {/* Prompt input */}
        <PromptInput
          onSubmit={handleSend}
          disabled={isDisabled}
          placeholder={placeholder}
          className="flex-1"
        />

        {/* Stop button */}
        {isStreaming && (
          <Button
            variant="destructive"
            size="icon"
            className="h-8 w-8 shrink-0"
            onClick={onStop}
          >
            <Square className="h-3.5 w-3.5" />
            <span className="sr-only">Stop</span>
          </Button>
        )}
      </div>
    </div>
  )
}
