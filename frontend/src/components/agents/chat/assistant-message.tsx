import { MarkdownRenderer } from "@/components/chat/markdown-renderer"
import { cn } from "@/lib/utils"
import type { ConversationTurn } from "@/stores/agent-conversation-store"
import { ChainOfThought } from "./chain-of-thought"
import { AgentToolCallCard } from "./agent-tool-call-card"

interface AssistantMessageProps {
  turn: ConversationTurn
  className?: string
}

export function AssistantMessage({ turn, className }: AssistantMessageProps) {
  const isStreaming = turn.status === "streaming"

  return (
    <div className={cn("space-y-3", className)}>
      {/* Chain of thought */}
      {turn.thinkingSteps.length > 0 && (
        <ChainOfThought
          steps={turn.thinkingSteps}
          isStreaming={isStreaming && turn.segments.length === 0}
        />
      )}

      {/* Segments: interleaved content and tool calls */}
      {turn.segments.map((segment, i) => {
        if (segment.type === "content") {
          const text = segment.text
          if (!text) return null
          return (
            <div key={i}>
              <MarkdownRenderer content={text} />
              {/* Streaming cursor on last content segment */}
              {isStreaming && i === turn.segments.length - 1 && (
                <span
                  className="ml-0.5 inline-block h-4 w-2 animate-pulse bg-foreground align-middle"
                  aria-hidden="true"
                />
              )}
            </div>
          )
        }
        if (segment.type === "tool_call") {
          return (
            <AgentToolCallCard
              key={segment.toolCall.id}
              toolCall={segment.toolCall}
            />
          )
        }
        return null
      })}

      {/* Error state */}
      {turn.status === "error" && !turn.content && (
        <p className="text-sm text-red-500">An error occurred while generating a response.</p>
      )}
    </div>
  )
}
