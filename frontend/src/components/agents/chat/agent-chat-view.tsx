import * as React from "react"
import { ArrowDown, Bot } from "lucide-react"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { useAgentConversation } from "@/hooks/use-agent-conversation"
import { ErrorBoundary } from "@/components/error-boundary"
import { AgentChatMessage } from "./agent-chat-message"
import { AgentPromptBar } from "./agent-prompt-bar"
import { ThinkingIndicator } from "./thinking-indicator"

interface AgentChatViewProps {
  instanceId: string
  sessionId: string | null
  className?: string
}

export function AgentChatView({ instanceId, sessionId, className }: AgentChatViewProps) {
  const {
    turns,
    status,
    agentState,
    isStreaming,
    error,
    sendMessage,
    stop,
  } = useAgentConversation(instanceId, sessionId)

  // ── Auto-scroll logic ──────────────────────────────────
  const scrollRef = React.useRef<HTMLDivElement>(null)
  const bottomRef = React.useRef<HTMLDivElement>(null)
  const [userScrolledUp, setUserScrolledUp] = React.useState(false)
  const [showScrollButton, setShowScrollButton] = React.useState(false)

  const scrollToBottom = React.useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
    setUserScrolledUp(false)
    setShowScrollButton(false)
  }, [])

  // Detect user scroll position
  const handleScroll = React.useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const target = e.currentTarget
    const isAtBottom = target.scrollHeight - target.scrollTop - target.clientHeight < 80
    setUserScrolledUp(!isAtBottom)
    setShowScrollButton(!isAtBottom && turns.length > 0)
  }, [turns.length])

  // Auto-scroll when streaming and user hasn't scrolled up
  React.useEffect(() => {
    if (!userScrolledUp && (isStreaming || turns.length > 0)) {
      bottomRef.current?.scrollIntoView({ behavior: "instant" })
    }
  }, [turns, isStreaming, userScrolledUp])

  // ── Empty state ────────────────────────────────────────

  if (turns.length === 0 && !isStreaming) {
    return (
      <div className={cn("flex flex-col h-full", className)}>
        <div className="flex-1 flex flex-col items-center justify-center p-6 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 mb-4">
            <Bot className="h-6 w-6 text-primary" />
          </div>
          <h3 className="text-sm font-medium mb-1">Agent Run</h3>
          <p className="text-xs text-muted-foreground max-w-xs">
            The agent&apos;s responses and tool calls will appear here.
            You can send follow-up messages after the initial run completes.
          </p>
        </div>
        <AgentPromptBar
          status={status}
          agentState={agentState}
          error={error}
          onSend={sendMessage}
          onStop={stop}
        />
      </div>
    )
  }

  // ── Chat view ──────────────────────────────────────────

  return (
    <div className={cn("flex flex-col h-full relative", className)}>
      {/* Messages area */}
      <ScrollArea
        className="flex-1 min-h-0"
        onScrollCapture={handleScroll}
        ref={scrollRef}
      >
        <div className="max-w-3xl mx-auto px-4 sm:px-6 py-4 space-y-6">
          {turns.map((turn) => (
            <ErrorBoundary
              key={turn.id}
              fallback={
                <div className="text-xs text-red-500 bg-red-500/5 p-3 rounded-lg border border-red-200 dark:border-red-900">
                  Failed to render message
                </div>
              }
            >
              <AgentChatMessage turn={turn} />
            </ErrorBoundary>
          ))}

          {/* Thinking indicator when streaming with no content yet */}
          {isStreaming && agentState !== "complete" && (
            (() => {
              const lastTurn = turns[turns.length - 1]
              const showIndicator =
                !lastTurn ||
                lastTurn.role === "user" ||
                (lastTurn.role === "assistant" && lastTurn.segments.length === 0 && lastTurn.thinkingSteps.length === 0)
              return showIndicator ? (
                <ThinkingIndicator state={agentState === "acting" ? "acting" : "thinking"} />
              ) : null
            })()
          )}

          {/* Scroll anchor */}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>

      {/* Scroll to bottom FAB */}
      {showScrollButton && (
        <div className="absolute bottom-20 left-1/2 -translate-x-1/2 z-10">
          <Button
            variant="outline"
            size="sm"
            className="rounded-full shadow-md gap-1.5"
            onClick={scrollToBottom}
          >
            <ArrowDown className="h-3.5 w-3.5" />
            <span className="text-xs">New messages</span>
          </Button>
        </div>
      )}

      {/* Input bar */}
      <AgentPromptBar
        status={status}
        agentState={agentState}
        error={error}
        onSend={sendMessage}
        onStop={stop}
      />
    </div>
  )
}
